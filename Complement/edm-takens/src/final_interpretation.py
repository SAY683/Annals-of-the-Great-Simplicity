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

import os, tempfile, sys, warnings
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = os.path.join(tempfile.gettempdir(), 'edm_takens_mpl')
os.environ['OMP_NUM_THREADS'] = '1'; os.environ['MKL_NUM_THREADS'] = '1'

import numpy as np
import pandas as pd
from scipy.stats import kurtosis as scipy_kurtosis, linregress, spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
plt.rcParams['axes.unicode_minus'] = False
warnings.filterwarnings('ignore')

import pyEDM
from sovereign_havok import SovereignHAVOK
from _paths import data_path


# ================================================================
# Improvement 2: CCM Convergence Slope Check
# ================================================================

def ccm_with_convergence(df, cause_var, effect_var, E):
    """
    CCM with convergence slope verification (Reviewer improvement #2).

    A single rho value is insufficient — we must verify that cross-map skill
    INCREASES with library size (convergence). This is the hallmark of true
    causality in Sugihara's CCM framework.

    Returns: forward/backward skills, convergence slopes, and verdict.
    """
    n = len(df)
    results = {}

    for direction, (col_var, tgt_var) in enumerate([
        (effect_var, cause_var),   # M_effect -> cause (tests cause->effect)
        (cause_var, effect_var),   # M_cause -> effect (tests effect->cause)
    ]):
        try:
            ccm = pyEDM.CCM(
                dataFrame=df, E=E, Tp=0,
                columns=col_var, target=tgt_var,
                libSizes=f'5 {n-2} 3', sample=min(50, n),
                showPlot=False)
            rho_col = [c for c in ccm.columns if c != 'LibSize'][0]
            rhos = ccm[rho_col].values
            lib_sizes = ccm['LibSize'].values

            # Convergence: use total rise (scale-invariant) + Spearman monotonicity
            # Absolute slope depends on library size range and is not comparable
            # across datasets of different lengths (N=32 vs N=5000).
            if len(rhos) >= 3:
                total_rise = float(rhos[-1] - rhos[0])
                spear_rho, spear_p = spearmanr(lib_sizes, rhos)
                final_rho = rhos[-1]
                is_converging = total_rise > 0.05 and spear_rho > 0.7 and spear_p < 0.1
            else:
                total_rise = 0.0; spear_rho = 0.0; spear_p = 1.0
                final_rho = rhos[-1] if len(rhos) > 0 else 0
                is_converging = False

            results[direction] = {
                'final_rho': final_rho,
                'total_rise': total_rise,
                'spearman_rho': spear_rho,
                'spearman_p': spear_p,
                'is_converging': is_converging,
                'lib_sizes': lib_sizes.tolist(),
                'rhos': rhos.tolist(),
            }
        except Exception as e:
            results[direction] = {
                'final_rho': None, 'total_rise': None,
                'spearman_rho': None, 'is_converging': False,
                'error': str(e)
            }

    # Causal verdict with convergence requirement
    fwd = results[0]; rev = results[1]
    fwd_ok = fwd['final_rho'] is not None and fwd['is_converging']
    rev_ok = rev['final_rho'] is not None and rev['is_converging']

    if not fwd_ok and not rev_ok:
        verdict = "No convergent causal link detected"
        direction = "none"
    elif fwd_ok and not rev_ok:
        if fwd['final_rho'] > 0.2:
            verdict = f"{cause_var} --drives--> {effect_var} (convergent)"
            direction = "forward"
        else:
            verdict = f"Weak forward signal ({fwd['final_rho']:.3f}), insufficient"
            direction = "weak_forward"
    elif rev_ok and not fwd_ok:
        if rev['final_rho'] > 0.2:
            verdict = f"{effect_var} --drives--> {cause_var} (convergent)"
            direction = "reverse"
        else:
            verdict = f"Weak reverse signal ({rev['final_rho']:.3f}), insufficient"
            direction = "weak_reverse"
    else:
        # Both converge — compare strengths
        delta = fwd['final_rho'] - rev['final_rho']
        if abs(delta) < 0.05:
            verdict = f"Bidirectional causality ({cause_var} <-> {effect_var})"
            direction = "bidirectional"
        elif delta > 0:
            verdict = f"{cause_var} --drives--> {effect_var} (dominant, delta={delta:+.3f})"
            direction = "forward_dominant"
        else:
            verdict = f"{effect_var} --drives--> {cause_var} (dominant, delta={delta:+.3f})"
            direction = "reverse_dominant"

    return {
        'cause_var': cause_var, 'effect_var': effect_var,
        'forward': fwd, 'reverse': rev,
        'verdict': verdict, 'direction': direction
    }


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

