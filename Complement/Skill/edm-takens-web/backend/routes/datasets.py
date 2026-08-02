"""
Routes — dataset management endpoints (debt-19).

Extracted from api.py using APIRouter. Handles file listing, upload,
column inspection, quality check, and embed-curve computation.
"""
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse

from core.locks import DATA_DIR
from services.file_management import (
    _list_uploaded_csvs,
    _read_csv_robust,
    _prepare_dataset,
    _recommend_target,
    _select_variables,
    _MAX_UPLOAD_BYTES,
    _SNIFF_BYTES,
)
from analysis_profiles import recommend_profile
from data_quality import evaluate_dataframe

router = APIRouter()

# D-P0-4 修复 (Round 21 §P0-A): 全端点鉴权链.
# - GET 端点用 require_auth_optional (弱鉴权, 区分读写审计)
# - POST 端点用 require_auth (强鉴权)
# 本地开发 (EDM_API_KEY 未设置) 自动放行环回地址, 不影响 dev 体验.
from core.auth import require_auth, require_auth_optional


def _safe_data_path(filename: str) -> str:
    """Strip directory components from filenames to prevent path traversal."""
    safe = os.path.basename(filename)
    if safe != filename:
        raise HTTPException(status_code=400, detail="Invalid filename: path separators not allowed")
    full = os.path.abspath(os.path.join(DATA_DIR, safe))
    if not full.startswith(os.path.abspath(DATA_DIR) + os.sep) and full != os.path.abspath(DATA_DIR):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return full


@router.get("/api/health", dependencies=[Depends(require_auth_optional)])
def health():
    """健康检查 — 真实检查核心依赖项就绪情况.

    盲审 P1-4 修缮 (2026-08-02):
        原版仅返回固定字符串 {status:'ok', time}, 未检查任何依赖项就绪情况,
        违反"健康检查应反映真实状态"的工程惯例. 本版真实检查:
          1. data/ 目录可读写
          2. results/ 目录可写
          3. pyEDM / numpy 核心依赖可导入
          4. 数据集数量 (便于监控)
        返回三态: healthy / degraded / unhealthy
    """
    import os
    import sys
    checks = {}
    overall = "healthy"

    # 1. 数据目录可读写
    try:
        from core.locks import DATA_DIR
        if os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK | os.R_OK):
            checks["data_dir"] = "ok"
        else:
            checks["data_dir"] = "fail"
            overall = "degraded"
    except Exception as e:
        checks["data_dir"] = f"error: {type(e).__name__}"
        overall = "degraded"

    # 2. 结果目录可写
    try:
        from core.locks import RESULTS_DIR
        if os.path.isdir(RESULTS_DIR) and os.access(RESULTS_DIR, os.W_OK):
            checks["results_dir"] = "ok"
        else:
            checks["results_dir"] = "fail"
            overall = "degraded"
    except Exception as e:
        checks["results_dir"] = f"error: {type(e).__name__}"
        overall = "degraded"

    # 3. 核心依赖可导入 (numpy 是 EDM 必备)
    try:
        import numpy  # noqa: F401
        checks["numpy"] = f"ok ({numpy.__version__})"
    except Exception as e:
        checks["numpy"] = f"fail: {e}"
        overall = "unhealthy"

    # 4. pyEDM 可选依赖 (缺失时降级到 numpy fallback, 不算 unhealthy)
    try:
        import pyEDM  # noqa: F401
        checks["pyEDM"] = "ok"
    except ImportError:
        checks["pyEDM"] = "not_installed (using numpy fallback)"
        if overall == "healthy":
            overall = "degraded"
    except Exception as e:
        checks["pyEDM"] = f"error: {type(e).__name__}"
        if overall == "healthy":
            overall = "degraded"

    # 5. 数据集数量 (便于监控)
    try:
        ds_count = len(_list_uploaded_csvs())
        checks["datasets"] = ds_count
    except Exception:
        checks["datasets"] = "unknown"

    return {
        "status": overall,
        "time": datetime.utcnow().isoformat(),
        "checks": checks,
    }


@router.get("/api/datasets", dependencies=[Depends(require_auth_optional)])
def list_datasets():
    return {"datasets": _list_uploaded_csvs()}


@router.post("/api/upload", dependencies=[Depends(require_auth)])
def upload_file(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    # 1) 大小校验：先看 Content-Length 头部，提前拒绝超大请求
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大：声明大小 {int(declared)} 字节超过上限 "
                    f"{_MAX_UPLOAD_BYTES} 字节（50MB）",
                )
        except ValueError:
            pass  # 非法头部值，交给下面的逐块读取兜底

    # 2) 流式读取并校验：边写边统计字节数，并对首块做文本性探测，
    #    避免把二进制文件当作 CSV 落盘后误导后续解析。
    dest = _safe_data_path(file.filename)
    total = 0
    sniffed = b""
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = file.file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大：已超过上限 {_MAX_UPLOAD_BYTES} 字节（50MB）",
                    )
                if len(sniffed) < _SNIFF_BYTES:
                    sniffed = (sniffed + chunk)[:_SNIFF_BYTES]
                f.write(chunk)
    except HTTPException:
        # 失败时清理半成品文件
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise
    except Exception:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail="保存上传文件失败")

    # 3) 内容校验：探测头部是否含 NUL 字节等二进制特征
    if b"\x00" in sniffed:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise HTTPException(
            status_code=415,
            detail="文件内容不是文本：检测到 NUL 字节，疑似二进制文件，请确认上传 CSV 文本",
        )

    return {"filename": file.filename, "saved": True, "size": total}


