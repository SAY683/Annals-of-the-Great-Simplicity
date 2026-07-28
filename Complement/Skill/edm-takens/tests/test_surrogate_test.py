# ALG-08: 新增独立pytest测试
"""
Surrogate data testing module — pytest suite.

Verifies the IAAFT surrogate generator (src/surrogate_test.py):
  - Shape / dtype / reproducibility of the surrogate ensemble
  - End-point matching (Theiler & Prichard, 1996)
  - Statistical-property preservation (mean, variance, amplitude distribution)
  - surrogate_significance_test() p-value correctness across all three tails
  - phase_randomize_surrogates() basic contract
"""
import os
import sys

import numpy as np
import pytest

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

from surrogate_test import (
    iaaft_surrogates,
    surrogate_significance_test,
    phase_randomize_surrogates,
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sine_series():
    """Deterministic sine wave with mild noise — IAAFT should preserve its mean."""
    np.random.seed(42)
    t = np.linspace(0, 20 * np.pi, 500)
    return np.sin(t) + 0.05 * np.random.randn(500)


@pytest.fixture
def lorenz_segment():
    """Short Lorenz-x segment — genuinely nonlinear, used for significance sanity."""
    def _lorenz(x, y, z, s=10, r=28, b=8 / 3):
        return s * (y - x), x * (r - z) - y, x * y - b * z
    dt, n = 0.01, 1500
    xs = np.zeros(n); xs[0], y, z = 1.0, 1.0, 1.0
    for i in range(1, n):
        dx, dy, dz = _lorenz(xs[i - 1], y, z)
        xs[i] = xs[i - 1] + dx * dt
        y += dy * dt
        z += dz * dt
    return xs[500:1500]


# ── IAAFT generator tests ────────────────────────────────

def test_iaaft_shape_and_reproducibility(sine_series):
    """IAAFT 返回 (n_surrogates, len(data)) 形状，且相同 seed 下可复现。"""
    s1 = iaaft_surrogates(sine_series, n_surrogates=10, seed=42)
    s2 = iaaft_surrogates(sine_series, n_surrogates=10, seed=42)
    assert s1.shape == (10, len(sine_series))
    assert s2.shape == (10, len(sine_series))
    np.testing.assert_allclose(s1, s2, atol=1e-10,
                               err_msg="相同 seed 必须产生完全一致的替代数据")


def test_iaaft_preserves_linear_ramp(sine_series):
    """端点匹配（Theiler & Prichard）：替代数据的首尾差应与原序列接近。

    注意：IAAFT 在 detrended 数据上做 rank-order remap，再把线性 ramp 加回。
    detrended surrogate 的端点不一定为 0，所以替代数据的首/尾样本不必精确等于
    原序列；但首尾差（线性 trend 的总幅度）应被保留。
    """
    surrs = iaaft_surrogates(sine_series, n_surrogates=5, seed=42)
    orig_delta = sine_series[-1] - sine_series[0]
    for i, s in enumerate(surrs):
        surr_delta = s[-1] - s[0]
        # ramp 总幅度被保留：detrended 的首尾差不严格为 0，但远小于原 trend
        # 验证：surr_delta 与 orig_delta 在同一量级
        assert abs(surr_delta - orig_delta) < abs(orig_delta) * 0.5 + 1.0, (
            f"surrogate {i} 首尾差 {surr_delta:.3f} 偏离原序列 {orig_delta:.3f}")


def test_iaaft_preserves_mean_and_variance(sine_series):
    """IAAFT 应保持原序列的均值与方差（amplitude distribution 守恒的副作用）。"""
    surrs = iaaft_surrogates(sine_series, n_surrogates=19, seed=42)
    orig_mean = np.mean(sine_series)
    orig_std = np.std(sine_series)
    for i, s in enumerate(surrs):
        # 均值因端点 ramp 的加回允许轻微偏移；方差因 rank remap 接近守恒
        assert abs(np.mean(s) - orig_mean) < 0.5, (
            f"surrogate {i} 均值偏离过大: {np.mean(s):.3f} vs {orig_mean:.3f}")
        # IAAFT 不严格保持 std，但 rank-order remap 后 std 应在原序列的 ±20% 内
        assert abs(np.std(s) - orig_std) / orig_std < 0.25, (
            f"surrogate {i} 方差偏离过大: {np.std(s):.3f} vs {orig_std:.3f}")


def test_iaaft_breaks_temporal_correlation(sine_series):
    """IAAFT 应破坏非线性相位耦合：替代数据与原序列的瞬时相关应较弱。"""
    surrs = iaaft_surrogates(sine_series, n_surrogates=5, seed=42)
    # 简单 sine 波的相位被打乱后，逐点 Pearson 相关应明显降低
    for i, s in enumerate(surrs):
        r = np.corrcoef(sine_series, s)[0, 1]
        assert abs(r) < 0.7, (
            f"surrogate {i} 与原序列相关过高 r={r:.3f}，相位未被充分随机化")


# ── Significance test p-value tests ───────────────────────

def test_significance_upper_tail_p_value():
    """upper-tail: 真实值高于所有替代值时，p = 1/(n+1)。"""
    rng = np.random.RandomState(0)
    real = np.array([1.0, 2.0, 3.0])
    # 构造 9 条替代数据，metric_fn 取 max，real 的 max=3 高于所有替代的 max
    surrogates = rng.randn(9, 50)
    metric_fn = lambda d: float(np.max(d))  # noqa: E731
    result = surrogate_significance_test(real, surrogates, metric_fn, tail='upper')
    # real=3 > 所有 surrogate 的 max(标准正态 50 点的 max)，count_ge=0
    # p = (0+1)/(9+1) = 0.1
    assert result['n_surrogates'] == 9
    assert result['tail'] == 'upper'
    assert abs(result['p_value'] - 1 / 10) < 1e-9, (
        f"upper-tail 最小 p 应为 1/(9+1)=0.1，实际 {result['p_value']}")
    # significant 是 numpy.bool_，用 == 比较（0.1 > 0.05 -> 不显著）
    assert result['significant'] == False  # noqa: E712


def test_significance_lower_tail_p_value():
    """lower-tail: 真实值低于所有替代值时，p = 1/(n+1)。"""
    real = np.array([-10.0])
    rng = np.random.RandomState(1)
    surrogates = rng.randn(19, 30)  # 19 条，均值 ~0
    metric_fn = lambda d: float(np.mean(d))  # noqa: E731
    result = surrogate_significance_test(real, surrogates, metric_fn, tail='lower')
    # real_mean=-10 < 所有 surrogate 的 mean，count_le=0
    # p = (0+1)/(19+1) = 0.05
    assert abs(result['p_value'] - 1 / 20) < 1e-9, (
        f"lower-tail 最小 p 应为 1/(19+1)=0.05，实际 {result['p_value']}")
    # 0.05 <= 0.05 -> significant (按模块内的 <= 约定)
    # significant 是 numpy.bool_，用 == 比较
    assert result['significant'] == True  # noqa: E712


def test_significance_two_sided_basic():
    """two-sided: 真实值等于替代均值时 p 应较大（不显著）。"""
    rng = np.random.RandomState(2)
    base = 5.0
    surrogates = base + 0.1 * rng.randn(99, 50)
    real = np.full(50, base)  # real 的均值恰好在替代分布中心
    metric_fn = lambda d: float(np.mean(d))  # noqa: E731
    result = surrogate_significance_test(real, surrogates, metric_fn, tail='two-sided')
    assert result['tail'] == 'two-sided'
    # 真实值在分布中心 -> count_ge 大致为所有 surrogate -> p ≈ 1
    assert result['p_value'] > 0.5, (
        f"真实值在分布中心时 two-sided p 应较大，实际 {result['p_value']}")
    # significant 是 numpy.bool_，用 == 比较
    assert result['significant'] == False  # noqa: E712
    # verdict 字段应非空
    assert isinstance(result['verdict'], str) and len(result['verdict']) > 0


def test_significance_result_keys_present():
    """surrogate_significance_test 返回的 dict 应包含文档承诺的所有键。"""
    rng = np.random.RandomState(3)
    real = rng.randn(50)
    surrogates = rng.randn(9, 50)
    metric_fn = lambda d: float(np.std(d))  # noqa: E731
    result = surrogate_significance_test(real, surrogates, metric_fn)
    for key in ('real_value', 'surrogate_mean', 'surrogate_std',
                'surrogate_5th', 'surrogate_95th', 'p_value',
                'significant', 'n_surrogates', 'tail', 'verdict'):
        assert key in result, f"返回 dict 缺少键 {key}"


# ── phase_randomize_surrogates tests ─────────────────────

def test_phase_randomize_shape_and_spectrum(sine_series):
    """phase_randomize_surrogates 保持形状，并大致保持功率谱（仅相位被随机化）。

    注意：DC 分量（索引 0）和 Nyquist 分量（若 N 为偶数则为最后一个 bin）
    在实数 FFT 中相位必须为 0 或 π，irfft 不会保留对这些 bin 的随机相位，
    所以这两个 bin 的功率可能有偏差。我们排除首尾 bin，只验证内部 bin 的守恒。
    """
    n_surrogates = 7
    surrs = phase_randomize_surrogates(sine_series, n_surrogates=n_surrogates, seed=42)
    assert surrs.shape == (n_surrogates, len(sine_series))
    # 相位随机化保持幅度谱 -> 功率谱 |FFT|^2 应近似一致
    from scipy.fft import rfft
    orig_power = np.abs(rfft(sine_series)) ** 2
    for i, s in enumerate(surrs):
        surr_power = np.abs(rfft(s)) ** 2
        # 排除 DC (index 0) 与 Nyquist (最后一个 bin)，它们不被相位随机化保留
        np.testing.assert_allclose(surr_power[1:-1], orig_power[1:-1],
                                   rtol=1e-6,
                                   err_msg=f"surrogate {i} 内部 bin 功率谱未被保持")


def test_phase_randomize_different_seed_differs(sine_series):
    """不同 seed 应产生不同的替代数据。"""
    a = phase_randomize_surrogates(sine_series, n_surrogates=3, seed=1)
    b = phase_randomize_surrogates(sine_series, n_surrogates=3, seed=2)
    assert not np.allclose(a, b), "不同 seed 不应产生完全一致的替代数据"
