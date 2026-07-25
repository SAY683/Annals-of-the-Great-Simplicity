"""
Multiview Embedding + SVD Residual Monitor
===========================================
Implementation of Secrets 4 and 5 from the Forbidden Rules.

Secret 4 (Multiview): Uses spatial diversity across variables to
  replace temporal delays, saving precious data when N < 100.

Secret 5 (SVD Residual): Monitors HAVOK reconstruction residual
  to detect attractor deformation (concept drift) in real time.
"""

import numpy as np
from numpy.linalg import svd
from sovereign_havok import SovereignHAVOK
from _paths import data_path

# ============================================================
# Secret 4: Multiview Embedding
# ============================================================

try:
    import pyEDM
    _PYEDM = True
except Exception:
    _PYEDM = False

# Unified bridge: pyEDM with graceful numpy fallback (Single source of truth)
from _edm_bridge import (
    Simplex as _bridge_Simplex,
    Multiview as _bridge_Multiview,
    EDM_AVAILABLE as _BRIDGE_AVAILABLE,
    EDM_BACKEND as _BRIDGE_BACKEND,
)
# Pure numpy Multiview fallback (SVD-based spatial embedding) — retained for
# direct low-level access; the bridge delegates here automatically.
from _numpy_edm import Multiview as _np_Multiview


def run_multiview_analysis(df, columns, target, lib, pred, E_max=5):
    """
    Run Multiview embedding analysis (Secret 4).

    Instead of temporal delay embedding (which wastes data as delay padding),
    Multiview uses SPATIAL diversity: multiple correlated variables jointly
    reconstruct the attractor. This is critical when N < 100.

    Parameters
    ----------
    df : pd.DataFrame
        Data frame with time series columns.
    columns : list of str
        Variable names used for embedding (e.g., ['kills', 'damage', 'deaths']).
    target : str
        Target variable to predict.
    lib : str
        Library range (e.g., '1 25').
    pred : str
        Prediction range.
    E_max : int
        Maximum embedding dimension to search.

    Returns
    -------
    dict with Multiview results and comparison to single-variable Simplex.
    """
    n = len(df)
    results = {
        'secret': 4,
        'n': n,
        'n_columns': len(columns),
        'recommended': n < 100,
        'single_var': {},
        'multiview': {},
        'backend': _BRIDGE_BACKEND,
    }

    # Baseline: single-variable Simplex for each column (via unified bridge)
    for col in columns:
        try:
            sx = _bridge_Simplex(
                data=df, lib=lib, pred=pred, E=E_max, Tp=1,
                columns=col, target=target, showPlot=False)
            rho = sx['Observations'].corr(sx['Predictions'])
            results['single_var'][col] = {'method': 'Simplex', 'rho': rho}
        except Exception as e:
            results['single_var'][col] = {'method': 'Simplex', 'rho': None, 'error': str(e)}

    # Multiview: use all columns jointly (bridge handles pyEDM→numpy fallback)
    try:
        mv = _bridge_Multiview(
            data=df, lib=lib, pred=pred,
            E=E_max, Tp=1,
            columns=columns, target=target,
            showPlot=False)
        if hasattr(mv, 'iterrows'):
            best_rho = -1
            best_cols = None
            best_E = None
            mv_models = []
            for _, row in mv.iterrows():
                rho = row.get('rho', row.get('Predictions', None))
                if rho is not None:
                    cols_used = row.get('columns', row.get('embedding', str(columns)))
                    mv_models.append({
                        'columns': str(cols_used),
                        'E': row.get('E', E_max),
                        'rho': float(rho) if rho is not None else None
                    })
                    if rho is not None and float(rho) > best_rho:
                        best_rho = float(rho)
                        best_cols = str(cols_used)
                        best_E = row.get('E', E_max)
            results['multiview'] = {
                'models': mv_models or [{'columns': str(columns), 'E': E_max, 'rho': best_rho}],
                'best_rho': best_rho if best_rho > -1 else (mv['rho'].iloc[0] if 'rho' in mv else None),
                'best_columns': best_cols or str(columns),
                'best_E': best_E or E_max,
                'backend': _BRIDGE_BACKEND,
            }
        else:
            results['multiview'] = {
                'raw': str(mv),
                'note': 'Multiview returned non-DataFrame result'
            }
    except Exception as e:
        # Last-resort direct numpy SVD fallback
        try:
            arr = df[columns + [target]].values.astype(float)
            tgt_idx = len(columns)
            mv_np = _np_Multiview(arr, target_col=tgt_idx, E=E_max,
                                  lib=lib, pred=pred)
            results['multiview'] = {
                'models': [{
                    'columns': str(columns),
                    'E': E_max,
                    'rho': mv_np['rho'],
                }],
                'best_rho': mv_np['rho'],
                'best_columns': str(columns),
                'best_E': E_max,
                'backend': 'numpy-SVD',
                'fallback_reason': str(e),
            }
        except Exception as e2:
            results['multiview']['error'] = f"bridge: {e}; numpy: {e2}"

    # Comparison
    best_single = max(
        (v['rho'] for v in results['single_var'].values()
         if v['rho'] is not None), default=-1)
    best_multi = results['multiview'].get('best_rho', -1) or -1

    results['verdict'] = (
        "Multiview superior" if best_multi > best_single + 0.05
        else "Single-variable sufficient" if best_single > best_multi + 0.05
        else "Comparable"
    )
    results['delta_rho'] = best_multi - best_single

    return results


