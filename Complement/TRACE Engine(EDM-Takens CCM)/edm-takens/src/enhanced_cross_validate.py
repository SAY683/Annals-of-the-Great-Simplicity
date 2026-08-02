"""
Enhanced EDM-HAVOK Cross-Validation with Three Algorithmic Safeguards
======================================================================
Incorporates three "forbidden rules" from nonlinear dynamics engineering:

  Safeguard 1: Lyapunov Horizon — absolute physical bound on prediction
  Safeguard 2: CCM Victim Mirror — correct causal direction verification
  Safeguard 3: Hankel Aspect Ratio — SVD numerical stability guard

Each safeguard is implemented as an independent verifier that runs
alongside the standard EDM/HAVOK pipeline and produces warnings when
numerical or physical boundaries are violated.
"""

import os, tempfile, warnings

# ── Environment setup: prevent multiprocessing subprocess memory issues ──
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', os.path.join(tempfile.gettempdir(), 'edm_takens_mpl'))
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('NUMEXPR_NUM_THREADS', '1')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
plt.rcParams['axes.unicode_minus'] = False

warnings.filterwarnings('ignore')

# Unified bridge: all EDM calls go through here (pyEDM with numpy fallback).
# (A local `try: import pyEDM` availability probe used to live here too —
# removed: it duplicated what _edm_bridge.py already does canonically
# (including its own graceful warnings.warn), and its result
# (`_PYEDM_AVAILABLE`) was computed but never actually read — the flag
# genuinely used throughout this file is `_BRIDGE_AVAILABLE` below. See
# docs/CHANGELOG.md.)
from _edm_bridge import (
    EmbedDimension as _bridge_EmbedDimension,
    Simplex as _bridge_Simplex,
    SMapPredictNonlinear as _bridge_SMapPredictNonlinear,
    EDM_AVAILABLE as _BRIDGE_AVAILABLE,
)

from sovereign_havok import SovereignHAVOK, classify_havok_stability

# P2-1 修复: 统一硬编码 eps 为单一真相源常量
from _numeric_constants import EPS_LYAPUNOV
from _paths import data_path
from edm_auditor import classify_hankel_ratio
from ccm_causality import ccm_causality_test


# ============================================================
# SAFEGUARD 1: Lyapunov Exponent & Prediction Horizon
# ============================================================

