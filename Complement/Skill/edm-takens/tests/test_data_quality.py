# ALG-08: 新增独立pytest测试
"""
Data quality module — pytest suite.

Verifies src/data_quality.py:
  - series_quality() detection of missing values / constants / ID-like columns
  - Outlier detection (IQR + MAD union) on injected anomalies
  - Numerical-issue auto-fix behavior through usable_for_edm / suggested_action
  - Quality-score / warning generation for typical column archetypes
  - evaluate_dataframe() dataset-level summary (duplicates, binary ratio)
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

from data_quality import (
    series_quality,
    evaluate_dataframe,
    _outlier_summary,
    _safe_lag1_autocorr,
    _safe_trend_score,
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def clean_continuous_series():
    """长度 200 的连续序列，可用作 EDM 输入。

    使用量化到 2 位小数的 sine + AR(1) 混合，使 unique_ratio < 0.95
    （避免触发 data_quality 的 "近似唯一值/疑似 ID 列" 检查）。
    """
    np.random.seed(0)
    n = 200
    t = np.linspace(0, 8 * np.pi, n)
    ar = np.zeros(n)
    for i in range(1, n):
        ar[i] = 0.6 * ar[i - 1] + np.random.randn() * 0.3
    x = np.sin(t) + 0.2 * ar
    # 量化到 1 位小数，确保有足够重复值 -> unique_ratio < 0.95
    x = np.round(x, 1)
    return pd.Series(x, name='x')


@pytest.fixture
def series_with_missing():
    """在干净序列中注入若干 NaN。"""
    np.random.seed(1)
    x = np.random.randn(100)
    x[5:8] = np.nan
    x[20] = np.nan
    return pd.Series(x, name='x')


@pytest.fixture
def series_with_outliers():
    """含明显异常值的序列（用于 IQR + MAD 检测）。"""
    np.random.seed(2)
    x = np.random.randn(200) * 1.0
    x[10] = 50.0  # 极端正向异常
    x[11] = -45.0  # 极端负向异常
    x[12] = 30.0
    return pd.Series(x, name='x')


# ── Missing-value detection ──────────────────────────────

def test_series_quality_detects_missing_values(series_with_missing):
    """series_quality 应正确统计缺失数量与缺失比例。"""
    report = series_quality(series_with_missing)
    assert report['missing'] == 4, f"期望缺失 4 个，实际 {report['missing']}"
    # 4/100 = 0.04
    assert abs(report['missing_ratio'] - 0.04) < 1e-6
    # 缺失 > 5% 才会进 warnings；4% 不会触发该 warning
    assert not any('缺失比例' in w for w in report['warnings'])


def test_series_quality_flags_high_missing_ratio():
    """缺失比例 > 5% 应触发 warning。"""
    np.random.seed(3)
    x = np.random.randn(100)
    x[:10] = np.nan  # 10% 缺失
    report = series_quality(pd.Series(x, name='x'))
    assert report['missing'] == 10
    assert report['missing_ratio'] >= 0.05
    assert any('缺失' in w for w in report['warnings'])


def test_series_quality_handles_inf_as_missing():
    """Inf 应被视作缺失（与下游 SovereignHAVOK.fit() 一致）。"""
    x = np.array([1.0, 2.0, np.inf, 4.0, 5.0,
                  6.0, 7.0, 8.0, 9.0, 10.0,
                  11.0, 12.0, 13.0, 14.0, 15.0], dtype=float)
    report = series_quality(pd.Series(x, name='x'))
    # Inf 应计入 missing
    assert report['missing'] == 1
    # Inf 不应污染 std（被 np.isfinite 过滤）
    assert report['std'] is not None and np.isfinite(report['std'])


# ── Outlier detection ────────────────────────────────────

def test_outlier_summary_detects_injected_outliers(series_with_outliers):
    """_outlier_summary 应识别出明显注入的异常值。"""
    summary = _outlier_summary(series_with_outliers.values.astype(float))
    assert summary['method'] == 'iqr+mad'
    # 注入了 3 个极端异常值，至少应检测到这些
    assert summary['n_outliers'] >= 3, (
        f"应至少检测到 3 个异常值，实际 {summary['n_outliers']}")
    assert summary['fraction'] > 0.0
    # iqr_outliers 与 mad_outliers 都应 > 0
    assert summary['iqr_outliers'] > 0
    assert summary['mad_outliers'] > 0


def test_outlier_summary_clean_series():
    """干净正态序列的异常值比例应较低。"""
    np.random.seed(4)
    x = np.random.randn(500)
    summary = _outlier_summary(x)
    # 标准正态分布 IQR 阈值外约 0.7%，不应超过 5%
    assert summary['fraction'] < 0.05, (
        f"干净正态序列异常比例应 < 5%，实际 {summary['fraction']}")


def test_outlier_summary_short_series():
    """短序列（< 5 个点）应安全返回 0 异常值。"""
    summary = _outlier_summary(np.array([1.0, 2.0, 3.0]))
    assert summary['n_outliers'] == 0
    assert summary['fraction'] == 0.0


# ── Constants / ID columns / usability ───────────────────

def test_series_quality_constant_column_flagged():
    """常数列应被标记为不可用，并在 warnings 中提示。"""
    s = pd.Series([3.14] * 100, name='const')
    report = series_quality(s)
    assert report['usable_for_edm'] is False
    assert any('常数' in w for w in report['warnings'])
    assert 'suggested_action' in report
    assert '常数' in report['suggested_action'] or '剔除' in report['suggested_action']


def test_series_quality_id_like_column_flagged():
    """近似唯一值的 ID/索引列应被识别为不可用。"""
    s = pd.Series(np.arange(200), dtype=float, name='id')
    report = series_quality(s)
    assert report['unique_ratio'] > 0.95
    assert report['usable_for_edm'] is False
    assert any('ID' in w or '索引' in w for w in report['warnings'])


def test_series_quality_clean_continuous_is_usable(clean_continuous_series):
    """干净 AR(1) 序列应通过 usable_for_edm 检查。"""
    report = series_quality(clean_continuous_series)
    assert report['usable_for_edm'] is True, (
        f"干净 AR(1) 应可用，warnings={report['warnings']}")
    # 应有 lag-1 自相关值，且为正
    assert report['lag1_autocorr'] is not None
    assert report['lag1_autocorr'] > 0.3


# ── Auto-fix / suggested_action ──────────────────────────

def test_suggested_action_for_clean_series(clean_continuous_series):
    """可用列的 suggested_action 应提示可用于分析。"""
    report = series_quality(clean_continuous_series)
    assert '可用' in report['suggested_action'] or 'EDM' in report['suggested_action']


def test_suggested_action_for_high_missing():
    """缺失比例 > 20% 的列应在 suggested_action 中提示插值/删除。"""
    np.random.seed(5)
    x = np.random.randn(100)
    x[:25] = np.nan  # 25% 缺失
    report = series_quality(pd.Series(x, name='x'))
    assert '缺失' in report['suggested_action']


# ── Quality score / warnings ─────────────────────────────

def test_series_quality_warnings_for_strong_trend():
    """强趋势序列应在 warnings 中触发提示。"""
    n = 200
    x = np.arange(n, dtype=float) * 0.5 + 0.01 * np.random.randn(n)
    report = series_quality(pd.Series(x, name='x'))
    # trend_score > 0.7 应触发 warning
    assert report['trend_score'] is not None and abs(report['trend_score']) > 0.7
    assert any('趋势' in w for w in report['warnings'])


def test_series_quality_small_sample_warning():
    """N < 50 的序列应触发样本量过小的 warning。"""
    np.random.seed(6)
    x = np.random.randn(30)
    report = series_quality(pd.Series(x, name='x'))
    assert any('样本量' in w for w in report['warnings'])


# ── evaluate_dataframe ───────────────────────────────────

def test_evaluate_dataframe_marks_target_and_selected():
    """evaluate_dataframe 应正确标注 is_target 与 selected 字段。"""
    np.random.seed(7)
    n = 100
    df = pd.DataFrame({
        'y': np.random.randn(n),
        'x1': np.random.randn(n),
        'x2': np.random.randn(n),
    })
    report = evaluate_dataframe(df, target_col='y',
                                selected_vars=['y', 'x1'],
                                all_numeric_cols=['y', 'x1', 'x2'])
    assert report['y']['is_target'] is True
    assert report['y']['selected'] is True
    assert report['x1']['is_target'] is False
    assert report['x1']['selected'] is True
    assert report['x2']['selected'] is False
    # 应包含 _dataset 摘要
    assert '_dataset' in report
    assert report['_dataset']['target_col'] == 'y'
    assert report['_dataset']['n_numeric'] == 3


def test_evaluate_dataframe_detects_duplicate_rows():
    """evaluate_dataframe 应检测出完全重复的行。"""
    df = pd.DataFrame({
        'y': [1.0, 1.0, 2.0, 2.0, 3.0, 3.0] * 2,
        'x1': [0.1, 0.1, 0.2, 0.2, 0.3, 0.3] * 2,
    })
    report = evaluate_dataframe(df, target_col='y',
                                selected_vars=['y', 'x1'])
    dup = report['_dataset']['duplicate_rows']
    assert dup['n_duplicate_rows'] > 0, "应检测到重复行"


def test_evaluate_dataframe_dataset_warnings_for_binary_target():
    """二值目标列在数据集中应触发 dataset_warnings 提示。"""
    np.random.seed(8)
    n = 100
    # 二值目标，少数类比例 < 0.15 -> 不可用
    y = np.array([0] * 95 + [1] * 5, dtype=float)
    df = pd.DataFrame({
        'y': y,
        'x1': np.random.randn(n),
        'x2': np.random.randn(n),
    })
    report = evaluate_dataframe(df, target_col='y',
                                selected_vars=['y', 'x1', 'x2'])
    # 目标列 usable_for_edm 应为 False
    assert report['y']['usable_for_edm'] is False
    # dataset_warnings 应提及目标列不可用
    assert any('目标列' in w for w in report['_dataset']['dataset_warnings'])
