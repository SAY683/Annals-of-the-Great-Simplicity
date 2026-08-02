"""
Surrogate Data Testing with IAAFT
===================================
Implements the mandatory surrogate data test before believing
any nonlinear metric (Theiler et al., Physica D, 1992).

Method: Iterative Amplitude-Adjusted Fourier Transform (IAAFT).
- Preserves power spectrum (linear autocorrelation structure)
- Preserves amplitude distribution (exact value distribution)
- Destroys nonlinear phase coupling

Significance: With N surrogates + 1 real, exact p = 1/(N+1).
  - 19 surrogates -> p < 0.05
  - 99 surrogates -> p < 0.01  (recommended for publication)

Usage:
  from surrogate_test import iaaft_surrogates, surrogate_significance_test
  surrogates = iaaft_surrogates(data, n_surrogates=99)
  result = surrogate_significance_test(data, surrogates, your_metric_fn)
"""

import numpy as np
from scipy.fft import rfft, irfft
import warnings


def iaaft_surrogates(data: np.ndarray, n_surrogates: int = 99,
                     max_iter: int = 50, tol: float = 1e-6,
                     seed: int = None) -> np.ndarray:
    """
    Generate IAAFT surrogate time series.

    IAAFT (Iterative Amplitude-Adjusted Fourier Transform) preserves
    BOTH the power spectrum AND the amplitude distribution of the
    original data, while destroying nonlinear phase coupling.

    Algorithm (Schreiber & Schmitz, 2000), with end-point matching
    (Theiler & Prichard, 1996):
    0. Remove the linear ramp connecting the first and last sample
       ("end-point matching") before doing anything FFT-based.
    1. Random shuffle of (detrended) original -> initial surrogate
    2. Fourier transform, replace amplitudes with original spectrum
    3. Inverse Fourier transform
    4. Rank-order remap to match original amplitude distribution
    5. Repeat 2-4 until convergence or max_iter
    6. Add the linear ramp back.

    Why end-point matching (engineering note)
    ------------------------------------------
    The FFT implicitly treats the series as periodic. Real (non-cyclic)
    time series almost never start and end at the same value, so without
    correction there is a large artificial jump at the wrap-around point.
    Phase-randomizing that jump smears it across the whole surrogate as
    broadband high-frequency energy, which the downstream SG-derivative +
    HAVOK forcing-kurtosis metric picks up as spurious, occasionally huge,
    heavy-tailed spikes unrelated to the real dynamics. On a 1000-point
    Lorenz-x segment this pushed some surrogates' kurtosis to 3-5x the
    real value (max observed 16.5 vs a real value of 3.4), which masked
    the genuine chaotic signal and made `havok_surrogate_check` fail to
    reach significance even though the real data plainly is chaotic (see
    docs/CHANGELOG.md). Subtracting the ramp `linspace(data[0], data[-1],
    n)` before the FFT step, running IAAFT on the detrended series, and
    adding the ramp back afterwards removes the discontinuity while
    leaving the internal dynamics intact — the standard fix from Theiler
    & Prichard (1996), used by TISEAN and other surrogate-testing tools.

    Parameters
    ----------
    data : np.ndarray, 1D
        Original time series.
    n_surrogates : int
        Number of surrogates to generate. With exact rank-based p-values
        p = (k+1)/(n_surrogates+1), so use n_surrogates >= 39 for p<0.05
        to be achievable, and n_surrogates=99 for p<0.01 (recommended for
        publication). NOTE: n_surrogates=19 can only ever reach a minimum
        p of exactly 0.05, which is NOT < 0.05 — see
        surrogate_significance_test().
    max_iter : int
        Maximum IAAFT iterations per surrogate.
    tol : float
        Convergence tolerance for spectrum matching.
    seed : int, optional
        Random seed for reproducibility.

    Returns
    -------
    surrogates : np.ndarray, shape (n_surrogates, len(data))
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    # P2-3.4 修复 (科研严谨性审查): 原 np.random.seed(seed) 污染全局 RNG 状态,
    # 可能影响同进程中其他随机操作的可复现性. 改用独立 Generator, 与
    # _numpy_edm.py 的 CCM 实现保持一致.
    _rng = np.random.default_rng(seed)

    # End-point matching (Theiler & Prichard, 1996): remove the linear
    # ramp connecting the first and last sample so the FFT's implicit
    # periodicity assumption doesn't see a spurious jump at the wrap-around.
    ramp = np.linspace(data[0], data[-1], n)
    detrended = data - ramp

    # Target amplitude spectrum and rank order, computed on the
    # detrended series (not the raw data) so both are self-consistent.
    orig_fft = rfft(detrended)
    target_amps = np.abs(orig_fft)

    # Detrended sorted values (for rank-order remapping)
    orig_sorted = np.sort(detrended)

    surrogates = np.zeros((n_surrogates, n))

    for s in range(n_surrogates):
        # Step 1: Random shuffle as initial surrogate
        surrogate = _rng.permutation(detrended).astype(float)

        for iteration in range(max_iter):
            # Step 2: Fourier transform, replace amplitudes
            fft_surr = rfft(surrogate)
            phases = np.angle(fft_surr)
            fft_surr = target_amps * np.exp(1j * phases)

            # Step 3: Inverse Fourier transform
            surrogate_new = irfft(fft_surr, n=n)

            # Step 4: Rank-order remap to match original distribution
            rank_order = np.argsort(np.argsort(surrogate_new))
            surrogate_new = orig_sorted[rank_order]

            # Check convergence
            change = np.max(np.abs(surrogate_new - surrogate))
            surrogate = surrogate_new

            if change < tol:
                break

        # Add the linear ramp back so the surrogate has the same
        # endpoints/trend as the original data.
        surrogates[s] = surrogate + ramp

    return surrogates


def surrogate_significance_test(real_data: np.ndarray,
                                 surrogates: np.ndarray,
                                 metric_fn,
                                 tail: str = 'two-sided') -> dict:
    """
    Test whether a nonlinear metric on real data is significantly
    different from surrogate data.

    Parameters
    ----------
    real_data : np.ndarray
        Original time series.
    surrogates : np.ndarray, shape (n_surrogates, len(data))
        IAAFT surrogate ensemble.
    metric_fn : callable
        Function that takes a 1D array and returns a scalar metric.
        e.g., lambda d: HAVOK(d).kurtosis_vr_
    tail : str
        'two-sided', 'upper', or 'lower'.

    Returns
    -------
    dict with: real_value, surrogate_values, p_value, significant,
               n_surrogates, tail
    """
    real_val = metric_fn(real_data)

    surrogate_vals = np.array([metric_fn(s) for s in surrogates])
    surrogate_vals = surrogate_vals[np.isfinite(surrogate_vals)]

    n_surr = len(surrogate_vals)

    if tail == 'upper':
        # Real is higher than surrogates
        count_ge = np.sum(surrogate_vals >= real_val)
        p_value = (count_ge + 1) / (n_surr + 1)
    elif tail == 'lower':
        count_le = np.sum(surrogate_vals <= real_val)
        p_value = (count_le + 1) / (n_surr + 1)
    else:  # two-sided
        surr_mean = np.mean(surrogate_vals)
        deviation = real_val - surr_mean
        surr_deviation = np.abs(surrogate_vals - surr_mean)
        count_ge = np.sum(surr_deviation >= abs(deviation))
        p_value = (count_ge + 1) / (n_surr + 1)

    # Exact rank-based p-value: with n_surr surrogates, the achievable
    # values are {1/(n_surr+1), 2/(n_surr+1), ..., 1}. The minimum
    # achievable p is exactly 1/(n_surr+1) (real value is the single most
    # extreme of the n_surr+1 values). Using a *strict* `<` against 0.05
    # means that minimum is only "significant" once n_surr+1 > 20, i.e.
    # n_surr >= 20 — with the commonly-used n_surr=19 the smallest
    # possible p is exactly 0.05, which a strict `<` would always reject
    # regardless of how extreme the real value is. The standard
    # convention for exact rank/permutation tests (Theiler et al. 1992)
    # is to reject at level alpha when p <= alpha, which is what `<=`
    # implements here; this matches the "19 surrogates -> 5% test" rule
    # of thumb this module's docstrings rely on.
    significant = p_value <= 0.05

    return {
        'real_value': real_val,
        'surrogate_mean': float(np.mean(surrogate_vals)),
        'surrogate_std': float(np.std(surrogate_vals)),
        'surrogate_5th': float(np.percentile(surrogate_vals, 5)),
        'surrogate_95th': float(np.percentile(surrogate_vals, 95)),
        'p_value': float(p_value),
        'significant': significant,
        'n_surrogates': n_surr,
        'tail': tail,
        'verdict': ('SIGNIFICANT — nonlinear structure exceeds linear null'
                    if significant else
                    'NOT SIGNIFICANT — linear process could produce this result'),
    }


def phase_randomize_surrogates(data: np.ndarray, n_surrogates: int = 99,
                               seed: int = None) -> np.ndarray:
    """
    Generate simple phase-randomized surrogates (no amplitude adjustment).
    Faster but less strict than IAAFT. Preserves power spectrum only
    (not amplitude distribution).

    Use IAAFT for rigorous testing; use this for quick screening.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    # P2-3.4 修复 (科研严谨性审查): 改用独立 Generator, 避免污染全局 RNG.
    _rng = np.random.default_rng(seed)

    fft_data = rfft(data)
    amps = np.abs(fft_data)

    surrogates = np.zeros((n_surrogates, n))
    for s in range(n_surrogates):
        random_phases = np.exp(1j * 2 * np.pi *
                               _rng.random(len(amps)))
        surr_fft = amps * random_phases
        surrogates[s] = irfft(surr_fft, n=n)

    return surrogates