@router.get("/api/datasets/{filename}/columns", dependencies=[Depends(require_auth_optional)])
def get_columns(filename: str):
    path = _safe_data_path(filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    df = _read_csv_robust(path)
    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    recommended_target = _recommend_target(numeric_cols, df=df)
    # 把 NaN / Inf 替换为 None（JSON null），避免 JSON 序列化报错
    import math
    preview = df.head(5).to_dict(orient="records")
    for row in preview:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
    return {
        "columns": list(df.columns),
        "numeric_columns": numeric_cols,
        "rows": len(df),
        "preview": preview,
        "recommended_target": recommended_target,
    }


@router.get("/api/datasets/{filename}/recommend", dependencies=[Depends(require_auth_optional)])
def recommend_analysis(filename: str, target_col: Optional[str] = None, variables: Optional[str] = None):
    """Return an automatic analysis-intensity recommendation for a dataset."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    profile = recommend_profile(df, target_col, selected_vars)
    return profile


@router.get("/api/datasets/{filename}/quality", dependencies=[Depends(require_auth_optional)])
def data_quality(filename: str, target_col: Optional[str] = None, variables: Optional[str] = None):
    """Return per-column EDM readiness diagnostics (algorithmic soundness)."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    try:
        report = evaluate_dataframe(df, target_col, selected_vars, all_numeric_cols=numeric_cols)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"数据质量评估失败: {type(e).__name__}: {e}",
        )
    # P0 fix: 清理 NaN/Infinity，避免 FastAPI JSON 序列化失败
    # (与 job_store.py 的 _sanitize_json 同类问题)
    import math

    def _sanitize(obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize(v) for v in obj]
        return obj

    return {"filename": filename, "target_col": target_col, "columns": _sanitize(report)}


@router.get("/api/datasets/{filename}/embed_curve", dependencies=[Depends(require_auth_optional)])
def embed_curve(
    filename: str,
    target_col: Optional[str] = None,
    max_e: int = 8,
):
    """Return the EmbedDimension rho(E) curve for confidence in embedding dimension."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, None)
    if target_col not in numeric_cols:
        raise HTTPException(status_code=400, detail="Target column must be numeric")

    n = len(df)

    # P0 fix: 小样本预检 — 与 pipeline.py 的 MIN_SAMPLES_HARD 保持一致。
    # N<10 时 lib 范围退化为 <=3 个点，EmbedDimension 数学上无法工作。
    if n < 10:
        raise HTTPException(
            status_code=400,
            detail=f"样本量 N={n} 不足，EmbedDimension 至少需要 10 个时间点"
                   f"（推荐 ≥30）。请收集更多数据后重试。",
        )

    # P1 fix: 小样本时 maxE 过大会导致 EmbedDimension 搜索到退化区域
    # (E=4, Tp=1, tau=-1 invalid for library)。与 pipeline.py 和
    # enhanced_cross_validate.py 的 auto-E-detection 保持一致：
    # maxE_effective = min(max_e, max(2, n // 5))
    max_e_effective = min(max_e, max(2, n // 5))

    # lib/pred 范围也需要根据 maxE_effective 动态调整，避免
    # n-7 < maxE_effective 时 lib 太小。
    lib_end = max(n - 7, max_e_effective + 2)
    if lib_end >= n:
        lib_end = n - 2
    if lib_end < 3:
        raise HTTPException(
            status_code=400,
            detail=f"样本量 N={n} 过小，无法构造有效的 lib/pred 分割",
        )
    lib = f"1 {lib_end}"
    pred = f"{lib_end + 1} {n}"
    from _edm_bridge import EmbedDimension

    try:
        rho_E = EmbedDimension(
            data=df, lib=lib, pred=pred,
            maxE=max_e_effective, Tp=1,
            columns=target_col, target=target_col,
            showPlot=False, numProcess=1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"EmbedDimension failed: {e}")

    E_values = []
    rho_values = []
    best_E = None
    best_rho = -float("inf")
    for _, row in rho_E.iterrows():
        e = int(row["E"])
        r = float(row["rho"]) if pd.notna(row["rho"]) else None
        E_values.append(e)
        rho_values.append(r)
        if r is not None and r > best_rho:
            best_rho = r
            best_E = e
    return {
        "filename": filename,
        "target_col": target_col,
        "max_e": max_e_effective,
        "max_e_requested": max_e,
        "n_samples": n,
        "E_values": E_values,
        "rho_values": rho_values,
        "optimal_E": best_E,
        "curve": [
            {"E": e, "rho": r} for e, r in zip(E_values, rho_values)
        ],
    }