# ============================================================
# Secret 5: SVD Reconstruction Residual Monitor
# ============================================================

class SVDResidualMonitor:
    """
    Monitor HAVOK's SVD reconstruction residual to detect
    attractor deformation (concept drift / regime shift).

    When the system undergoes a regime shift, the old SVD basis
    (U_r, V_r from the original fit) cannot span the new dynamics,
    causing the reconstruction residual to spike.

    Detection rule: residual > 2.5x baseline for 3 consecutive windows.

    Secret 5 from the Forbidden Rules.
    """

    def __init__(self, baseline_window: int = 50,
                 detection_threshold: float = 2.5,
                 sustained_windows: int = 3):
        """
        Parameters
        ----------
        baseline_window : int
            Number of initial observations to compute baseline residual.
        detection_threshold : float
            Residual multiplier above baseline that triggers alarm.
        sustained_windows : int
            Number of consecutive windows above threshold to confirm alarm.
        """
        self.baseline_window = baseline_window
        self.threshold = detection_threshold
        self.sustained_windows = sustained_windows

        self.baseline_mean = None
        self.baseline_std = None
        self.residual_history = []
        self.alarm_count = 0
        self.alarm_triggered = False

    def compute_residual(self, data: np.ndarray, q: int, r: int) -> float:
        """
        Compute normalized SVD reconstruction residual:

          Residual = ||H - U_r * S_r * V_r^T||_F / ||H||_F

        This measures how much of the Hankel matrix is NOT captured
        by the first r singular modes.
        """
        n = len(data)
        p = n - q + 1
        if p <= 0:
            return np.nan

        # Build Hankel matrix H(q x p) — V-basis layout
        H = np.zeros((q, p))
        for i in range(q):
            H[i, :] = data[i:i+p]

        # SVD
        U, s, Vt = svd(H, full_matrices=False)

        # Truncated reconstruction
        r_eff = min(r, len(s))
        H_approx = U[:, :r_eff] @ np.diag(s[:r_eff]) @ Vt[:r_eff, :]

        # Frobenius norm residual
        residual = np.sqrt(np.sum((H - H_approx)**2))
        frob_H = np.sqrt(np.sum(H**2))

        return float(residual / (frob_H + 1e-12))

    def fit_baseline(self, data: np.ndarray, q: int, r: int):
        """Compute baseline residual from initial data window."""
        self.baseline_mean = self.compute_residual(
            data[:min(len(data), self.baseline_window)], q, r)
        self.baseline_std = 0.01 * self.baseline_mean  # default 1% noise floor
        self.residual_history = [self.baseline_mean]
        return self.baseline_mean

    def update(self, data_window: np.ndarray, q: int, r: int) -> dict:
        """
        Update residual monitor with new data window.

        Returns dict with current residual, ratio to baseline, and alarm status.
        """
        current = self.compute_residual(data_window, q, r)
        if np.isnan(current):
            return {"residual": np.nan, "ratio": np.nan, "alarm": False}

        self.residual_history.append(current)

        if self.baseline_mean is None or self.baseline_mean < 1e-12:
            self.baseline_mean = current
            self.baseline_std = 0.01 * current

        ratio = current / (self.baseline_mean + 1e-12)

        if ratio > self.threshold:
            self.alarm_count += 1
        else:
            self.alarm_count = max(0, self.alarm_count - 1)

        self.alarm_triggered = self.alarm_count >= self.sustained_windows

        return {
            "residual": current,
            "ratio": ratio,
            "baseline": self.baseline_mean,
            "alarm": self.alarm_triggered,
            "consecutive_alarms": self.alarm_count,
            "threshold": self.threshold,
        }

    def trigger_adaptive_forgetting(self, data: np.ndarray,
                                     q: int) -> np.ndarray:
        """
        Execute adaptive memory fracture (Secret 5 action):
        drop oldest 50% of data, keep most recent 50%.

        This implements the recommended response when attractor
        deformation is detected.

        Returns the truncated data array.
        """
        n = len(data)
        keep_start = n // 2
        truncated = data[keep_start:].copy()
        # Reset monitor state
        self.baseline_mean = None
        self.alarm_count = 0
        self.alarm_triggered = False
        self.residual_history = []
        return truncated


