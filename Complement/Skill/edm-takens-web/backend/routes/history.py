"""
Routes — history and archive management endpoints (debt-19).

Extracted from api.py using APIRouter. Handles task listing, archiving,
download, deletion, cleanup, batch operations, comparison, and export.
"""
import os
import io
import re
import csv
import json
import time
import shutil
import zipfile
import tempfile
import html
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.locks import RESULTS_DIR, ARCHIVE_DIR, _PROJECT_ROOT
# D-P0-4 修复 (Round 21 §P0-A): 全端点鉴权链.
from core.auth import require_auth, require_auth_optional
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


# P0-7 (Round 21 §P0-A): Pydantic 请求模型 — 替代裸 dict 校验
class BatchRequest(BaseModel):
    """batch_history 端点的请求体模型. 兼容 ids 旧字段名."""
    action: str = Field(..., description="操作类型: archive|delete|download")
    task_ids: Optional[List[str]] = Field(None, min_items=1, description="任务 ID 列表, 至少 1 个")
    ids: Optional[List[str]] = Field(None, min_items=1, description="task_ids 的旧别名")

    def normalized_ids(self) -> List[str]:
        """返回有效的 task_ids, 优先 task_ids 字段, 回退到 ids."""
        return self.task_ids if self.task_ids else (self.ids or [])


class CompareRequest(BaseModel):
    """compare_tasks 端点的请求体模型.

    P1 修复 (Round 24 §3): 取消 max_items=2 限制, 支持 2-8 个任务的对比,
    前端按数量动态渲染对比网格. 仍保留 min_items=2 保证至少有对比意义.
    """
    task_ids: List[str] = Field(..., min_items=2, max_items=8, description="任务 ID 列表, 2-8 个")


@router.get("/api/history", dependencies=[Depends(require_auth_optional)])
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


@router.get("/api/history/{task_id}", dependencies=[Depends(require_auth_optional)])
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


@router.post("/api/history/{task_id}/archive", dependencies=[Depends(require_auth)])
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


@router.get("/api/history/{task_id}/download", dependencies=[Depends(require_auth_optional)])
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


@router.delete("/api/history/{task_id}", dependencies=[Depends(require_auth)])
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


@router.post("/api/history/cleanup", dependencies=[Depends(require_auth)])
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


@router.get("/api/archives", dependencies=[Depends(require_auth_optional)])
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


@router.post("/api/archives/{task_id}/restore", dependencies=[Depends(require_auth)])
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


@router.get("/api/archives/{task_id}/preview", dependencies=[Depends(require_auth_optional)])
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


@router.delete("/api/archives/{task_id}", dependencies=[Depends(require_auth)])
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


@router.post("/api/history/batch", dependencies=[Depends(require_auth)])
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
    # P0-7 (Round 21 §P0-A): 用 Pydantic 模型替换裸 dict 校验
    # 保留 dict 入参以兼容旧客户端, 但用模型做严格校验
    try:
        req = BatchRequest(**body)
    except Exception as ve:
        # 提取 Pydantic 校验错误信息
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in ve.errors())
        raise HTTPException(status_code=422, detail=f"参数校验失败: {detail}")
    action = req.action.lower()
    task_ids = req.normalized_ids()
    if action not in ("archive", "delete", "download"):
        raise HTTPException(status_code=400, detail="action must be archive|delete|download")
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")

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


