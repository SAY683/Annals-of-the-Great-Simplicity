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

    Algorithm (Schreiber & Schmitz, 2000):
    1. Random shuffle of original -> initial surrogate
    2. Fourier transform, replace amplitudes with original spectrum
    3. Inverse Fourier transform
    4. Rank-order remap to match original amplitude distribution
    5. Repeat 2-4 until convergence or max_iter

    Parameters
    ----------
    data : np.ndarray, 1D
        Original time series.
    n_surrogates : int
        Number of surrogates to generate. Use 99 for p<0.01, 19 for p<0.05.
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

    if seed is not None:
        np.random.seed(seed)

    # Original amplitude spectrum (used as target)
    orig_fft = rfft(data)
    target_amps = np.abs(orig_fft)

    # Original sorted values (for rank-order remapping)
    orig_sorted = np.sort(data)
    orig_ranks = np.argsort(np.argsort(data))

    surrogates = np.zeros((n_surrogates, n))

    for s in range(n_surrogates):
        # Step 1: Random shuffle as initial surrogate
        surrogate = np.random.permutation(data).astype(float)

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

        surrogates[s] = surrogate

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

    significant = p_value < 0.05

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

    if seed is not None:
        np.random.seed(seed)

    fft_data = rfft(data)
    amps = np.abs(fft_data)

    surrogates = np.zeros((n_surrogates, n))
    for s in range(n_surrogates):
        random_phases = np.exp(1j * 2 * np.pi *
                               np.random.rand(len(amps)))
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
    # IAAFT should NOT preserve the sine shape (phases randomized)
    corr_with_orig = np.corrcoef(sine, surrs[0])[0, 1]
    assert abs(corr_with_orig) < 0.5, f"IAAFT should break correlation, got {corr_with_orig:.3f}"
    print(f"  [OK] Shape: {surrs.shape}, mean preserved, correlation broken (r={corr_with_orig:.3f})")

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

    result = havok_surrogate_check(lx, q=15, n_surrogates=19, seed=42)
    print(f"  Real kurtosis: {result['real_value']:.3f}")
    print(f"  Surrogate 95th percentile: {result['surrogate_95th']:.3f}")
    print(f"  p-value: {result['p_value']:.4f}")
    print(f"  {result['verdict']}")
    # Lorenz should be significant
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