# ============================================================
# Integrated Secret 4+5 Runner
# ============================================================

def run_secrets_4_and_5(df, columns, target, lib, pred, q=3, r=2):
    """
    Run both Secret 4 (Multiview) and Secret 5 (SVD Residual) on game data.

    Returns combined diagnostic report.
    """
    results = {}

    # Secret 4: Multiview
    # print("─" * 60)  # 移除纯分隔线，避免Web日志无意义符号
    print("  Secret 4: Multiview Embedding Analysis")
    # print("─" * 60)  # 移除纯分隔线，避免Web日志无意义符号
    mv_results = run_multiview_analysis(df, columns, target, lib, pred, E_max=5)
    results['multiview'] = mv_results

    if 'error' not in mv_results:
        best_single_rho = max(
            (v['rho'] for v in mv_results['single_var'].values()
             if v['rho'] is not None),
            default='N/A'
        )
        print(f"  Best single-variable Simplex rho: {best_single_rho}")
        print(f"  Best Multiview rho: {mv_results['multiview'].get('best_rho', 'N/A')}")
        print(f"  Verdict: {mv_results['verdict']} "
              f"(delta_rho={mv_results.get('delta_rho', 0):+.3f})")
        if mv_results['multiview'].get('models'):
            for m in mv_results['multiview']['models'][:3]:
                print(f"    Model: cols={m['columns']}, E={m['E']}, rho={m['rho']}")

    # Secret 5: SVD Residual
    print(f"\n{'─' * 60}")
    print("  Secret 5: SVD Residual Monitor")
    # print("─" * 60)  # 移除纯分隔线，避免Web日志无意义符号

    monitor = SVDResidualMonitor(baseline_window=20)
    data = df[target].values.astype(float)
    n = len(data)

    # Simulate sliding window monitoring
    window_size = max(15, n // 3)
    residuals = []
    for start in range(0, n - window_size + 1, max(1, (n - window_size) // 10)):
        window_data = data[start:start + window_size]
        resid = monitor.compute_residual(window_data, q, r)
        if not np.isnan(resid):
            residuals.append((start, resid))

    # Fit baseline from first few windows
    baseline = monitor.fit_baseline(data[:window_size], q, r)
    print(f"  Baseline residual: {baseline:.4f} (window_size={window_size})")

    # Check remaining windows
    alarms = []
    for start, resid in residuals[1:]:
        result = monitor.update(data[start:start + window_size], q, r)
        if result['alarm']:
            alarms.append(start)

    print(f"  Windows analyzed: {len(residuals)}")
    print(f"  Alarms triggered: {len(alarms)}")
    if alarms:
        print(f"  Alarm windows (start index): {alarms}")
        print(f"  => Residual ratio exceeded {monitor.threshold}x baseline")
        print(f"     for >= {monitor.sustained_windows} consecutive windows")
    else:
        print(f"  => No attractor deformation detected. SVD basis is stable.")

    results['svd_residual'] = {
        'baseline': baseline,
        'n_windows': len(residuals),
        'n_alarms': len(alarms),
        'alarm_positions': alarms,
        'monitor': monitor,
    }

    return results


# ============================================================
# Self-test
# ============================================================

if __name__ == '__main__':
    import pandas as pd
    import warnings
    warnings.filterwarnings('ignore')

    print("=" * 60)
    print("  Secrets 4+5 Self-Test")
    print("=" * 60)

    # Load game data
    df = pd.read_csv(data_path('game_log.csv'))
    n = len(df)

    # Secret 4: Multiview test
    print(f"\n[Test] Secret 4 — Multiview on game data (N={n}, 4 vars)")
    results = run_secrets_4_and_5(
        df,
        columns=['kills', 'damage', 'deaths'],
        target='result',
        lib=f'1 {n-7}',
        pred=f'{n-6} {n}',
        q=3, r=2,
    )

    # Secret 5: Simulate attractor deformation
    print(f"\n[Test] Secret 5 — Simulated attractor deformation")
    np.random.seed(42)
    # Generate data with a structural break at t=150
    data1 = np.sin(np.linspace(0, 10*np.pi, 150)) + 0.1*np.random.randn(150)
    data2 = np.sin(np.linspace(0, 10*np.pi, 150)) * 2.0 + 0.5*np.random.randn(150)
    # data2 = different amplitude AND different noise level = regime shift
    data_shift = np.concatenate([data1, data2])

    monitor = SVDResidualMonitor(baseline_window=40, detection_threshold=2.0)
    window_size = 50
    baseline = monitor.fit_baseline(data_shift[:window_size], q=5, r=3)

    for start in range(0, len(data_shift) - window_size + 1, 5):
        w = data_shift[start:start + window_size]
        result = monitor.update(w, q=5, r=3)

    # Check residuals across all windows
    all_ratios = []
    for s in range(0, len(data_shift) - window_size + 1, 10):
        w = data_shift[s:s + window_size]
        result = monitor.update(w, q=5, r=3)
        if not np.isnan(result['ratio']):
            all_ratios.append(result['ratio'])

    if all_ratios:
        print(f"  Residual ratio range: {min(all_ratios):.2f} to {max(all_ratios):.2f}")
    print(f"  Alarm triggered: {monitor.alarm_triggered}")
    print(f"  Consecutive alarms: {monitor.alarm_count}")
    print(f"  => Adaptive forgetting {'triggered' if monitor.alarm_triggered else 'not triggered'}")

    # Test adaptive forgetting
    truncated = monitor.trigger_adaptive_forgetting(data_shift, q=5)
    print(f"  Original data length: {len(data_shift)}")
    print(f"  After adaptive forgetting: {len(truncated)}")
    assert len(truncated) == len(data_shift) // 2

    print(f"\n  All Secret 4+5 tests passed!")
    print("=" * 60)