def estimate_lyapunov_exponent(data, E, dt=1.0, n_expand=20):
    """
    Estimate the maximal Lyapunov exponent using Rosenstein's algorithm.

    Based on: Rosenstein, Collins & De Luca (1993), "A practical method
    for calculating largest Lyapunov exponents from small data sets."

    Algorithm:
    1. Reconstruct phase space with embedding dimension E
    2. For each point, find nearest neighbor with temporal separation > mean period
    3. Track divergence rate d(t) ~ exp(lambda_max * t)
    4. lambda_max = slope of <ln(d)> vs t

    Parameters
    ----------
    data : np.ndarray
        1D time series
    E : int
        Embedding dimension
    dt : float
        Sampling interval

    Returns
    -------
    dict with keys: lambda_max, lyapunov_time, prediction_horizon_3x, n_points
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    # Reconstruct phase space: each row is a delay vector of length E
    N = n - E + 1
    if N < 20:
        return {
            'lambda_max': None,
            'lyapunov_time': None,
            'prediction_horizon_3x': None,
            'warning': f'Too few state-space points (N={N}) for reliable estimation'
        }

    # Build delay-embedded state vectors
    X = np.zeros((N, E))
    for i in range(E):
        X[:, i] = data[i:i+N]

    # Estimate mean period from first zero-crossing of autocorrelation
    x_centered = data - np.mean(data)
    autocorr = np.correlate(x_centered, x_centered, mode='full')
    autocorr = autocorr[len(autocorr)//2:]
    # P1-5 修复 (Round 21 §P0-B): autocorr[0] 可能为 0 (常量序列或 std=0),
    # 导致除以 0 产生 NaN 传播到下游. 用 safe division + fallback.
    ac0 = autocorr[0] if len(autocorr) > 0 else 0.0
    if abs(ac0) < EPS_LYAPUNOV:
        # 常量序列: 无法定义 mean period, 用 E+1 作为保守值
        mean_period = max(5, E + 1)
    else:
        autocorr = autocorr / ac0
        zero_cross = np.where(np.diff(np.sign(autocorr - 1/np.exp(1))))[0]
        mean_period = zero_cross[0] + 1 if len(zero_cross) > 0 else max(5, E)

    # Find nearest neighbors for each point (with temporal separation)
    div_curves = []
    for i in range(N - n_expand):
        # Find nearest neighbor with temporal separation > mean_period
        dists = np.sum((X[:N - n_expand] - X[i])**2, axis=1)
        dists[i] = np.inf  # exclude self
        # Exclude points too close in time
        for j in range(max(0, i - mean_period), min(N - n_expand, i + mean_period + 1)):
            if 0 <= j < len(dists):
                dists[j] = np.inf

        j = np.argmin(dists)
        if np.isinf(dists[j]):
            continue

        # Track divergence for n_expand steps
        div = np.zeros(n_expand)
        for k in range(min(n_expand, N - max(i, j) - 1)):
            div[k] = np.sqrt(np.sum((X[i+k+1] - X[j+k+1])**2))
        if div[0] > EPS_LYAPUNOV:
            # ROUND26 算法审视 P0 修复: 同步 final_interpretation.py:127 的 log(0) 防护
            # 原 np.log(div + 1e-12) 当 div→0 时引入 -27.6 偏差, 拉低 div_mean 使 λ_max 低估
            log_div = np.log(div, where=div > EPS_LYAPUNOV, out=np.full_like(div, np.nan))
            div_curves.append(log_div)

    if len(div_curves) < 10:
        return {
            'lambda_max': None,
            'lyapunov_time': None,
            'prediction_horizon_3x': None,
            'warning': f'Too few valid divergence curves ({len(div_curves)})'
        }

    # Average divergence over all pairs
    # ROUND26 算法审视 P0 修复 (续): div_curves 现含 NaN (div→0 处), 用 nanmean 忽略
    div_arr = np.array(div_curves)
    div_mean = np.nanmean(div_arr, axis=0) if np.any(~np.isnan(div_arr)) else np.zeros(n_expand)
    t_div = np.arange(len(div_mean)) * dt

    # Fit line to the linear growth region (first half of divergence)
    fit_end = min(n_expand // 2, len(div_mean) - 5)
    if fit_end < 5:
        fit_end = len(div_mean) - 2
    coeffs = np.polyfit(t_div[:fit_end], div_mean[:fit_end], 1)
    # Q9 P1-17 修复: 允许负 Lyapunov 指数以正确表示稳定系统
    # 之前 max(0.001, coeffs[0]) 强制为正，导致稳定系统也被报告为混沌
    lambda_max = coeffs[0]

    # Lyapunov time: 使用绝对值，稳定系统 lambda_max<=0 时 tau_L 为 inf
    tau_L = 1.0 / abs(lambda_max) if abs(lambda_max) > 1e-10 else float('inf')

    # Prediction horizons (in original time units, i.e. games)
    horizon_1x = tau_L
    horizon_3x = 3 * tau_L
    horizon_5x = 5 * tau_L

    return {
        'lambda_max': lambda_max,
        'lyapunov_time': tau_L,
        'prediction_horizon_1x': horizon_1x,
        'prediction_horizon_3x': horizon_3x,
        'prediction_horizon_5x': horizon_5x,
        'n_divergence_curves': len(div_curves),
        'fit_r2': float(np.corrcoef(t_div[:fit_end], div_mean[:fit_end])[0, 1])**2,
        'warning': None
    }


# ============================================================
# SAFEGUARD 2: CCM Causal Direction Verifier
# ============================================================

def verify_ccm_direction(df, cause_var, effect_var, E, lib_sizes=None):
    """
    Correctly test the causal hypothesis: cause_var -> effect_var.

    CCM Principle (Sugihara et al., Science 2012):
      If X drives Y (X->Y), then Y's shadow manifold M_Y encodes information
      about X. Therefore, M_Y should be able to cross-map X with high skill.

    In pyEDM: CCM(columns=Y, target=X) tests X->Y.
    Because: columns builds the manifold, target is what we predict.
    The manifold is built from Y, and we predict X using it.

    This function performs BOTH directions and reports the correct
    causal interpretation.

    Thin wrapper: the actual test (including the library-size-convergence
    check) lives in `ccm_causality.ccm_causality_test()`, shared with
    `final_interpretation.ccm_with_convergence()`. This used to be an
    independent implementation that (a) only looked at the cross-map
    skill at the largest library size with no convergence check, and
    (b) used a different, hardcoded library-size sweep ('5 25 5')
    than final_interpretation's data-length-scaled one — so the two
    functions could report different verdicts, and different "final
    rho" values, for the identical data. See ccm_causality.py's module
    docstring for the full account. `lib_sizes=None` now defers to the
    canonical data-length-scaled default; pass an explicit string to
    override it as before.

    Returns
    -------
    dict with: forward_skill, reverse_skill, causal_verdict, forward_ccm,
    reverse_ccm, plus the convergence diagnostics
    (forward_total_rise, forward_spearman_rho, forward_converging,
    reverse_total_rise, reverse_spearman_rho, reverse_converging) so
    callers (e.g. pipeline.py) can forward them into
    edm_auditor.audit_ccm_direction() instead of leaving it to silently
    assume convergence — see docs/CHANGELOG.md.
    """
    result = ccm_causality_test(df, cause_var, effect_var, E,
                                 lib_sizes=lib_sizes)
    fwd, rev = result['forward'], result['reverse']
    forward_skill = fwd['final_rho']
    reverse_skill = rev['final_rho']

    return {
        'cause_var': cause_var,
        'effect_var': effect_var,
        'forward_skill': forward_skill,   # M_effect -> cause (correct test for cause->effect)
        'reverse_skill': reverse_skill,   # M_cause -> effect (reverse test)
        'causal_verdict': result['verdict'],
        'forward_ccm': fwd.get('ccm_raw'),
        'reverse_ccm': rev.get('ccm_raw'),
        'forward_total_rise': fwd.get('total_rise'),
        'forward_spearman_rho': fwd.get('spearman_rho'),
        'forward_converging': fwd.get('is_converging'),
        'reverse_total_rise': rev.get('total_rise'),
        'reverse_spearman_rho': rev.get('spearman_rho'),
        'reverse_converging': rev.get('is_converging'),
        'disclaimer': result.get('disclaimer'),  # Secret 11
        'method_note': ('forward = M_effect predicts cause (correct test '
                         'for cause->effect); verdict requires library-'
                         'size convergence (Secret 2/7) — see ccm_causality.py'),
    }


# ============================================================
# SAFEGUARD 3: Hankel Aspect Ratio Check
# ============================================================

def check_hankel_aspect_ratio(n, q):
    """
    Check the Hankel matrix aspect ratio for SVD numerical stability.

    Delegates to shared classify_hankel_ratio() from edm_auditor.py
    to ensure consistent thresholds across all audit layers.
    """
    status, ratio, p, q_recommended = classify_hankel_ratio(n, q)

    status_map = {
        'GOOD': 'GOOD',
        'MARGINAL': 'WARNING',
        'DEGRADED': 'CRITICAL',
        'BROKEN': 'CRITICAL',
    }

    if status == 'GOOD':
        recommendation = None
    elif status == 'MARGINAL':
        recommendation = (f"Aspect ratio p/q={ratio:.1f} is marginal. "
                         f"Recommend q <= {q_recommended} (would give p/q >= 10). "
                         f"Current q={q} may cause mild numerical stiffness in SVD.")
    else:
        recommendation = (f"Aspect ratio p/q={ratio:.1f} is too low! "
                         f"q={q} should be reduced to <= {q_recommended} "
                         f"to avoid SVD degradation and spurious A-matrix rigidity. "
                         f"Results using q={q} may be numerically unreliable.")

    return {
        'n': n, 'q': q, 'p': p, 'aspect_ratio': ratio,
        'status': status_map[status], 'recommendation': recommendation,
        'q_recommended_max': q_recommended
    }


# ============================================================
# Full EDM Pipeline
# ============================================================

def edm_pipeline_full(df, target_col, lib, pred, max_E=8):
    """Run EDM pipeline: EmbedDimension, Simplex, S-Map."""
    results = {}

    # P1 fix: 小样本时 maxE 过大会导致 EmbedDimension 搜索到退化区域
    # (E > N/5 时吸引子稀疏)。与 pipeline.py 的 auto-E-detection 保持
    # 一致，动态限制 maxE。
    _n = len(df)
    _maxE_effective = min(max_E, max(2, _n // 5))

    rho_E = _bridge_EmbedDimension(
        data=df, lib=lib, pred=pred,
        maxE=_maxE_effective, Tp=1, columns=target_col, target=target_col,
        showPlot=False, numProcess=1)
    if not rho_E['rho'].notna().any():
        raise ValueError(
            f"EmbedDimension returned all-NA rho for '{target_col}'. "
            f"The series is too sparse or constant for the EDM library/prediction split."
        )
    best_idx = rho_E['rho'].idxmax()
    E_opt = int(rho_E.loc[best_idx, 'E'])
    results['E_opt'] = E_opt
    results['rho_embed'] = rho_E.loc[best_idx, 'rho']
    results['rho_E_curve'] = rho_E

    sx = _bridge_Simplex(
        data=df, lib=lib, pred=pred,
        E=E_opt, Tp=1, columns=target_col, target=target_col,
        showPlot=False)
    if sx['Observations'].notna().sum() < 2 or sx['Predictions'].notna().sum() < 2:
        raise ValueError(
            f"Simplex produced insufficient non-NA predictions for '{target_col}'."
        )
    results['rho_simplex'] = sx['Observations'].corr(sx['Predictions'])
    results['simplex'] = sx

    smap = _bridge_SMapPredictNonlinear(
        data=df, lib=lib, pred=pred,
        E=E_opt, columns=target_col, target=target_col,
        showPlot=False)
    if not smap['rho'].notna().any():
        raise ValueError(
            f"S-Map returned all-NA rho for '{target_col}'."
        )
    rho_0 = smap.loc[smap['theta'] == smap['theta'].min(), 'rho'].values[0]
    rho_max = smap['rho'].max()
    theta_best = smap.loc[smap['rho'].idxmax(), 'theta']
    results['rho_theta_0'] = rho_0
    results['rho_smap_max'] = rho_max
    results['theta_best'] = theta_best
    results['is_nonlinear'] = (rho_max - rho_0) >= 0.05 and theta_best > 0
    results['smap'] = smap

    return results


def havok_pipeline(data, q, dt=1.0):
    """Run SovereignHAVOK V-basis and U-basis."""
    n = len(data)
    p = n - q + 1
    wl = min(11, p)  # 窗口绝不能超过 Hankel 行数 p
    if wl % 2 == 0: wl -= 1  # 确保奇数
    if wl < 5: wl = min(5, p)
    if wl % 2 == 0: wl -= 1  # 二次确保奇偶

    sh_v = SovereignHAVOK(
        q_delays=q, dt=dt, energy_threshold=0.99,
        poly_order=min(3, wl-1), window_length=wl, basis="V")
    sh_v.fit(data)

    sh_u = SovereignHAVOK(
        q_delays=q, dt=dt, energy_threshold=0.99,
        poly_order=min(3, wl-1), window_length=wl, basis="U")
    sh_u.fit(data)

    return sh_v, sh_u


# ============================================================
# Heuristic Validation with all 3 safeguards
# (D-P0-2: 原 "Cross-Validation" 命名误导, 实为算法间一致性启发式验证)
# ============================================================

def heuristic_validation_with_safeguards(edm, hv, hu, lyap, hankel_check, var_name, df):
    """启发式一致性验证 (非统计交叉验证).

    D-P0-2 修复 (Round 21 §P0-A): 原函数名 `cross_validate_with_safeguards`
    暗示统计意义上的 KFold/train-test CV, 但实际仅做算法间的 if-else 一致性
    检查 (EDM vs HAVOK, Lyapunov horizon, Hankel ratio), 不涉及样本划分.
    对时间序列相邻 hold-out (lib='1 {n-7}', pred='{n-6} {n}') 在 AR(1) φ=0.9
    下互信息 ≈ 0.83 nats, 测试集 ρ 被系统性高估, 不构成独立 CV.

    本函数已重命名为 `heuristic_validation_with_safeguards` 以反映其本质.
    `cross_validate_with_safeguards` 保留为别名以兼容现有调用点.
    """
    checks = []
    warnings_list = []
    n = len(df)

    # ── Standard checks ──
    if edm['is_nonlinear']:
        if hv.kurtosis_vr_ > 1.5:
            checks.append(("CONSISTENT",
                f"EDM nonlinear (theta={edm['theta_best']:.1f}), "
                f"HAVOK confirms heavy-tailed (kurt={hv.kurtosis_vr_:.2f})"))
        elif hv.kurtosis_vr_ > 0.5:
            checks.append(("PARTIAL",
                f"EDM nonlinear, HAVOK mild tails (kurt={hv.kurtosis_vr_:.2f})"))
        else:
            checks.append(("DISCREPANCY",
                f"EDM nonlinear but HAVOK near-Gaussian (kurt={hv.kurtosis_vr_:.2f})"))
    else:
        if hv.kurtosis_vr_ > 1.5:
            checks.append(("DISCREPANCY",
                f"EDM linear but HAVOK heavy-tailed (kurt={hv.kurtosis_vr_:.2f})"))
        else:
            checks.append(("CONSISTENT",
                "Both EDM and HAVOK agree: near-linear or stochastic dynamics"))

    # ── Safeguard 1: Lyapunov Horizon ──
    if lyap['lambda_max'] is not None:
        tau_L = lyap['lyapunov_time']
        horizon_3 = lyap['prediction_horizon_3x']
        checks.append(("SAFEGUARD",
            f"[Lyapunov] lambda_max={lyap['lambda_max']:.4f}, "
            f"tau_L={tau_L:.1f} games, "
            f"3*tau_L={horizon_3:.1f} games (hard prediction limit)"))

        # Warn if prediction was attempted beyond horizon
        pred_end = n
        if horizon_3 < pred_end:
            warnings_list.append(
                f"WARNING: 3*tau_L={horizon_3:.1f} games < prediction range ({pred_end} games). "
                f"Predictions beyond game {int(horizon_3)} are physically unreliable "
                f"(chaotic divergence).")
    elif lyap.get('warning'):
        checks.append(("SAFEGUARD",
            f"[Lyapunov] Estimation failed: {lyap['warning']}"))

    # ── Safeguard 2: CCM direction ──
    # Add note about CCM methodology
    checks.append(("SAFEGUARD",
        "[CCM] Reminder: to test X->Y, build M_Y (effect's manifold) "
        "and predict X. 'Victim bears the imprint of the perpetrator.' "
        "See enhanced CCM analysis below."))

    # ── Safeguard 3: Hankel Aspect Ratio ──
    ratio_status = hankel_check['status']
    ratio = hankel_check['aspect_ratio']
    if ratio_status == "GOOD":
        checks.append(("SAFEGUARD",
            f"[Hankel] Aspect ratio p/q={ratio:.1f} — numerically stable"))
    elif ratio_status == "WARNING":
        checks.append(("SAFEGUARD",
            f"[Hankel] WARNING: p/q={ratio:.1f} is marginal. "
            f"Recommend q <= {hankel_check['q_recommended_max']}"))
        warnings_list.append(hankel_check['recommendation'])
    else:
        checks.append(("SAFEGUARD",
            f"[Hankel] CRITICAL: p/q={ratio:.1f} — SVD may be degraded!"))
        warnings_list.append(hankel_check['recommendation'])

    # ── V-U basis agreement ──
    if abs(hv.kurtosis_vr_ - hu.kurtosis_vr_) < 0.3:
        checks.append(("CONSISTENT",
            f"V-basis and U-basis agree (delta-kurt={abs(hv.kurtosis_vr_-hu.kurtosis_vr_):.3f})"))
    else:
        checks.append(("DISCREPANCY",
            f"Basis mismatch: V-kurt={hv.kurtosis_vr_:.3f} vs U-kurt={hu.kurtosis_vr_:.3f}"))

    return checks, warnings_list


# D-P0-2 兼容别名: 旧调用方仍可使用 `cross_validate_with_safeguards`,
# 但建议迁移到 `heuristic_validation_with_safeguards` 以避免命名误导.
cross_validate_with_safeguards = heuristic_validation_with_safeguards


# ============================================================
# Visualization
# ============================================================

def plot_enhanced_report(df, all_results, safeguards, output_path):
    """Generate enhanced visualization with safeguard overlays."""
    variables = list(all_results.keys())
    n_vars = len(variables)

    fig = plt.figure(figsize=(20, 5 * n_vars + 3))
    gs = GridSpec(n_vars + 1, 4, figure=fig,
                  width_ratios=[1.2, 1.6, 1.4, 1.6],
                  height_ratios=[1]*n_vars + [0.6])

    colors = {'result': '#2196F3', 'kills': '#FF5722',
              'damage': '#4CAF50', 'deaths': '#9C27B0'}

    for row, var in enumerate(variables):
        r = all_results[var]
        color = colors.get(var, '#607D8B')
        sh = r['havok_v']

        # ── Col 0: Raw + EDM EmbedDim ──
        ax0 = fig.add_subplot(gs[row, 0])
        ax0_twin = ax0.twinx()
        rE = r['edm']['rho_E_curve']
        ax0_twin.plot(rE['E'], rE['rho'], 's-', color='crimson', markersize=8,
                      linewidth=2, label=f'EmbedDim rho')
        ax0_twin.set_ylabel('rho (prediction skill)', color='crimson', fontsize=9)
        ax0_twin.tick_params(axis='y', labelcolor='crimson')
        ax0_twin.axvline(r['edm']['E_opt'], color='red', ls='--', alpha=0.5,
                         label=f'E={r["edm"]["E_opt"]}')
        # P0 回流：泛化 x 轴——优先用 'game' 列，缺失时回退到样本序号，
        # 避免对非游戏类数据（无 'game' 列）抛 KeyError。
        x_axis = df['game'].values if 'game' in df.columns else np.arange(len(df))
        ax0.plot(x_axis, df[var], 'o-', color=color, markersize=7,
                 linewidth=1.5, markerfacecolor='white')
        ax0.set_title(f'{var}', fontsize=12, fontweight='bold')
        ax0.set_xlabel('Sample #'); ax0.set_ylabel(var)
        ax0.grid(True, alpha=0.2)
        lines0, labels0 = ax0_twin.get_legend_handles_labels()
        ax0_twin.legend(lines0, labels0, fontsize=7, loc='lower right')

        # ── Col 1: HAVOK Forcing + Lyapunov Horizon ──
        ax1 = fig.add_subplot(gs[row, 1])
        forcing = sh.forcing_
        # Q9 P1-17 修复: forcing_ 长度 = n - q + 1，索引 j 对应时刻 j + q - 1
        # 之前 t = np.arange(len(forcing)) + sh.q 导致末尾超出数据范围
        t = np.arange(len(forcing)) + sh.q - 1
        ax1.fill_between(t, forcing, alpha=0.2, color=color)
        ax1.plot(t, forcing, 'o-', color=color, markersize=4, linewidth=0.8)
        ax1.axhline(0, color='gray', alpha=0.3)

        # Mark Lyapunov horizon
        lyap = r.get('lyapunov', {})
        if lyap.get('prediction_horizon_3x') is not None:
            horizon = lyap['prediction_horizon_3x']
            if horizon < len(df):
                ax1.axvline(horizon, color='red', ls='-.', alpha=0.6, linewidth=1.5)
                ax1.text(horizon + 0.3, ax1.get_ylim()[1]*0.9,
                        f'3*tau_L = {horizon:.0f}', fontsize=8,
                        color='red', fontweight='bold', rotation=90, va='top')
                ax1.axvspan(horizon, len(df) + 1, alpha=0.08, color='red',
                           label='Beyond prediction horizon')

        # Annotate spikes
        th = 1.5 * np.std(forcing)
        for si in np.where(np.abs(forcing) > th)[0]:
            # Q9 P1-17 修复: si 是 forcing_ 索引，对应时刻 si + q - 1
            gi = si + sh.q - 1
            if 0 <= gi < len(df):
                # P0 回流：泛化 result 列检测——无 'result' 列时用中性标记，
                # 避免对非游戏类数据抛 KeyError。
                if 'result' in df.columns:
                    res = 'W' if df['result'].iloc[gi] == 1 else 'L'
                else:
                    res = '•'
                ax1.annotate(f'G{gi+1}\n{res}', (gi, forcing[si]),
                            xytext=(0, 12 if forcing[si] > 0 else -14),
                            textcoords='offset points', ha='center', fontsize=6.5,
                            color='green' if res == 'W' else 'red', fontweight='bold')

        ax1.set_title(f'HAVOK Forcing (kurt={sh.kurtosis_vr_:.2f}, r={sh.r_})', fontsize=11)
        ax1.set_xlabel('Game #'); ax1.set_ylabel('v_r (forcing)')
        ax1.grid(True, alpha=0.2)

        # ── Col 2: Divergence curve (Lyapunov) ──
        ax2 = fig.add_subplot(gs[row, 2])
        # We'll compute a simplified divergence plot
        data = df[var].values.astype(float)
        n_data = len(data)
        # Build phase space for divergence estimation
        E_div = r['edm']['E_opt']
        N_div = n_data - E_div
        X_div = np.zeros((N_div, E_div))
        for i in range(E_div):
            X_div[:, i] = data[i:i+N_div]

        # Simplified: track mean neighbor divergence
        mean_period = max(3, E_div)
        div_all = []
        for i in range(0, min(N_div - 20, 20), max(1, N_div // 40)):
            dists = np.sum((X_div - X_div[i])**2, axis=1)
            for j in range(max(0, i-mean_period), min(N_div, i+mean_period+1)):
                if 0 <= j < len(dists): dists[j] = np.inf
            j = np.argmin(dists)
            if np.isinf(dists[j]): continue
            # Q9 P1-17 修复: 限制循环范围避免截断伪影
            # 之前使用 min(i+k, N_div-1) 导致当 i+k >= N_div 时比较自身，
            # log(0 + 1e-12) ≈ -27.6 人为拉平发散曲线尾部，Lyapunov 估计偏低
            max_k = min(20, N_div - max(i, j) - 1)
            # ROUND26 算法审视 P0 修复: 同步 log(0) 防护, 用 where 掩码替代 + 1e-12
            div_ij = []
            for k in range(max_k):
                d = np.sqrt(np.sum((X_div[i+k] - X_div[j+k])**2))
                if d > EPS_LYAPUNOV:
                    div_ij.append(np.log(d))
                else:
                    div_ij.append(np.nan)
            div_all.append(div_ij)

        if len(div_all) > 3:
            max_len = max(len(d) for d in div_all)
            div_padded = np.array([d + [np.nan]*(max_len-len(d)) for d in div_all])
            div_mean = np.nanmean(div_padded, axis=0)
            div_std = np.nanstd(div_padded, axis=0)
            t_div = np.arange(len(div_mean))
            ax2.fill_between(t_div, div_mean-div_std, div_mean+div_std,
                            alpha=0.2, color='steelblue')
            ax2.plot(t_div, div_mean, color='steelblue', linewidth=2, label='<ln(divergence)>')
            # Fit line
            fit_end = min(10, len(div_mean) - 3)
            if fit_end >= 3:
                valid = ~np.isnan(div_mean[:fit_end])
                if valid.sum() >= 3:
                    coeffs = np.polyfit(t_div[:fit_end][valid], div_mean[:fit_end][valid], 1)
                    ax2.plot(t_div[:fit_end], np.polyval(coeffs, t_div[:fit_end]),
                            'r--', linewidth=1.5, label=f'slope={coeffs[0]:.4f}')
        ax2.set_title(f'Divergence (Lyapunov est.)', fontsize=11)
        ax2.set_xlabel('Time steps'); ax2.set_ylabel('ln(d)')
        ax2.legend(fontsize=7); ax2.grid(True, alpha=0.2)

        # ── Col 3: Summary + all 3 Safeguards ──
        ax3 = fig.add_subplot(gs[row, 3])
        ax3.axis('off')

        lines = []
        lines.append("=== EDM Diagnostics ===")
        lines.append(f"Embedding E = {r['edm']['E_opt']}")
        lines.append(f"Simplex rho = {r['edm']['rho_simplex']:.3f}")
        lines.append(f"S-Map theta = {r['edm']['theta_best']:.1f}")
        lines.append(f"Nonlinear = {r['edm']['is_nonlinear']}")
        lines.append("")
        lines.append("=== HAVOK Diagnostics ===")
        lines.append(f"Rank r = {sh.r_}  |  R^2 = {sh.regression_r2_:.3f}")
        lines.append(f"Kurtosis = {sh.kurtosis_vr_:.3f}")
        lines.append(f"Expl. var = {sh.explained_var_:.1%}")
        # P0 修复：退化 HAVOK（近常量信号）的 eigenvalues_d_ 为空，跳过 max 计算
        if len(sh.eigenvalues_d_) > 0:
            ev_max = np.max(np.abs(sh.eigenvalues_d_))
            lines.append(f"Max |eig_d| = {ev_max:.3f}")
        else:
            lines.append("Max |eig_d| = N/A (degenerate HAVOK)")

        # Safeguard status
        lines.append("")
        lines.append("=== 3 SAFEGUARDS ===")

        # SG1: Lyapunov
        if lyap.get('lambda_max') is not None:
            tau_L = lyap['lyapunov_time']
            h3 = lyap['prediction_horizon_3x']
            lines.append(f"[SG1] lambda_max = {lyap['lambda_max']:.4f}")
            lines.append(f"      tau_L = {tau_L:.1f} games")
            lines.append(f"      3*tau_L = {h3:.1f} games")
            if h3 < n_data:
                lines.append(f"      !! Predict beyond game {h3:.0f}")
                lines.append(f"         is PHYSICALLY UNRELIABLE")
        else:
            lines.append(f"[SG1] Lyapunov: {lyap.get('warning', 'N/A')}")

        # SG2: CCM
        ccm = r.get('ccm_verification', {})
        if ccm.get('causal_verdict'):
            lines.append(f"[SG2] {ccm['causal_verdict'][:55]}")

        # SG3: Hankel ratio
        hk = r.get('hankel_check', {})
        status_icon = {'GOOD': '[OK]', 'WARNING': '[!!]', 'CRITICAL': '[XX]'}.get(
            hk.get('status', ''), '[?]')
        lines.append(f"[SG3] {status_icon} p/q = {hk.get('aspect_ratio', 'N/A'):.1f}")
        if hk.get('status') != 'GOOD':
            lines.append(f"      Recommend q <= {hk.get('q_recommended_max', 'N/A')}")

        ax3.text(0.05, 0.97, '\n'.join(lines), fontsize=7.2,
                 family='monospace', va='top', transform=ax3.transAxes)

    # ── Bottom row: CCM convergence plots ──
    ax_ccm = fig.add_subplot(gs[n_vars, :])
    ax_ccm.axis('off')
    ccm_text = []
    ccm_text.append("=== CCM Causal Direction Analysis (Safeguard 2: Victim Mirror Principle) ===")
    ccm_text.append("Rule: To test X->Y, build M_Y (effect's manifold), predict X (cause).")
    ccm_text.append("      'The victim (Y) bears the imprint of the perpetrator (X).'")
    ccm_text.append("")

    for var in variables:
        ccm = all_results[var].get('ccm_verification', {})
        if ccm:
            ccm_text.append(f"  {var} causality: {ccm.get('causal_verdict', 'N/A')}")
    ccm_text.append("")
    ccm_text.append("=== Hankel Aspect Ratio Analysis (Safeguard 3: Golden Ratio) ===")
    ccm_text.append("Rule: p/q >= 10 for robust SVD. Below 5: numerical degradation.")
    ccm_text.append("      p = n - q + 1 (time steps), q = embedding dimension (delays)")
    ccm_text.append("")

    for var in variables:
        hk = all_results[var].get('hankel_check', {})
        if hk:
            status = hk.get('status', 'N/A')
            ratio = hk.get('aspect_ratio', 0)
            icon = {'GOOD': '[OK]', 'WARNING': '[!!]', 'CRITICAL': '[XX]'}.get(status, '[?]')
            ccm_text.append(f"  {var:8s}: q={hk.get('q', '?'):2d}, p={hk.get('p', '?'):2d}, "
                          f"p/q={ratio:.1f} {icon} ({status})")

    ax_ccm.text(0.02, 0.95, '\n'.join(ccm_text), fontsize=7.5,
                family='monospace', va='top', transform=ax_ccm.transAxes)

    plt.suptitle('Enhanced EDM + SovereignHAVOK Cross-Validation\n'
                 'with Lyapunov Horizon / CCM Victim Mirror / Hankel Aspect Ratio Safeguards',
                 fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# Main Enhanced Pipeline
# ============================================================

def run_enhanced_validation(csv_path=data_path('game_log.csv'),
                            output_dir='results',
                            variables=None,
                            target_col='result'):
    """Run full enhanced cross-validation with all 3 safeguards."""
    os.makedirs(output_dir, exist_ok=True)

    df = pd.read_csv(csv_path)
    n = len(df)
    lib = f'1 {n - 7}'
    pred = f'{n - 6} {n}'

    print("=" * 72)
    print("  ENHANCED EDM + SovereignHAVOK Cross-Validation")
    print("  with 3 Algorithmic Safeguards")
    print("=" * 72)
    print(f"  Data: {csv_path}")
    if target_col in df.columns:
        mean_target = df[target_col].mean()
        print(f"  Games: {n}  |  Win rate: {mean_target*100:.0f}%")
    else:
        print(f"  Games: {n}  |  target '{target_col}' not found for win-rate summary")
    print()

    # P0 fix: 样本量预检查 — 与 pipeline.py 保持一致。
    # 当 N < 10 时 lib 范围退化为 <=3 个点，pyEDM 的 EmbedDimension/
    # Simplex 会崩溃或返回全 NA。提前返回友好错误，避免下游 3 个
    # safeguard 在退化数据上浪费计算。
    if n < 10:
        print(f"  [FATAL] Insufficient samples: N={n} < 10 (absolute minimum).")
        print(f"    Cross-validation requires >= 10 time points (>= 30 recommended).")
        print(f"    With N={n}, EmbedDimension lib='1 {n-7}' is degenerate.")
        print(f"    Collect more data before re-running.")
        return {
            'error': 'insufficient_samples',
            'n_samples': n,
            'min_required': 10,
            'recommended': 30,
        }
    elif n < 30:
        print(f"  [WARN] Small sample size: N={n} < 30 (recommended minimum).")
        print(f"    Results exploratory only — Lyapunov/Hankel safeguards limited.")
        print()

    default_variables = ['result', 'kills', 'damage', 'deaths']
    variables = list(variables) if variables else default_variables
    variables = [v for v in variables if v in df.columns]
    if not variables:
        raise ValueError(f"None of the requested variables {variables} found in {csv_path}")

    all_results = {}
    all_warnings = {}

    for var in variables:
        print(f"\n{'─' * 72}")
        print(f"  [{var}]")
        print(f"{'─' * 72}")

        try:
            data = df[var].values.astype(float)

            # ── EDM ──
            edm = edm_pipeline_full(df, var, lib, pred)
            E_opt = edm['E_opt']
            print(f"  EDM: E={E_opt}, simplex_rho={edm['rho_simplex']:.4f}, "
                  f"S-Map theta={edm['theta_best']:.1f}, nonlinear={edm['is_nonlinear']}")

            # ── SAFEGUARD 3: Hankel Aspect Ratio ──
            hankel_check = check_hankel_aspect_ratio(n, E_opt)
            print(f"  [SG3] Hankel: q={E_opt}, p={hankel_check['p']}, "
                  f"p/q={hankel_check['aspect_ratio']:.1f} -> {hankel_check['status']}")
            if hankel_check['recommendation']:
                print(f"         {hankel_check['recommendation']}")

            # ── SAFEGUARD 1: Lyapunov Exponent ──
            lyap = estimate_lyapunov_exponent(data, E_opt)
            if lyap['lambda_max'] is not None:
                tau_L = lyap['lyapunov_time']
                h3 = lyap['prediction_horizon_3x']
                print(f"  [SG1] Lyapunov: lambda_max={lyap['lambda_max']:.4f}, "
                      f"tau_L={tau_L:.1f} games, 3*tau_L={h3:.1f} games")
                if h3 < n:
                    print(f"         !! WARNING: Prediction horizon ({h3:.0f} games) "
                          f"< data length ({n} games)")
                    print(f"         Predictions beyond game ~{h3:.0f} are PHYSICALLY UNRELIABLE")
            else:
                print(f"  [SG1] Lyapunov: {lyap.get('warning', 'Estimation failed')}")

            # ── SovereignHAVOK ──
            hv, hu = havok_pipeline(data, E_opt)
            print(f"  HAVOK: r={hv.r_}, R2={hv.regression_r2_:.4f}, "
                  f"kurtosis={hv.kurtosis_vr_:.3f}, expl_var={hv.explained_var_:.1%}")

            # Eigenvalue analysis — delegates to the shared
            # classify_havok_stability() (sovereign_havok.py) so this
            # short-label printout can never drift out of sync with the
            # canonical 1.05/0.90 thresholds used elsewhere (diagnose(),
            # pipeline.py). See classify_havok_stability's docstring.
            evals = hv.eigenvalues_d_  # discrete-time eigenvalues for stability
            if len(evals) == 0:
                # 退化 HAVOK 模型（近常量信号），跳过 eigenvalue-dependent 输出
                # 而不是让它被外层 except Exception 捕获并报晦涩的 [SKIPPED]
                all_results[var] = {
                    'edm': edm, 'havok_v': hv, 'havok_u': hu,
                    'lyapunov': lyap, 'hankel_check': hankel_check,
                    'ccm_verification': {}, 'cross_checks': [],
                }
                print(f"  [SKIPPED] Variable '{var}': HAVOK degenerate — eigenvalues empty")
                continue
            growth = np.sort(np.abs(evals))[::-1]
            max_ev = growth[0]
            print(f"  Koopman: max|eig_d|={max_ev:.4f} ", end='')
            stab_tier = classify_havok_stability(max_ev)
            if stab_tier.startswith("Divergent"):
                print("(DIVERGENT)")
            elif stab_tier.startswith("Highly dissipative"):
                print("(dissipative)")
            else:
                print("(stable)")

            # Forcing spikes
            forcing = hv.forcing_
            spike_th = 1.5 * np.std(forcing)
            spike_idx = np.where(np.abs(forcing) > spike_th)[0]
            for si in spike_idx[:5]:
                # Q9 P1-17 修复: si 是 forcing_ 索引，对应时刻 si + q - 1
                gi = si + hv.q - 1
                if 0 <= gi < len(df):
                    # P0 回流：泛化 target_col 检测——无 target_col 列时标记 N/A。
                    if target_col in df.columns:
                        outcome = 'W' if df[target_col].iloc[gi] == 1 else 'L'
                    else:
                        outcome = f"{target_col}=N/A"
                    print(f"    Spike G{gi+1:2d}: forcing={forcing[si]:+.4f} -> {outcome}")

            # ── SAFEGUARD 2: CCM Direction ──
            # Test relationships of interest
            ccm_results = {}
            # P0 回流：泛化 CCM 方向测试——用 target_col 替代硬编码 'result'，
            # 用 variables 列表推导替代硬编码 ['kills','damage','deaths']，
            # 使核心库支持任意列名（与 web 端副本一致）。
            if var == target_col:
                # Test other variables -> target
                for cause in [v for v in variables if v != target_col]:
                    ccm_r = verify_ccm_direction(df, cause, target_col, E_opt)
                    ccm_results[f'{cause}->{target_col}'] = ccm_r
                    print(f"  [SG2] CCM {cause}->{target_col}: {ccm_r['causal_verdict']}")
            elif 'kills' in variables and 'damage' in variables and var == 'kills':
                ccm_r = verify_ccm_direction(df, 'kills', 'damage', E_opt)
                ccm_results['kills->damage'] = ccm_r
                print(f"  [SG2] CCM kills->damage: {ccm_r['causal_verdict']}")
            if ccm_results:
                # Secret 11 — printed once per variable's CCM block, not once
                # per pair (unconditional, but not spammed).
                any_r = next(iter(ccm_results.values()))
                print(f"  [Secret 11 disclaimer] {any_r.get('disclaimer', '')}")

            # ── Cross-validation ──
            checks, warns = cross_validate_with_safeguards(
                edm, hv, hu, lyap, hankel_check, var, df)
            all_warnings[var] = warns
            for w in warns:
                print(f"  [WARNING] {w}")

            all_results[var] = {
                'edm': edm, 'havok_v': hv, 'havok_u': hu,
                'lyapunov': lyap, 'hankel_check': hankel_check,
                'ccm_verification': ccm_results.get(f'{var}->{target_col}', ccm_results.get('kills->damage', {})),
                'cross_checks': checks
            }
        # P0 回流：except 块改为 [SKIPPED] 标记并记录警告，不再 continue 跳过——
        # 这样 all_results 中缺失的 var 会在后续 Safeguard Summary 中被自然跳过，
        # 同时 all_warnings[var] 保留了失败原因供下游诊断。
        except Exception as e:
            print(f"  [SKIPPED] Variable '{var}' failed cross-validation: {e}")
            all_warnings[var] = [str(e)]

    # ── Visualization ──
    print(f"\n{'─' * 72}")
    print("  Generating enhanced visualization...")
    plot_enhanced_report(df, all_results, {},
                         os.path.join(output_dir, 'enhanced_cross_validation.png'))

    # ── Final Safeguard Summary ──
    print(f"\n{'=' * 72}")
    print("  SAFEGUARD VERDICT SUMMARY")
    print(f"{'=' * 72}")

    print(f"\n  [Safeguard 1: Lyapunov Horizon]")
    print(f"  {'─' * 40}")
    # P0 回流：遍历 all_results 而非 variables——失败的 var 已被 except 块
    # 标记为 [SKIPPED] 且不在 all_results 中，避免 KeyError。
    for var in all_results:
        lyap = all_results[var]['lyapunov']
        if lyap['lambda_max'] is not None:
            h3 = lyap['prediction_horizon_3x']
            status = "WITHIN HORIZON" if h3 >= n else f"BEYOND HORIZON at game {h3:.0f}"
            print(f"    {var:10s}: lambda={lyap['lambda_max']:.4f}, "
                  f"tau_L={lyap['lyapunov_time']:.1f}, {status}")

    print(f"\n  [Safeguard 2: CCM Victim Mirror]")
    print(f"  {'─' * 40}")
    print(f"    Method verified: pyEDM CCM(columns=effect, target=cause)")
    print(f"    tests cause->effect correctly.")
    # P0 回流：泛化 target_col 替代硬编码 'result'，并用
    # `if target_col in all_results` 保护——若 target_col 处理失败
    # （被 [SKIPPED]），跳过 CCM summary 避免 KeyError。
    ccm_disclaimer = ""
    if target_col in all_results:
        target_E = all_results[target_col]['edm']['E_opt']
        for cause in [v for v in all_results if v != target_col]:
            ccm_r = verify_ccm_direction(df, cause, target_col, target_E)
            print(f"    {cause}->{target_col}: {ccm_r['causal_verdict']}")
            ccm_disclaimer = ccm_r.get('disclaimer', '')
    print(f"    [Secret 11 disclaimer] {ccm_disclaimer}")

    print(f"\n  [Safeguard 3: Hankel Aspect Ratio]")
    print(f"  {'─' * 40}")
    total_warnings = 0
    for var in all_results:
        hk = all_results[var]['hankel_check']
        icon = {'GOOD': '[OK]', 'WARNING': '[!!]', 'CRITICAL': '[XX]'}[hk['status']]
        print(f"    {var:10s}: q={hk['q']}, p={hk['p']}, "
              f"ratio={hk['aspect_ratio']:.1f} {icon}")
        if hk['status'] in ('WARNING', 'CRITICAL'):
            total_warnings += 1

    if total_warnings > 0:
        q_rec = hankel_check['q_recommended_max'] if 'hankel_check' in dir() else 3
        print(f"\n    RECOMMENDATION: For n={n} games, keep q <= {q_rec}")
        print(f"    to maintain p/q >= 10 for numerical stability.")

    print(f"\n{'=' * 72}")
    print(f"  Enhanced cross-validation complete.")
    print(f"  Report: results/enhanced_cross_validation.png")
    print(f"{'=' * 72}")

    return all_results


if __name__ == '__main__':
    run_enhanced_validation()
