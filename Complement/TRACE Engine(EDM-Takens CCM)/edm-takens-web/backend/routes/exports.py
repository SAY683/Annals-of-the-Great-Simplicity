"""Task export routes."""
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from core.auth import require_auth_optional
from services import history_export
from services.summary_builder import _task_summary

router = APIRouter()


@router.get("/api/history/{task_id}/export/json", dependencies=[Depends(require_auth_optional)])
def export_task_json(task_id: str):
    summary = _task_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = history_export.summary_json(summary)
    return StreamingResponse(
        io.BytesIO(payload.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{task_id}_summary.json"'},
    )


@router.get("/api/history/{task_id}/export/csv", dependencies=[Depends(require_auth_optional)])
def export_task_csv(task_id: str):
    summary = _task_summary(task_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return StreamingResponse(
        io.BytesIO(history_export.summary_csv(summary)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{task_id}_summary.csv"'},
    )


@router.get("/api/history/{task_id}/export/md", dependencies=[Depends(require_auth_optional)])
def export_task_md(task_id: str):
    md_content = history_export.report_md(task_id)
    return StreamingResponse(
        io.BytesIO(md_content.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/api/history/{task_id}/export/html", dependencies=[Depends(require_auth_optional)])
def export_task_html(task_id: str):
    html_content = history_export.report_html(task_id)
    return StreamingResponse(
        io.BytesIO(html_content.encode("utf-8")),
        media_type="text/html; charset=utf-8",
    )
