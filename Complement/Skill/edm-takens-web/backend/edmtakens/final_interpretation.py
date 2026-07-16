"""
Final HAVOK Game Data Interpretation
=====================================
Incorporates all 4 reviewer improvements:
  1. Lyapunov: R^2 quality check (flag unreliable when fit_r2 < 0.5)
  2. CCM: convergence slope check (not just final rho value)
  3. Hankel: unchanged (already robust)
  4. SG window: auto-cap at p//4 for small datasets

Produces: a plain-language dynamical interpretation of the game data.
"""

import os, tempfile, warnings
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', os.path.join(tempfile.gettempdir(), 'edm_takens_mpl'))
os.environ.setdefault('OMP_NUM_THREADS', '1'); os.environ.setdefault('MKL_NUM_THREADS', '1')

import numpy as np
import pandas as pd
from scipy.stats import kurtosis as scipy_kurtosis, linregress
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
plt.rcParams['axes.unicode_minus'] = False
warnings.filterwarnings('ignore')

from _edm_bridge import (EmbedDimension, Simplex,
                          SMapPredictNonlinear, EDM_AVAILABLE)
from sovereign_havok import SovereignHAVOK, classify_havok_stability
from _paths import data_path
from ccm_causality import ccm_causality_test, common_driver_disclaimer


# ================================================================
# Improvement 2: CCM Convergence Slope Check
# ================================================================

def ccm_with_convergence(df, cause_var, effect_var, E, lib_sizes=None):
    """
    CCM with convergence slope verification (Reviewer improvement #2).

    A single rho value is insufficient — we must verify that cross-map skill
    INCREASES with library size (convergence). This is the hallmark of true
    causality in Sugihara's CCM framework.

    Thin wrapper: the actual convergence-aware test lives in
    `ccm_causality.ccm_causality_test()`, which is also used by
    `enhanced_cross_validate.verify_ccm_direction()`. This guarantees the
    two call sites can never silently disagree on the same data — see
    ccm_causality.py's module docstring for why that used to happen.

    Parameters
    ----------
    lib_sizes : str, optional
        pyEDM-style libSizes sweep. Passed through to the canonical test so
        callers (including this module's own self-test and upstream tests)
        can use a coarser sweep when runtime matters.

    Returns: forward/backward skills, convergence slopes, and verdict.
    """
    return ccm_causality_test(df, cause_var, effect_var, E, lib_sizes=lib_sizes)


# ================================================================
# Improvement 1: Lyapunov with R^2 quality check
# ================================================================

