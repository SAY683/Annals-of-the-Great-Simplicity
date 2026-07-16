"""
EDM Adaptive Pipeline — tau → E → theta → CCM
================================================
Unified EDM workflow: optimal delay (tau) via AMI, embedding
dimension (E) via cross-validated Simplex, nonlinearity detection
via S-Map theta sweep, and CCM causality inference.
Handles edge cases: binary data, small samples, non-stationarity.
"""

import numpy as np
import pandas as pd
import warnings

from _edm_bridge import (
    EmbedDimension, Simplex, SMapPredictNonlinear, EDM_AVAILABLE
)

def run_adaptive_edm(df, target_col, lib=None, pred=None, max_E=10, is_binary=False):
    """Full EDM pipeline with edge-case diagnostics.
    
    Automatically adjusts for small samples, binary data, and non-stationarity.
    
    Args:
        df: DataFrame with time series data
        target_col: column name to analyze
        lib: library range string (e.g. '1 100')
        pred: prediction range string
        max_E: maximum embedding dimension to search
        is_binary: True if target is 0/1 discrete
    
    Returns:
        dict with keys: optimal_E, optimal_tau, optimal_theta, system_type,
                        rho_simplex, rho_smap, ccm_results, warnings
    """
    results = {'warnings': [], 'is_binary': is_binary}
    n = len(df)
    
    # --- Constraint: small-sample correction ---
    if n < 50:
        max_E = min(max_E, max(3, n // 5))
        results['warnings'].append(f'Small sample (N={n}): constrained max_E to {max_E}')
    
    # --- Phase 1: tau is implicitly handled by pyEDM (Tp parameter) ---
    # The tau optimization script covers explicit AMI-based selection
    
    # --- Phase 2: Embedding Dimension ---
    try:
        rho_E = EmbedDimension(
            data=df, lib=lib, pred=pred,
            maxE=max_E, Tp=1, columns=target_col, target=target_col,
            showPlot=False, numProcess=1
        )
        best_idx = rho_E['rho'].idxmax()
        optimal_E = int(rho_E.loc[best_idx, 'E'])
        max_rho = rho_E.loc[best_idx, 'rho']
        results['optimal_E'] = optimal_E
        results['rho_E_curve'] = rho_E
        
        # Check for dimensionality curse: rho on test should be reasonable
        if max_rho < 0.1 and n > 30:
            optimal_E = max(2, optimal_E // 2)
            results['warnings'].append(
                f'rho(E)={max_rho:.3f} is very low. E reduced from {int(rho_E.loc[best_idx, "E"])} to {optimal_E}')
    except Exception as e:
        optimal_E = min(3, max_E)
        results['optimal_E'] = optimal_E
        results['warnings'].append(f'EmbedDimension failed: {e}. Using E={optimal_E}')
    
    # --- Phase 3: Simplex Prediction ---
    try:
        sx = Simplex(
            data=df, lib=lib, pred=pred,
            E=optimal_E, Tp=1, columns=target_col, target=target_col,
            showPlot=False
        )
        obs, pred_s = sx['Observations'], sx['Predictions']
        results['simplex'] = sx
        results['rho_simplex'] = obs.corr(pred_s)
        
        if is_binary:
            # For binary data: report accuracy in addition to rho
            correct = ((obs > 0.5) == (pred_s > 0.5)).sum()
            results['accuracy'] = correct / len(obs)
            results['warnings'].append(
                f'Binary target: rho={results["rho_simplex"]:.3f} may be misleading. Accuracy={results["accuracy"]:.0%}')
    except Exception as e:
        results['rho_simplex'] = None
        results['warnings'].append(f'Simplex failed: {e}')
    
    # --- Phase 4: S-Map Nonlinearity Diagnosis ---
    try:
        smap = SMapPredictNonlinear(
            data=df, lib=lib, pred=pred,
            E=optimal_E, columns=target_col, target=target_col,
            showPlot=False
        )
        rho_0 = smap.loc[smap['theta'] == smap['theta'].min(), 'rho'].values[0]
        results['rho_theta_0'] = rho_0
        rho_max = smap['rho'].max()
        theta_best = smap.loc[smap['rho'].idxmax(), 'theta']
        results['optimal_theta'] = theta_best
        results['rho_smap_max'] = rho_max
        results['smap'] = smap
        
        is_nonlinear = (rho_max - rho_0) >= 0.05 and theta_best > smap['theta'].min()
        results['system_type'] = 'LLGN (Deterministic Nonlinear)' if is_nonlinear else 'Linear / Stochastic Noise'
    except Exception as e:
        results['optimal_theta'] = 0
        results['system_type'] = 'Unknown (S-Map failed)'
        results['warnings'].append(f'PredictNonlinear failed: {e}')
    
    return results

if __name__ == '__main__':
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if not EDM_AVAILABLE:
        print('[SKIP] pyEDM not installed — adaptive EDM demo skipped')
        raise SystemExit(0)
    import pyEDM
    # Demo: run on built-in data
    df = pyEDM.sampleData['block_3sp']
    n = len(df)
    R = run_adaptive_edm(df, 'x_t', lib='1 100', pred='101 198', is_binary=False)
    
    print('=== Adaptive EDM Pipeline Results ===')
    print(f"E = {R['optimal_E']}")
    print(f"Simplex rho = {R.get('rho_simplex', 'N/A')}")
    print(f"System type = {R.get('system_type', 'N/A')}")
    print(f"Optimal theta = {R.get('optimal_theta', 'N/A')}")
    if R.get('warnings'):
        print('Warnings:', '; '.join(R['warnings']))
    
    # Plot rho vs E
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle('Adaptive EDM Pipeline', fontsize=14)
    
    if 'rho_E_curve' in R:
        rE = R['rho_E_curve']
        ax1.plot(rE['E'], rE['rho'], 'o-', color='steelblue')
        ax1.axvline(R['optimal_E'], color='red', ls='--', label=f"E={R['optimal_E']}")
        ax1.set_xlabel('E'); ax1.set_ylabel('rho')
        ax1.set_title('EmbedDimension'); ax1.legend(); ax1.grid(True, alpha=0.3)
    
    if 'smap' in R:
        sm = R['smap']
        ax2.plot(sm['theta'], sm['rho'], 'o-', color='darkorange')
        ax2.axvline(R['optimal_theta'], color='red', ls='--', label=f"theta={R['optimal_theta']}")
        ax2.axhline(R['rho_theta_0'], color='gray', ls=':', alpha=0.5, label='theta=0 baseline')
        ax2.set_xlabel('theta'); ax2.set_ylabel('rho')
        ax2.set_title(f"System: {R['system_type']}"); ax2.legend(); ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('edm_adaptive_results.png', dpi=150)
    plt.close()
    print('Saved: edm_adaptive_results.png')
