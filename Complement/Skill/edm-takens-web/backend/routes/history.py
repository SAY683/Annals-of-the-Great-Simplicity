"""
Routes — history and archive management endpoints (debt-19).

Extracted from api.py using APIRouter. Handles task listing, archiving,
download, deletion, cleanup, batch operations, comparison, and export.
"""
import os
import io
import csv
import json
import time
import shutil
import zipfile
import tempfile
from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import FileResponse, StreamingResponse

from core.locks import RESULTS_DIR, ARCHIVE_DIR, _PROJECT_ROOT
from services.file_management import (
    _safe_task_path,
    _zip_task,
    _total_size_mb,
)
from services.summary_builder import _task_summary
# 复用 _sanitize_json 清理从 SQLite 反查的 summary 中的 NaN/Inf 浮点值，
# 避免 FastAPI 响应序列化时抛 ValueError: Out of range float values。
from job_store import _sanitize_json

router = APIRouter()


@router.get("/api/history")
def list_history(limit: int = 50):
    """List completed analysis task directories under ``results/``."""
    # P0 fix: 防御性创建 results/ 目录 — 同步脚本或外部操作可能
    # 在后端运行期间删除该目录，导致 os.listdir 失败（HTTP 500）。
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tasks = []
    for name in os.listdir(RESULTS_DIR):
        task_dir = os.path.join(RESULTS_DIR, name)
        if not os.path.isdir(task_dir):
            continue
        # 改用 _task_summary() 统一扫描逻辑，避免与 summary_builder 的
        # config 读取逻辑分叉；同时取回 params 字段。
        summary = _task_summary(name)
        if summary is None:
            continue
        tasks.append({
            "task_id": summary["task_id"],
            "updated_at": summary["updated_at"],
            "images": summary["images"],
            "has_config": summary["config"] is not None,
            "config": summary["config"],
            "params": summary["params"],
        })
    tasks.sort(key=lambda x: x["updated_at"], reverse=True)
    return tasks[:limit]


def _lookup_summary_by_task_id(task_id: str) -> Optional[dict]:
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


@router.get("/api/history/{task_id}")
def get_history_detail(task_id: str):
    """返回单任务的完整数据：config + params + images + summary。

    ``summary`` 字段从 SQLite jobs 表反查（``result.task_id == task_id``），
    若找不到匹配的 job（例如数据库被清空）则为 null，前端会跳过摘要渲染。
    """
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail="Task not found")
    summary = _task_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Task not found")
    rich_summary = _lookup_summary_by_task_id(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "config": summary.get("config"),
        "params": summary.get("params"),
        "images": summary.get("images", []),
        "summary": rich_summary,
        "task_updated": summary.get("updated_at"),
    }


@router.post("/api/history/{task_id}/archive")
def archive_task(task_id: str):
    """Compress a task's results into archive/{task_id}.zip and remove the active directory."""
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        zip_path = _zip_task(task_id)
        shutil.rmtree(task_dir)
        return {"task_id": task_id, "archived": True, "zip": zip_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Archive failed: {e}")


@router.get("/api/history/{task_id}/download")
def download_task(task_id: str):
    """Download a task's results as a zip archive."""
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        # Try to serve an existing archive
        zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
        if zip_path and os.path.exists(zip_path):
            return FileResponse(zip_path, filename=f"{task_id}.zip", media_type="application/zip")
        raise HTTPException(status_code=404, detail="Task not found")
    zip_path = _zip_task(task_id)
    return FileResponse(zip_path, filename=f"{task_id}.zip", media_type="application/zip")


@router.delete("/api/history/{task_id}")
def delete_task(task_id: str):
    """Delete a task's active results and any associated archive."""
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    deleted = {"result_dir": False, "zip": False}
    if task_dir and os.path.isdir(task_dir):
        shutil.rmtree(task_dir)
        deleted["result_dir"] = True
    if zip_path and os.path.exists(zip_path):
        os.remove(zip_path)
        deleted["zip"] = True
    if not any(deleted.values()):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "deleted": deleted}