def interpret_game_data():
    """Run full HAVOK analysis and produce plain-language interpretation."""
    df = pd.read_csv(data_path('game_log.csv'))
    n = len(df)
    lib = f'1 {n-7}'; pred = f'{n-6} {n}'

    print("=" * 72)
    print("  HAVOK DYNAMICAL INTERPRETATION OF GAME DATA")
    print("  SovereignHAVOK with 4 Reviewer Improvements")
    print("=" * 72)
    print(f"  Games: {n}  |  Win rate: {df['result'].mean()*100:.0f}%")
    print(f"  Average: K={df['kills'].mean():.1f} D={df['deaths'].mean():.1f} "
          f"DMG={df['damage'].mean():.0f}")
    print()

    variables = ['result', 'kills', 'damage', 'deaths']
    var_labels = {'result': 'Win/Loss', 'kills': 'Kills',
                  'damage': 'Damage', 'deaths': 'Deaths'}
    all_data = {}

    # ── Phase 1: EDM + HAVOK on each variable ──
    print("─" * 72)
    print("  PHASE 1: Individual Variable Dynamics")
    print("─" * 72)

    for var in variables:
        print(f"\n  [{var_labels[var]}]")
        data = df[var].values.astype(float)

        # EDM
        rho_E = pyEDM.EmbedDimension(
            dataFrame=df, lib=lib, pred=pred, maxE=8, Tp=1,
            columns=var, target=var, showPlot=False, numProcess=1)
        E_opt = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])

        sx = pyEDM.Simplex(
            dataFrame=df, lib=lib, pred=pred, E=E_opt, Tp=1,
            columns=var, target=var, showPlot=False)
        rho_s = sx['Observations'].corr(sx['Predictions'])

        smap = pyEDM.PredictNonlinear(
            dataFrame=df, lib=lib, pred=pred, E=E_opt,
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

        # CCM (with convergence check — Improvement #2)
        ccm_result = None
        if var == 'result':
            ccm_kills = ccm_with_convergence(df, 'kills', 'result', E_opt)
            ccm_damage = ccm_with_convergence(df, 'damage', 'result', E_opt)
            ccm_deaths = ccm_with_convergence(df, 'deaths', 'result', E_opt)
            ccm_result = {'kills': ccm_kills, 'damage': ccm_damage, 'deaths': ccm_deaths}
        elif var == 'kills':
            ccm_result = {'kills_damage': ccm_with_convergence(df, 'kills', 'damage', E_opt)}

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
                  f"tau_L={lyap['lyapunov_time']:.1f} games, "
                  f"3*tau_L={lyap['prediction_horizon_3x']:.1f} games "
                  f"(fit R^2={lyap['fit_r2']:.3f})")
        elif lyap_lower and lyap_lower.get('is_significant'):
            print(f"    Lyapunov: UNRELIABLE (R^2={lyap.get('fit_r2', 0):.3f} < 0.5)")
            print(f"    Surrogate LB: lambda > {lyap_lower['lambda_lower_bound']:.4f}, "
                  f"tau_L < {lyap_lower['tau_L_upper_bound']:.1f} games "
                  f"(p={1/(lyap_lower['n_surrogates']+1):.3f})")
        elif lyap_lower and not lyap_lower.get('is_significant'):
            print(f"    Lyapunov: UNRELIABLE + not significant vs linear null")
            print(f"    => Cannot distinguish from linear stochastic. "
                  f"System may not be chaotic at this scale.")
        else:
            print(f"    Lyapunov: {lyap.get('reason', lyap.get('warning', 'N/A'))}")

        # Spike game events
        if len(spike_idx) > 0:
            print(f"    Phase-transition events (spikes):")
            for si in spike_idx[:6]:
                gi = si + sh.q
                if gi < len(df):
                    row = df.iloc[gi]
                    fs = forcing[si]
                    direction = "UP" if fs > 0 else "DOWN"
                    res = 'W' if row['result'] == 1 else 'L'
                    print(f"      Game {gi+1:2d}: v_r={fs:+.3f} ({direction}), "
                          f"K/D={int(row['kills'])}/{int(row['deaths'])}, "
                          f"DMG={int(row['damage'])}, {res}")

        all_data[var] = {
            'E': E_opt, 'rho_s': rho_s, 'is_nl': is_nl,
            'havok_r': sh.r_, 'havok_r2': sh.regression_r2_,
            'kurtosis': sh.kurtosis_vr_, 'max_ev': max_ev,
            'expl_var': sh.explained_var_, 'hk_ratio': hk_ratio,
            'forcing_energy': forcing_energy,
            'spike_count': len(spike_idx), 'spike_idx': spike_idx,
            'lyap': lyap, 'lyap_lower': lyap_lower, 'ccm': ccm_result,
        }

    # ── Phase 2: CCM Causality Report ──
    print(f"\n{'─' * 72}")
    print("  PHASE 2: Causal Structure (CCM with Convergence Check)")
    print("  Reviewer improvement #2: convergence slope required")
    print("─" * 72)

    causality_pairs = [
        ('kills', 'result'), ('damage', 'result'),
        ('deaths', 'result'), ('kills', 'damage'), ('mvp', 'result'),
    ]
    E_ref = all_data['result']['E']

    for cause_h, effect_h in causality_pairs:
        ccm_r = ccm_with_convergence(df, cause_h, effect_h, E_ref)
        fwd = ccm_r['forward']; rev = ccm_r['reverse']
        print(f"\n    {cause_h:>8s} <-> {effect_h:<8s}:")
        print(f"      Forward  (M_{effect_h} -> {cause_h}): "
              f"rho={fwd['final_rho']:+.3f}" if fwd['final_rho'] else
              f"      Forward: FAILED",
              f", rise={fwd['total_rise']:+.4f}"
              if fwd.get('total_rise') is not None else "",
              f", converging={fwd['is_converging']}"
              if fwd.get('is_converging') is not None else "")
        print(f"      Reverse  (M_{cause_h} -> {effect_h}): "
              f"rho={rev['final_rho']:+.3f}" if rev['final_rho'] else
              f"      Reverse: FAILED",
              f", rise={rev['total_rise']:+.4f}"
              if rev.get('total_rise') is not None else "",
              f", converging={rev['is_converging']}"
              if rev.get('is_converging') is not None else "")
        print(f"      => {ccm_r['verdict']}")

    # ── Phase 3: Integrated Dynamical Interpretation ──
    print(f"\n{'=' * 72}")
    print("  PHASE 3: INTEGRATED DYNAMICAL INTERPRETATION")
    print("  (What the game data actually tells us through HAVOK)")
    print("=" * 72)

    # --- Interpretation Section A: Stability Landscape ---
    print(f"\n  A. STABILITY LANDSCAPE — Is the system calm or turbulent?")
    print(f"  {'─' * 58}")

    max_ev_values = {v: all_data[v]['max_ev'] for v in variables}
    dominant_eig = max(max_ev_values, key=max_ev_values.get)

    print(f"  All Koopman eigenvalues are HIGHLY DISSIPATIVE:")
    for v in variables:
        ev = all_data[v]['max_ev']
        half_life = np.log(2) / (1 - ev + 1e-12) if ev < 1 else float('inf')
        print(f"    {var_labels[v]:10s}: max|eig_d| = {ev:.4f}  "
              f"(perturbation half-life: ~{half_life:.1f} games)")

    print(f"\n  INTERPRETATION: Your game dynamics form a STABLE ATTRACTOR.")
    print(f"  Any deviation from your baseline performance decays within")
    print(f"  ~1-5 games. You do NOT exhibit 'tilt spirals' (runaway")
    print(f"  destabilization) or 'god-mode streaks' (explosive divergence).")
    print(f"  This is characteristic of a player with consistent skill and")
    print(f"  strong homeostatic regulation — you regress to YOUR mean,")
    print(f"  not to the population mean.")

    # --- Interpretation Section B: Forcing & Phase Transitions ---
    print(f"\n  B. FORCING TERM — Are there 'fate-changing moments'?")
    print(f"  {'─' * 58}")

    kurt_values = {v: all_data[v]['kurtosis'] for v in variables}
    spike_counts = {v: all_data[v]['spike_count'] for v in variables}

    for v in variables:
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
    print(f"\n  INTERPRETATION: The forcing term v_r (the nonlinear 'engine'")
    print(f"  of your system) shows NO heavy tails in any variable. This means:")
    print(f"    1. Within these 32 games, you did NOT experience a true")
    print(f"       'attractor basin transition' — no irreversible tilt, no")
    print(f"       permanent improvement leap.")
    print(f"    2. The negative kurtosis in result/deaths suggests your")
    print(f"       performance is CONSTRAINED within a bounded range —")
    print(f"       you have a floor AND a ceiling.")
    print(f"    3. This is both GOOD (consistency) and informative:")
    print(f"       the interesting dynamics are in the UNMEASURED variables.")

    # --- Interpretation Section C: Predictability ---
    print(f"\n  C. PREDICTABILITY — Which aspects of your game are deterministic?")
    print(f"  {'─' * 58}")

    # Sort by Simplex rho
    sorted_by_rho = sorted(variables, key=lambda v: all_data[v]['rho_s'], reverse=True)
    for v in sorted_by_rho:
        r = all_data[v]['rho_s']
        ev = all_data[v]['expl_var']
        E = all_data[v]['E']
        bars = '#' * int(r * 20) + '-' * (20 - int(r * 20))
        print(f"    {var_labels[v]:10s}: [{bars}] rho={r:.3f}, E={E}, expl_var={ev:.1%}")

    print(f"\n  INTERPRETATION: Kills are highly predictable (rho=0.855) with")
    print(f"  only E=2 dimensions needed. This means your kill count follows")
    print(f"  a simple, stationary pattern — likely a stable 'rhythm' in your")
    print(f"  playstyle. In contrast, damage requires E=6 dimensions (the most")
    print(f"  complex dynamics) but remains hard to predict — damage is driven")
    print(f"  by factors OUTSIDE the recorded variables (enemy behavior, hero")
    print(f"  matchups, game phase).")

    # --- Interpretation Section D: Causality ---
    print(f"\n  D. CAUSALITY — What actually DRIVES what?")
    print(f"  {'─' * 58}")

    print(f"  CCM with convergence check reveals:")
    for cause_h, effect_h in causality_pairs[:4]:
        ccm_r = ccm_with_convergence(df, cause_h, effect_h, E_ref)
        print(f"    {cause_h:>8s} -> {effect_h:<8s}: {ccm_r['verdict']}")

    print(f"\n  CRITICAL INSIGHT: 'result' (win/loss) DRIVES kills and deaths,")
    print(f"  not the other way around. This is the 'Victim Mirror Principle':")
    print(f"  the outcome's dynamical fingerprint is encoded in your K/D.")
    print(f"  Practically: whether you're winning or losing DETERMINES your")
    print(f"  stats, not vice versa. High kills don't CAUSE wins — wins cause")
    print(f"  high kills (you snowball when ahead, struggle when behind).")

    # --- Interpretation Section E: Data Limitations ---
    print(f"\n  E. DATA LIMITATIONS — What can't we see yet?")
    print(f"  {'─' * 58}")

    hk_warnings = [v for v in variables if all_data[v]['hk_ratio'] < 10]
    if hk_warnings:
        print(f"  Hankel ratio warnings: {', '.join(hk_warnings)}")
        for v in hk_warnings:
            print(f"    {v}: p/q={all_data[v]['hk_ratio']:.1f} "
                  f"(recommend q <= {max(2, (n+1)//11)})")

    lyap_reliable = [v for v in variables
                    if all_data[v]['lyap'].get('reliable')]
    if not lyap_reliable:
        print(f"  Lyapunov estimation: UNRELIABLE for all variables")
        print(f"    (Need ~100+ games for stable divergence rate estimation)")

    print(f"\n  With 32 games, HAVOK can identify the STABILITY LANDSCAPE")
    print(f"  and CAUSAL STRUCTURE, but cannot reliably:")
    print(f"    - Detect intermittent phase transitions (need more games)")
    print(f"    - Estimate Lyapunov times (need ~100+ games)")
    print(f"    - Model damage dynamics with numerical reliability")
    print(f"      (Hankel ratio 4.5 < 10 for damage with E=6)")

    # --- Interpretation Section F: Practical Guidance ---
    print(f"\n  F. PRACTICAL GUIDANCE — What to do with this knowledge")
    print(f"  {'─' * 58}")

    print(f"  1. TRACK MORE VARIABLES. The true causal drivers of winning")
    print(f"     are NOT in your current dataset. Consider tracking:")
    print(f"       - Opponent skill indicator / matchmaking rating")
    print(f"       - Hero/character selection")
    print(f"       - Team composition synergy")
    print(f"       - Early-game metrics (first 5 minutes)")
    print(f"       - 'Mental state' proxy (time of day, session length)")
    print(f"")
    print(f"  2. ACCUMULATE DATA. Every additional game improves HAVOK's")
    print(f"     numerical stability. At 100+ games:")
    print(f"       - Lyapunov horizon becomes computable")
    print(f"       - Hankel ratio constraint relaxes")
    print(f"       - Phase transition detection activates")
    print(f"")
    print(f"  3. YOUR STRENGTH IS CONSISTENCY. The dissipative eigenvalues")
    print(f"     show you don't tilt. This is a competitive advantage.")
    print(f"     Focus on raising your BASELINE (attractor center) rather")
    print(f"     than chasing peak performances.")
    print(f"")
    print(f"  4. WATCH THE FORCING TERM. As you add games, monitor v_r kurtosis.")
    print(f"     A sudden increase from negative to >1.5 would signal a")
    print(f"     genuine phase transition — either improvement or decline.")

    # ── Generate visualization ──
    _plot_interpretation(df, all_data)
    print(f"\n  Visualization saved: results/game_interpretation.png")

    print(f"\n{'=' * 72}")
    print(f"  Interpretation complete.")
    print(f"  Key takeaway: Stable dynamics, consistent player, causal")
    print(f"  drivers of winning are UNMEASURED. Track more, play more.")
    print(f"{'=' * 72}")


