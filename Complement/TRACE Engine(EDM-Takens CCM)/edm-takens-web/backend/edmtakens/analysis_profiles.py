"""
EDM-Takens Web MVP — 自动分析强度分级推荐

根据数据规模、目标列特性和可用协变量数量，自动推荐
light / medium / heavy 三档分析参数，避免小样本/稀疏数据
被默认参数过度拟合或崩溃。
"""
from typing import Any, Dict, List, Optional

import pandas as pd

from _usability import is_usable_for_edm  # debt-22: 共享可用性检查

# 保留别名以兼容模块内现有调用点（L71 等）。
_is_usable_for_edm = is_usable_for_edm


def _target_sparsity(target: pd.Series) -> Optional[float]:
    """For binary/categorical targets, return minority-class ratio."""
    vals = target.dropna()
    n = len(vals)
    if n == 0:
        return None
    unique = vals.unique()
    if len(unique) <= 2:
        counts = vals.value_counts()
        return float(counts.min() / n)
    return None


def recommend_profile(
    df: pd.DataFrame,
    target_col: str,
    selected_vars: List[str],
    level: Optional[str] = None,
    user_q: Optional[int] = None,
    user_max_e: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Recommend an analysis intensity level and its concrete parameters.

    Parameters
    ----------
    df : pd.DataFrame
        Raw dataset (before pipeline column mapping).
    target_col : str
        Selected target column.
    selected_vars : list of str
        Variables chosen for analysis (target first).
    level : {'light', 'medium', 'heavy'} or None
        Force a fixed level. If None, level is derived from a data score.
    user_q, user_max_e : int or None
        User overrides. If provided, they take precedence over the recommendation.

    Returns
    -------
    dict with keys: level, score, params, notes, data_profile
    """
    n = len(df)
    target = df[target_col]
    sparsity = _target_sparsity(target)
    usable_vars = [v for v in selected_vars if v != target_col and _is_usable_for_edm(df[v])]
    target_std = float(target.std(skipna=True))
    target_unique = int(target.nunique(dropna=True))

    notes: List[str] = []
    score = 0

    # Sample size
    if n >= 200:
        score += 2
        notes.append(f"样本量充足 (N={n})")
    elif n >= 60:
        score += 1
        notes.append(f"样本量中等 (N={n})")
    else:
        score -= 1
        notes.append(f"样本量较小 (N={n})，建议保守解读")

    # Usable covariates
    if len(usable_vars) >= 3:
        score += 1
        notes.append(f"可用协变量 {len(usable_vars)} 个")
    elif len(usable_vars) == 0:
        score -= 1
        notes.append("可用协变量不足")

    # Target type / sparsity
    if target_unique > 5:
        score += 1
        notes.append("目标列近似连续，适合 EDM")
    else:
        if sparsity is None or sparsity >= 0.2:
            notes.append("目标列类别数较少但分布尚可")
        elif sparsity >= 0.1:
            score -= 1
            notes.append("目标列较稀疏，预测 skill 可能受限")
        else:
            score -= 2
            notes.append("目标列极稀疏，结果可能不稳定")

    if target_std < 1e-6:
        score -= 1
        notes.append("目标列方差极低")

    if level is None:
        if score <= 0:
            level = "light"
        elif score <= 2:
            level = "medium"
        else:
            level = "heavy"

    # Parameter mapping
    if level == "light":
        rec_q = user_q if user_q is not None else max(2, n // 6)
        rec_max_e = user_max_e if user_max_e is not None else 6
        rec_auto_fix = True
        notes.append("已启用轻度分析参数（保守 embedding、强制 auto-fix）")
    elif level == "heavy":
        rec_q = user_q
        rec_max_e = user_max_e if user_max_e is not None else min(12, max(8, n // 5))
        rec_auto_fix = True
        notes.append("已启用重度分析参数（更大搜索空间）")
    else:  # medium
        rec_q = user_q
        rec_max_e = user_max_e if user_max_e is not None else 8
        rec_auto_fix = True
        notes.append("使用默认中度参数")

    # Hard safety cap: E > N/5 makes the attractor too sparse
    safe_max_e = max(2, n // 5)
    if rec_max_e is not None and rec_max_e > safe_max_e:
        rec_max_e = int(safe_max_e)
        notes.append(f"max_e 已按 N/5 安全上限截断为 {rec_max_e}")

    return {
        "level": level,
        "score": score,
        "params": {
            "q": rec_q,
            "max_e": rec_max_e,
            "auto_fix": rec_auto_fix,
        },
        "notes": notes,
        "data_profile": {
            "n": n,
            "usable_variables": len(usable_vars),
            "target_unique_count": target_unique,
            "target_sparsity": sparsity,
            "target_std": target_std,
        },
    }
