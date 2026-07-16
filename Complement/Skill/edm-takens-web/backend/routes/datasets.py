"""
Routes — dataset management endpoints (debt-19).

Extracted from api.py using APIRouter. Handles file listing, upload,
column inspection, quality check, and embed-curve computation.
"""
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Request
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


@router.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@router.get("/api/datasets")
def list_datasets():
    return {"datasets": _list_uploaded_csvs()}


@router.post("/api/upload")
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
    dest = os.path.join(DATA_DIR, file.filename)
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


@router.get("/api/datasets/{filename}/columns")
def get_columns(filename: str):
    path = os.path.join(DATA_DIR, filename)
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


@router.get("/api/datasets/{filename}/recommend")
def recommend_analysis(filename: str, target_col: Optional[str] = None, variables: Optional[str] = None):
    """Return an automatic analysis-intensity recommendation for a dataset."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    profile = recommend_profile(df, target_col, selected_vars)
    return profile


@router.get("/api/datasets/{filename}/quality")
def data_quality(filename: str, target_col: Optional[str] = None, variables: Optional[str] = None):
    """Return per-column EDM readiness diagnostics (algorithmic soundness)."""
    csv_path, df, numeric_cols = _prepare_dataset(filename)
    target_col, selected_vars = _select_variables(df, numeric_cols, target_col, variables)
    report = evaluate_dataframe(df, target_col, selected_vars, all_numeric_cols=numeric_cols)
    return {"filename": filename, "target_col": target_col, "columns": report}


@router.get("/api/datasets/{filename}/embed_curve")
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
    lib = f"1 {n - 7}"
    pred = f"{n - 6} {n}"
    from _edm_bridge import EmbedDimension

    try:
        rho_E = EmbedDimension(
            data=df, lib=lib, pred=pred,
            maxE=max_e, Tp=1,
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
        "max_e": max_e,
        "E_values": E_values,
        "rho_values": rho_values,
        "optimal_E": best_E,
        "curve": [
            {"E": e, "rho": r} for e, r in zip(E_values, rho_values)
        ],
    }
