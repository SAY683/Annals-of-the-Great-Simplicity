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
    """compare_tasks 端点的请求体模型."""
    task_ids: List[str] = Field(..., min_items=2, max_items=2, description="必须包含恰好 2 个任务 ID")


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
    """Return side-by-side summaries and image lists for two tasks.

    Accepts either ``{task_ids: [id1, id2]}`` or ``{left_id, right_id}``.
    """
    # P0-7 (Round 21 §P0-A): 用 Pydantic 模型替换裸 dict 校验
    # 支持两种入参形态, 优先 task_ids, 回退 left_id/right_id
    task_ids = body.get("task_ids") or []
    if not isinstance(task_ids, list) or len(task_ids) != 2:
        left_id = body.get("left_id")
        right_id = body.get("right_id")
        if left_id and right_id:
            task_ids = [left_id, right_id]
        else:
            raise HTTPException(status_code=400, detail="task_ids 必须包含 2 个元素, 或同时提供 left_id 和 right_id")
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
    return {"task_ids": task_ids, "left_task": summaries[0], "right_task": summaries[1], "summaries": summaries}


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
    }
    return mapping.get(tier, tier)


def _fmt_timestamp(ts):
    """Unix 时间戳 → 可读时间."""
    if ts is None:
        return "N/A"
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


