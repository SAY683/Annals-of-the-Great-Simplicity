"""
EDM usability check — shared canonical implementation (debt-22).

Extracted from the duplicated ``_is_usable_for_edm`` definitions that
previously lived inline in ``api.py`` and ``analysis_profiles.py``.
Provides a single source of truth for whether a numeric column has
enough variation for EDM / HAVOK analysis.

Binary columns with too few minority-class samples often produce all-NA
prediction skill in pyEDM (the prediction set collapses to a single
value), so they are filtered out before the pipeline sees them.
"""
import pandas as pd
import numpy as np


def is_usable_for_edm(series) -> bool:
    """Return True if a numeric column has enough variation for EDM/HAVOK.

    A column is considered usable when:
      0. It contains no NaN or Inf values — SovereignHAVOK.fit() rejects
         non-finite data with ValueError, so we must flag it here first.
      1. Its standard deviation is non-negligible (>= 1e-12), ruling out
         constant columns.
      2. If it is binary (<= 2 unique values), the minority class has at
         least 5 samples AND comprises >= 15 % of the column — otherwise
         the cross-map prediction set degenerates to a single value.
    """
    # 兼容 numpy 数组输入
    if not isinstance(series, pd.Series):
        series = pd.Series(series)
    # 深度复审修复：NaN/Inf 检查必须先于其他检查，与 SovereignHAVOK.fit() 一致
    if series.isna().any():
        return False
    try:
        if not np.isfinite(series.values).all():
            return False
    except (TypeError, ValueError):
        return False
    if series.std(skipna=True) < 1e-12:
        return False
    unique_vals = series.dropna().unique()
    if len(unique_vals) <= 2:
        counts = series.value_counts()
        minority_count = int(counts.min())
        minority_ratio = minority_count / len(series)
        if minority_count < 5 or minority_ratio < 0.15:
            return False
    return True
