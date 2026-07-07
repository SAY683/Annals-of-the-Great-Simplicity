"""
Optimal Time Delay (tau) via Average Mutual Information
=========================================================
AMI-based optimal delay selection (Fraser & Swinney, 1986).
Finds the first local minimum of mutual information vs lag.
Fallbacks: ACF 1/e crossing, then default tau=1.
"""

import numpy as np
import warnings

def compute_ami(series, max_lag, bins=16):
    """Average Mutual Information I(tau) vs lag - measures nonlinear dependence.
    
    Args:
        series: 1D time series
        max_lag: maximum lag to compute
        bins: histogram bins for density estimation
    
    Returns:
        (lags, ami_values) arrays
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    ser_min, ser_max = series.min(), series.max()
    edges = np.linspace(ser_min, ser_max, bins + 1)
    
    # 2D histogram for joint distribution at each lag
    ami = np.zeros(max_lag + 1)
    for lag in range(max_lag + 1):
        x = series[:n - lag]
        y = series[lag:]
        joint, _, _ = np.histogram2d(x, y, bins=[edges, edges])
        joint_p = joint / joint.sum() + 1e-12  # avoid log(0)
        px = joint_p.sum(axis=1)
        py = joint_p.sum(axis=0)
        # I = sum p(x,y) * log(p(x,y) / (p(x) * p(y)))
        outer = np.outer(px, py) + 1e-12
        ami[lag] = np.sum(joint_p * np.log(joint_p / outer))
    lags = np.arange(max_lag + 1)
    return lags, ami

def find_first_local_min(values):
    """Return index of first local minimum in sequence."""
    n = len(values)
    for i in range(2, n - 2):
        if values[i] < values[i-1] and values[i] <= values[i+1]:
            # confirm it is not a trivial fluctuation
            if values[i] < values[i-2] * 0.95 or values[i] < values[i+2] * 0.95:
                return i
    return None

def find_acf_threshold(series, max_lag, threshold=1.0/np.e):
    """First lag where autocorrelation drops below threshold (default 1/e)."""
    n = len(series)
    acf = np.array([np.corrcoef(series[:-lag] if lag > 0 else series[:n-1],
                                series[lag:] if lag > 0 else series[1:])[0, 1]
                     for lag in range(1, max_lag + 1)])
    acf = np.nan_to_num(acf)
    crossing = np.where(acf < threshold)[0]
    if len(crossing) > 0:
        return int(crossing[0]) + 1
    return None

def optimal_tau(series, max_lag=None, method='auto'):
    """Determine optimal embedding delay tau using multiple strategies.
    
    Strategy:
    1. Primary: First local minimum of AMI (recommended for nonlinear systems)
    2. Fallback: First zero-crossing of ACF or 1/e decay
    3. Last resort: tau = 1 (assumes uniform sampling)
    
    Args:
        series: 1D time series array
        max_lag: maximum lag to search (default: len(series)//10)
        method: 'ami', 'acf', or 'auto'
    
    Returns:
        (tau, diagnostics_dict)
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    if max_lag is None:
        max_lag = max(2, min(n // 10, 50))
    max_lag = min(max_lag, n // 3)
    
    lags, ami = compute_ami(series, max_lag)
    
    diag = {'ami': ami, 'lags': lags, 'max_lag': max_lag}
    
    # Primary: first local minimum of AMI
    first_min = find_first_local_min(ami)
    if first_min is not None and first_min > 1 and first_min < max_lag * 0.9:
        diag['method'] = 'ami_first_local_min'
        diag['ami_min_idx'] = first_min
        return first_min, diag
    
    # If AMI is monotonically decreasing, use ACF 1/e criterion
    acf_first = find_acf_threshold(series, max_lag)
    if acf_first is not None:
        diag['method'] = 'acf_1e_crossing'
        diag['acf_crossing'] = acf_first
        return acf_first, diag
    
    # Absolute fallback
    diag['method'] = 'fallback_default_one'
    diag['warning'] = 'No clear optimum found; using tau=1'
    warnings.warn('No clear optimum for tau. Using tau=1.')
    return 1, diag

if __name__ == '__main__':
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    import pyEDM
    # Demo on pyEDM sample data
    df = pyEDM.sampleData['block_3sp']
    data = df['x_t'].values
    
    tau, diag = optimal_tau(data)
    lags, ami = diag['lags'], diag['ami']
    
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(lags[1:], ami[1:], 'o-', color='steelblue', label='AMI')
    ax.axvline(tau, color='red', linestyle='--', label=f'Optimal tau = {tau}')
    ax.set_xlabel('Lag (tau)'); ax.set_ylabel('Average Mutual Information')
    ax.set_title(f'AMI First Local Minimum -> tau = {tau}')
    ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('tau_optimization.png', dpi=150)
    print(f'Optimal tau = {tau} | Method = {diag["method"]}')
    plt.close()
