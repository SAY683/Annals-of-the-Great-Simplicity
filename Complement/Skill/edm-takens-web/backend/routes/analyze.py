"""
Routes — analysis execution endpoints (debt-19).

Extracted from api.py using APIRouter. Handles job submission (async and
blocking), status polling, log streaming, and result image serving.
"""
import os
import sys
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from core.locks import _BLOCKING_ENDPOINT_SLOT, RESULTS_DIR
from core.runtime import _JOB_STORE
# D-P0-4 修复 (Round 21 §P0-A): 全端点鉴权链.
from core.auth import require_auth, require_auth_optional
from job_store import _sanitize_json
from services.file_management import (
    _prepare_dataset,
    _select_variables,
    _resolve_analysis_params,
    _check_target_quality,
    _safe_task_path,
)

router = APIRouter()


@router.post("/api/analyze/jobs", dependencies=[Depends(require_auth)])
def create_analysis_job(
    filename: str = Form(...),
    target_col: Optional[str] = Form(None),
    variables: Optional[str] = Form(None),
    auto_fix: bool = Form(True),
    intensity: str = Form("medium"),
    project_name: Optional[str] = Form(None),
    q: Optional[int] = Form(None),
    max_e: Optional[int] = Form(None),
):
    """Submit an analysis job and return a job_id for polling/streaming."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    q, max_e, profile = _resolve_analysis_params(
        df, target_col, selected_vars, intensity, q, max_e
    )
    data_quality_warning, _ = _check_target_quality(df, target_col, selected_vars)

    job = _JOB_STORE.create({
        "filename": filename,
        "csv_path": csv_path,
        "target_col": target_col,
        "selected_vars": selected_vars,
        "auto_fix": auto_fix,
        "intensity": intensity,
        "project_name": project_name,
        "q": q,
        "max_e": max_e,
        "profile": profile,
        "data_quality_warning": data_quality_warning,
    })
    _JOB_STORE.spawn(job)
    response = {"job_id": job.id, "status": job.status, "profile": profile}
    if data_quality_warning:
        response["data_quality_warning"] = data_quality_warning
    return response


@router.get("/api/analyze/jobs/{job_id}", dependencies=[Depends(require_auth_optional)])
def get_job_status(job_id: str, limit_logs: int = 200):
    """Poll job status, latest logs and final result."""
    job = _JOB_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_public_dict(limit_logs=limit_logs)


@router.get("/api/analyze/jobs/{job_id}/stream", dependencies=[Depends(require_auth_optional)])
def stream_job(job_id: str):
    """Stream a job's logs as NDJSON."""
    return StreamingResponse(
        _JOB_STORE.events(job_id),
        media_type="application/x-ndjson",
    )


@router.post("/api/analyze", dependencies=[Depends(require_auth)])
def analyze(
    filename: str = Form(...),
    target_col: Optional[str] = Form(None),
    variables: Optional[str] = Form(None),
    auto_fix: bool = Form(True),
    intensity: str = Form("medium"),
    project_name: Optional[str] = Form(None),
    q: Optional[int] = Form(None),
    max_e: Optional[int] = Form(None),
):
    """Run the full EDM-Takens pipeline on an uploaded CSV (blocking)."""
    # P1 修复：阻塞端点并发限流——槽位满时立即返回 429，避免挂起耗尽线程池。
    if not _BLOCKING_ENDPOINT_SLOT.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=(
                "Server is currently processing another blocking analysis. "
                "Please retry later or use the streaming endpoint "
                "/api/analyze/stream."
            ),
        )
    try:
        csv_path, df, numeric_cols = _prepare_dataset(filename)
        target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
        q, max_e, profile = _resolve_analysis_params(
            df, target_col, selected_vars, intensity, q, max_e
        )
        data_quality_warning, _ = _check_target_quality(df, target_col, selected_vars)

        job = _JOB_STORE.create({
            "filename": filename,
            "csv_path": csv_path,
            "target_col": target_col,
            "selected_vars": selected_vars,
            "auto_fix": auto_fix,
            "intensity": intensity,
            "project_name": project_name,
            "q": q,
            "max_e": max_e,
            "profile": profile,
            "data_quality_warning": data_quality_warning,
        })
        _JOB_STORE.spawn(job)
        job._done.wait()

        if job.error:
            # P0-6 (Round 21 §P0-A): 不向客户端泄露内部错误细节
            # 完整错误写入 stderr 供运维排查, 客户端只收到通用文案
            print(f"[analyze:blocking] job error: {job.error}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raise HTTPException(status_code=500, detail="分析任务执行失败, 请查看服务端日志")

        response = {
            **_sanitize_json(job.result),
            "logs": "\n".join(job.logs),
        }
        if data_quality_warning:
            response["data_quality_warning"] = data_quality_warning
        return response
    finally:
        _BLOCKING_ENDPOINT_SLOT.release()


@router.get("/api/analyze/stream", dependencies=[Depends(require_auth_optional)])
def analyze_stream(
    filename: str,
    target_col: Optional[str] = None,
    variables: Optional[str] = None,
    auto_fix: bool = True,
    intensity: str = "medium",
    project_name: Optional[str] = None,
    q: Optional[int] = None,
    max_e: Optional[int] = None,
):
    """Run the full pipeline and stream stdout logs as NDJSON (convenience endpoint)."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    q, max_e, profile = _resolve_analysis_params(
        df, target_col, selected_vars, intensity, q, max_e
    )
    data_quality_warning, _ = _check_target_quality(df, target_col, selected_vars)

    job = _JOB_STORE.create({
        "filename": filename,
        "csv_path": csv_path,
        "target_col": target_col,
        "selected_vars": selected_vars,
        "auto_fix": auto_fix,
        "intensity": intensity,
        "project_name": project_name,
        "q": q,
        "max_e": max_e,
        "profile": profile,
        "data_quality_warning": data_quality_warning,
    })
    _JOB_STORE.spawn(job)
    return StreamingResponse(
        _JOB_STORE.events(job.id),
        media_type="application/x-ndjson",
    )


@router.get("/api/results/{image_path:path}", dependencies=[Depends(require_auth_optional)])
def get_image(image_path: str):
    """Serve a result image, optionally nested under a task directory."""
    # AUD-03: 路径遍历防护 — 复用 _safe_task_path 统一的安全检查函数，
    # 防止 "../../../etc/passwd" 等路径遍历攻击逃逸出 RESULTS_DIR。
    # _safe_task_path 会将 image_path 拼接到 RESULTS_DIR 下并做 abspath 规范化，
    # 若解析结果不在 RESULTS_DIR 子树内则返回 None。
    requested = _safe_task_path(image_path, RESULTS_DIR)
    if not requested:
        raise HTTPException(status_code=400, detail="Invalid image path")
    # 额外防护：拒绝请求根目录本身（image_path 为空或 "."），
    # 以及拒绝请求目录（FileResponse 不应服务目录）。
    if requested == os.path.abspath(RESULTS_DIR):
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not os.path.exists(requested):
        raise HTTPException(status_code=404, detail="Image not found")
    if os.path.isdir(requested):
        raise HTTPException(status_code=400, detail="Invalid image path")
    return FileResponse(requested)