@router.post("/api/history/cleanup")
def cleanup_history(
    days: int = 30,
    max_size_mb: Optional[float] = None,
    dry_run: bool = False,
):
    """Remove result directories and archives older than ``days`` days.

    Parameters
    ----------
    days : int
        Age threshold in days (1..365 inclusive).
    max_size_mb : float, optional
        If total size of results + archives exceeds this, delete oldest items
        until the total is under the cap.
    dry_run : bool
        If True, return what would be removed without deleting anything.
    """
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    cutoff = time.time() - days * 86400

    candidates = []
    for base_dir in (RESULTS_DIR, ARCHIVE_DIR):
        if not os.path.isdir(base_dir):
            continue
        for name in os.listdir(base_dir):
            path = os.path.join(base_dir, name)
            if os.path.isdir(path) or os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if mtime < cutoff:
                    candidates.append({
                        "path": path,
                        "mtime": mtime,
                        "rel": os.path.relpath(path, _PROJECT_ROOT),
                    })

    removed = []
    for item in candidates:
        if not dry_run:
            try:
                if os.path.isdir(item["path"]):
                    shutil.rmtree(item["path"])
                else:
                    os.remove(item["path"])
            except Exception:
                continue
        removed.append(item["rel"])

    # Optional size cap enforcement: delete oldest items first until under cap.
    size_deleted = []
    if max_size_mb is not None and max_size_mb > 0:
        remaining = []
        for base_dir in (RESULTS_DIR, ARCHIVE_DIR):
            if not os.path.isdir(base_dir):
                continue
            for name in os.listdir(base_dir):
                path = os.path.join(base_dir, name)
                if os.path.isdir(path) or os.path.isfile(path):
                    remaining.append({
                        "path": path,
                        "mtime": os.path.getmtime(path),
                        "rel": os.path.relpath(path, _PROJECT_ROOT),
                    })
        current_mb = _total_size_mb([i["path"] for i in remaining])
        if current_mb > max_size_mb:
            remaining.sort(key=lambda x: x["mtime"])
            while remaining and current_mb > max_size_mb:
                item = remaining.pop(0)
                if not dry_run:
                    try:
                        if os.path.isdir(item["path"]):
                            shutil.rmtree(item["path"])
                        else:
                            os.remove(item["path"])
                    except Exception:
                        continue
                size_deleted.append(item["rel"])
                current_mb = _total_size_mb([i["path"] for i in remaining])

    return {
        "dry_run": dry_run,
        "days": days,
        "max_size_mb": max_size_mb,
        "removed": removed,
        "removed_count": len(removed),
        "size_deleted": size_deleted,
        "size_deleted_count": len(size_deleted),
    }


@router.get("/api/archives")
def list_archives():
    """List zip files in the archive directory."""
    archives = []
    if os.path.isdir(ARCHIVE_DIR):
        for name in os.listdir(ARCHIVE_DIR):
            if not name.lower().endswith(".zip"):
                continue
            path = os.path.join(ARCHIVE_DIR, name)
            if not os.path.isfile(path):
                continue
            archives.append({
                "task_id": name[:-4],
                "filename": name,
                "size_bytes": os.path.getsize(path),
                "updated_at": os.path.getmtime(path),
            })
    archives.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"archives": archives}


@router.post("/api/archives/{task_id}/restore")
def restore_archive(task_id: str):
    """Unzip an archive back into the results directory."""
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="Archive not found")
    task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir:
        raise HTTPException(status_code=400, detail="Invalid task_id")
    if os.path.exists(task_dir):
        raise HTTPException(status_code=409, detail="Task directory already exists")
    try:
        shutil.unpack_archive(zip_path, task_dir, format="zip")
        return {"task_id": task_id, "restored": True, "path": task_dir}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")