@router.get("/api/history/{task_id}/export/md", dependencies=[Depends(require_auth_optional)])
def export_task_md(task_id: str):
    """导出人话版 Markdown 报告 — 面向非技术读者.

    报告结构:
      1. 概览 (任务 ID, 时间, 数据集, 目标变量)
      2. 稳定性诊断 (HAVOK 分级 + 解读)
      3. 各变量 EDM 技能 (ρ + 非线性判定)
      4. CCM 因果链 (源→目标 + 收敛判定 + p 值)
      5. 数据质量与后审计
      6. 配置参数 (附录)
    """
    base = _task_summary(task_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Task not found")
    rich = _lookup_summary_by_task_id(task_id) or {}

    config = base.get("config") or {}
    params = base.get("params") or {}
    target_col = rich.get("target_col") or config.get("target_col") or "(未指定)"
    project_name = rich.get("project_name") or config.get("project_name") or "(默认)"
    intensity = rich.get("intensity") or "(未设置)"
    intensity_notes = rich.get("intensity_notes") or []

    lines = []
    lines.append(f"# EDM-Takens 分析报告: {task_id}\n")
    lines.append(f"> 自动生成 — 面向非技术读者的人话版解读.\n")
    lines.append("")

    # 1. 概览
    lines.append("## 1. 概览\n")
    lines.append(f"- **任务 ID**: `{task_id}`")
    lines.append(f"- **完成时间**: {_fmt_timestamp(base.get('updated_at'))}")
    lines.append(f"- **项目**: {project_name}")
    lines.append(f"- **目标变量**: `{target_col}`")
    lines.append(f"- **分析强度档位**: {intensity}")
    if intensity_notes:
        lines.append(f"- **强度说明**: {'; '.join(map(str, intensity_notes))}")
    lines.append(f"- **生成图表数**: {len(base.get('images', []))}")
    lines.append("")

    # 2. 稳定性诊断
    lines.append("## 2. 稳定性诊断\n")
    havok = rich.get("havok") or {}
    if havok:
        tier = havok.get("stability_tier")
        lines.append(f"- **整体判定**: {_fmt_stability(tier)}")
        if havok.get("max_eigenvalue") is not None:
            lines.append(f"- **最大特征值 |λ_max|**: {havok['max_eigenvalue']:.4f}")
            lines.append(f"  - |λ_max| < 0.05 → 稳定/近临界; |λ_max| ≥ 0.05 → 混沌.")
        lines.append(f"- **HAVOK 秩 r**: {havok.get('rank')} (线性主导模态数)")
        lines.append(f"- **线性解释方差占比**: {havok.get('explained_variance', 0) * 100:.1f}%")
        lines.append(f"- **回归 R²**: {havok.get('regression_r2', 0):.3f}")
        lines.append(f"- **峭度**: {havok.get('kurtosis', 0):.3f} (>3 表示重尾, 罕见事件频繁)")
        # P0-2 修复 (Round 21 §P0-C): 暴露 condition_number 诊断.
        # sovereign_havok.py 已计算 condition_number (L624/L677/L692),
        # 论文已披露 5.5×10¹² 病态问题, cond > 1e10 时特征值计算可能有 10 位有效数字丢失.
        cond_raw = havok.get("condition_number_raw")
        if cond_raw is None:
            # 尝试从字符串字段解析
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
        lines.append("> **解读**: 稳定性分级告诉我们系统是 \"可预测的稳定系统\" 还是 \"不可预测的混沌系统\". "
                     "近临界意味着系统正在接近相变点, 一次小扰动可能引发结构性重组.\n")
    else:
        lines.append("- 未提供 HAVOK 诊断信息 (可能因样本量不足或信号退化).\n")

    # 3. 各变量 EDM 技能
    lines.append("## 3. 各变量 EDM 预测技能\n")
    variables = rich.get("variables") or {}
    if variables:
        lines.append("| 变量 | 简单x粗 ρ | S-Map 最大 ρ | 最佳 θ | 非线性? |")
        lines.append("|------|-----------|-------------|--------|---------|")
        for var_name, m in variables.items():
            rho_s = _fmt_rho(m.get("rho_simplex"))
            rho_sm = _fmt_rho(m.get("rho_smap_max"))
            theta = m.get("theta_best")
            theta_str = f"{theta:.2f}" if theta is not None else "N/A"
            nonlin = "是 ✓" if m.get("is_nonlinear") else "否"
            lines.append(f"| `{var_name}` | {rho_s} | {rho_sm} | {theta_str} | {nonlin} |")
        lines.append("")
        lines.append("> **解读**: ρ 越接近 1 表示预测越准. "
                     "若 S-Map ρ 显著高于简单x粗 ρ, 说明系统具有非线性特征, "
                     "线性模型 (如 AR / VAR) 会严重低估其可预测性.\n")
    else:
        lines.append("- 未提供变量级 EDM 指标.\n")

    # 4. CCM 因果链
    lines.append("## 4. CCM 因果链 (Sugihara 因果关系)\n")
    ccm = rich.get("ccm") or {}
    if ccm and ccm.get("pairs"):
        lines.append(f"- **测试对数**: {ccm.get('n_pairs', len(ccm['pairs']))}")
        lines.append(f"- **原始显著数 (p<0.05)**: {ccm.get('n_significant_raw', 0)}")
        lines.append(f"- **Bonferroni 校正后显著数**: {ccm.get('n_significant_corrected', 0)}")
        lines.append(f"- **多重假设校正方法**: {ccm.get('method', 'N/A')}")
        lines.append("")
        lines.append("| 源 → 目标 | p 值 | 校正后显著? | 收敛? | 判定 |")
        lines.append("|-----------|------|-------------|-------|------|")
        for p in ccm["pairs"]:
            cause = p.get("cause", "?")
            effect = p.get("effect", "?")
            pval = p.get("p_value")
            pval_str = f"{pval:.4f}" if pval is not None else "N/A"
            sig = "是 ✓" if p.get("significant_corrected") else "否"
            conv = "是 ✓" if p.get("is_converging") else "否"
            verdict = p.get("verdict") or "未判定"
            lines.append(f"| `{cause}` → `{effect}` | {pval_str} | {sig} | {conv} | {verdict} |")
        lines.append("")
        lines.append("> **解读**: CCM 通过 \"能否从效应的流形预测原因\" 来判定因果方向. "
                     "收敛 (converging) + p 值显著 = 存在因果链; "
                     "Bonferroni 校正后仍显著 = 多重假设检验下仍稳健.\n")
    else:
        lines.append("- 未提供 CCM 因果分析结果 (可能因样本量不足或变量对数 < 2).\n")

    # 5. 数据质量与后审计
    lines.append("## 5. 数据质量与后审计\n")
    dq_warn = rich.get("data_quality_warning")
    if dq_warn:
        lines.append(f"- ⚠️ **数据质量警告**: {dq_warn}")
    else:
        lines.append("- 数据质量: 无警告.")

    pa_verdict = rich.get("post_audit_verdict")
    if pa_verdict:
        lines.append(f"- **后审计判定**: {pa_verdict}")
        if rich.get("post_audit_passed") is not None:
            passed = "通过 ✓" if rich.get("post_audit_passed") else "未通过 ✗"
            lines.append(f"- **是否通过**: {passed}")
        warns = rich.get("post_audit_warnings") or []
        if warns:
            lines.append("- **警告项**:")
            for w in warns:
                lines.append(f"  - {w}")
        fails = rich.get("post_audit_failures") or []
        if fails:
            lines.append("- **失败项**:")
            for f in fails:
                lines.append(f"  - {f}")
    else:
        lines.append("- 后审计: 未运行.")
    lines.append("")

    # 6. 配置附录
    lines.append("## 6. 配置附录\n")
    if config:
        lines.append("### 运行配置\n")
        lines.append("| 参数 | 值 |")
        lines.append("|------|----|")
        for k, v in sorted(config.items()):
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"| `{k}` | `{v}` |")
        lines.append("")
    if params:
        lines.append("### 算法参数\n")
        lines.append("| 参数 | 值 |")
        lines.append("|------|----|")
        for k, v in sorted(params.items()):
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"| `{k}` | `{v}` |")
        lines.append("")

    # 7. 总结
    lines.append("## 7. 一句话总结\n")
    summary_parts = []
    if havok:
        tier = havok.get("stability_tier", "")
        if "Stable" in tier:
            summary_parts.append("系统稳定可预测")
        elif "Near-critical" in tier:
            summary_parts.append("系统接近临界点, 警惕突发重组")
        elif "Chaotic" in tier:
            summary_parts.append("系统混沌, 长期预测不可靠")
    if ccm and ccm.get("n_significant_corrected", 0) > 0:
        summary_parts.append(f"识别出 {ccm['n_significant_corrected']} 条显著因果链")
    elif ccm:
        summary_parts.append("未识别出显著因果链")
    if variables:
        nonlin_count = sum(1 for v in variables.values() if v.get("is_nonlinear"))
        if nonlin_count > 0:
            summary_parts.append(f"{nonlin_count}/{len(variables)} 个变量呈非线性")

    if summary_parts:
        lines.append("**" + "; ".join(summary_parts) + ".**")
    else:
        lines.append("_数据不足, 无法给出总结._")
    lines.append("")
    lines.append("---")
    lines.append(f"_报告由 EDM-Takens Web 自动生成于 {_fmt_timestamp(time.time())}._")

    md_content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(md_content.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{task_id}_report.md"',
        },
    )