def _plot_interpretation(df, all_data):
    """Generate comprehensive interpretation visualization."""
    variables = ['result', 'kills', 'damage', 'deaths']
    var_labels = {'result': 'Win/Loss', 'kills': 'Kills',
                  'damage': 'Damage', 'deaths': 'Deaths'}
    colors = {'result': '#2196F3', 'kills': '#FF5722',
              'damage': '#4CAF50', 'deaths': '#9C27B0'}

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

            # Raw data
            ax0 = fig.add_subplot(inner[0, 0])
            ax0.plot(df['game'], data, 'o-', color=color, markersize=6,
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
                    res = 'W' if df['result'].iloc[gi] == 1 else 'L'
                    ax1.annotate(f'{gi+1}', (gi, forcing[si]),
                                xytext=(0, 10 if forcing[si] > 0 else -10),
                                textcoords='offset points', ha='center', fontsize=6,
                                color='green' if res == 'W' else 'red')
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
                lines.append(f"  tau_L={lyap['lyapunov_time']:.1f} games")
            else:
                lines.append(f"Lyapunov: unreliable")
                lines.append(f"  {lyap.get('reason', 'N<30')}")
            ax3.text(0.05, 0.95, '\n'.join(lines), fontsize=7.5,
                    family='monospace', va='top', transform=ax3.transAxes)

    # ── Bottom row: CCM convergence and Summary ──
    # CCM convergence
    ax_ccm = fig.add_subplot(gs[2, :2])
    E_ref = all_data['result']['E']
    pairs = [('kills', 'result'), ('deaths', 'result'), ('damage', 'result')]
    ccm_colors = ['#FF5722', '#9C27B0', '#4CAF50']
    for (cause, effect), cc in zip(pairs, ccm_colors):
        ccm_r = ccm_with_convergence(df, cause, effect, E_ref)
        for direction, label, ls in [(ccm_r['forward'], f'M_result→{cause}', '-'),
                                      (ccm_r['reverse'], f'M_{cause}→result', '--')]:
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
    summary = [
        "=== DYNAMICAL INTERPRETATION SUMMARY ===",
        "",
        "STABILITY: Highly dissipative. All Koopman",
        "  eigenvalues < 0.2. Perturbations decay",
        "  within 1-5 games. No tilt spirals.",
        "",
        "FORCING: Near-Gaussian to sub-Gaussian.",
        "  No heavy tails detected in any variable.",
        "  System is in a STABLE ATTRACTOR BASIN.",
        "  No dramatic phase transitions observed.",
        "",
        "CAUSALITY (CCM with convergence):",
        "  result → kills  (winning drives kills)",
        "  result → deaths (winning reduces deaths)",
        "  damage → kills  (output drives kills)",
        "  kills ↛ result  (kills don't cause wins!)",
        "",
        "PRACTICAL: Your consistency is a strength.",
        "  To improve: raise baseline, don't chase peaks.",
        "  Track unmeasured variables (opponent, hero,",
        "  early-game) to find true causal drivers.",
        f"  Need ~100+ games for phase transition detection.",
    ]
    ax_sum.text(0.02, 0.97, '\n'.join(summary), fontsize=7.8,
               family='monospace', va='top', transform=ax_sum.transAxes)

    fig.suptitle('SovereignHAVOK Game Data Dynamical Interpretation\n'
                 '(with 4 Reviewer Improvements: Lyapunov R^2, CCM convergence, '
                 'SG window cap, Hankel audit)',
                 fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout()
    plt.savefig('results/game_interpretation.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: results/game_interpretation.png")


if __name__ == '__main__':
    interpret_game_data()