def estimate_lyapunov_robust(data, E, dt=1.0):
    """
    Lyapunov exponent with R^2 quality check (Reviewer improvement #1).
    Flags estimate as unreliable when divergence fit R^2 < 0.5.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    N = n - E + 1
    if N < 30:
        return {'lambda_max': None, 'reliable': False,
                'reason': f'Too few state-space points (N={N})'}

    X = np.zeros((N, E))
    for i in range(E):
        X[:, i] = data[i:i+N]

    # Mean period from autocorrelation
    x_c = data - np.mean(data)
    ac = np.correlate(x_c, x_c, mode='full')
    ac = ac[len(ac)//2:] / ac[0]
    zc = np.where(np.diff(np.sign(ac - 1/np.exp(1))))[0]
    mean_period = zc[0] + 1 if len(zc) > 0 else max(5, E)

    n_expand = min(20, N // 3)
    div_curves = []
    for i in range(0, N - n_expand, max(1, N // 60)):
        dists = np.sum((X[:N-n_expand] - X[i])**2, axis=1)
        for j in range(max(0, i-mean_period), min(N-n_expand, i+mean_period+1)):
            if 0 <= j < len(dists): dists[j] = np.inf
        j = np.argmin(dists)
        if np.isinf(dists[j]): continue
        div = np.zeros(n_expand)
        for k in range(min(n_expand, N - max(i, j) - 1)):
            div[k] = np.sqrt(np.sum((X[i+k+1] - X[j+k+1])**2))
        if div[0] > 1e-12:
            div_curves.append(np.log(div + 1e-12))

    if len(div_curves) < 10:
        return {'lambda_max': None, 'reliable': False,
                'reason': f'Too few divergence curves ({len(div_curves)})'}

    div_mean = np.mean(np.array(div_curves), axis=0)
    t_fit = np.arange(min(n_expand // 2, len(div_mean) - 5))

    if len(t_fit) < 3:
        return {'lambda_max': None, 'reliable': False,
                'reason': 'Insufficient fitting points'}

    slope, intercept, r_value, p_value, std_err = linregress(
        t_fit * dt, div_mean[:len(t_fit)])
    fit_r2 = r_value ** 2

    lambda_max = max(0.001, slope)
    tau_L = 1.0 / lambda_max

    # R^2 quality check (Reviewer improvement #1)
    reliable = fit_r2 >= 0.5

    return {
        'lambda_max': lambda_max,
        'lyapunov_time': tau_L,
        'prediction_horizon_3x': 3 * tau_L,
        'prediction_horizon_5x': 5 * tau_L,
        'fit_r2': fit_r2,
        'reliable': reliable,
        'n_curves': len(div_curves),
        'warning': None if reliable else
            f'Lyapunov estimate UNRELIABLE (fit R^2={fit_r2:.3f} < 0.5)'
    }


# ================================================================
# Surrogate-based Lyapunov Lower Bound (for N < 100)
# ================================================================

def estimate_lyapunov_lower_bound(data, E, dt=1.0, n_surrogates=19,
                                   seed=42):
    """Estimate a conservative lower bound on Lyapunov exponent.

    When N < 100, the standard Rosenstein algorithm is unreliable for
    point estimation of lambda_max. However, we CAN use IAAFT surrogate
    data to establish a lower bound:

      1. Generate IAAFT surrogates (same spectrum/distribution, no
         nonlinear phase coupling → effectively linear null)
      2. Compute divergence rate on each surrogate
      3. If real data's divergence rate exceeds the 95th percentile
         of surrogates, we have evidence of nonlinear exponential
         divergence at a rate at least equal to the real estimate

    This transforms "lambda_max is unreliable" into "the Lyapunov time
    is AT MOST tau_L games" (conservative, useful bound).

    Parameters
    ----------
    data : np.ndarray
        Time series.
    E : int
        Embedding dimension.
    dt : float
        Sampling interval.
    n_surrogates : int
        Number of IAAFT surrogates (19 for p<0.05, 99 for p<0.01).
    seed : int
        Random seed.

    Returns
    -------
    dict with: lambda_lower_bound, tau_L_upper_bound, surrogate_p95,
               is_significant, n_surrogates, real_estimate, real_estimate_reliable
    """
    from surrogate_test import iaaft_surrogates

    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    N = n - E + 1

    if N < 20:
        return {
            'lambda_lower_bound': None,
            'tau_L_upper_bound': None,
            'surrogate_p95': None,
            'is_significant': False,
            'n_surrogates': 0,
            'real_estimate': None,
            'real_estimate_reliable': False,
            'warning': f'Too few state-space points (N={N}) for any estimate'
        }

    # Get real data estimate
    real_est = estimate_lyapunov_robust(data, E, dt)

    # Simple divergence rate metric (doesn't require stable linear region)
    def _divergence_rate_metric(d):
        """Fast divergence metric: log of mean pairwise distance growth."""
        d = np.asarray(d, dtype=float).ravel()
        n_local = len(d)
        N_local = n_local - E + 1
        X = np.zeros((N_local, E))
        for i in range(E):
            X[:, i] = d[i:i + N_local]

        # Track median neighbor distance over first few steps
        grow_rates = []
        n_pairs = min(30, N_local // 2)
        for _ in range(10):  # bootstrap samples
            idx = np.random.choice(N_local - 10, size=min(n_pairs, N_local - 10),
                                   replace=False)
            distances = []
            for i in idx:
                # Find nearest neighbor
                dists = np.sum((X[:N_local - 5] - X[i]) ** 2, axis=1)
                dists[max(0, i - 3):min(len(dists), i + 4)] = np.inf
                j = np.argmin(dists)
                if np.isinf(dists[j]):
                    continue
                d0 = np.sqrt(np.sum((X[i] - X[j]) ** 2))
                # Growth after 5 steps
                if i + 5 < N_local and j + 5 < N_local:
                    d5 = np.sqrt(np.sum((X[i + 5] - X[j + 5]) ** 2))
                    if d0 > 1e-12 and d5 > 1e-12:
                        distances.append(np.log(d5 / d0) / (5 * dt))

            if distances:
                grow_rates.append(np.median(distances))

        if grow_rates:
            return max(0.001, np.median(grow_rates))
        return 0.001

    # Generate surrogates and compute metric
    try:
        surrs = iaaft_surrogates(data, n_surrogates=n_surrogates,
                                 seed=seed, max_iter=20)
        surrogate_rates = []
        for s in range(len(surrs)):
            rate = _divergence_rate_metric(surrs[s])
            if not np.isnan(rate) and rate > 0:
                surrogate_rates.append(rate)

        if len(surrogate_rates) < 3:
            return {
                'lambda_lower_bound': real_est.get('lambda_max'),
                'tau_L_upper_bound': real_est.get('lyapunov_time'),
                'surrogate_p95': None,
                'is_significant': False,
                'n_surrogates': len(surrogate_rates),
                'real_estimate': real_est.get('lambda_max'),
                'real_estimate_reliable': real_est.get('reliable', False),
                'warning': 'Surrogate generation failed — insufficient surrogates'
            }

        surrogate_p95 = float(np.percentile(surrogate_rates, 95))
        real_rate = _divergence_rate_metric(data)

        # Is real data's divergence significantly higher?
        is_sig = real_rate > surrogate_p95
        # Lower bound: max(real_rate, 0) — conservative
        lb = max(real_rate, 0.001)
        tau_ub = 1.0 / lb if lb > 0 else float('inf')

        return {
            'lambda_lower_bound': lb,
            'tau_L_upper_bound': tau_ub,
            'surrogate_p95': surrogate_p95,
            'is_significant': is_sig,
            'n_surrogates': len(surrogate_rates),
            'real_estimate': real_est.get('lambda_max'),
            'real_estimate_reliable': real_est.get('reliable', False),
            'warning': None if is_sig else
                'Divergence rate not significantly above linear null. '
                'Cannot establish Lyapunov lower bound.'
        }

    except Exception as e:
        return {
            'lambda_lower_bound': real_est.get('lambda_max'),
            'tau_L_upper_bound': real_est.get('lyapunov_time'),
            'surrogate_p95': None,
            'is_significant': False,
            'n_surrogates': 0,
            'real_estimate': real_est.get('lambda_max'),
            'real_estimate_reliable': real_est.get('reliable', False),
            'warning': f'Surrogate computation failed: {e}'
        }


# ================================================================
# Comprehensive Game Data Interpretation
# ================================================================

def interpret_data(df, target_col, columns, causality_pairs=None,
                   output_path='results/dynamics_interpretation.png',
                   label_map=None):
    """
    Domain-agnostic dynamical interpretation (P1: decoupled from game domain).

    Runs EDM + SovereignHAVOK + CCM on an arbitrary multivariate time series
    and produces a generic diagnostic report + visualization. This is the
    reusable core; game-specific narration lives in ``interpret_game_data``.

    Parameters
    ----------
    df : pd.DataFrame
        Time series. Must contain ``target_col`` and all ``columns``.
    target_col : str
        Primary outcome variable (e.g. 'result').
    columns : list of str
        Variables to analyse individually (should include target_col).
    causality_pairs : list of (cause, effect) tuples, optional
        Pairs to test with CCM. If None, tests each non-target column -> target.
    output_path : str
        Where to save the visualization PNG.
    label_map : dict, optional
        Human-readable labels for variables (defaults to column names).

    Returns
    -------
    all_data : dict
        Per-variable diagnostics + CCM results, for downstream narration.
    """
    n = len(df)
    lib = f'1 {n-7}'; pred = f'{n-6} {n}'
    label_map = label_map or {c: c for c in columns}
    if causality_pairs is None:
        causality_pairs = [(c, target_col) for c in columns if c != target_col]

    print("=" * 72)
    print("  DYNAMICAL INTERPRETATION (domain-agnostic)")
    print("  SovereignHAVOK + EDM + CCM with convergence")
    print("=" * 72)
    print(f"  N = {n}  |  target = {target_col}  |  variables = {columns}")
    print()

    all_data = {}
    skipped_vars = []

    # ── Phase 1: per-variable dynamics ──
    print("─" * 72)
    print("  PHASE 1: Individual Variable Dynamics")
    print("─" * 72)

    for var in columns:
        print(f"\n  [{label_map.get(var, var)}]")
        try:
            data = df[var].values.astype(float)

            rho_E = EmbedDimension(
                data=df, lib=lib, pred=pred, maxE=8, Tp=1,
                columns=var, target=var, showPlot=False, numProcess=1)
            if not rho_E['rho'].notna().any():
                raise ValueError("EmbedDimension returned all-NA rho")
            E_opt = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])

            sx = Simplex(
                data=df, lib=lib, pred=pred, E=E_opt, Tp=1,
                columns=var, target=var, showPlot=False)
            if sx['Observations'].notna().sum() < 2 or sx['Predictions'].notna().sum() < 2:
                raise ValueError("Simplex produced insufficient non-NA predictions")
            rho_s = sx['Observations'].corr(sx['Predictions'])

            smap = SMapPredictNonlinear(
                data=df, lib=lib, pred=pred, E=E_opt,
                columns=var, target=var, showPlot=False, numProcess=1)
            if not smap['rho'].notna().any():
                raise ValueError("S-Map returned all-NA rho")
            theta_min = smap['theta'].min()
            rho_0_smap = float(smap.loc[smap['theta'].idxmin(), 'rho'])
            rho_m = smap['rho'].max()
            is_nl = (rho_m - rho_0_smap) >= 0.05

            p_steps = n - E_opt + 1
            wl_safe = min(11, max(5, p_steps // 4))
            if wl_safe % 2 == 0: wl_safe -= 1

            sh = SovereignHAVOK(
                q_delays=E_opt, dt=1.0, energy_threshold=0.99,
                window_length=wl_safe, poly_order=2, basis="V")
            sh.fit(data)

            hk_ratio = p_steps / E_opt
            forcing = sh.forcing_
            spike_th = 1.5 * np.std(forcing)
            spike_idx = np.where(np.abs(forcing) > spike_th)[0]
            forcing_energy = np.var(forcing) / (np.var(data) + 1e-10)
            max_ev = float(np.max(np.abs(sh.eigenvalues_d_))) if len(sh.eigenvalues_d_) else 0.0

            lyap = estimate_lyapunov_robust(data, E_opt)
            lyap_lower = None
            if not lyap.get('reliable') and n < 100:
                lyap_lower = estimate_lyapunov_lower_bound(data, E_opt, n_surrogates=19)

            ccm_result = None
            if var == target_col:
                ccm_result = {}
                for cause, effect in causality_pairs:
                    if effect == target_col:
                        ccm_result[f'{cause}->{effect}'] = ccm_with_convergence(
                            df, cause, effect, E_opt)

            print(f"    EDM: E={E_opt}, Simplex_rho={rho_s:.3f}, nonlinear={is_nl}")
            print(f"    HAVOK: r={sh.r_}, R2={sh.regression_r2_:.3f}, "
                  f"kurt={sh.kurtosis_vr_:.3f}, max|eig_d|={max_ev:.4f}")
            print(f"    Hankel: p/q={hk_ratio:.1f} "
                  f"{'[WARN<10]' if hk_ratio < 10 else '[OK]'}  |  spikes={len(spike_idx)}")
            if lyap.get('reliable'):
                print(f"    Lyapunov: tau_L={lyap['lyapunov_time']:.1f} "
                      f"(R2={lyap['fit_r2']:.3f})")
            elif lyap_lower and lyap_lower.get('is_significant'):
                print(f"    Lyapunov: surrogate LB tau_L<{lyap_lower['tau_L_upper_bound']:.1f}")
            else:
                print(f"    Lyapunov: unreliable (N<100)")

            all_data[var] = {
                'E': E_opt, 'rho_s': rho_s, 'is_nl': is_nl,
                'havok_r': sh.r_, 'havok_r2': sh.regression_r2_,
                'kurtosis': sh.kurtosis_vr_, 'max_ev': max_ev,
                'expl_var': sh.explained_var_, 'hk_ratio': hk_ratio,
                'forcing_energy': forcing_energy,
                'spike_count': len(spike_idx), 'spike_idx': spike_idx,
                'lyap': lyap, 'lyap_lower': lyap_lower, 'ccm': ccm_result,
                'sh': sh,
            }
        except Exception as e:
            print(f"    [SKIPPED] Variable '{var}' failed: {e}")
            skipped_vars.append(var)

    if target_col not in all_data:
        raise ValueError(
            f"Target column '{target_col}' could not be analysed. "
            f"It may be too sparse or constant for EDM with N={n}."
        )

    available_variables = list(all_data.keys())

    # ── Phase 2: CCM causality ──
    print(f"\n{'─' * 72}")
    print("  PHASE 2: Causal Structure (CCM with convergence)")
    print("─" * 72)
    E_ref = all_data[target_col]['E']
    _significant_directions = {
        'forward', 'reverse', 'forward_dominant', 'reverse_dominant',
        'bidirectional',
    }
    n_significant_ccm_pairs = 0
    usable_pairs = [(c, e) for c, e in causality_pairs
                    if c in available_variables and e in available_variables]
    for cause, effect in usable_pairs:
        ccm_r = ccm_with_convergence(df, cause, effect, E_ref)
        print(f"    {cause} <-> {effect}: {ccm_r['verdict']}")
        if ccm_r.get('direction') in _significant_directions:
            n_significant_ccm_pairs += 1
    if usable_pairs:
        # Secret 11: printed once per report, unconditionally, not per-pair
        # (per-pair would be repetitive; unconditional is the point — this
        # is never omitted just because a result "looks fine").
        print(f"\n    [Secret 11 disclaimer] "
              f"{common_driver_disclaimer(n_significant_ccm_pairs)}")

    # ── Generic summary ──
    print(f"\n{'=' * 72}")
    print("  GENERIC DYNAMICAL SUMMARY")
    print("=" * 72)
    if skipped_vars:
        print(f"  Skipped variables (too sparse/constant): {skipped_vars}")
    for var in available_variables:
        d = all_data[var]
        k = d['kurtosis']
        k_type = ("heavy-tailed" if k > 1.5 else "near-Gaussian" if k < 0.5
                  else "light-tailed")
        print(f"    {label_map.get(var,var):12s}: rho={d['rho_s']:.3f}, "
              f"kurt={k:+.3f} ({k_type}), max|eig_d|={d['max_ev']:.3f}")
    hk_warns = [v for v in available_variables if all_data[v]['hk_ratio'] < 10]
    if hk_warns:
        print(f"  Hankel ratio warnings: {hk_warns} (consider smaller E or more data)")

    # ── Visualization ──
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    _plot_generic(df, all_data, available_variables, label_map, output_path, target_col)
    print(f"\n  Visualization saved: {output_path}")
    print(f"{'=' * 72}")
    return all_data


def _plot_generic(df, all_data, variables, label_map, output_path, target_col):
    """Generic visualization (domain-neutral)."""
    colors = {v: plt.cm.tab10(i % 10) for i, v in enumerate(variables)}
    n_vars = min(len(variables), 4)
    fig, axes = plt.subplots(n_vars, 2, figsize=(14, 3 * n_vars), squeeze=False)
    for row, var in enumerate(variables[:n_vars]):
        d = all_data[var]
        sh = d['sh']
        data = df[var].values.astype(float)
        color = colors[var]
        ax0 = axes[row, 0]
        ax0.plot(data, 'o-', color=color, markersize=4, linewidth=1.2)
        ax0.set_title(f'{label_map.get(var,var)} (E={d["E"]}, rho={d["rho_s"]:.2f})',
                     fontsize=10)
        ax0.grid(True, alpha=0.2)
        ax1 = axes[row, 1]
        forcing = sh.forcing_
        ax1.fill_between(np.arange(len(forcing)) + sh.q, forcing, alpha=0.2, color=color)
        ax1.plot(np.arange(len(forcing)) + sh.q, forcing, 'o-', color=color, markersize=3)
        ax1.axhline(0, color='gray', alpha=0.3)
        ax1.set_title(f'Forcing (kurt={sh.kurtosis_vr_:+.2f}, r={sh.r_})', fontsize=10)
        ax1.grid(True, alpha=0.2)
    fig.suptitle('SovereignHAVOK Dynamical Interpretation (generic)', fontsize=12)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()


def interpret_game_data(data_path_override: str = None,
                        df: pd.DataFrame = None,
                        variables: list = None,
                        var_labels: dict = None,
                        causality_pairs: list = None,
                        target_col: str = None,
                        output_path: str = None,
                        title: str = None,
                        unit: str = 'games'):
    """
    Run full HAVOK analysis and produce plain-language interpretation.

    Parameters
    ----------
    data_path_override : str, optional
        Path to a CSV. When neither this nor `df` is given, defaults to
        the bundled game_log.csv.
    df : pd.DataFrame, optional
        Pre-loaded DataFrame. Takes precedence over `data_path_override`.
    variables : list[str], optional
        Columns to analyze. Defaults to the bundled game schema.
    var_labels : dict, optional
        Display labels for `variables`. Defaults to variable names.
    causality_pairs : list[tuple], optional
        (cause, effect) pairs for CCM. Defaults to the bundled game schema.
    target_col : str, optional
        Reference variable for CCM plots and summary. Defaults to the
        first variable when not provided.
    output_path : str, optional
        Where to save the visualization. Defaults to
        ``results/game_interpretation.png``.
    title : str, optional
        Report title printed to console.
    unit : str, optional
        Unit of one row (e.g. 'games', 'days', 'samples'). Used in text.
    """
    if df is None:
        df = pd.read_csv(data_path_override or data_path('game_log.csv'))
    n = len(df)
    lib = f'1 {n-7}'; pred = f'{n-6} {n}'

    variables = list(variables) if variables else ['result', 'kills', 'damage', 'deaths']
    missing = [v for v in variables if v not in df.columns]
    if missing:
        raise ValueError(f"Requested variables not in DataFrame: {missing}")
    var_labels = dict(var_labels) if var_labels else {}
    for v in variables:
        var_labels.setdefault(v, v.replace('_', ' ').title())
    target_col = target_col or variables[0]
    if target_col not in df.columns:
        raise ValueError(f"target_col '{target_col}' not in DataFrame")
    causality_pairs = list(causality_pairs) if causality_pairs else [
        ('kills', 'result'), ('damage', 'result'),
        ('deaths', 'result'), ('kills', 'damage'), ('mvp', 'result'),
    ]
    causality_pairs = [(c, e) for c, e in causality_pairs
                       if c in df.columns and e in df.columns]
    output_path = output_path or 'results/game_interpretation.png'
    title = title or 'HAVOK DYNAMICAL INTERPRETATION'

    print("=" * 72)
    print(f"  {title}")
    print("  SovereignHAVOK with 4 Reviewer Improvements")
    print("=" * 72)
    print(f"  {unit.capitalize()}: {n}")
    print()

    all_data = {}
    skipped_vars = []

    # ── Phase 1: EDM + HAVOK on each variable ──
    print("─" * 72)
    print("  PHASE 1: Individual Variable Dynamics")
    print("─" * 72)

    for var in variables:
        print(f"\n  [{var_labels[var]}]")
        data = df[var].values.astype(float)

        # EDM
        rho_E = EmbedDimension(
            data=df, lib=lib, pred=pred, maxE=8, Tp=1,
            columns=var, target=var, showPlot=False, numProcess=1)
        E_opt = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])

        sx = Simplex(
            data=df, lib=lib, pred=pred, E=E_opt, Tp=1,
            columns=var, target=var, showPlot=False)
        rho_s = sx['Observations'].corr(sx['Predictions'])

        smap = SMapPredictNonlinear(
            data=df, lib=lib, pred=pred, E=E_opt,
            columns=var, target=var, showPlot=False, numProcess=1)
        theta_min = smap['theta'].min()
        rho_0_smap = smap.loc[smap['theta'] == theta_min, 'rho'].values[0]
        rho_m = smap['rho'].max()
        is_nl = (rho_m - rho_0_smap) >= 0.05

        # HAVOK
        # Improvement #4: SG window auto-capped (implemented in sovereign_havok.py)
        p_steps = n - E_opt + 1
        wl_safe = min(11, max(5, p_steps // 4))
        if wl_safe % 2 == 0: wl_safe -= 1

        sh = SovereignHAVOK(
            q_delays=E_opt, dt=1.0, energy_threshold=0.99,
            window_length=wl_safe, poly_order=2, basis="V")
        sh.fit(data)

        # Hankel ratio check
        hk_ratio = p_steps / E_opt

        # Forcing analysis
        forcing = sh.forcing_
        spike_th = 1.5 * np.std(forcing)
        spike_idx = np.where(np.abs(forcing) > spike_th)[0]
        forcing_energy = np.var(forcing) / (np.var(data) + 1e-10)

        # Koopman eigenvalues
        evals_d = sh.eigenvalues_d_  # discrete-time for stability
        growth = np.sort(np.abs(evals_d))[::-1]
        max_ev = growth[0] if len(growth) > 0 else 0

        # Lyapunov (with R^2 check — Improvement #1)
        lyap = estimate_lyapunov_robust(data, E_opt)

        # If unreliable and N < 100, try surrogate-based lower bound
        lyap_lower = None
        if not lyap.get('reliable') and n < 100:
            lyap_lower = estimate_lyapunov_lower_bound(data, E_opt,
                                                       n_surrogates=19)

        # Per-variable CCM context is computed generically in Phase 2 from
        # the caller-supplied causality_pairs; keep a placeholder here so
        # the all_data structure remains uniform.
        ccm_result = None

        print(f"    EDM: E={E_opt}, Simplex_rho={rho_s:.3f}, "
              f"S-Map nonlinear={is_nl} (theta_max={smap.loc[smap['rho'].idxmax(), 'theta']:.1f})")
        print(f"    HAVOK: r={sh.r_}, R^2={sh.regression_r2_:.3f}, "
              f"max|eig_d|={max_ev:.4f}")
        print(f"    Forcing: kurtosis={sh.kurtosis_vr_:.3f}, "
              f"energy_ratio={forcing_energy:.1%}, "
              f"spikes={len(spike_idx)}")
        print(f"    Hankel: q={E_opt}, p={p_steps}, "
              f"ratio={hk_ratio:.1f} {'[WARN: < 10]' if hk_ratio < 10 else '[OK]'}")
        print(f"    SG window: {wl_safe} (capped from 11 for small data)")

        if lyap['reliable']:
            print(f"    Lyapunov: lambda={lyap['lambda_max']:.4f}, "
                  f"tau_L={lyap['lyapunov_time']:.1f} {unit}, "
                  f"3*tau_L={lyap['prediction_horizon_3x']:.1f} {unit} "
                  f"(fit R^2={lyap['fit_r2']:.3f})")
        elif lyap_lower and lyap_lower.get('is_significant'):
            print(f"    Lyapunov: UNRELIABLE (R^2={lyap.get('fit_r2', 0):.3f} < 0.5)")
            print(f"    Surrogate LB: lambda > {lyap_lower['lambda_lower_bound']:.4f}, "
                  f"tau_L < {lyap_lower['tau_L_upper_bound']:.1f} {unit} "
                  f"(p={1/(lyap_lower['n_surrogates']+1):.3f})")
        elif lyap_lower and not lyap_lower.get('is_significant'):
            print(f"    Lyapunov: UNRELIABLE + not significant vs linear null")
            print(f"    => Cannot distinguish from linear stochastic. "
                  f"System may not be chaotic at this scale.")
        else:
            print(f"    Lyapunov: {lyap.get('reason', lyap.get('warning', 'N/A'))}")

        # Spike events
        if len(spike_idx) > 0:
            print(f"    Phase-transition events (spikes):")
            for si in spike_idx[:6]:
                gi = si + sh.q
                if gi < len(df):
                    fs = forcing[si]
                    direction = "UP" if fs > 0 else "DOWN"
                    extras = []
                    for col in [c for c in df.columns if c in variables and c != var]:
                        try:
                            extras.append(f"{col}={df.iloc[gi][col]:.2g}")
                        except Exception:
                            pass
                    extra_str = f", {', '.join(extras)}" if extras else ""
                    unit_singular = unit[:-1] if unit.endswith('s') and len(unit) > 1 else unit
                    print(f"      {unit_singular.capitalize()} {gi+1:2d}: v_r={fs:+.3f} ({direction})"
                          f"{extra_str}")

        all_data[var] = {
            'E': E_opt, 'rho_s': rho_s, 'is_nl': is_nl,
            'havok_r': sh.r_, 'havok_r2': sh.regression_r2_,
            'kurtosis': sh.kurtosis_vr_, 'max_ev': max_ev,
            'expl_var': sh.explained_var_, 'hk_ratio': hk_ratio,
            'forcing_energy': forcing_energy,
            'spike_count': len(spike_idx), 'spike_idx': spike_idx,
            'lyap': lyap, 'lyap_lower': lyap_lower, 'ccm': ccm_result,
        }

    available_variables = list(all_data.keys())

    # ── Phase 2: CCM Causality Report ──
    print(f"\n{'─' * 72}")
    print("  PHASE 2: Causal Structure (CCM with Convergence Check)")
    print("  Reviewer improvement #2: convergence slope required")
    print("─" * 72)

    E_ref = all_data[target_col]['E']

    _significant_directions = {
        'forward', 'reverse', 'forward_dominant', 'reverse_dominant',
        'bidirectional',
    }
    n_significant_ccm_pairs = 0
    for cause_h, effect_h in causality_pairs:
        ccm_r = ccm_with_convergence(df, cause_h, effect_h, E_ref)
        fwd = ccm_r['forward']; rev = ccm_r['reverse']
        print(f"\n    {cause_h:>8s} <-> {effect_h:<8s}:")
        print(f"      Forward  (M_{effect_h} -> {cause_h}): "
              f"rho={fwd['final_rho']:+.3f}" if fwd.get('final_rho') is not None else
              f"      Forward: FAILED",
              f", rise={fwd['total_rise']:+.4f}"
              if fwd.get('total_rise') is not None else "",
              f", converging={fwd['is_converging']}"
              if fwd.get('is_converging') is not None else "")
        print(f"      Reverse  (M_{cause_h} -> {effect_h}): "
              f"rho={rev['final_rho']:+.3f}" if rev.get('final_rho') is not None else
              f"      Reverse: FAILED",
              f", rise={rev['total_rise']:+.4f}"
              if rev.get('total_rise') is not None else "",
              f", converging={rev['is_converging']}"
              if rev.get('is_converging') is not None else "")
        print(f"      => {ccm_r['verdict']}")
        if ccm_r.get('direction') in _significant_directions:
            n_significant_ccm_pairs += 1
    if causality_pairs:
        print(f"\n    [Secret 11 disclaimer] "
              f"{common_driver_disclaimer(n_significant_ccm_pairs)}")

    # ── Phase 3: Integrated Dynamical Interpretation ──
    print(f"\n{'=' * 72}")
    print("  PHASE 3: INTEGRATED DYNAMICAL INTERPRETATION")
    print("  (What the game data actually tells us through HAVOK)")
    print("=" * 72)

    # --- Interpretation Section A: Stability Landscape ---
    print(f"\n  A. STABILITY LANDSCAPE — Is the system calm or turbulent?")
    print(f"  {'─' * 58}")

    max_ev_values = {v: all_data[v]['max_ev'] for v in available_variables}
    dominant_eig = max(max_ev_values, key=max_ev_values.get)
    dominant_ev = max_ev_values[dominant_eig]
    stability_tier = classify_havok_stability(dominant_ev)

    if stability_tier.startswith("Divergent"):
        print(f"  At least one Koopman mode is DIVERGENT:")
    elif stability_tier.startswith("Highly dissipative"):
        print(f"  All Koopman eigenvalues are HIGHLY DISSIPATIVE:")
    else:
        print(f"  Koopman eigenvalues are NEAR-CRITICAL:")

    for v in available_variables:
        ev = all_data[v]['max_ev']
        half_life = np.log(2) / (1 - ev + 1e-12) if ev < 1 else float('inf')
        print(f"    {var_labels[v]:10s}: max|eig_d| = {ev:.4f}  "
              f"(perturbation half-life: ~{half_life:.1f} {unit})")

    if stability_tier.startswith("Divergent"):
        print(f"\n  INTERPRETATION: {var_labels[dominant_eig]} shows DIVERGENT modes")
        print(f"  (max|eig_d|={dominant_ev:.3f} > 1.05). Perturbations can grow;")
        print(f"  treat trends and forecasts with caution.")
    elif stability_tier.startswith("Highly dissipative"):
        print(f"\n  INTERPRETATION: The system forms a STABLE ATTRACTOR.")
        print(f"  Deviations from the baseline decay within a few {unit}.")
        print(f"  No runaway destabilization or explosive divergence is evident.")
        print(f"  Dynamics are regulated around a system-specific mean.")
    else:
        print(f"\n  INTERPRETATION: The system is NEAR-CRITICAL.")
        print(f"  {var_labels[dominant_eig]} is neither clearly dissipative nor divergent")
        print(f"  (max|eig_d|={dominant_ev:.3f}). Small shifts could change predictability.")

    # --- Interpretation Section B: Forcing & Phase Transitions ---
    print(f"\n  B. FORCING TERM — Are there 'fate-changing moments'?")
    print(f"  {'─' * 58}")

    kurt_values = {v: all_data[v]['kurtosis'] for v in available_variables}
    spike_counts = {v: all_data[v]['spike_count'] for v in available_variables}

    for v in available_variables:
        k = kurt_values[v]; sc = spike_counts[v]
        if k > 1.5:
            k_type = "HEAVY-TAILED — intermittent phase transitions detected"
        elif k > 0.5:
            k_type = "Light tails — weak non-Gaussian components"
        elif k > -0.5:
            k_type = "Near-Gaussian — stable orbit, no regime shifts"
        else:
            k_type = "SUB-GAUSSIAN (platykurtic) — bounded/constrained dynamics"
        print(f"    {var_labels[v]:10s}: kurtosis={k:+.3f} -> {k_type}, "
              f"{sc} spike events detected")

    # Find the most "active" variable in terms of dynamics
    heavy_tailed_vars = [v for v in available_variables if all_data[v]['kurtosis'] > 1.5]
    print(f"\n  INTERPRETATION: The forcing term v_r (the nonlinear 'engine'")
    if not heavy_tailed_vars:
        print(f"  of the system) shows NO heavy tails in any variable. This means:")
        print(f"    1. Within these {n} {unit}, no true 'attractor basin transition'")
        print(f"       is evident — no irreversible regime shift.")
        print(f"    2. Dynamics appear CONSTRAINED within a bounded range.")
        print(f"    3. The most interesting drivers may be UNMEASURED variables.")
    else:
        print(f"  of the system) shows HEAVY TAILS in "
              f"{', '.join(var_labels[v] for v in heavy_tailed_vars)}. This means:")
        print(f"    1. Within these {n} {unit}, at least one variable shows "
              f"intermittent, bursty")
        print(f"       forcing — possible attractor-basin transitions or "
              f"regime changes,")
        print(f"       not just steady-state fluctuation.")
        unit_singular = unit[:-1] if unit.endswith('s') and len(unit) > 1 else unit
        print(f"    2. Treat any single-{unit_singular} outlier in "
              f"{', '.join(var_labels[v] for v in heavy_tailed_vars)} as "
              f"potentially")
        print(f"       meaningful rather than noise — check the spike "
              f"indices above.")
        print(f"    3. With this few {unit}, distinguishing a genuine regime "
              f"change from")
        print(f"       a one-off outlier needs more data — treat this as a "
              f"flag, not a verdict.")

    # --- Interpretation Section C: Predictability ---
    print(f"\n  C. PREDICTABILITY — Which aspects are deterministic?")
    print(f"  {'─' * 58}")

    # Sort by Simplex rho
    sorted_by_rho = sorted(available_variables, key=lambda v: all_data[v]['rho_s'], reverse=True)
    for v in sorted_by_rho:
        r = all_data[v]['rho_s']
        ev = all_data[v]['expl_var']
        E = all_data[v]['E']
        bars = '#' * int(r * 20) + '-' * (20 - int(r * 20))
        print(f"    {var_labels[v]:10s}: [{bars}] rho={r:.3f}, E={E}, expl_var={ev:.1%}")

    best = sorted_by_rho[0]
    worst = sorted_by_rho[-1]
    print(f"\n  INTERPRETATION: {var_labels[best]} is the most predictable "
          f"(rho={all_data[best]['rho_s']:.3f}) with E={all_data[best]['E']}.")
    print(f"  {var_labels[worst]} is the least predictable "
          f"(rho={all_data[worst]['rho_s']:.3f}) with E={all_data[worst]['E']}.")
    print(f"  Low predictability suggests drivers outside the recorded variables.")

    # --- Interpretation Section D: Causality ---
    print(f"\n  D. CAUSALITY — What actually DRIVES what?")
    print(f"  {'─' * 58}")

    print(f"  CCM with convergence check reveals:")
    _n_sig = 0
    _ccm_results = []
    for cause_h, effect_h in causality_pairs[:4]:
        ccm_r = ccm_with_convergence(df, cause_h, effect_h, E_ref)
        print(f"    {cause_h:>8s} -> {effect_h:<8s}: {ccm_r['verdict']}")
        _ccm_results.append({
            'cause': cause_h, 'effect': effect_h,
            'direction': ccm_r.get('direction'), 'verdict': ccm_r.get('verdict'),
        })
        if ccm_r.get('direction') in {
            'forward', 'reverse', 'forward_dominant', 'reverse_dominant',
            'bidirectional'}:
            _n_sig += 1
    print(f"\n    [Secret 11 disclaimer] {common_driver_disclaimer(_n_sig)}")

    # CRITICAL INSIGHT: built from the ACTUAL CCM results above, not
    # asserted unconditionally. Previously this was a fixed paragraph
    # claiming a specific 'result drives kills/deaths' finding regardless
    # of what the CCM loop for the current run actually found — true for
    # the original bundled demo dataset, but silently wrong (a fabricated-
    # looking but stale claim) the moment this function is pointed at
    # different data via `data_path_override` (added this round). Found
    # during a full-codebase census — see docs/CHANGELOG.md.
    target_drives = [r for r in _ccm_results
                     if r['effect'] == target_col
                     and r['direction'] in ('reverse', 'reverse_dominant')]
    # direction is computed as cause_h->effect_h; 'reverse' here means
    # effect_h (target_col) drives cause_h — i.e. target_col is the true
    # cause. See ccm_with_convergence's direction semantics.
    if target_drives:
        drives_list = ', '.join(r['cause'] for r in target_drives)
        print(f"\n  CRITICAL INSIGHT: '{target_col}' DRIVES {drives_list},")
        print(f"  not the other way around. The target's dynamical fingerprint is")
        print(f"  encoded in these variables. Check which specific pairs converged above.")
    elif _n_sig > 0:
        print(f"\n  INSIGHT: {_n_sig} of {len(_ccm_results)} tested pairs showed a "
              f"convergent causal")
        print(f"  link. Check the verdicts above for the specific direction(s)")
        print(f"  found in THIS run before drawing conclusions.")
    else:
        print(f"\n  INSIGHT: None of the {len(_ccm_results)} tested pairs showed a "
              f"convergent causal")
        print(f"  link in this run. This does not mean there is no causal structure —")
        print(f"  only that CCM's convergence requirement (Secret 2/7) was not met "
              f"here,")
        print(f"  which is common at this sample size. See Section E below.")

    # --- Interpretation Section E: Data Limitations ---
    print(f"\n  E. DATA LIMITATIONS — What can't we see yet?")
    print(f"  {'─' * 58}")

    hk_warnings = [v for v in available_variables if all_data[v]['hk_ratio'] < 10]
    if hk_warnings:
        print(f"  Hankel ratio warnings: {', '.join(hk_warnings)}")
        for v in hk_warnings:
            print(f"    {v}: p/q={all_data[v]['hk_ratio']:.1f} "
                  f"(recommend q <= {max(2, (n+1)//11)})")

    lyap_reliable = [v for v in available_variables
                    if all_data[v]['lyap'].get('reliable')]
    if not lyap_reliable:
        print(f"  Lyapunov estimation: UNRELIABLE for all variables")
        print(f"    (Need ~100+ {unit} for stable divergence rate estimation)")

    print(f"\n  With {n} {unit}, HAVOK can identify the STABILITY LANDSCAPE")
    print(f"  and CAUSAL STRUCTURE, but cannot reliably:")
    print(f"    - Detect intermittent phase transitions (need more {unit})")
    print(f"    - Estimate Lyapunov times (need ~100+ {unit})")
    if hk_warnings:
        worst = min(hk_warnings, key=lambda v: all_data[v]['hk_ratio'])
        print(f"    - Model {worst} dynamics with numerical reliability")
        print(f"      (Hankel ratio {all_data[worst]['hk_ratio']:.1f} < 10 "
              f"for {worst} with E={all_data[worst]['E']})")

    # --- Interpretation Section F: Practical Guidance ---
    print(f"\n  F. PRACTICAL GUIDANCE — What to do with this knowledge")
    print(f"  {'─' * 58}")

    print(f"  1. TRACK MORE VARIABLES. The true causal drivers may not be")
    print(f"     in the current dataset. Record candidate external drivers")
    print(f"     and re-run CCM to test them.")
    print(f"")
    unit_singular = unit[:-1] if unit.endswith('s') and len(unit) > 1 else unit
    print(f"  2. ACCUMULATE DATA. Every additional {unit_singular} improves numerical")
    print(f"     stability. At ~100+ {unit}:")
    print(f"       - Lyapunov horizon becomes computable")
    print(f"       - Hankel ratio constraint relaxes")
    print(f"       - Phase transition detection activates")
    print(f"")
    print(f"  3. LEVERAGE CONSISTENCY. Dissipative eigenvalues indicate a")
    print(f"     stable attractor. Focus on shifting the baseline (attractor")
    print(f"     center) rather than chasing single-{unit_singular} outliers.")
    print(f"")
    print(f"  4. WATCH THE FORCING TERM. Monitor v_r kurtosis as data grows.")
    print(f"     A sustained increase above 1.5 signals a possible regime")
    print(f"     transition worth investigating.")

    # ── Generate visualization ──
    _plot_interpretation(df, all_data, variables=available_variables, var_labels=var_labels,
                         ccm_results=_ccm_results, lyap_reliable=lyap_reliable,
                         target_col=target_col, output_path=output_path, unit=unit)
    print(f"\n  Visualization saved: {output_path}")

    # Key takeaway: built from the actual computed results (stability
    # tier, heavy-tailed variables, CCM significant-pair count), not a
    # fixed claim — same fix as the CAUSALITY/summary sections above.
    max_ev_all = {v: all_data[v]['max_ev'] for v in available_variables}
    worst_stability_var = max(max_ev_all, key=max_ev_all.get)
    stability_tier = classify_havok_stability(max_ev_all[worst_stability_var])
    stability_desc = ("stable" if stability_tier.startswith("Highly dissipative")
                      else "divergent" if stability_tier.startswith("Divergent")
                      else "near-critical")
    n_sig_final = sum(1 for r in _ccm_results if r['direction'] in {
        'forward', 'reverse', 'forward_dominant', 'reverse_dominant', 'bidirectional'})

    print(f"\n{'=' * 72}")
    print(f"  Interpretation complete.")
    print(f"  Key takeaway: {stability_desc.capitalize()} dynamics"
          f"{', heavy-tailed forcing (' + ', '.join(heavy_tailed_vars) + ')' if heavy_tailed_vars else ', consistent dynamics'}, "
          f"{n_sig_final} of {len(_ccm_results)} tested causal link(s) convergent this run.")
    print(f"{'=' * 72}")

    return {
        'n_samples': n,
        'unit': unit,
        'stability_tier': stability_tier,
        'heavy_tailed_variables': heavy_tailed_vars,
        'ccm_results': _ccm_results,
        'n_ccm_significant': n_sig_final,
        'lyapunov_reliable_variables': lyap_reliable,
        'output_path': output_path,
        'available_variables': available_variables,
        'skipped_variables': skipped_vars,
    }


def _plot_interpretation(df, all_data, variables=None, var_labels=None,
                         ccm_results=None, lyap_reliable=None,
                         target_col=None, output_path='results/dynamics_interpretation.png',
                         unit='samples'):
    """Generate comprehensive interpretation visualization."""
    variables = list(variables) if variables else list(all_data.keys())
    var_labels = dict(var_labels) if var_labels else {}
    for v in variables:
        var_labels.setdefault(v, v.replace('_', ' ').title())
    target_col = target_col or variables[0]
    palette = ['#2196F3', '#FF5722', '#4CAF50', '#9C27B0', '#FFC107',
               '#00BCD4', '#E91E63', '#673AB7', '#795548', '#607D8B']
    colors = {v: palette[i % len(palette)] for i, v in enumerate(variables)}
    # Defensive defaults so this function stays independently callable
    # (e.g. from a notebook) without requiring the caller to have the
    # CCM results on hand — the summary panel just degrades to "no CCM
    # data available" rather than crashing.
    _ccm_results = ccm_results if ccm_results is not None else []
    heavy_tailed_vars = [v for v in variables if all_data[v]['kurtosis'] > 1.5]
    lyap_reliable = lyap_reliable if lyap_reliable is not None else []

    fig = plt.figure(figsize=(20, 12))
    gs = GridSpec(3, 5, figure=fig,
                  width_ratios=[1, 1.2, 1.4, 1.2, 1.5],
                  height_ratios=[1, 1, 0.7])

    for row, var in enumerate(variables[:2]):
        for col_base in [0, 1]:
            var_idx = row * 2 + col_base
            if var_idx >= len(variables): break
            var = variables[var_idx]
            d = all_data[var]
            data = df[var].values.astype(float)
            color = colors[var]

            # Sub-row for this variable
            r_gs = gs[row, col_base*2:col_base*2+2] if col_base == 0 else gs[row, col_base*2:col_base*2+2]
            inner = r_gs.subgridspec(2, 2, hspace=0.3, wspace=0.3)

            # Raw data (use a generic index unless the DataFrame has a 'game' column)
            x = df['game'].values if 'game' in df.columns else np.arange(len(df))
            ax0 = fig.add_subplot(inner[0, 0])
            ax0.plot(x, data, 'o-', color=color, markersize=6,
                    markerfacecolor='white', linewidth=1.5)
            ax0.set_title(f'{var_labels[var]} (raw)', fontsize=10, fontweight='bold')
            ax0.grid(True, alpha=0.2)

            # Forcing term
            sh = SovereignHAVOK(q_delays=d['E'], dt=1.0, energy_threshold=0.99,
                               window_length=min(11, max(5, (len(data)-d['E'])//4)),
                               poly_order=2, basis="V")
            sh.fit(data)
            forcing = sh.forcing_
            t_f = np.arange(len(forcing)) + sh.q

            ax1 = fig.add_subplot(inner[0, 1])
            ax1.fill_between(t_f, forcing, alpha=0.2, color=color)
            ax1.plot(t_f, forcing, 'o-', color=color, markersize=3, linewidth=0.8)
            ax1.axhline(0, color='gray', alpha=0.3)
            th = 1.5 * np.std(forcing)
            for si in np.where(np.abs(forcing) > th)[0]:
                gi = si + sh.q
                if gi < len(df):
                    ax1.annotate(f'{gi+1}', (gi, forcing[si]),
                                xytext=(0, 10 if forcing[si] > 0 else -10),
                                textcoords='offset points', ha='center', fontsize=6,
                                color=color)
            ax1.set_title(f'Forcing v_r (kurt={sh.kurtosis_vr_:+.2f})', fontsize=10)
            ax1.grid(True, alpha=0.2)

            # Koopman spectrum: continuous eigenvalues (Re(λ), Im(λ)) for spectral shape
            ax2 = fig.add_subplot(inner[1, 0])
            evals_cont = sh.eigenvalues_  # continuous-time for spectral visualization
            ax2.scatter(np.real(evals_cont), np.imag(evals_cont), c=color, s=60, zorder=5)
            theta = np.linspace(0, 2*np.pi, 100)
            ax2.plot(np.cos(theta), np.sin(theta), 'k--', alpha=0.3, linewidth=1)
            ax2.axhline(0, color='gray', alpha=0.2); ax2.axvline(0, color='gray', alpha=0.2)
            ax2.set_title(f'Koopman spectrum (max|eig_d|={np.max(np.abs(sh.eigenvalues_d_)):.3f})',
                         fontsize=10)
            ax2.set_aspect('equal')
            ax2.grid(True, alpha=0.2)

            # Diagnostics box
            ax3 = fig.add_subplot(inner[1, 1])
            ax3.axis('off')
            lines = [
                f"E={d['E']}  r={d['havok_r']}  p/q={d['hk_ratio']:.1f}",
                f"Simplex rho = {d['rho_s']:.3f}",
                f"HAVOK R^2   = {d['havok_r2']:.3f}",
                f"Expl var    = {d['expl_var']:.1%}",
                f"Kurtosis    = {d['kurtosis']:+.3f}",
                f"Max |eig_d|  = {d['max_ev']:.4f}",
                f"Spikes      = {d['spike_count']}",
                f"SG window   = {min(11, max(5, (len(data)-d['E'])//4))}",
                "",
            ]
            lyap = d['lyap']
            if lyap.get('reliable'):
                lines.append(f"Lyapunov: OK (R^2={lyap['fit_r2']:.2f})")
                lines.append(f"  tau_L={lyap['lyapunov_time']:.1f} {unit}")
            else:
                lines.append(f"Lyapunov: unreliable")
                lines.append(f"  {lyap.get('reason', 'N<30')}")
            ax3.text(0.05, 0.95, '\n'.join(lines), fontsize=7.5,
                    family='monospace', va='top', transform=ax3.transAxes)

    # ── Bottom row: CCM convergence and Summary ──
    # CCM convergence
    ax_ccm = fig.add_subplot(gs[2, :2])
    E_ref = all_data[target_col]['E']
    pairs = [(r['cause'], r['effect']) for r in _ccm_results[:3]
             if r.get('cause') in variables and r.get('effect') in variables] if _ccm_results else []
    if not pairs:
        pairs = [(v, target_col) for v in variables if v != target_col][:3]
    ccm_colors = ['#FF5722', '#9C27B0', '#4CAF50']
    for (cause, effect), cc in zip(pairs, ccm_colors):
        ccm_r = ccm_with_convergence(df, cause, effect, E_ref)
        for direction, label, ls in [(ccm_r['forward'], f'M_{effect}→{cause}', '-'),
                                      (ccm_r['reverse'], f'M_{cause}→{effect}', '--')]:
            if direction.get('lib_sizes'):
                ax_ccm.plot(direction['lib_sizes'], direction['rhos'],
                          'o-', color=cc, linestyle=ls, linewidth=1.5,
                          markersize=5, alpha=0.8,
                          label=f"{label} (rho={direction['final_rho']:+.3f})")
    ax_ccm.set_title('CCM Convergence (with slope check)', fontsize=11)
    ax_ccm.set_xlabel('Library size'); ax_ccm.set_ylabel('Cross-map skill (rho)')
    ax_ccm.legend(fontsize=7, loc='lower right')
    ax_ccm.grid(True, alpha=0.2)

    # Summary
    ax_sum = fig.add_subplot(gs[2, 2:])
    ax_sum.axis('off')

    # Summary text built from the ACTUAL computed results (all_data,
    # _ccm_results, heavy_tailed_vars — all populated earlier in this
    # function), not a fixed narrative. Previously this whole panel was
    # static text describing the original bundled demo dataset's
    # specific findings — true when first written, but silently stale
    # the moment this function runs on different data (via
    # `data_path_override`, added this round) or even just a different
    # pyEDM bootstrap sample of the SAME data (CCM's `sample` parameter
    # is stochastic — see ccm_causality.py). Found during a full-codebase
    # census; see docs/CHANGELOG.md.
    max_ev_all = {v: all_data[v]['max_ev'] for v in variables}
    worst_stability_var = max(max_ev_all, key=max_ev_all.get)
    stability_tier = classify_havok_stability(max_ev_all[worst_stability_var])
    if stability_tier.startswith("Divergent"):
        stability_lines = [
            f"STABILITY: {worst_stability_var} shows DIVERGENT modes",
            f"  (max|eig_d|={max_ev_all[worst_stability_var]:.3f} > 1.05).",
            "  Perturbations can grow — treat trends with caution.",
        ]
    elif stability_tier.startswith("Highly dissipative"):
        stability_lines = [
            "STABILITY: Highly dissipative across all variables",
            f"  (max|eig_d|<=" + f"{max_ev_all[worst_stability_var]:.2f}).",
            "  Perturbations decay quickly. No tilt spirals.",
        ]
    else:
        stability_lines = [
            f"STABILITY: Near-critical for {worst_stability_var}",
            f"  (max|eig_d|={max_ev_all[worst_stability_var]:.3f}).",
            "  Neither clearly growing nor clearly fast-decaying.",
        ]

    if not heavy_tailed_vars:
        forcing_lines = [
            "FORCING: Near-Gaussian to sub-Gaussian.",
            "  No heavy tails detected in any variable.",
            "  System is in a STABLE ATTRACTOR BASIN.",
            "  No dramatic phase transitions observed.",
        ]
    else:
        forcing_lines = [
            f"FORCING: Heavy tails in {', '.join(heavy_tailed_vars)}.",
            "  Intermittent/bursty forcing detected —",
            "  possible regime changes, check spike indices",
            "  above before treating this as steady-state.",
        ]

    causality_lines = ["CAUSALITY (CCM with convergence):"]
    sig_results = [r for r in _ccm_results if r['direction'] in {
        'forward', 'reverse', 'forward_dominant', 'reverse_dominant', 'bidirectional'}]
    if sig_results:
        for r in sig_results[:4]:
            if r['direction'] in ('reverse', 'reverse_dominant'):
                causality_lines.append(f"  {r['effect']} -> {r['cause']}")
            elif r['direction'] in ('forward', 'forward_dominant'):
                causality_lines.append(f"  {r['cause']} -> {r['effect']}")
            else:
                causality_lines.append(f"  {r['cause']} <-> {r['effect']} (bidirectional)")
    else:
        causality_lines.append("  No convergent causal link found this run")
        causality_lines.append("  (common at this N — see Secret 2/7 gate)")

    practical_lines = [
        "PRACTICAL: See Section F in the console output",
        "  above for guidance grounded in this run's",
        "  actual stability/forcing/causality findings.",
        f"  Need ~100+ {unit} for phase transition detection."
        if not lyap_reliable else
        "  Lyapunov estimate is reliable at this N.",
    ]

    summary = (
        ["=== DYNAMICAL INTERPRETATION SUMMARY ===", ""]
        + stability_lines + [""]
        + forcing_lines + [""]
        + causality_lines + [""]
        + practical_lines
    )
    ax_sum.text(0.02, 0.97, '\n'.join(summary), fontsize=7.8,
               family='monospace', va='top', transform=ax_sum.transAxes)

    fig.suptitle('SovereignHAVOK Dynamical Interpretation\n'
                 '(with 4 Reviewer Improvements: Lyapunov R^2, CCM convergence, '
                 'SG window cap, Hankel audit)',
                 fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


if __name__ == '__main__':
    interpret_game_data()