@router.post("/api/history/compare", dependencies=[Depends(require_auth)])
def compare_tasks(body: dict = Body(...)):
    """Return side-by-side summaries and image lists for multiple tasks.

    P1 修复 (Round 24 §3): 支持 2-8 个任务的对比, 不再限制恰好 2 个.
    返回的 ``summaries`` 列表包含所有请求的任务; 同时保留 ``left_task`` /
    ``right_task`` 字段为前 2 个任务的别名, 向后兼容旧前端.
    Accepts either ``{task_ids: [id1, id2, ...]}`` (2-8 items) or
    ``{left_id, right_id}`` (legacy 2-task form).
    """
    # P0-7 (Round 21 §P0-A): 用 Pydantic 模型替换裸 dict 校验
    # 支持两种入参形态, 优先 task_ids, 回退 left_id/right_id
    task_ids = body.get("task_ids") or []
    # P1 修复 (Round 24 §3): 允许 2-8 个任务, 不再要求恰好 2 个
    if not isinstance(task_ids, list) or len(task_ids) < 2:
        left_id = body.get("left_id")
        right_id = body.get("right_id")
        if left_id and right_id:
            task_ids = [left_id, right_id]
        else:
            raise HTTPException(
                status_code=400,
                detail="task_ids 必须包含至少 2 个元素, 或同时提供 left_id 和 right_id"
            )
    if len(task_ids) > 8:
        raise HTTPException(
            status_code=400,
            detail="task_ids 最多支持 8 个任务同时对比"
        )
    try:
        req = CompareRequest(task_ids=task_ids)
    except Exception as ve:
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in ve.errors())
        raise HTTPException(status_code=422, detail=f"参数校验失败: {detail}")
    task_ids = req.task_ids
    summaries = []
    for task_id in task_ids:
        summary = _task_summary(task_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        summaries.append(summary)
    # 向后兼容: 仍返回 left_task / right_task (取前 2 个), 但前端应优先使用 summaries
    return {
        "task_ids": task_ids,
        "left_task": summaries[0] if len(summaries) > 0 else None,
        "right_task": summaries[1] if len(summaries) > 1 else None,
        "summaries": summaries,
        "count": len(summaries),
    }


@router.get("/api/history/{task_id}/export/json", dependencies=[Depends(require_auth_optional)])
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


@router.get("/api/history/{task_id}/export/csv", dependencies=[Depends(require_auth_optional)])
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


# P2 (§20.12): 一键导出人话版 Markdown 报告
# 将 SQLite 中缓存的 rich summary + 基础 task_summary 转译为非技术读者可理解的中文报告.
# 设计目标: 用户读这份 .md 就能知道 "这次分析说了什么、稳不稳定、有哪些因果链、可不可信".
# P1 修复 (Round 24 §1): 大幅增强报告完整度 — 新增图谱解析、八正道审计章节,
# 补全所有数值字段的中文描述, 解决 "人话版粗糙 + 部分汉化缺失 + 未解析图谱" 问题.

def _fmt_rho(rho):
    """将相关系数 ρ 转译为人话强度的中文标签."""
    if rho is None:
        return "N/A"
    abs_rho = abs(rho)
    # P1 修复 (Round 21 §P0-C): ρ 精度从 3 位提升到 4 位, 与论文要求一致.
    if abs_rho >= 0.85:
        return f"{rho:.4f} (极强)"
    if abs_rho >= 0.7:
        return f"{rho:.4f} (强)"
    if abs_rho >= 0.5:
        return f"{rho:.4f} (中等)"
    if abs_rho >= 0.3:
        return f"{rho:.4f} (弱)"
    return f"{rho:.4f} (极弱/无)"


def _fmt_stability(tier):
    """将稳定性分级翻译为人话."""
    if not tier:
        return "未提供"
    mapping = {
        "Stable / dissipative": "稳定 (耗散系统, 可长期预测)",
        "Near-critical / stable": "近临界 (稳定但接近相变点, 需警惕突发重组)",
        "Chaotic / unstable": "混沌 (不稳定, 长期预测不可靠)",
        # final_interpretation 中的分级标签
        "Highly dissipative": "强耗散 (高度稳定, 系统会自发回归平衡)",
        "Divergent": "发散 (不稳定, 系统持续偏离平衡)",
        "Near-critical": "近临界 (稳定但接近相变点)",
    }
    if isinstance(tier, str) and tier in mapping:
        return mapping[tier]
    # 退化或未知分级: 尽量给出中文解释
    if isinstance(tier, str) and "degenerate" in tier.lower():
        return f"退化 (信号近常量或样本量不足, 无法判定): {tier}"
    return str(tier)


def _fmt_direction(direction):
    """将 CCM 方向判定翻译为人话因果链描述."""
    if not direction:
        return "未判定"
    mapping = {
        "forward": "单向因果 (源 → 目标)",
        "reverse": "反向因果 (目标 → 源)",
        "forward_dominant": "主导正向 (源 → 目标, 反向较弱)",
        "reverse_dominant": "主导反向 (目标 → 源, 正向较弱)",
        "bidirectional": "双向耦合 (互相影响, 存在反馈回路)",
        "none": "无显著因果",
        "inconclusive": "无法判定",
    }
    return mapping.get(direction, str(direction))


def _fmt_timestamp(ts):
    """Unix 时间戳 → 可读时间."""
    if ts is None:
        return "N/A"
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _fmt_kurtosis(kurt):
    """将峭度数值转译为分布形态的人话描述."""
    if kurt is None:
        return "N/A"
    try:
        k = float(kurt)
    except (TypeError, ValueError):
        return str(kurt)
    if k > 1.5:
        return f"{k:.3f} (重尾 — 罕见极端事件频繁, 需警惕突发)"
    if k < 0.5:
        return f"{k:.3f} (近高斯 — 事件分布较均匀)"
    return f"{k:.3f} (轻尾 — 偶发极端事件)"


def _build_human_report_md(task_id: str) -> str:
    """生成人话版 Markdown 报告内容（供 /export/md 与 /export/html 复用）."""
    base = _task_summary(task_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Task not found")
    rich = _lookup_summary_by_task_id(task_id) or {}

    config = base.get("config") or {}
    params = base.get("params") or {}
    images = base.get("images", []) or []
    target_col = rich.get("target_col") or config.get("target_col") or "(未指定)"
    project_name = rich.get("project_name") or config.get("project_name") or "(默认)"
    intensity = rich.get("intensity") or "(未设置)"
    intensity_notes = rich.get("intensity_notes") or []
    intensity_params = rich.get("intensity_params") or {}

    # 数据集/样本信息 (从解释结果中提取, 若缺失则回退到 config)
    n_samples = rich.get("n_samples") or config.get("n_samples")
    unit = rich.get("unit") or "样本"
    available_variables = rich.get("available_variables") or []
    skipped_variables = rich.get("skipped_variables") or []
    lyap_reliable = rich.get("lyapunov_reliable_variables") or []

    lines = []
    lines.append(f"# EDM-Takens 分析报告: {task_id}\n")
    lines.append(f"> 自动生成 — 面向非技术读者的人话版解读.\n")
    lines.append(f"> _报告生成时间: {_fmt_timestamp(time.time())}_\n")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 1. 概览
    # ─────────────────────────────────────────────────────
    lines.append("## 1. 概览\n")
    lines.append(f"- **任务 ID**: `{task_id}`")
    lines.append(f"- **完成时间**: {_fmt_timestamp(base.get('updated_at'))}")
    lines.append(f"- **项目名称**: {project_name}")
    lines.append(f"- **数据源**: `{params.get('filename') or '(未记录)'}`")
    lines.append(f"- **目标变量**: `{target_col}`")
    if n_samples is not None:
        lines.append(f"- **样本量**: {n_samples} {unit}")
    if available_variables:
        lines.append(f"- **成功分析的变量**: {', '.join(f'`{v}`' for v in available_variables)}")
    if skipped_variables:
        lines.append(f"- **跳过的变量 (数据不足/近常量)**: {', '.join(f'`{v}`' for v in skipped_variables)}")
    lines.append(f"- **分析强度档位**: {intensity}")
    if intensity_params:
        q_disp = intensity_params.get("q", "自动")
        max_e_disp = intensity_params.get("max_e", "默认")
        auto_fix_disp = intensity_params.get("auto_fix", True)
        lines.append(f"  - 嵌入维度 q={q_disp}, 最大嵌入维度 max_e={max_e_disp}, 自动修正={auto_fix_disp}")
    if intensity_notes:
        lines.append(f"- **强度说明**:")
        for note in intensity_notes:
            lines.append(f"  - {note}")
    lines.append(f"- **生成图表数**: {len(images)} 张")
    if images:
        lines.append(f"  - 图表文件: {', '.join(f'`{img}`' for img in images)}")
    # 列映射说明 (display_map)
    column_mapping = rich.get("column_mapping")
    if column_mapping and isinstance(column_mapping, dict) and column_mapping:
        mapping_items = [f"`{k}` → `{v}`" for k, v in column_mapping.items() if k != v]
        if mapping_items:
            lines.append(f"- **列名映射** (内部→显示): {', '.join(mapping_items)}")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 2. 稳定性诊断
    # ─────────────────────────────────────────────────────
    lines.append("## 2. 稳定性诊断 (HAVOK)\n")
    lines.append("> HAVOK (HAVOK 分析) 通过奇异值分解重构系统动力学, "
                 "判断系统是稳定、近临界还是混沌.\n")
    havok = rich.get("havok") or {}
    if havok:
        tier = havok.get("stability_tier")
        lines.append(f"- **整体稳定性判定**: {_fmt_stability(tier)}")
        if havok.get("max_eigenvalue") is not None:
            try:
                max_ev = float(havok['max_eigenvalue'])
                lines.append(f"- **最大特征值 |λ_max|**: {max_ev:.4f}")
                # 人话解读: 特征值大小决定系统稳定性
                if max_ev < 0.05:
                    lines.append(f"  - _解读_: |λ_max| < 0.05 → 系统耗散, 稳定可预测.")
                elif max_ev < 0.5:
                    lines.append(f"  - _解读_: 0.05 ≤ |λ_max| < 0.5 → 近临界, 接近相变点.")
                else:
                    lines.append(f"  - _解读_: |λ_max| ≥ 0.5 → 系统混沌, 长期预测不可靠.")
            except (TypeError, ValueError):
                lines.append(f"- **最大特征值 |λ_max|**: {havok['max_eigenvalue']}")
        lines.append(f"- **HAVOK 秩 r**: {havok.get('rank')} (线性主导模态数, 越大表示系统越复杂)")
        # 解释方差占比
        try:
            ev = havok.get('explained_variance', 0)
            ev = float(ev) if ev is not None else 0.0
            lines.append(f"- **线性解释方差占比**: {ev * 100:.1f}%")
            lines.append(f"  - _解读_: 前 r 个模态能解释的方差比例, 越高表示线性近似越有效.")
        except (TypeError, ValueError):
            lines.append("- **线性解释方差占比**: N/A")
        # 回归 R²
        try:
            r2 = havok.get('regression_r2', 0)
            r2 = float(r2) if r2 is not None else 0.0
            lines.append(f"- **回归 R²**: {r2:.3f}")
            if r2 >= 0.8:
                lines.append(f"  - _解读_: R² ≥ 0.8 → 线性模型拟合良好.")
            elif r2 >= 0.5:
                lines.append(f"  - _解读_: 0.5 ≤ R² < 0.8 → 拟合一般, 非线性成分不可忽视.")
            else:
                lines.append(f"  - _解读_: R² < 0.5 → 线性拟合差, 非线性主导.")
        except (TypeError, ValueError):
            lines.append("- **回归 R²**: N/A")
        # 峭度
        kurt = havok.get('kurtosis')
        lines.append(f"- **强迫项峭度**: {_fmt_kurtosis(kurt)}")
        # 采样充分性
        sampling_adequacy = havok.get('sampling_adequacy')
        if sampling_adequacy is not None:
            try:
                sa = float(sampling_adequacy)
                if sa >= 0.8:
                    sa_desc = "充分 — 结论可信"
                elif sa >= 0.5:
                    sa_desc = "勉强 — 结论应谨慎解读"
                else:
                    sa_desc = "不足 — 结论可能不可靠, 建议增加样本量"
                lines.append(f"- **采样充分性**: {sa:.3f} ({sa_desc})")
            except (TypeError, ValueError):
                lines.append(f"- **采样充分性**: {sampling_adequacy}")
        # 条件数诊断
        cond_raw = havok.get("condition_number_raw")
        if cond_raw is None:
            cond_str = havok.get("condition_number", "N/A")
            if cond_str not in (None, "N/A", "nan"):
                try:
                    cond_raw = float(cond_str)
                except (TypeError, ValueError):
                    cond_raw = None
        if cond_raw is not None and cond_raw == cond_raw:  # NaN check
            if cond_raw > 1e10:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ⚠️ **病态** — 特征值/稳定性结论可信度受损")
            elif cond_raw > 1e6:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ⚠️ 接近病态, 稳定性结论应谨慎解读")
            else:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ✓ 良好")
        if havok.get("is_degenerate"):
            lines.append("- ⚠️ **HAVOK 退化**: 信号近常量或样本量不足, 稳定性结论仅供参考.")
        lines.append("")
        lines.append("> **整体解读**: 稳定性分级告诉我们系统是 \"可预测的稳定系统\" 还是 \"不可预测的混沌系统\". "
                     "近临界意味着系统正在接近相变点, 一次小扰动可能引发结构性重组; "
                     "混沌则意味着长期预测不可靠, 需要缩短预测视野或增加数据.\n")
    else:
        lines.append("- 未提供 HAVOK 诊断信息 (可能因样本量不足或信号退化).\n")

    # ─────────────────────────────────────────────────────
    # 3. 各变量 EDM 预测技能
    # ─────────────────────────────────────────────────────
    lines.append("## 3. 各变量 EDM 预测技能\n")
    lines.append("> EDM (经验动态建模) 用过去状态预测未来值, "
                 "ρ (相关系数) 越接近 1 表示预测越准; "
                 "S-Map 的 θ 越大表示系统越非线性.\n")
    variables = rich.get("variables") or {}
    if variables:
        lines.append("| 变量 | Simplex ρ | S-Map 最大 ρ | 最佳 θ | 非线性? | 预测能力判定 |")
        lines.append("|------|-----------|-------------|--------|---------|-------------|")
        for var_name, m in variables.items():
            if not isinstance(m, dict):
                lines.append(f"| `{var_name}` | N/A | N/A | N/A | (数据缺失) | 无法判定 |")
                continue
            rho_s = _fmt_rho(m.get("rho_simplex"))
            rho_sm = _fmt_rho(m.get("rho_smap_max"))
            theta = m.get("theta_best")
            theta_str = f"{theta:.2f}" if theta is not None else "N/A"
            nonlin = "是 ✓" if m.get("is_nonlinear") else "否"
            # 预测能力人话判定
            rho_simplex = m.get("rho_simplex")
            if rho_simplex is not None and abs(rho_simplex) >= 0.7:
                skill = "强预测能力"
            elif rho_simplex is not None and abs(rho_simplex) >= 0.5:
                skill = "中等预测能力"
            elif rho_simplex is not None and abs(rho_simplex) >= 0.3:
                skill = "弱预测能力"
            else:
                skill = "几乎不可预测"
            lines.append(f"| `{var_name}` | {rho_s} | {rho_sm} | {theta_str} | {nonlin} | {skill} |")
        lines.append("")
        lines.append("> **解读**: ρ 越接近 1 表示预测越准. "
                     "若 S-Map ρ 显著高于 Simplex ρ, 说明系统具有非线性特征, "
                     "线性模型 (如 AR / VAR) 会严重低估其可预测性. "
                     "θ 为 S-Map 的最佳非线性参数, θ=0 为纯线性, θ 越大非线性越强.\n")
    else:
        lines.append("- 未提供变量级 EDM 指标.\n")

    # ─────────────────────────────────────────────────────
    # 4. CCM 因果链
    # ─────────────────────────────────────────────────────
    lines.append("## 4. CCM 因果链 (Sugihara 因果关系)\n")
    lines.append("> CCM (收敛交叉映射) 通过 \"能否从效应的流形预测原因\" 来判定因果方向. "
                 "收敛 + p 值显著 = 存在因果链.\n")
    ccm = rich.get("ccm") or {}
    ccm_directions = rich.get("ccm_directions") or []
    if ccm and ccm.get("pairs"):
        lines.append(f"- **测试对数**: {ccm.get('n_pairs', len(ccm['pairs']))}")
        lines.append(f"- **原始显著数 (p<0.05)**: {ccm.get('n_significant_raw', 0)}")
        lines.append(f"- **Bonferroni 校正后显著数**: {ccm.get('n_significant_corrected', 0)}")
        lines.append(f"- **多重假设校正方法**: {ccm.get('method', 'N/A')}")
        lines.append("")
        lines.append("| 源 → 目标 | p 值 | 校正后显著? | 收敛? | 最终 ρ | Spearman ρ | 方向判定 |")
        lines.append("|-----------|------|-------------|-------|--------|-----------|---------|")
        for p in ccm["pairs"]:
            if not isinstance(p, dict):
                lines.append(f"| (数据缺失) | N/A | N/A | N/A | N/A | N/A | N/A |")
                continue
            cause = p.get("cause", "?")
            effect = p.get("effect", "?")
            pval = p.get("p_value")
            pval_str = f"{pval:.4f}" if pval is not None else "N/A"
            sig = "是 ✓" if p.get("significant_corrected") else "否"
            conv = "是 ✓" if p.get("is_converging") else "否"
            final_rho = p.get("final_rho")
            final_rho_str = f"{final_rho:.4f}" if final_rho is not None else "N/A"
            spearman = p.get("spearman_rho")
            spearman_str = f"{spearman:.4f}" if spearman is not None else "N/A"
            # 方向判定 (优先从 ccm_directions 取, 其次从 pair verdict 取)
            direction = None
            for d in ccm_directions:
                if isinstance(d, dict) and d.get("cause") == cause and d.get("effect") == effect:
                    direction = d.get("direction")
                    break
            if direction is None:
                direction = p.get("verdict") or "未判定"
            dir_str = _fmt_direction(direction)
            lines.append(f"| `{cause}` → `{effect}` | {pval_str} | {sig} | {conv} | {final_rho_str} | {spearman_str} | {dir_str} |")
        lines.append("")
        lines.append("> **解读**: ")
        lines.append("> - **p 值**: 越小越显著, p<0.05 为显著, Bonferroni 校正后更严格.")
        lines.append("> - **收敛 (converging)**: 库大小增加时 ρ 是否收敛, 收敛=存在因果链.")
        lines.append("> - **最终 ρ**: 收敛时的最大相关系数, 越高因果链越强.")
        lines.append("> - **Spearman ρ**: 单调相关性, 辅助验证线性关系强度.")
        lines.append("> - **方向判定**: forward=源→目标, reverse=目标→源, bidirectional=双向耦合.\n")
    else:
        lines.append("- 未提供 CCM 因果分析结果 (可能因样本量不足或变量对数 < 2).\n")

    # ─────────────────────────────────────────────────────
    # 5. 图谱解析 (新增 — P1 修复 Round 24 §1)
    # ─────────────────────────────────────────────────────
    lines.append("## 5. 图谱解析 (dynamics_interpretation.png)\n")
    has_interp_img = any("dynamics_interpretation" in img or "interpretation" in img.lower() for img in images)
    if has_interp_img:
        interp_img_name = next(
            (img for img in images if "dynamics_interpretation" in img or "interpretation" in img.lower()),
            "dynamics_interpretation.png"
        )
        lines.append(f"> 任务结果目录中包含图谱文件 `{interp_img_name}`, "
                     "该图通过 SovereignHAVOK + EDM + CCM 三件套生成, "
                     "包含以下面板:\n")
        lines.append("### 5.1 面板含义解读\n")
        lines.append("- **时序面板** (左列): 各变量的原始时间序列, 展示数据本身的波动模式.")
        lines.append("- **强迫项面板** (右列): HAVOK 提取的 v_r 强迫项, "
                     "代表系统无法用线性模态解释的 \"外部扰动\". "
                     "峭度越高表示极端事件越频繁.")
        lines.append("- **特征值谱**: 离散特征值 λ_d 的分布, "
                     "|λ_max| 决定系统稳定性 (见第 2 节).")
        lines.append("- **CCM 收敛曲线**: 库大小 L → ρ 的关系, "
                     "曲线上升并收敛 = 存在因果链; 平坦 = 无因果.")
        lines.append("- **S-Map 非线性曲线**: θ → ρ 的关系, "
                     "θ 增大时 ρ 上升 = 系统非线性; 平坦 = 系统线性.")
        lines.append("- **综合摘要面板**: 文字形式的稳定性分级、重尾变量、显著因果对数.")
        lines.append("")
        # 5.2 基于可用数据的图谱内容解读
        lines.append("### 5.2 本次图谱内容解读\n")
        if havok:
            tier = havok.get("stability_tier", "")
            try:
                if isinstance(tier, str) and ("Stable" in tier or "dissipative" in tier.lower()):
                    lines.append("- **稳定性面板**: 显示耗散特征值, 系统会自发回归平衡 — 稳定可预测.")
                elif isinstance(tier, str) and ("Near-critical" in tier or "near-critical" in tier.lower()):
                    lines.append("- **稳定性面板**: 特征值接近临界, 系统可能在扰动下发生结构性重组.")
                elif isinstance(tier, str) and ("Chaotic" in tier or "Divergent" in tier):
                    lines.append("- **稳定性面板**: 特征值发散, 系统混沌 — 长期预测不可靠.")
                else:
                    lines.append(f"- **稳定性面板**: {tier}")
            except Exception:
                lines.append(f"- **稳定性面板**: {tier}")
        if variables:
            nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
            total = len(variables)
            lines.append(f"- **S-Map 非线性面板**: {nonlin_count}/{total} 个变量呈现非线性特征 "
                         f"({'需用非线性模型' if nonlin_count > 0 else '可用线性模型近似'}).")
        if ccm and ccm.get("pairs"):
            n_conv = sum(1 for p in ccm["pairs"] if isinstance(p, dict) and p.get("is_converging"))
            n_total = len(ccm["pairs"])
            lines.append(f"- **CCM 收敛面板**: {n_conv}/{n_total} 对变量呈现收敛 (存在因果链).")
            n_sig = ccm.get("n_significant_corrected", 0)
            lines.append(f"- **统计显著性**: Bonferroni 校正后 {n_sig} 对显著 (p<0.05).")
        if lyap_reliable:
            lines.append(f"- **李雅普诺夫指数面板**: 变量 {', '.join(f'`{v}`' for v in lyap_reliable)} "
                         f"的李雅普诺夫指数可靠 — 可估算预测视野.")
        elif n_samples is not None and isinstance(n_samples, (int, float)) and n_samples < 100:
            lines.append("- **李雅普诺夫指数面板**: 样本量不足 (<100), 无法可靠估算 — 建议增加数据.")
        lines.append("")
        lines.append("> **如何阅读图谱**: 对照本节解读查看 `dynamics_interpretation.png`, "
                     "图中的颜色与变量一一对应, 上方为时序, 下方为强迫项. "
                     "若需查看大图, 在 Web 控制台点击历史任务的 \"查看\" 按钮.\n")
    else:
        lines.append("- 本次任务结果目录中未找到 `dynamics_interpretation.png` 图谱文件. "
                     "可能因解释阶段被跳过 (例如 Stage 1 失败导致 Stage 3 跳过).")
        lines.append("")
        # 即便没有图谱, 仍然根据已有数据给出文字解读
        if havok or variables or ccm:
            lines.append("### 5.1 基于数据的文字解读\n")
            if havok:
                lines.append(f"- **稳定性**: {_fmt_stability(havok.get('stability_tier'))}")
            if variables:
                nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
                lines.append(f"- **非线性**: {nonlin_count}/{len(variables)} 个变量呈现非线性.")
            if ccm and ccm.get("pairs"):
                n_conv = sum(1 for p in ccm["pairs"] if isinstance(p, dict) and p.get("is_converging"))
                lines.append(f"- **因果链**: {n_conv}/{len(ccm['pairs'])} 对收敛.")
            lines.append("")

    # ─────────────────────────────────────────────────────
    # 6. 八正道审计 (新增 — P1 修复 Round 24 §1, 重命名自原 "后审计")
    # ─────────────────────────────────────────────────────
    lines.append("## 6. 八正道审计 (Eightfold Path Audit)\n")
    lines.append("> 八正道审计是 EDM 流水线的最后一道质量关卡, "
                 "从 8 个维度检查分析是否可信: "
                 "数据质量、样本量、嵌入维度、HAVOK 退化、CCM 收敛、多重假设校正、"
                 "可复现性、数值稳定性. 通过 = 可信, 警告 = 可参考, 失败 = 不可信.\n")
    pa_verdict = rich.get("post_audit_verdict")
    if pa_verdict:
        # 裁决中文映射
        verdict_cn = {
            "PASS": "通过 ✓ — 分析结果可信",
            "PASS_WITH_NOTES": "通过 (附说明) ✓ — 可信但需关注警告",
            "WARN": "警告 ▲ — 结果可参考但存在隐患",
            "FAIL": "未通过 ✗ — 结果不可信, 建议重做",
            "BLOCKED": "阻断 ✗ — 流水线被阻断, 无法完成",
            "INCONCLUSIVE": "无法判定 ▲ — 数据不足以裁决",
        }
        verdict_disp = verdict_cn.get(str(pa_verdict).upper(), str(pa_verdict))
        lines.append(f"- **审计裁决**: {verdict_disp}")
        if rich.get("post_audit_passed") is not None:
            passed = "通过 ✓" if rich.get("post_audit_passed") else "未通过 ✗"
            lines.append(f"- **是否通过**: {passed}")
        # 警告项
        warns_raw = rich.get("post_audit_warnings")
        warn_count = rich.get("post_audit_warning_count")
        if isinstance(warns_raw, (list, tuple)):
            warns = list(warns_raw)
            if warn_count is None:
                warn_count = len(warns)
        elif isinstance(warns_raw, int):
            warns = []
            if warn_count is None:
                warn_count = warns_raw
        else:
            warns = []
            if warn_count is None:
                warn_count = 0
        if warns:
            lines.append(f"- **警告项** ({warn_count} 项):")
            for w in warns:
                lines.append(f"  - ⚠️ {w}")
        elif warn_count:
            lines.append(f"- **警告项**: {warn_count} 项 (历史数据未保存消息)")

        # 失败项
        fails_raw = rich.get("post_audit_failures")
        fail_count = rich.get("post_audit_failure_count")
        if isinstance(fails_raw, (list, tuple)):
            fails = list(fails_raw)
            if fail_count is None:
                fail_count = len(fails)
        elif isinstance(fails_raw, int):
            fails = []
            if fail_count is None:
                fail_count = fails_raw
        else:
            fails = []
            if fail_count is None:
                fail_count = 0
        if fails:
            lines.append(f"- **失败项** ({fail_count} 项):")
            for f in fails:
                lines.append(f"  - ✗ {f}")
        elif fail_count:
            lines.append(f"- **失败项**: {fail_count} 项 (历史数据未保存消息)")
        lines.append("")
        lines.append("> **解读**: 警告 (WARN) 表示分析可进行但需关注隐患; "
                     "失败 (FAIL) 表示对应环节不可信, 下游结论应作废. "
                     "通过 (PASS) 仅代表审计未发现问题, 不保证结论 \"正确\" — 仍需结合领域知识判断.\n")
    else:
        lines.append("- 八正道审计: 未运行 (可能因 Stage 1 失败导致审计被跳过).\n")

    # ─────────────────────────────────────────────────────
    # 7. 数据质量与采样充分性
    # ─────────────────────────────────────────────────────
    lines.append("## 7. 数据质量与采样充分性\n")
    dq_warn = rich.get("data_quality_warning")
    if dq_warn:
        lines.append(f"- ⚠️ **数据质量警告**: {dq_warn}")
    else:
        lines.append("- **数据质量**: 无警告.")
    if n_samples is not None:
        try:
            n = int(n_samples)
            if n < 30:
                lines.append(f"- ⚠️ **样本量偏少** ({n} {unit}): EDM 建议 N≥30, 当前处于下限, 结论仅供参考.")
            elif n < 100:
                lines.append(f"- **样本量** ({n} {unit}): 勉强可用, 李雅普诺夫指数无法可靠估算, 建议 N≥100.")
            else:
                lines.append(f"- **样本量** ({n} {unit}): 充足, 各项诊断均可信.")
        except (TypeError, ValueError):
            lines.append(f"- **样本量**: {n_samples}")
    if skipped_variables:
        lines.append(f"- **跳过的变量** ({len(skipped_variables)} 个): "
                     f"{', '.join(f'`{v}`' for v in skipped_variables)} — 数据不足或近常量, 无法分析.")
    if havok and havok.get("is_degenerate"):
        lines.append("- ⚠️ **HAVOK 退化**: 信号近常量, 强迫项/特征值诊断无意义.")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 8. 配置参数附录
    # ─────────────────────────────────────────────────────
    lines.append("## 8. 配置参数附录\n")
    if config:
        lines.append("### 8.1 运行配置 (PipelineConfig)\n")
        lines.append("| 参数 | 值 | 含义 |")
        lines.append("|------|----|------|")
        # 中文参数说明映射
        config_cn = {
            "data_path": "数据文件路径",
            "n_samples": "样本量",
            "n_variables": "变量数",
            "target_col": "目标变量",
            "columns": "分析变量列表",
            "E": "嵌入维度",
            "tau": "时间延迟",
            "theta": "S-Map 非线性参数",
            "q": "HAVOK 延迟嵌入维度",
            "r": "HAVOK 秩",
            "energy_threshold": "能量阈值",
            "dt": "时间步长",
            "window_length": "SVD 窗口长度",
            "poly_order": "多项式阶数",
            "basis": "HAVOK 基函数",
            "n_surrogates": "代理样本数",
            "surrogate_method": "代理检验方法",
            "timestamp": "运行时间戳",
            "analysis_type": "分析类型",
            "random_seed": "随机种子",
            "audit_verdict": "审计裁决",
            "audit_findings_summary": "审计发现摘要",
        }
        for k in sorted(config.keys()):
            v = config[k]
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            cn_desc = config_cn.get(k, "")
            lines.append(f"| `{k}` | `{v}` | {cn_desc} |")
        lines.append("")
    if params:
        lines.append("### 8.2 任务输入参数\n")
        lines.append("| 参数 | 值 | 含义 |")
        lines.append("|------|----|------|")
        params_cn = {
            "filename": "数据文件名",
            "target_col": "目标变量",
            "selected_vars": "选中变量",
            "q": "嵌入维度",
            "max_e": "最大嵌入维度",
            "intensity": "分析强度档位",
            "project_name": "项目名称",
            "auto_fix": "自动修正次优配置",
        }
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            cn_desc = params_cn.get(k, "")
            lines.append(f"| `{k}` | `{v}` | {cn_desc} |")
        lines.append("")

    # ─────────────────────────────────────────────────────
    # 9. 一句话总结
    # ─────────────────────────────────────────────────────
    lines.append("## 9. 一句话总结\n")
    summary_parts = []
    if havok:
        tier = havok.get("stability_tier", "") or ""
        if not isinstance(tier, str):
            tier = str(tier) if tier is not None else ""
        if "Stable" in tier or "dissipative" in tier.lower():
            summary_parts.append("系统稳定可预测")
        elif "Near-critical" in tier or "near-critical" in tier.lower():
            summary_parts.append("系统接近临界点, 警惕突发重组")
        elif "Chaotic" in tier or "Divergent" in tier:
            summary_parts.append("系统混沌, 长期预测不可靠")
    if ccm and ccm.get("n_significant_corrected", 0) > 0:
        summary_parts.append(f"识别出 {ccm['n_significant_corrected']} 条显著因果链 (Bonferroni 校正后)")
    elif ccm:
        summary_parts.append("未识别出显著因果链")
    if variables:
        nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
        if nonlin_count > 0:
            summary_parts.append(f"{nonlin_count}/{len(variables)} 个变量呈非线性")
    if pa_verdict:
        if str(pa_verdict).upper() in ("FAIL", "BLOCKED"):
            summary_parts.append("八正道审计未通过, 结果不可信")
        elif str(pa_verdict).upper() == "WARN":
            summary_parts.append("八正道审计警告, 结果可参考但存在隐患")

    if summary_parts:
        lines.append("**" + "; ".join(summary_parts) + ".**")
    else:
        lines.append("_数据不足, 无法给出总结._")
    lines.append("")
    lines.append("---")
    lines.append(f"_报告由 EDM-Takens Web 自动生成于 {_fmt_timestamp(time.time())}._")
    lines.append(f"_如需查看原始图表, 请在 Web 控制台打开任务 `{task_id}`._")

    md_content = "\n".join(lines)

    # P1 fix (Round 25 §2): 实际落盘到任务结果目录, 而非仅声称落盘.
    try:
        task_dir = _safe_task_path(task_id, RESULTS_DIR)
        if task_dir and os.path.isdir(task_dir):
            report_path = os.path.join(task_dir, "report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(md_content)
    except Exception:
        pass  # 落盘失败不影响浏览器展示

    return md_content


@router.get("/api/history/{task_id}/export/md", dependencies=[Depends(require_auth_optional)])
def export_task_md(task_id: str):
    """导出人话版 Markdown 报告 — 面向非技术读者."""
    md_content = _build_human_report_md(task_id)
    # P2 fix (Round 24 §10): 改为直接展示 (无 Content-Disposition: attachment),
    # 让浏览器在新标签页中显示 Markdown, 不触发下载.
    return StreamingResponse(
        io.BytesIO(md_content.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
    )


def _md_to_html(md: str) -> str:
    """极简 Markdown → HTML，仅支持本项目报告用到的语法.

    不引入外部 Markdown 库，避免依赖膨胀。
    """
    lines = md.split('\n')
    out = []
    i = 0
    in_ul = False
    in_ol = False

    def escape(s: str) -> str:
        return html.escape(s, quote=True)

    def inline(s: str) -> str:
        s = escape(s)
        s = s.replace('\\*', '\x00asterisk\x00')
        s = s.replace('\\`', '\x00backtick\x00')
        s = s.replace('\\_', '\x00underscore\x00')
        # code
        s = re.sub(r'`([^`]*)`', r'<code>\1</code>', s)
        # bold
        s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
        # italic
        s = re.sub(r'_([^_]+)_', r'<em>\1</em>', s)
        s = s.replace('\x00asterisk\x00', '*').replace('\x00backtick\x00', '`').replace('\x00underscore\x00', '_')
        return s

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append('</ul>')
            in_ul = False
        if in_ol:
            out.append('</ol>')
            in_ol = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.lstrip()

        # 空行
        if not stripped:
            close_lists()
            i += 1
            continue

        # 表格
        if stripped.startswith('|') and stripped.endswith('|'):
            close_lists()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2:
                header = [c.strip() for c in table_lines[0].split('|')[1:-1]]
                body_rows = []
                for r in table_lines[2:]:
                    cells = [c.strip() for c in r.split('|')[1:-1]]
                    if cells:
                        body_rows.append(cells)
                if header and body_rows:
                    out.append('<table>')
                    out.append('<thead><tr>' + ''.join(f'<th>{inline(h)}</th>' for h in header) + '</tr></thead>')
                    out.append('<tbody>')
                    for row in body_rows:
                        out.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in row) + '</tr>')
                    out.append('</tbody></table>')
            continue

        # 无序列表
        m = re.match(r'^(\s*)[-*]\s+(.*)', raw)
        if m:
            if in_ol:
                out.append('</ol>')
                in_ol = False
            if not in_ul:
                out.append('<ul>')
                in_ul = True
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        # 有序列表
        m = re.match(r'^(\s*)\d+\.\s+(.*)', raw)
        if m:
            if in_ul:
                out.append('</ul>')
                in_ul = False
            if not in_ol:
                out.append('<ol>')
                in_ol = True
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        close_lists()

        # 引用
        if stripped.startswith('>'):
            out.append(f'<blockquote>{inline(stripped[1:].strip())}</blockquote>')
            i += 1
            continue

        # 标题
        if stripped.startswith('# '):
            out.append(f'<h1>{inline(stripped[2:])}</h1>')
            i += 1
            continue
        if stripped.startswith('## '):
            out.append(f'<h2>{inline(stripped[3:])}</h2>')
            i += 1
            continue
        if stripped.startswith('### '):
            out.append(f'<h3>{inline(stripped[4:])}</h3>')
            i += 1
            continue
        if stripped.startswith('#### '):
            out.append(f'<h4>{inline(stripped[5:])}</h4>')
            i += 1
            continue

        # 段落
        out.append(f'<p>{inline(line)}</p>')
        i += 1

    close_lists()
    return '\n'.join(out)


# P2 (§20.12): 新增 HTML 版人话报告端点，便于浏览器直接查看格式化的报告.
@router.get("/api/history/{task_id}/export/html", dependencies=[Depends(require_auth_optional)])
def export_task_html(task_id: str):
    """导出人话版报告的 HTML 版本 — 暗色主题，便于浏览器直接阅读."""
    base = _task_summary(task_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # 复用 Markdown 生成逻辑（直接取字符串，避免操作 StreamingResponse）
    md_content = _build_human_report_md(task_id)

    html_body = _md_to_html(md_content)
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>EDM-Takens 人话版报告 — {task_id}</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --panel: #111827;
      --panel-solid: #0f1520;
      --border: #1f2a36;
      --text: #d1d5db;
      --muted: #94a3b8;
      --dept-color: #00ff9d;
      --dept-color-rgb: 0, 255, 157;
      --dept-dim: #00cc7d;
      --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: "JetBrains Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.6;
    }}
    .report-wrap {{
      max-width: 960px;
      margin: 0 auto;
      border: 1px solid rgba(var(--dept-color-rgb), 0.25);
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.32);
      padding: 24px;
      box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.3);
    }}
    h1, h2, h3, h4 {{
      color: var(--dept-color);
      font-weight: 700;
      margin-top: 1.4em;
      margin-bottom: 0.6em;
    }}
    h1 {{ font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4em; margin-top: 0; }}
    h2 {{ font-size: 1.15rem; border-left: 3px solid var(--dept-color); padding-left: 10px; }}
    h3 {{ font-size: 1rem; color: var(--dept-dim); }}
    h4 {{ font-size: 0.95rem; color: var(--muted); }}
    p {{ margin: 0.6em 0; }}
    a {{ color: var(--dept-color); text-decoration: underline; text-underline-offset: 2px; }}
    ul, ol {{ margin: 0.6em 0; padding-left: 1.4em; }}
    li {{ margin-bottom: 0.35em; }}
    blockquote {{
      margin: 1em 0;
      padding: 10px 14px;
      border-left: 3px solid var(--dept-color);
      background: rgba(var(--dept-color-rgb), 0.06);
      color: var(--muted);
    }}
    code {{
      background: rgba(255, 255, 255, 0.08);
      padding: 2px 5px;
      border-radius: 4px;
      font-family: var(--font-mono);
      color: var(--dept-dim);
      font-size: 0.9em;
    }}
    pre {{
      background: var(--panel-solid);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      font-family: var(--font-mono);
      font-size: 0.85em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1em 0;
      font-size: 0.9em;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{
      background: rgba(var(--dept-color-rgb), 0.08);
      color: var(--dept-color);
      font-weight: 600;
    }}
    tr:nth-child(even) td {{ background: rgba(255, 255, 255, 0.02); }}
    strong {{ color: var(--dept-dim); }}
    .meta {{ color: var(--muted); font-size: 0.85em; margin-bottom: 1em; }}
    .footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85em; text-align: center; }}
    @media (max-width: 640px) {{
      body {{ padding: 12px; }}
      .report-wrap {{ padding: 16px; }}
      table {{ font-size: 0.8em; }}
      th, td {{ padding: 4px 5px; }}
    }}
  </style>
</head>
<body>
  <div class="report-wrap">
    {html_body}
    <div class="footer">报告由 EDM-Takens Web 自动生成 | task {task_id}</div>
  </div>
</body>
</html>"""
    return StreamingResponse(
        io.BytesIO(html_content.encode("utf-8")),
        media_type="text/html; charset=utf-8",
    )
