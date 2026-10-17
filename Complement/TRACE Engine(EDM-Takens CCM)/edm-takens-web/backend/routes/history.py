"""Thin history routes composed from history services."""
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse

from core.auth import require_auth, require_auth_optional
from schemas.history import BatchRequest, CompareRequest
from services import history_service

router = APIRouter()


@router.get("/api/history", dependencies=[Depends(require_auth_optional)])
def list_history(limit: int = 50):
    """List completed analysis task directories under results/."""
    return history_service.list_history(limit)


@router.get("/api/history/{task_id}", dependencies=[Depends(require_auth_optional)])
def get_history_detail(task_id: str):
    """Return one task's config, params, images and rich summary."""
    result = history_service.get_history_detail(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.post("/api/history/{task_id}/archive", dependencies=[Depends(require_auth)])
def archive_task(task_id: str):
    """Compress a task's results into archive/{task_id}.zip."""
    try:
        return history_service.archive_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive failed: {exc}")


@router.get("/api/history/{task_id}/download", dependencies=[Depends(require_auth_optional)])
def download_task(task_id: str):
    """Download a task's results as a zip archive."""
    try:
        path = history_service.task_download_path(task_id)
        return FileResponse(path, filename=f"{task_id}.zip", media_type="application/zip")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.delete("/api/history/{task_id}", dependencies=[Depends(require_auth)])
def delete_task(task_id: str):
    """Delete a task's active results and any associated archive."""
    try:
        return history_service.delete_task(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post("/api/history/cleanup", dependencies=[Depends(require_auth)])
def cleanup_history(days: int = 30, max_size_mb: float | None = None, dry_run: bool = False):
    """Remove old result directories and archives."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    return history_service.cleanup_history(days, max_size_mb, dry_run)


@router.post("/api/history/batch", dependencies=[Depends(require_auth)])
def batch_history(body: dict = Body(...)):
    """Batch archive, delete, or download multiple tasks."""
    try:
        req = BatchRequest(**body)
    except Exception as exc:
        errors = getattr(exc, "errors", lambda: [])()
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in errors)
        raise HTTPException(status_code=422, detail=f"参数校验失败: {detail or exc}")
    action = req.action.lower()
    task_ids = req.normalized_ids()
    if action not in ("archive", "delete", "download"):
        raise HTTPException(status_code=400, detail="action must be archive|delete|download")
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    result = history_service.batch_history(action, task_ids)
    if "download_path" in result:
        return FileResponse(result["download_path"], filename="batch_download.zip", media_type="application/zip")
    return result


@router.post("/api/history/compare", dependencies=[Depends(require_auth)])
def compare_tasks(body: dict = Body(...)):
    """Return side-by-side summaries for 2-8 tasks."""
    task_ids = body.get("task_ids") or []
    if not isinstance(task_ids, list) or len(task_ids) < 2:
        left_id = body.get("left_id")
        right_id = body.get("right_id")
        if left_id and right_id:
            task_ids = [left_id, right_id]
        else:
            raise HTTPException(status_code=400, detail="task_ids 必须包含至少 2 个元素, 或同时提供 left_id 和 right_id")
    if len(task_ids) > 8:
        raise HTTPException(status_code=400, detail="task_ids 最多支持 8 个任务同时对比")
    try:
        req = CompareRequest(task_ids=task_ids)
    except Exception as exc:
        errors = getattr(exc, "errors", lambda: [])()
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in errors)
        raise HTTPException(status_code=422, detail=f"参数校验失败: {detail or exc}")
    try:
        return history_service.compare_task_summaries(req.task_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"Task not found: {exc}")