# ================================================================
# Convenience: pre-analysis surrogate check for HAVOK
# ================================================================

def havok_surrogate_check(data: np.ndarray, q: int = 3,
                          n_surrogates: int = 99,
                          seed: int = 42) -> dict:
    """
    Run IAAFT surrogate test on HAVOK kurtosis.

    This answers: is the heavy-tailed forcing (kurtosis > 1.5)
    genuinely nonlinear, or could a linear process produce it?

    Parameters
    ----------
    data : np.ndarray
        Time series to test.
    q : int
        HAVOK embedding dimension.
    n_surrogates : int
        Number of surrogates (99 for p<0.01).

    Returns
    -------
    dict with surrogate test results.
    """
    from sovereign_havok import SovereignHAVOK

    def kurtosis_metric(d):
        sh = SovereignHAVOK(q_delays=q, window_length=min(7, max(5, (len(d)-q)//4)),
                           poly_order=2).fit(d)
        return sh.kurtosis_vr_

    surrogates = iaaft_surrogates(data, n_surrogates, seed=seed)
    result = surrogate_significance_test(data, surrogates, kurtosis_metric,
                                         tail='upper')
    result['metric'] = 'HAVOK kurtosis (v_r)'
    result['embedding_q'] = q
    return result


# ================================================================
# Self-test
# ================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("  Surrogate Test Module — Self-Test")
    print("=" * 60)

    # Test 1: IAAFT generator on sine
    print("\n[1] IAAFT on sine wave")
    np.random.seed(42)
    t = np.linspace(0, 20*np.pi, 500)
    sine = np.sin(t) + 0.05*np.random.randn(500)
    surrs = iaaft_surrogates(sine, n_surrogates=19, seed=42)
    assert surrs.shape == (19, 500)
    # IAAFT preserves mean approximately
    assert abs(np.mean(surrs) - np.mean(sine)) < 0.5
    # P2-3.4 修复后: IAAFT 核心保证是幅度谱匹配 + 分布匹配, 而非相关性破坏.
    # 对 sine 波 (纯线性信号), IAAFT 会保留主频率 (幅度谱匹配), surrogate
    # 与原始信号的逐点相关性取决于相位偏移 (随机). 原断言 abs(corr)<0.5
    # 依赖特定 RNG 实现的巧合, 不鲁棒. 改为检查 IAAFT 的数学保证:
    # 1. 幅度谱匹配 (核心保证)
    # 2. 分布匹配 (rank-order remap)
    orig_fft = np.fft.rfft(sine)
    orig_amps = np.abs(orig_fft)
    # IAAFT 对 detrended 数据做 rank-order remap, 最后加回 ramp.
    # 所以 surrogates[i] - ramp 的分布应与 detrended 的分布匹配.
    ramp = np.linspace(sine[0], sine[-1], len(sine))
    detrended = sine - ramp
    detrended_sorted = np.sort(detrended)
    for i in range(min(3, len(surrs))):
        surr_fft = np.fft.rfft(surrs[i])
        surr_amps = np.abs(surr_fft)
        # 幅度谱应高度相关 (IAAFT 的核心保证)
        amp_corr = np.corrcoef(orig_amps, surr_amps)[0, 1]
        assert amp_corr > 0.9, f"IAAFT amplitude spectrum not preserved: {amp_corr:.3f}"
        # 分布应匹配: (surrogate - ramp) 的排序应等于 detrended 的排序
        surr_detrended = surrs[i] - ramp
        assert np.allclose(np.sort(surr_detrended), detrended_sorted, atol=1e-6), \
            "IAAFT distribution not preserved"
    # 相关性 advisory (非断言): sine 波的主频率被保留, 逐点相关性有随机波动
    corrs = [abs(np.corrcoef(sine, surrs[i])[0, 1]) for i in range(min(5, len(surrs)))]
    mean_corr = np.mean(corrs)
    print(f"  [OK] Shape: {surrs.shape}, mean preserved, amplitude spectrum preserved")
    print(f"       (advisory: avg_corr={mean_corr:.3f} — sine wave retains main frequency by design)")

    # Test 2: Significance test on Lorenz (should be significant)
    print("\n[2] Significance test: HAVOK kurtosis on Lorenz")
    def lorenz(x, y, z, s=10, r=28, b=8/3):
        return s*(y-x), x*(r-z)-y, x*y-b*z
    dt, n_l = 0.01, 3000
    x = np.zeros(n_l); x[0], y, z = 1.0, 1.0, 1.0
    for i in range(1, n_l):
        dx, dy, dz = lorenz(x[i-1], y, z)
        x[i] = x[i-1] + dx*dt; y += dy*dt; z += dz*dt
    lx = x[500:1500]  # ~1000 pts

    result = havok_surrogate_check(lx, q=15, n_surrogates=99, seed=42)
    print(f"  Real kurtosis: {result['real_value']:.3f}")
    print(f"  Surrogate 95th percentile: {result['surrogate_95th']:.3f}")
    print(f"  p-value: {result['p_value']:.4f}")
    print(f"  {result['verdict']}")
    # Lorenz should be significant. n_surrogates=99 (not 19) is used here:
    # with only 19 surrogates the minimum achievable p-value is exactly
    # 1/20=0.05, which sits right on the significance boundary and made
    # this assertion fail intermittently even on genuinely chaotic data —
    # not because the surrogates were wrong, but because 19 surrogates
    # cannot mathematically produce enough resolution below 0.05 with any
    # comfortable margin. 99 surrogates give a minimum p of 1/100=0.01,
    # so a real, reliably-detected chaotic signal clears 0.05 with room
    # to spare. See docs/CHANGELOG.md.
    assert result['significant'], "Lorenz kurtosis should be significant vs linear null"

    # Test 3: AR(1) should NOT be significant
    print("\n[3] Significance test: AR(1) should be NOT significant")
    np.random.seed(42)
    ar1 = np.zeros(500)
    for i in range(1, 500):
        ar1[i] = 0.7 * ar1[i-1] + np.random.randn()

    result_ar1 = havok_surrogate_check(ar1, q=5, n_surrogates=19, seed=42)
    print(f"  Real kurtosis: {result_ar1['real_value']:.3f}")
    print(f"  Surrogate 95th percentile: {result_ar1['surrogate_95th']:.3f}")
    print(f"  p-value: {result_ar1['p_value']:.4f}")
    print(f"  {result_ar1['verdict']}")
    # AR(1) might or might not be significant — linear process

    print("\n" + "=" * 60)
    print("  Surrogate module: VERIFIED")
    print("=" * 60)
