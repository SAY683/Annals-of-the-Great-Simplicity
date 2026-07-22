"""
EDM-Takens Web MVP — 数据质量 / 算法健全性诊断

对每一列计算可直接用于判断 EDM 适用性的指标，避免把 ID、常数、
极稀疏或近白噪声的列送进 embedding 阶段。
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# debt-22 audit 修复：复用 _usability.py 的基础可用性判定，
# 避免两套阈值漂移。data_quality 在基础检查之上叠加趋势/平稳性/异常值等综合条件。
from _usability import is_usable_for_edm


def _safe_lag1_autocorr(values: np.ndarray) -> float:
    """Lag-1 Pearson autocorrelation, ignoring NaNs."""
    x = values[:-1]
    y = values[1:]
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 5:
        return float("nan")
    xm = x[mask] - np.mean(x[mask])
    ym = y[mask] - np.mean(y[mask])
    denom = np.sqrt(np.sum(xm ** 2) * np.sum(ym ** 2))
    if denom < 1e-12:
        return 0.0
    return float(np.sum(xm * ym) / denom)


def _safe_trend_score(values: np.ndarray) -> float:
    """Spearman correlation with time index; strong trend suggests detrending."""
    n = len(values)
    idx = np.arange(n, dtype=float)
    mask = np.isfinite(values)
    if mask.sum() < 5:
        return float("nan")
    try:
        rho, _ = spearmanr(idx[mask], values[mask])
        return float(rho) if np.isfinite(rho) else 0.0
    except Exception:
        return 0.0


def _adf_test(values: np.ndarray) -> Optional[Dict[str, Any]]:
    """Run Augmented Dickey-Fuller test via statsmodels if available."""
    try:
        from statsmodels.tsa.stattools import adfuller
        clean = values[np.isfinite(values)]
        if len(clean) < 10:
            return None
        stat, pvalue, _, _, crit, _ = adfuller(clean, regression="ct", autolag="AIC")
        return {
            "test": "ADF",
            "statistic": float(stat),
            "pvalue": float(pvalue),
            "critical_values": {str(k): float(v) for k, v in crit.items()},
        }
    except Exception:
        return None


def _robust_stationarity_check(values: np.ndarray) -> Dict[str, Any]:
    """
    Robust stationarity proxy when statsmodels is unavailable or series is short.
    Combines lag-1 autocorrelation, linear trend score, and variance shift.
    """
    clean = values[np.isfinite(values)]
    n = len(clean)
    if n < 5:
        return {"test": "robust", "is_stationary": None, "note": "too few values"}

    lag1 = _safe_lag1_autocorr(clean)
    trend = _safe_trend_score(clean)

    # Midpoint variance shift
    half = n // 2
    var_first = float(np.var(clean[:half], ddof=1)) if half > 1 else 0.0
    var_second = float(np.var(clean[half:], ddof=1)) if (n - half) > 1 else 0.0
    pooled_var = max((var_first + var_second) / 2.0, 1e-12)
    var_shift = abs(var_second - var_first) / pooled_var

    # Heuristic thresholds tuned to flag obvious non-stationarity without
    # over-flagging weak autocorrelation common in short deterministic series.
    is_stationary = bool(
        abs(lag1) < 0.95
        and abs(trend) < 0.7
        and var_shift < 2.0
    )
    concerns = []
    if abs(lag1) >= 0.95:
        concerns.append(f"very high lag-1 autocorr ({lag1:.3f})")
    if abs(trend) >= 0.7:
        concerns.append(f"strong trend ({trend:.3f})")
    if var_shift >= 2.0:
        concerns.append(f"large variance shift ({var_shift:.2f})")

    return {
        "test": "robust",
        "is_stationary": is_stationary,
        "lag1_autocorr": round(lag1, 4) if np.isfinite(lag1) else None,
        "trend_score": round(trend, 4) if np.isfinite(trend) else None,
        "variance_shift": round(var_shift, 4),
        "concerns": concerns,
        "note": (
            "Stationary" if is_stationary
            else "Possibly non-stationary: " + "; ".join(concerns)
            if concerns else "inconclusive"
        ),
    }


def _stationarity_check(values: np.ndarray) -> Dict[str, Any]:
    """Best-effort stationarity check: ADF when available, robust fallback otherwise."""
    adf = _adf_test(values)
    if adf is not None:
        is_stationary = bool(adf["pvalue"] < 0.05)
        return {
            "test": "ADF",
            "is_stationary": is_stationary,
            "pvalue": round(adf["pvalue"], 6),
            "statistic": round(adf["statistic"], 4),
            "note": (
                "Stationary (ADF p<0.05)" if is_stationary
                else "Possibly non-stationary (ADF p>=0.05); consider differencing/detrending"
            ),
        }
    return _robust_stationarity_check(values)


def _outlier_summary(values: np.ndarray) -> Dict[str, Any]:
    """Detect univariate outliers using IQR and MAD."""
    clean = values[np.isfinite(values)]
    n = len(clean)
    if n < 5:
        return {"method": "iqr+mad", "n_outliers": 0, "fraction": 0.0}

    q1, q3 = np.percentile(clean, [25.0, 75.0])
    iqr = q3 - q1
    lower_iqr = q1 - 1.5 * iqr
    upper_iqr = q3 + 1.5 * iqr
    iqr_outliers = int(np.sum((clean < lower_iqr) | (clean > upper_iqr)))

    med = float(np.median(clean))
    mad = float(np.median(np.abs(clean - med)))
    threshold = 3.5 * max(mad, 1e-12)
    mad_outliers = int(np.sum(np.abs(clean - med) > threshold))

    # Union of the two methods
    outlier_mask = ((clean < lower_iqr) | (clean > upper_iqr)) | (np.abs(clean - med) > threshold)
    n_outliers = int(np.sum(outlier_mask))
    return {
        "method": "iqr+mad",
        "n_outliers": n_outliers,
        "fraction": round(n_outliers / n, 4),
        "iqr_outliers": iqr_outliers,
        "mad_outliers": mad_outliers,
    }


def _detect_duplicate_rows(df: pd.DataFrame, selected_vars: List[str]) -> Dict[str, Any]:
    """Detect fully duplicate rows across selected numeric columns."""
    sub = df[selected_vars].dropna()
    if len(sub) <= 1:
        return {"n_duplicate_rows": 0, "fraction": 0.0}
    dup_mask = sub.duplicated(keep=False)
    n_dup = int(dup_mask.sum())
    return {
        "n_duplicate_rows": n_dup,
        "fraction": round(n_dup / len(sub), 4),
    }


def _detect_duplicate_timestamps(df: pd.DataFrame) -> Dict[str, Any]:
    """Detect duplicate timestamps in a candidate time/index column."""
    time_like = {"time", "date", "timestamp", "datetime", "index", "seq", "序号", "时间", "日期", "时序"}
    candidates = [c for c in df.columns if any(t in c.lower() for t in time_like)]
    if not candidates:
        return {"has_time_column": False, "n_duplicate_timestamps": 0, "fraction": 0.0}
    col = candidates[0]
    try:
        series = pd.to_datetime(df[col], errors="coerce")
    except Exception:
        series = df[col]
    n_dup = int(series.duplicated(keep=False).sum())
    return {
        "has_time_column": True,
        "time_column": col,
        "n_duplicate_timestamps": n_dup,
        "fraction": round(n_dup / len(df), 4) if len(df) else 0.0,
    }


def _sample_size_note(n: int) -> Optional[str]:
    """Warn about small sample sizes that constrain EDM reliability."""
    if n < 50:
        return (
            f"样本量 N={n} < 50，EmbedDimension/Simplex 的 rho 上限会明显受"
            "限（稀疏库 / 少近邻），结果应作为探索性参考"
        )
    if n < 100:
        return f"样本量 N={n} 偏小，Lyapunov 与 CCM 收敛判断可能不够稳定"
    return None


def _build_suggested_action(
    missing_ratio: float,
    is_constant: bool,
    std: float,
    unique_ratio: float,
    sparsity: Optional[float],
    lag1: float,
    trend: float,
    stationarity: Dict[str, Any],
    outliers: Dict[str, Any],
    n: int,
) -> str:
    """Return a concise recommended action for this column."""
    actions: List[str] = []
    if is_constant or std < 1e-12:
        return "剔除：常数/近常数列，无可分析动力学信息"
    if unique_ratio > 0.95:
        return "剔除：疑似 ID/索引列，不应参与嵌入"
    if missing_ratio > 0.2:
        actions.append("缺失比例高，优先插值或删除")
    elif missing_ratio > 0.05:
        actions.append("缺失比例偏高，建议插值")
    if sparsity is not None and sparsity < 0.15:
        actions.append("稀疏二值/类别列，EDM skill 可能受限；建议聚合或换用分类模型")
    if np.isfinite(lag1) and abs(lag1) < 0.1:
        actions.append("近白噪声，预测能力弱；考虑引入滞后变量或外部驱动变量")
    if np.isfinite(trend) and abs(trend) > 0.7:
        actions.append("存在强趋势，建议差分或去趋势")
    sta = stationarity.get("is_stationary")
    if sta is False:
        actions.append("可能非平稳，" + stationarity.get("note", "建议差分/去趋势"))
    if outliers.get("fraction", 0.0) > 0.05:
        actions.append(f"异常值比例 {outliers['fraction']:.1%}，建议检查并稳健化")
    if n < 50:
        actions.append("样本量小，rho 结果可能接近经验上限，仅作探索")
    if not actions:
        return "可用于 EDM/HAVOK 分析"
    return "；".join(actions)


def series_quality(series: pd.Series) -> Dict[str, Any]:
    """Compute per-column quality metrics for EDM readiness."""
    n = len(series)
    # Convert once; non-numeric series raise here (existing behavior).
    values = series.values.astype(float)
    # pandas isna()/dropna() do NOT detect Inf, and std(skipna=True) lets
    # Inf propagate (→ Inf/NaN std). Use np.isfinite uniformly so Inf is
    # treated as missing/unusable, matching how downstream EDM stages
    # handle it.
    finite_mask = np.isfinite(values)
    finite_values = values[finite_mask]
    missing = int(np.sum(~finite_mask))
    missing_ratio = missing / n if n else 0.0
    unique_count = int(len(np.unique(finite_values)))
    unique_ratio = unique_count / n if n else 0.0
    if len(finite_values) > 1:
        std = float(np.std(finite_values, ddof=1))
    else:
        std = None  # 常量列无标准差，None→JSON null（避免 NaN 破坏 JSON）
    is_constant = unique_count <= 1

    # Sparsity: minority-class ratio for low-cardinality columns
    sparsity = None
    if unique_count <= 5:
        counts = pd.Series(finite_values).value_counts()
        sparsity = float(counts.min() / n) if n else None

    lag1 = _safe_lag1_autocorr(values)
    trend = _safe_trend_score(values)
    stationarity = _stationarity_check(values)
    outliers = _outlier_summary(values)

    warnings: List[str] = []
    if missing_ratio > 0.05:
        warnings.append(f"缺失比例 {missing_ratio:.1%}，建议插值或清洗")
    if is_constant:
        warnings.append("常数列，无可分析动力学信息")
    elif std < 1e-12:
        warnings.append("方差极低，近似常数")
    if unique_ratio > 0.95:
        warnings.append("近似唯一值，疑似 ID/索引列")
    if sparsity is not None and sparsity < 0.15:
        warnings.append(f"稀疏二值/类别列（少数类 {sparsity:.1%}），EDM skill 可能受限")
    if np.isfinite(lag1) and abs(lag1) < 0.1:
        warnings.append("lag-1 自相关极低，近白噪声，预测能力可能不足")
    if np.isfinite(trend) and abs(trend) > 0.7:
        warnings.append("强趋势，建议差分或去趋势后重试")
    if stationarity.get("is_stationary") is False:
        warnings.append(stationarity.get("note", "可能非平稳"))
    if outliers.get("fraction", 0.0) > 0.05:
        warnings.append(f"异常值比例 {outliers['fraction']:.1%}，可能扭曲吸引子结构")

    usable = (
        not is_constant
        and std >= 1e-12
        and unique_ratio <= 0.95
        and (sparsity is None or sparsity >= 0.15)
    )
    # debt-22 audit 修复：用 _usability.py 的基础判定作为双重校验，
    # 确保 data_quality 的综合判定不会与基础可用性判定矛盾。
    # _usability.is_usable_for_edm 使用更严格的 minority_count < 5 检查，
    # 若基础判定为不可用，则综合判定也强制为不可用。
    if not is_usable_for_edm(values):
        usable = False

    sample_note = _sample_size_note(n)
    if sample_note:
        warnings.append(sample_note)

    suggested_action = _build_suggested_action(
        missing_ratio=missing_ratio,
        is_constant=is_constant,
        std=std,
        unique_ratio=unique_ratio,
        sparsity=sparsity,
        lag1=lag1,
        trend=trend,
        stationarity=stationarity,
        outliers=outliers,
        n=n,
    )

    return {
        "n": n,
        "missing": missing,
        "missing_ratio": round(missing_ratio, 4),
        "unique_count": unique_count,
        "unique_ratio": round(unique_ratio, 4),
        "std": round(std, 6) if std is not None else None,
        "sparsity": round(sparsity, 4) if sparsity is not None else None,
        "lag1_autocorr": round(lag1, 4) if np.isfinite(lag1) else None,
        "trend_score": round(trend, 4) if np.isfinite(trend) else None,
        "stationarity": stationarity,
        "outliers": outliers,
        "usable_for_edm": usable,
        "warnings": warnings,
        "suggested_action": suggested_action,
    }


def evaluate_dataframe(
    df: pd.DataFrame,
    target_col: str,
    selected_vars: List[str],
    all_numeric_cols: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate target column and selected variables.

    If ``all_numeric_cols`` is provided, quality metrics are computed for every
    numeric column; each entry is annotated with ``selected`` and ``is_target``
    so callers can present the full picture (e.g. wide tables) while still
    highlighting the columns that will enter the pipeline.
    """
    report: Dict[str, Dict[str, Any]] = {}
    cols = [target_col] + [v for v in selected_vars if v != target_col]
    eval_cols = list(dict.fromkeys((all_numeric_cols or []) + cols))
    for col in eval_cols:
        report[col] = series_quality(df[col])
        report[col]["selected"] = col in selected_vars
        report[col]["is_target"] = col == target_col

    # Dataset-level summary for wide / sparse tables.
    numeric_cols = all_numeric_cols or selected_vars
    n_numeric = len(numeric_cols)
    n_binary = sum(1 for c in numeric_cols if len(df[c].dropna().unique()) <= 2)
    n_selected = len(selected_vars)
    target_report = report.get(target_col, {})
    dataset_warnings = []
    if n_binary / max(n_numeric, 1) > 0.5:
        dataset_warnings.append(
            f"数值列中 {n_binary}/{n_numeric} 为二值/指示变量，EDM 假设度量空间，"
            "此类宽表更适合作为分类或特征工程输入，而非延迟嵌入"
        )
    if target_report.get("usable_for_edm") is False:
        dataset_warnings.append(
            f"目标列 '{target_col}' 不建议用于 EDM，请考虑更换目标列或聚合指标"
        )

    report["_dataset"] = {
        "duplicate_rows": _detect_duplicate_rows(df, selected_vars),
        "duplicate_timestamps": _detect_duplicate_timestamps(df),
        "n_numeric": n_numeric,
        "n_selected": n_selected,
        "n_binary": n_binary,
        "target_col": target_col,
        "dataset_warnings": dataset_warnings,
    }
    return report
