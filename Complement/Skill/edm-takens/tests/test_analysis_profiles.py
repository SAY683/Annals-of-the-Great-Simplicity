# ALG-08: 新增独立pytest测试
"""
Analysis profiles module — pytest suite.

Verifies src/analysis_profiles.py:
  - Profile-level recommendation (light / medium / heavy) based on data score
  - Parameter override logic (user_q / user_max_e take precedence)
  - Default value fallback when overrides are None
  - Safety cap (max_e capped to N/5)
  - Forced level via the `level` parameter
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

from analysis_profiles import recommend_profile, _target_sparsity


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def large_clean_df():
    """N=250, 3 个可用协变量，连续目标 -> 期望 heavy。"""
    np.random.seed(0)
    n = 250
    return pd.DataFrame({
        'y': np.random.randn(n) + np.linspace(0, 5, n),
        'x1': np.random.randn(n),
        'x2': np.random.randn(n),
        'x3': np.random.randn(n),
    })


@pytest.fixture
def tiny_df():
    """N=30, 单协变量，小样本 -> 期望 light。"""
    np.random.seed(1)
    n = 30
    return pd.DataFrame({
        'y': np.random.randn(n),
        'x1': np.random.randn(n),
    })


@pytest.fixture
def medium_df():
    """N=80, 2 协变量，连续目标 -> 期望 medium。"""
    np.random.seed(2)
    n = 80
    return pd.DataFrame({
        'y': np.random.randn(n),
        'x1': np.random.randn(n),
        'x2': np.random.randn(n),
    })


# ── Profile level recommendation ─────────────────────────

def test_large_clean_df_recommends_heavy(large_clean_df):
    """大样本、多协变量、连续目标应被推荐为 heavy。"""
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'])
    assert result['level'] == 'heavy', (
        f"期望 heavy，实际 {result['level']} (score={result['score']})")
    # score 应较高
    assert result['score'] > 2
    # data_profile 应反映数据特征
    assert result['data_profile']['n'] == 250
    assert result['data_profile']['usable_variables'] == 3
    assert result['data_profile']['target_unique_count'] > 5


def test_tiny_df_recommends_light(tiny_df):
    """小样本、协变量不足应被推荐为 light。"""
    result = recommend_profile(tiny_df, target_col='y',
                               selected_vars=['y', 'x1'])
    assert result['level'] == 'light', (
        f"期望 light，实际 {result['level']} (score={result['score']})")
    # notes 应提示样本量较小
    assert any('样本量' in n for n in result['notes'])


def test_medium_df_recommends_medium(medium_df):
    """中等样本、适量协变量应被推荐为 medium。"""
    result = recommend_profile(medium_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2'])
    assert result['level'] == 'medium', (
        f"期望 medium，实际 {result['level']} (score={result['score']})")


# ── Forced level override ────────────────────────────────

def test_forced_level_overrides_score(large_clean_df):
    """level 参数应强制覆盖基于 score 的推荐。"""
    # large_clean_df 默认会是 heavy，强制 light
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'],
                               level='light')
    assert result['level'] == 'light'
    # light 的 max_e 默认应为 6
    assert result['params']['max_e'] == 6
    # light 应启用 auto_fix
    assert result['params']['auto_fix'] is True


def test_forced_level_heavy_on_tiny_df(tiny_df):
    """小样本强制 heavy 时仍应为 heavy（level 优先于 score）。"""
    result = recommend_profile(tiny_df, target_col='y',
                               selected_vars=['y', 'x1'], level='heavy')
    assert result['level'] == 'heavy'
    # heavy 的 max_e 默认 = min(12, max(8, N//5)) = min(12, max(8, 6)) = 8
    # 但 safe_max_e = N//5 = 30//5 = 6，所以 max_e 应被截断为 6
    assert result['params']['max_e'] <= 6


# ── Parameter override (user_q / user_max_e) ─────────────

def test_user_q_overrides_recommendation(large_clean_df):
    """user_q 应覆盖任何级别的默认 q 值。"""
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'],
                               user_q=15)
    assert result['params']['q'] == 15


def test_user_max_e_overrides_recommendation(large_clean_df):
    """user_max_e 应覆盖默认 max_e（但仍受 N/5 安全上限约束）。"""
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'],
                               user_max_e=10)
    # N=250, safe_max_e = 250//5 = 50，user_max_e=10 < 50 -> 不截断
    assert result['params']['max_e'] == 10


def test_user_max_e_capped_by_safe_limit(tiny_df):
    """user_max_e 超过 N/5 时应被安全上限截断。"""
    # N=30, safe_max_e = 30//5 = 6
    result = recommend_profile(tiny_df, target_col='y',
                               selected_vars=['y', 'x1'],
                               user_max_e=20)
    assert result['params']['max_e'] <= 6, (
        f"max_e 应被 N/5=6 截断，实际 {result['params']['max_e']}")
    # notes 中应有截断提示
    assert any('安全上限' in n or '截断' in n for n in result['notes'])


# ── Default value fallback ───────────────────────────────

def test_light_level_default_q_when_no_override(medium_df):
    """light 级别在无 user_q 时默认 q = max(2, N//6)。"""
    result = recommend_profile(medium_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2'],
                               level='light')
    # N=80, max(2, 80//6) = max(2, 13) = 13
    assert result['params']['q'] == max(2, 80 // 6)
    assert result['params']['q'] == 13


def test_light_level_default_max_e_is_6(medium_df):
    """light 级别在无 user_max_e 时默认 max_e = 6。"""
    result = recommend_profile(medium_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2'],
                               level='light')
    assert result['params']['max_e'] == 6


def test_medium_level_default_max_e_is_8(medium_df):
    """medium 级别在无 user_max_e 时默认 max_e = 8。"""
    result = recommend_profile(medium_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2'],
                               level='medium')
    assert result['params']['max_e'] == 8


def test_medium_level_q_none_when_no_override(medium_df):
    """medium 级别在无 user_q 时 q 应为 None（不强制默认）。"""
    result = recommend_profile(medium_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2'],
                               level='medium')
    assert result['params']['q'] is None


def test_heavy_level_default_max_e_formula(large_clean_df):
    """heavy 级别默认 max_e = min(12, max(8, N//5))。"""
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'],
                               level='heavy')
    # N=250, max(8, 250//5)=50, min(12, 50)=12
    # 但 safe_max_e = 250//5 = 50，12 < 50 不截断
    assert result['params']['max_e'] == min(12, max(8, 250 // 5))
    assert result['params']['max_e'] == 12


# ── _target_sparsity helper ──────────────────────────────

def test_target_sparsity_binary_balanced():
    """平衡二值目标的 sparsity 应接近 0.5。"""
    s = pd.Series([0] * 50 + [1] * 50)
    sparsity = _target_sparsity(s)
    assert sparsity == 0.5


def test_target_sparsity_binary_imbalanced():
    """不平衡二值目标的 sparsity 应反映少数类比例。"""
    s = pd.Series([0] * 90 + [1] * 10)
    sparsity = _target_sparsity(s)
    assert sparsity == 0.1


def test_target_sparsity_continuous_returns_none():
    """连续目标（>2 个唯一值）应返回 None。"""
    s = pd.Series(np.random.randn(100))
    assert _target_sparsity(s) is None


def test_target_sparsity_empty_series_returns_none():
    """空 Series 应安全返回 None。"""
    assert _target_sparsity(pd.Series([], dtype=float)) is None


# ── Result structure & data_profile ──────────────────────

def test_result_contains_required_keys(large_clean_df):
    """recommend_profile 返回 dict 应包含文档承诺的所有键。"""
    result = recommend_profile(large_clean_df, target_col='y',
                               selected_vars=['y', 'x1', 'x2', 'x3'])
    for key in ('level', 'score', 'params', 'notes', 'data_profile'):
        assert key in result, f"返回 dict 缺少键 {key}"
    for key in ('q', 'max_e', 'auto_fix'):
        assert key in result['params'], f"params 缺少键 {key}"
    for key in ('n', 'usable_variables', 'target_unique_count',
                'target_sparsity', 'target_std'):
        assert key in result['data_profile'], f"data_profile 缺少键 {key}"


def test_low_std_target_decreases_score():
    """目标列方差极低应扣分。"""
    np.random.seed(3)
    n = 100
    df = pd.DataFrame({
        'y': np.full(n, 1.0) + 1e-9 * np.random.randn(n),  # 方差 ~0
        'x1': np.random.randn(n),
    })
    result = recommend_profile(df, target_col='y', selected_vars=['y', 'x1'])
    # 方差极低应扣 1 分，并在 notes 中提示
    assert any('方差' in n for n in result['notes'])
    # 极低方差 + 协变量充足 -> score 不应太高
    assert result['score'] <= 2
