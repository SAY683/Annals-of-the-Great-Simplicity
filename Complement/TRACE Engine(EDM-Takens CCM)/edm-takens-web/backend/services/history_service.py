"""History-domain services shared by thin route modules."""
import json
from typing import Optional

from job_store import _sanitize_json
from repositories import task_repository


def lookup_summary_by_task_id(task_id: str) -> Optional[dict]:
    """从 SQLite 缓存中反查与 task_id 关联的完整分析摘要。

    遍历 jobs 表的 result 字段，匹配 ``result.task_id == task_id`` 的最新一行，
    返回其 ``result.summary``。若 JobStore 不是 PersistentJobStore 或未找到
    匹配项，返回 None。任何异常都吞掉返回 None，避免影响主流程。
    """
    try:
        # 延迟导入避免循环依赖
        from core.runtime import _JOB_STORE
        from job_store import PersistentJobStore
        if not isinstance(_JOB_STORE, PersistentJobStore):
            return None
        with _JOB_STORE._connect() as conn:
            # 优先使用 json_extract（性能更优，依赖 JSON1 扩展）
            try:
                cur = conn.execute(
                    "SELECT result FROM jobs "
                    "WHERE result IS NOT NULL "
                    "AND json_extract(result, '$.task_id') = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (task_id,),
                )
                row = cur.fetchone()
            except Exception:
                # JSON1 不可用时退化到 Python 侧过滤
                cur = conn.execute(
                    "SELECT result FROM jobs "
                    "WHERE result IS NOT NULL "
                    "ORDER BY updated_at DESC"
                )
                row = None
                for r in cur.fetchall():
                    try:
                        obj = json.loads(r[0])
                    except Exception:
                        continue
                    if isinstance(obj, dict) and obj.get("task_id") == task_id:
                        row = r
                        break
        if not row or not row[0]:
            return None
        result_obj = json.loads(row[0])
        summary = result_obj.get("summary") if isinstance(result_obj, dict) else None
        # 清理 NaN/Inf（HAVOK 退化等场景产生的非法浮点值），否则 FastAPI
        # 响应序列化会抛 ValueError。
        return _sanitize_json(summary) if summary is not None else None
    except Exception:
        return None




def list_history(limit: int = 50):
    return task_repository.list_task_summaries(limit)


def get_history_detail(task_id: str):
    summary = task_repository.get_task_summary(task_id)
    if summary is None:
        return None
    return {
        "success": True,
        "task_id": task_id,
        "config": summary.get("config"),
        "params": summary.get("params"),
        "images": summary.get("images", []),
        "summary": lookup_summary_by_task_id(task_id),
        "task_updated": summary.get("updated_at"),
    }


def archive_task(task_id: str):
    zip_path = task_repository.archive_task(task_id)
    return {"task_id": task_id, "archived": True, "zip": zip_path}


def task_download_path(task_id: str):
    return task_repository.task_download_path(task_id)


def delete_task(task_id: str):
    return {"task_id": task_id, "deleted": task_repository.delete_task(task_id)}


def cleanup_history(days: int, max_size_mb=None, dry_run: bool = False):
    return task_repository.cleanup_results(days, max_size_mb, dry_run)


def batch_history(action: str, task_ids):
    if action == "download":
        return {"download_path": task_repository.build_batch_download(task_ids)}
    return {"action": action, "results": task_repository.batch_archive_or_delete(action, task_ids)}


def compare_task_summaries(task_ids):
    summaries = []
    for task_id in task_ids:
        summary = task_repository.get_task_summary(task_id)
        if summary is None:
            raise LookupError(task_id)
        summaries.append(summary)
    return {
        "task_ids": task_ids,
        "left_task": summaries[0] if summaries else None,
        "right_task": summaries[1] if len(summaries) > 1 else None,
        "summaries": summaries,
        "count": len(summaries),
    }
