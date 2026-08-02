"""
Persistent SQLite-backed JobStore for EDM-Takens Web.

Implements the same interface as the in-memory JobStore in backend/api.py:
  create(params: dict) -> Job
  get(job_id: str) -> Optional[Job]
  spawn(job: Job) -> None
  events(job_id: str) -> AsyncIterator[dict]

When ``JOBS_DB`` is set, it is used as the SQLite database path. Otherwise a
``jobs.sqlite`` file in the project root is used.
"""
import abc
import asyncio
import json
import math
import os
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract + In-memory implementations (mirrors backend/api.py)
# ═══════════════════════════════════════════════════════════════════════════════


def _sanitize_json(obj):
    """递归清理 JSON 不兼容的浮点值（NaN, Infinity, -Infinity）。

    EDM 结果中常出现这些值（HAVOK 退化、除零、log(0) 等），
    标准 JSON 序列化器会抛 ValueError。将它们替换为 None（JSON null）
    以确保 API 响应可以正常序列化。
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


class Job:
    """A single asynchronous analysis job."""

    def __init__(self, job_id: str, params: dict):
        self.id = job_id
        self.params = params
        self.status = "pending"
        self.logs: List[str] = []
        # P2-5: 日志总行数。活跃任务中等同于 len(logs)；
        # 从 SQLite 恢复时可能大于 len(logs)（仅持久化了尾部摘要）。
        self.log_count: int = 0
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self._queue: queue.Queue = queue.Queue()
        self._done = threading.Event()
        self._on_finish: Optional[Any] = None

    def set_on_finish(self, callback):
        self._on_finish = callback

    def append_log(self, line: str):
        self.logs.append(line)
        self.log_count = len(self.logs)
        self._queue.put(("log", line))

    def finish(self, result: Optional[dict] = None, error: Optional[str] = None):
        self.result = result
        self.error = error
        self.status = "error" if error else "done"
        self.updated_at = time.time()
        if result:
            self._queue.put(("result", result))
        if error:
            self._queue.put(("error", {"detail": error}))
        self._queue.put(None)
        self._done.set()
        if self._on_finish:
            try:
                self._on_finish(self)
            except Exception:
                pass

    def to_public_dict(self, limit_logs: int = 200) -> dict:
        # P0 fix: EDM 结果中可能包含 NaN/Infinity 浮点数（来自 HAVOK 退化、
        # 除零、log(0) 等数学运算），这些值在 JSON 序列化时会抛
        # ValueError: Out of range float values are not JSON compliant。
        # 使用 _sanitize_json 递归清理，将 NaN/Inf 替换为 None。
        return {
            "job_id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": self.logs[-limit_logs:],
            "log_count": self.log_count,
            "result": _sanitize_json(self.result),
            "error": self.error,
        }


class JobStore(abc.ABC):
    """Abstract interface for job lifecycle management."""

    @abc.abstractmethod
    def create(self, params: dict) -> Job:
        """Create and persist a new job, returning its in-memory view."""
        ...

    @abc.abstractmethod
    def get(self, job_id: str) -> Optional[Job]:
        """Retrieve the latest in-memory view of a job."""
        ...

    @abc.abstractmethod
    def spawn(self, job: Job) -> None:
        """Start execution of the job in the background."""
        ...

    @abc.abstractmethod
    async def events(self, job_id: str) -> AsyncIterator[dict]:
        """Yield NDJSON-serializable events for a job."""
        ...


class InMemoryJobStore(JobStore):
    """In-memory JobStore with bounded history and thread-based workers."""

    def __init__(self, max_history: int = 50):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_history = max_history

    def create(self, params: dict) -> Job:
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = Job(job_id, params)
        with self._lock:
            self._jobs[job_id] = job
            if len(self._jobs) > self._max_history:
                ordered = sorted(self._jobs.items(), key=lambda kv: kv[1].created_at)
                for old_id, _ in ordered[: len(self._jobs) - self._max_history]:
                    self._jobs.pop(old_id, None)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def spawn(self, job: Job) -> None:
        # Import here to avoid a circular dependency at module load time.
        from api import _job_worker

        threading.Thread(target=_job_worker, args=(self, job), daemon=True).start()

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        job = self.get(job_id)
        if not job:
            return
        async for event in _stream_from_job(job):
            yield event


async def _stream_from_job(job: Job):
    """Yield NDJSON events from a job's internal queue."""
    import json as _json

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
        yield _json.dumps({"type": typ, "data": payload}, ensure_ascii=False) + "\n"
        if typ in ("result", "error"):
            break


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite-backed persistent implementation
# ═══════════════════════════════════════════════════════════════════════════════

