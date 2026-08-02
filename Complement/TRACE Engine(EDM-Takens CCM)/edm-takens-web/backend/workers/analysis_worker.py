"""
Workers — analysis job execution (debt-19).

Extracted from api.py. Contains the _JobStream class, the _job_worker
function that runs the pipeline in a background thread, and the
_stream_from_job async generator for NDJSON event streaming.
"""
import os
import time
import json
import queue
import asyncio
import contextlib
import traceback

from core.locks import (
    _STDOUT_LOCK, _ANALYSIS_LOCK, _MOVE_LOCK,
    DATA_DIR, RESULTS_DIR,
)
from services.file_management import (
    _prepare_pipeline_data, _make_config, _move_results_to_task,
)
from services.summary_builder import _build_summary
from pipeline import run_full_analysis
from job_store import Job, JobStore


class _JobStream:
    """File-like that buffers by newline and feeds both job.logs and job.queue."""

    def __init__(self, job: Job):
        self.job = job
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.job.append_log(line)
        return len(s)

    def flush(self):
        if self._buf:
            self.job.append_log(self._buf)
            self._buf = ""


def _job_worker(store: JobStore, job: Job):
    """Run pipeline for a single job, populating job.logs / job.result / job.error.

    `store` is passed in so that a persistent JobStore can be notified of log
    updates if needed.  The in-memory store only needs the Job object.
    """
    os.environ["EDMTAKENS_DATA_DIR"] = DATA_DIR
    params = job.params
    temp_csv = None
    stream = _JobStream(job)
    start_time = time.time()
    job.status = "running"

    # P0 修复：用 _STDOUT_LOCK 串行化 redirect_stdout 临界区，防止并发
    # job 的进程级 stdout 替换互相串台。acquire 顺序固定为
    # _STDOUT_LOCK → _ANALYSIS_LOCK，避免与 _MOVE_LOCK 等锁形成跨任务环。
    with _STDOUT_LOCK, _ANALYSIS_LOCK, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            # NEW-3: cwd 已在模块加载时统一设置为 _PROJECT_ROOT，此处不再
            # 逐任务 os.chdir/restore，避免多线程下进程级 cwd 互相干扰。
            # 先对 results/ 做文件名快照，后续 _move_results_to_task 只迁移
            # 快照中不存在的新增文件，防止误移其它并发任务的产物。
            # P0 fix: 防御性创建 results/ 目录 — 同步脚本或外部操作可能
            # 在后端运行期间删除该目录，导致 os.listdir 失败。
            os.makedirs(RESULTS_DIR, exist_ok=True)
            preexisting_files = set(os.listdir(RESULTS_DIR))

            # P0 fix: 清理 results/ 根目录中上次任务残留的产物文件。
            # 否则 pipeline 生成同名 png 时会覆盖残留文件，但
            # _move_results_to_task 的快照过滤会因文件名已存在于
            # preexisting_files 中而跳过移动，导致 images=[] 且
            # 结果子目录为空。只清理根目录中的散落文件，不影响子目录。
            for _stale in list(preexisting_files):
                _stale_path = os.path.join(RESULTS_DIR, _stale)
                if os.path.isfile(_stale_path):
                    try:
                        os.remove(_stale_path)
                    except OSError:
                        pass
            preexisting_files = set()  # 清理后重置快照

            csv_path, pipeline_target, pipeline_vars, original_target, display_map = _prepare_pipeline_data(
                params["csv_path"], params["target_col"], params["selected_vars"]
            )
            if csv_path != params["csv_path"]:
                temp_csv = csv_path

            config = _make_config(
                csv_path=csv_path,
                target_col=pipeline_target,
                selected_vars=pipeline_vars,
                q=params.get("q"),
                max_e=params.get("max_e"),
                auto_fix=params["auto_fix"],
                intensity=params.get("intensity"),  # S1 修复: 传入 intensity 以映射到 analysis_type
            )
            result = run_full_analysis(config, auto_fix=params["auto_fix"])
            # NEW-3: 串行化文件迁移——两个并发任务共享 results/，若不加锁
            # Job A 的迁移可能把 Job B 刚写入的文件一起移走。_MOVE_LOCK
            # 确保"快照→迁移"作为原子临界区执行。
            with _MOVE_LOCK:
                task_id, images = _move_results_to_task(
                    start_time,
                    preexisting_files=preexisting_files,
                    project_name=params.get("project_name"),
                )
            # 写入 params_*.json（与 config_*.json 同 timestamp 命名模式），
            # 用于历史面板回看任务的输入参数。写入失败不阻断主流程。
            try:
                _task_dir = os.path.join(RESULTS_DIR, task_id)
                _params_payload = {
                    "filename": params.get("filename"),
                    "target_col": params.get("target_col"),
                    "selected_vars": params.get("selected_vars", []),
                    "q": params.get("q"),
                    "max_e": params.get("max_e"),
                    "intensity": params.get("intensity"),
                    "project_name": params.get("project_name"),
                    "auto_fix": params.get("auto_fix"),
                }
                _params_path = os.path.join(
                    _task_dir, f"params_{int(time.time())}.json"
                )
                with open(_params_path, "w", encoding="utf-8") as _pf:
                    json.dump(_params_payload, _pf, ensure_ascii=False, indent=2)
            except Exception as _e:
                print(f"[analysis_worker] params_*.json 写入失败（不阻断主流程）: {_e}")
            summary = _build_summary(
                result,
                params["selected_vars"],
                original_target,
                display_map,
                profile=params.get("profile"),
                project_name=params.get("project_name"),
                data_quality_warning=params.get("data_quality_warning"),
            )
            job.finish(result={
                "success": True,
                "filename": params["filename"],
                "target_col": original_target,
                "variables": params["selected_vars"],
                "summary": summary,
                "task_id": task_id,
                "images": images,
            })
        except Exception as e:
            traceback.print_exc()
            # P0-5 修复 (Round 27 审计): 不将完整异常消息传给前端，避免泄露
            # 文件路径/库内部信息/栈追踪片段。完整异常已通过 traceback.print_exc()
            # 输出到 stderr，前端仅显示通用文案。
            job.finish(error="分析任务执行失败，请查看服务端日志获取详细信息")
        finally:
            if temp_csv and os.path.exists(temp_csv):
                try:
                    os.remove(temp_csv)
                except OSError:
                    pass


async def _stream_from_job(job: Job):
    """Yield NDJSON events from a job's internal queue."""
    while True:
        try:
            item = await asyncio.to_thread(job._queue.get, timeout=0.2)
        except queue.Empty:
            if job._done.is_set() and job._queue.empty():
                break
            continue
        if item is None:
            break
        typ, payload = item
        yield json.dumps({"type": typ, "data": payload}, ensure_ascii=False) + "\n"
        if typ in ("result", "error"):
            break