@router.get("/api/archives/{task_id}/preview")
def preview_archive(task_id: str):
    """临时解压 zip 到临时目录，返回 config + params + images 列表。

    不删除原 zip；解压后的临时目录在请求结束时清理。``summary`` 字段从
    SQLite jobs 表反查（与 ``GET /api/history/{task_id}`` 同逻辑）。
    """
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="Archive not found")
    tmp_dir = tempfile.mkdtemp(prefix="edmtakens_preview_")
    try:
        shutil.unpack_archive(zip_path, tmp_dir, format="zip")
        # 调用 _task_summary 复用 config/params/images 读取逻辑
        summary = _task_summary(task_id, task_dir=tmp_dir)
        if summary is None:
            raise HTTPException(status_code=500, detail="Preview build failed")
        rich_summary = _lookup_summary_by_task_id(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "config": summary.get("config"),
            "params": summary.get("params"),
            "images": summary.get("images", []),
            "summary": rich_summary,
            "task_updated": os.path.getmtime(zip_path),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")
    finally:
        # 清理临时目录，原 zip 不动
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


@router.delete("/api/archives/{task_id}")
def delete_archive(task_id: str):
    """Delete an archive zip file."""
    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="Archive not found")
    try:
        os.remove(zip_path)
        return {"task_id": task_id, "deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


@router.post("/api/history/batch")
def batch_history(body: dict = Body(...)):
    """Batch archive, delete, or download multiple tasks.

    Body schema (also accepts ``ids`` as an alias for ``task_ids``):
      {
        "action": "archive" | "delete" | "download",
        "task_ids": [id1, id2, ...]
      }

    For ``download``, returns a zip containing each task's zip (or its result
    directory if not yet archived).
    """
    action = (body.get("action") or "").lower()
    task_ids = body.get("task_ids") or body.get("ids") or []
    if action not in ("archive", "delete", "download"):
        raise HTTPException(status_code=400, detail="action must be archive|delete|download")
    if not isinstance(task_ids, list) or not task_ids:
        raise HTTPException(status_code=400, detail="task_ids must be a non-empty list")

    if action == "download":
        fd, bundle_path = tempfile.mkstemp(suffix=".zip", prefix="edmtakens_batch_")
        os.close(fd)
        try:
            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for task_id in task_ids:
                    zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
                    task_dir = _safe_task_path(task_id, RESULTS_DIR)
                    if zip_path and os.path.exists(zip_path):
                        zf.write(zip_path, arcname=f"{task_id}.zip")
                    elif task_dir and os.path.isdir(task_dir):
                        for root, _, files in os.walk(task_dir):
                            for fname in files:
                                fpath = os.path.join(root, fname)
                                rel = os.path.relpath(fpath, task_dir)
                                zf.write(fpath, arcname=os.path.join(task_id, rel))
            return FileResponse(
                bundle_path,
                filename="batch_download.zip",
                media_type="application/zip",
            )
        except Exception as e:
            if os.path.exists(bundle_path):
                os.remove(bundle_path)
            raise HTTPException(status_code=500, detail=f"Batch download failed: {e}")

    results = []
    for task_id in task_ids:
        task_dir = _safe_task_path(task_id, RESULTS_DIR)
        zip_path = _safe_task_path(task_id + ".zip", ARCHIVE_DIR)
        entry = {"task_id": task_id, "success": False, "detail": ""}
        try:
            if action == "archive":
                if not task_dir or not os.path.isdir(task_dir):
                    entry["detail"] = "Task not found"
                else:
                    _zip_task(task_id)
                    shutil.rmtree(task_dir)
                    entry["success"] = True
                    entry["detail"] = "archived"
            elif action == "delete":
                deleted = []
                if task_dir and os.path.isdir(task_dir):
                    shutil.rmtree(task_dir)
                    deleted.append("result_dir")
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
                    deleted.append("zip")
                if deleted:
                    entry["success"] = True
                    entry["detail"] = ",".join(deleted)
                else:
                    entry["detail"] = "Task not found"
        except Exception as e:
            entry["detail"] = str(e)
        results.append(entry)

    return {"action": action, "results": results}


@router.post("/api/history/compare")
def compare_tasks(body: dict = Body(...)):
    """Return side-by-side summaries and image lists for two tasks.

    Accepts either ``{task_ids: [id1, id2]}`` or ``{left_id, right_id}``.
    """
    task_ids = body.get("task_ids") or []
    if not isinstance(task_ids, list) or len(task_ids) != 2:
        left_id = body.get("left_id")
        right_id = body.get("right_id")
        if left_id and right_id:
            task_ids = [left_id, right_id]
        else:
            raise HTTPException(status_code=400, detail="task_ids must contain exactly 2 items")
    summaries = []
    for task_id in task_ids:
        summary = _task_summary(task_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        summaries.append(summary)
    return {"task_ids": task_ids, "left_task": summaries[0], "right_task": summaries[1], "summaries": summaries}


@router.get("/api/history/{task_id}/export/json")
def export_task_json(task_id: str):
    """Export a task summary and image list as a downloadable JSON file."""
    summary = _task_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    return StreamingResponse(
        io.BytesIO(payload.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{task_id}_summary.json"'},
    )


@router.get("/api/history/{task_id}/export/csv")
def export_task_csv(task_id: str):
    """Export a task summary as a CSV of summary fields."""
    summary = _task_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Task not found")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    writer.writerow(["task_id", summary["task_id"]])
    writer.writerow(["updated_at", summary["updated_at"]])
    writer.writerow(["image_count", len(summary["images"])])
    writer.writerow(["images", ";".join(summary["images"])])
    config = summary.get("config") or {}
    for key, value in config.items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        writer.writerow([f"config.{key}", value])
    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{task_id}_summary.csv"'},
    )