# P2-5: 持久化到 SQLite 的日志尾部行数。
# 完整日志仅保留在内存的 Job 对象中；这里只存最近 N 行作为摘要，
# 避免每次持久化都全量序列化上千行日志。
_PERSISTED_LOG_TAIL = 50


class PersistentJobStore(JobStore):
    """SQLite-backed JobStore with in-memory active-job cache."""

    def __init__(self, db_path: Optional[str] = None, max_history: int = 200):
        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent
            db_path = str(project_root / "jobs.sqlite")
        self._db_path = db_path
        self._max_history = max_history
        self._lock = threading.Lock()
        self._active_jobs: Dict[str, Job] = {}
        self._ensure_schema()
        # ROB-03 修复: 后端进程被强杀后重启时，将所有遗留的 running 状态任务
        # 标记为 interrupted（而非 error），以准确区分"任务自身执行出错"与
        # "任务因后端重启而被中断"。该操作幂等：仅影响 status='running' 的行，
        # 重复调用无副作用。
        self.recover()

    def recover(self) -> int:
        """将所有遗留的 running 状态任务标记为 interrupted。

        ROB-03: 后端进程被强杀（kill -9 / 崩溃 / 容器重启）后重启时调用。
        崩溃前处于 running 的任务无法继续执行，会被永久卡住；本方法将它们
        一次性标记为 ``interrupted``，错误信息标注为
        "Backend process restarted while task was running"。

        与 ``error`` 的区别：``interrupted`` 表示任务本身未出错，只是因为
        后端进程重启而被迫中断，便于运维与用户区分故障来源。

        幂等性：仅更新 status='running' 的行，已为 interrupted/error/done
        的行不受影响，因此多次调用不会产生副作用。

        Returns:
            被恢复（标记为 interrupted）的任务数量。
        """
        recovered = 0
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT job_id FROM jobs WHERE status = ?",
                ("running",),
            )
            stuck_ids = [row[0] for row in cur.fetchall()]
            if not stuck_ids:
                return 0
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    "interrupted",
                    "Backend process restarted while task was running",
                    time.time(),
                    "running",
                ),
            )
            conn.commit()
            recovered = len(stuck_ids)
        if recovered:
            print(
                f"[JobStore] recover(): marked {recovered} stuck 'running' "
                f"job(s) as 'interrupted' (Backend process restarted while task was running)."
            )
        return recovered

    # NEW-4: 统一的 SQLite 连接工厂。timeout=30 让 SQLite 在遇到 BUSY
    # 锁时内部等待最多 30 秒；若仍超时则进入 _busy_retry 的指数退避重试。
    _BUSY_RETRY_MAX = 5
    _BUSY_RETRY_BASE = 0.1

    def _connect(self) -> sqlite3.Connection:
        """创建带 timeout 和 busy 重试的 SQLite 连接。"""
        last_err = None
        for attempt in range(self._BUSY_RETRY_MAX):
            try:
                return sqlite3.connect(self._db_path, timeout=30)
            except sqlite3.OperationalError as e:
                last_err = e
                time.sleep(self._BUSY_RETRY_BASE * (2 ** attempt))
        raise last_err  # type: ignore[misc]

    def _ensure_schema(self):
        # P0 fix: 如果数据库文件存在但为 0 字节（空文件，可能由同步脚本
        # 或崩溃残留创建），sqlite3.connect() 不会自动初始化 SQLite 文件头，
        # 后续 CREATE TABLE 可能静默失败。先检查并删除 0 字节文件，
        # 让 SQLite 重新创建有效的数据库文件。
        try:
            if (os.path.exists(self._db_path)
                    and os.path.getsize(self._db_path) == 0):
                os.remove(self._db_path)
                print(f"[JobStore] Removed 0-byte database file: {self._db_path}")
        except OSError as e:
            print(f"[JobStore] WARNING: cannot remove 0-byte db file: {e}")

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    params TEXT,
                    logs TEXT,
                    result TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            # P2-5: 新增 log_count 列，记录日志总行数；
            # logs 列改为只保留尾部摘要（最后 _PERSISTED_LOG_TAIL 行），
            # 完整日志仅保留在内存的 Job 对象中，避免每次全量 JSON 持久化。
            try:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN log_count INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在（旧库迁移幂等）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)"
            )
            conn.commit()

        # P0 fix: 验证表确实已创建（防御性编程，防止某些 SQLite 边缘情况
        # 下 CREATE TABLE 静默失败）
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
            )
            if not cur.fetchone():
                raise RuntimeError(
                    f"_ensure_schema() failed: jobs table not created in {self._db_path}"
                )

    def _insert_job(self, job: Job):
        # P0 fix: 如果 jobs 表不存在（数据库被外部清空或损坏），
        # 自动重新创建 schema 后重试。这防止了 "no such table: jobs"
        # 错误导致整个 EDM 任务失败。
        for _attempt in range(2):
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO jobs
                        (job_id, status, params, logs, result, error,
                         created_at, updated_at, log_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job.id,
                            job.status,
                            json.dumps(job.params, ensure_ascii=False),
                            # P2-5: 仅持久化日志尾部摘要，完整日志保留在内存。
                            json.dumps(job.logs[-_PERSISTED_LOG_TAIL:], ensure_ascii=False),
                            json.dumps(job.result, ensure_ascii=False) if job.result else None,
                            job.error,
                            job.created_at,
                            job.updated_at,
                            len(job.logs),
                        ),
                    )
                    conn.commit()
                return  # 成功，退出重试循环
            except sqlite3.OperationalError as e:
                if "no such table" in str(e) and _attempt == 0:
                    print(f"[JobStore] WARNING: {e} — auto-recreating schema and retrying...")
                    self._ensure_schema()
                    continue
                raise  # 第二次尝试仍失败，或非 "no such table" 错误，向上抛出

    def _persist(self, job: Job):
        self._insert_job(job)
        with self._lock:
            # ROB-03: "interrupted" 也属于终态，需从活跃任务缓存中移除，
            # 避免被中断的任务长期占用内存。
            if job.status in ("done", "error", "interrupted"):
                self._active_jobs.pop(job.id, None)

    def _load_job(self, job_id: str) -> Optional[Job]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT status, params, logs, result, error, created_at, "
                "updated_at, log_count FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        # P2-5: log_count 可能为 None（旧库未迁移行）；logs 仅含尾部摘要。
        (status, params_json, logs_json, result_json, error,
         created_at, updated_at, log_count) = row
        job = Job(job_id, json.loads(params_json or "{}"))
        job.status = status
        # 仅恢复持久化的尾部摘要；完整日志只在内存的活跃 Job 中可用。
        job.logs = json.loads(logs_json or "[]")
        # 记录日志总行数，便于 UI 提示“仅显示最近 N / 共 M 行”。
        job.log_count = log_count if log_count is not None else len(job.logs)
        job.result = json.loads(result_json or "null")
        if job.result is None:
            job.result = None
        job.error = error
        job.created_at = created_at
        job.updated_at = updated_at
        # Completed jobs have no live queue; mark done so event loops exit cleanly.
        # ROB-03: "interrupted" 也属于终态，标记 _done 以便事件循环正常退出。
        if status in ("done", "error", "interrupted"):
            job._done.set()
        return job

    def create(self, params: dict) -> Job:
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = Job(job_id, params)
        job.set_on_finish(self._persist)
        self._insert_job(job)
        with self._lock:
            self._active_jobs[job_id] = job
            # Prune oldest completed jobs if we exceed max_history.
            # ROB-03: "interrupted" 也属于终态，纳入可清理范围。
            completed = sorted(
                [
                    (jid, j)
                    for jid, j in self._active_jobs.items()
                    if j.status in ("done", "error", "interrupted")
                ],
                key=lambda kv: kv[1].updated_at,
            )
            if len(self._active_jobs) > self._max_history:
                for jid, _ in completed[: len(self._active_jobs) - self._max_history]:
                    self._active_jobs.pop(jid, None)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._active_jobs.get(job_id)
        if job is not None:
            return job
        return self._load_job(job_id)

    def spawn(self, job: Job) -> None:
        from api import _job_worker

        def _worker_wrapper(store, j):
            try:
                _job_worker(store, j)
            finally:
                self._persist(j)

        threading.Thread(target=_worker_wrapper, args=(self, job), daemon=True).start()

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        job = self.get(job_id)
        if not job:
            return
        async for event in _stream_from_job(job):
            yield event
