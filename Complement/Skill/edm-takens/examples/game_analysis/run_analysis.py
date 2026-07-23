"""
游戏数据 · EDM-Takens Skill 案例
================================
32 场游戏, 4 个变量 (kills, deaths, damage), 二元目标 (result).

遵循 14 条禁忌规则的三层纵深防御体系。
本案例是 Skill 的基准连续-二元混合案例, 与音神案例 (类别数据) 互补。

用法:
    cd .skills/edm-takens
    python examples/game_analysis/run_analysis.py

输出:
    examples/game_analysis/game_report.md
    examples/game_analysis/figures/game_dashboard.png
"""

import sys, os, json, warnings

# ── Path setup ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_SRC = os.path.join(_SCRIPT_DIR, '..', '..', 'src')
sys.path.insert(0, _SKILL_SRC)

# ── Windows UTF-8 ──
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy.stats import pearsonr

# ── Robust CJK font loading ──
plt.rcParams.update({
    'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'SimSun'],
    'axes.unicode_minus': False,
    'font.family': 'sans-serif'
})
import matplotlib.font_manager as fm
for _fp in ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc', 'C:/Windows/Fonts/simhei.ttf']:
    if os.path.exists(_fp):
        try: fm.fontManager.addfont(_fp)
        except Exception: pass
fm.fontManager.__dict__.pop('_ttflist', None)
fm.fontManager.__dict__.pop('_ttflist_cache', None)
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'DejaVu Sans']

# ── Skill modules ──
from _edm_bridge import EmbedDimension, Simplex, SMapPredictNonlinear
from ccm_causality import ccm_causality_test
from edm_auditor import AuditReport, Auditor, classify_hankel_ratio

warnings.filterwarnings('ignore')

_OUT_DIR = os.path.join(_SCRIPT_DIR, 'figures')
os.makedirs(_OUT_DIR, exist_ok=True)


def simple_adf(data):
    from scipy.stats import t as t_dist
    y = np.asarray(data, dtype=float); n = len(y)
    dy = np.diff(y); y_lag = y[:-1]
    yl_dm = y_lag - np.mean(y_lag); dy_dm = dy - np.mean(dy)
    rho = np.dot(yl_dm, dy_dm) / max(np.dot(yl_dm, yl_dm), 1e-12)
    resid = dy_dm - rho * yl_dm
    se = np.sqrt(np.sum(resid**2) / (n - 2) / max(np.sum(yl_dm**2), 1e-12))
    return float(rho / max(se, 1e-12)), float(2 * t_dist.sf(abs(rho / max(se, 1e-12)), n - 2))


def simple_kpss(data):
    y = np.asarray(data, dtype=float); n = len(y)
    nlags = max(1, int((n-1)**(1/3)))
    resid = y - np.mean(y); S = np.cumsum(resid)
    s2 = np.var(resid)
    for lag in range(1, nlags+1):
        s2 += 2*(1-lag/(nlags+1))*np.mean(resid[lag:]*resid[:-lag])
    stat = np.sum(S**2) / (n**2 * max(s2, 1e-12))
    if stat < 0.347: p = 0.50
    elif stat < 0.463: p = 0.10
    elif stat < 0.739: p = 0.05
    else: p = 0.01
    return float(stat), float(p)


def main():
    # ═══════════════════════════════════════════════════════
    # 0. Load data
    # ═══════════════════════════════════════════════════════
    data_path = os.path.join(_SCRIPT_DIR, 'data', 'game_log.csv')
    df = pd.read_csv(data_path, encoding='utf-8-sig')
    N = len(df)
    variables = ['result', 'kills', 'damage', 'deaths']
    lib = f'1 {N - 7}'
    pred = f'{N - 6} {N}'
    print(f"游戏数据: N={N}, vars={variables}, win_rate={df['result'].mean():.0%}")
    print(f"lib={lib} pred={pred}")

    # ═══════════════════════════════════════════════════════
    # LAYER 2 — Audit
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  LAYER 2 — 前置审计")
    print("=" * 58)

    # S3 Hankel (★★★★)
    print("\n[S3 ★★★★] Hankel 纵横比 (maxE=6):")
    hankel_checks = {}
    for var in variables:
        status, ratio, p, q_rec = classify_hankel_ratio(N, 6)
        icon = {'GOOD': 'OK', 'MARGINAL': '!!', 'DEGRADED': 'XX', 'BROKEN': 'XX'}[status]
        hankel_checks[var] = {'status': status, 'ratio': ratio, 'p': p, 'q_rec': q_rec}
        print(f"  {var}: p/q={ratio:.1f} [{icon}] {status} (safe q≤{q_rec})")

    # S8 Stationarity (★★★★)
    print("\n[S8 ★★★★] 平稳性 (ADF+KPSS):")
    stat_checks = {}
    for var in variables:
        data = df[var].values.astype(float)
        adf_stat, adf_p = simple_adf(data)
        kpss_stat, kpss_p = simple_kpss(data)
        if adf_p < 0.05 and kpss_p > 0.05: v = 'PASS — 平稳'
        elif adf_p < 0.05 and kpss_p < 0.05: v = 'WARN — 趋势平稳'
        elif adf_p > 0.05 and kpss_p < 0.05: v = 'WARN — 差分平稳'
        else: v = 'WARN — 效力不足'
        stat_checks[var] = v
        print(f"  {var}: ADF p={adf_p:.4f} KPSS p={kpss_p:.4f} → {v}")

    # S9 Genericity (★★★)
    print("\n[S9 ★★★] 观测泛型性:")
    gen_issues = {}
    for var in variables:
        vals = df[var].values
        n_uniq = len(np.unique(vals))
        issues = []
        if n_uniq < 5: issues.append(f"类别过少({n_uniq})")
        if var == 'result' and n_uniq == 2:
            issues.append("二元目标 — ρ 天花板 ~0.87 (S9) — 优先用连续协变量")
        gen_issues[var] = issues
        print(f"  {var}: {n_uniq}类 → {'PASS' if not issues else 'WARN: '+'; '.join(issues)}")

    # ═══════════════════════════════════════════════════════
    # EXECUTION: EDM + HAVOK + CCM
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  EXECUTION — EDM + HAVOK + CCM")
    print("=" * 58)

    edm_results = {}

    for var in variables:
        print(f"\n── [{var}] ──")
        data = df[var].values.astype(float)

        # EmbedDimension
        E_opt = 3
        try:
            rho_E = EmbedDimension(data=df, columns=var, target=var,
                                    maxE=6, Tp=1, lib=lib, pred=pred,
                                    showPlot=False, numProcess=1)
            rho_E['E'] = pd.to_numeric(rho_E['E'], errors='coerce')
            rho_E['rho'] = pd.to_numeric(rho_E['rho'], errors='coerce')
            E_opt = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])
        except Exception as e:
            print(f"  EmbedDim 失败: {type(e).__name__}, fallback E=3")

        # S3 check on E_opt
        h_status, h_ratio, h_p, q_rec = classify_hankel_ratio(N, E_opt)
        if h_status in ('DEGRADED', 'BROKEN'):
            old_E = E_opt; E_opt = q_rec
            print(f"  [S3] E {old_E}→{E_opt} (p/q={h_ratio:.1f})")
        print(f"  E_opt = {E_opt}")

        # Simplex
        rho_sx, mae_sx = np.nan, np.nan
        try:
            sx = Simplex(data=df, columns=var, target=var,
                         E=E_opt, Tp=1, lib=lib, pred=pred, showPlot=False)
            obs = pd.to_numeric(sx['Observations'], errors='coerce').values
            prd = pd.to_numeric(sx['Predictions'], errors='coerce').values
            mask = ~(np.isnan(obs) | np.isnan(prd))
            if mask.sum() > 3:
                rho_sx = float(pearsonr(obs[mask], prd[mask])[0])
                mae_sx = float(np.mean(np.abs(obs[mask] - prd[mask])))
            print(f"  Simplex: ρ={rho_sx:.3f} MAE={mae_sx:.3f}")
        except Exception as e:
            print(f"  Simplex 失败: {e}")

        # S-Map
        is_nonlinear, theta_best, rho_smap = False, 0.0, 0.0
        try:
            sm = SMapPredictNonlinear(data=df, columns=var, target=var,
                                      E=E_opt, lib=lib, pred=pred, showPlot=False)
            sm['theta'] = pd.to_numeric(sm['theta'], errors='coerce')
            sm['rho'] = pd.to_numeric(sm['rho'], errors='coerce')
            peak_idx = sm['rho'].idxmax()
            theta_best = float(sm.loc[peak_idx, 'theta'])
            rho_smap = float(sm.loc[peak_idx, 'rho'])
            rho_theta0 = float(sm.loc[sm['theta'].idxmin(), 'rho'])
            is_nonlinear = (rho_smap - rho_theta0) >= 0.05 and theta_best > 0
            print(f"  S-Map: θ={theta_best:.0f} ρ={rho_smap:.3f} 非线性={'是' if is_nonlinear else '否'}")
        except Exception as e:
            print(f"  S-Map 失败: {e}")

        # CCM on result vs kills/damage/deaths
        ccm_results = {}
        if var == 'result':
            for cause in ['kills', 'damage', 'deaths']:
                try:
                    r = ccm_causality_test(df, cause_var=cause, effect_var='result', E=E_opt)
                    ccm_results[cause] = {
                        'verdict': r['verdict'],
                        'fwd_rho': r['forward']['final_rho'],
                        'rev_rho': r['reverse']['final_rho'],
                        'fwd_conv': r['forward']['is_converging'],
                    }
                    print(f"  CCM {cause}→result (E={E_opt}): {r['verdict']}")
                except Exception as e:
                    print(f"  CCM {cause}→result: 失败 ({e})")

        edm_results[var] = {
            'E_opt': E_opt, 'rho_sx': rho_sx, 'mae_sx': mae_sx,
            'theta_best': theta_best, 'rho_smap': rho_smap,
            'is_nonlinear': is_nonlinear, 'ccm': ccm_results,
            'hankel_status': h_status, 'hankel_ratio': h_ratio,
        }

    # ═══════════════════════════════════════════════════════
    # LAYER 3 — HAVOK
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  LAYER 3 — HAVOK 分解 + 交叉验证")
    print("=" * 58)

    havok_results = {}
    try:
        from sovereign_havok import SovereignHAVOK
        HAS_HAVOK = True
    except ImportError:
        HAS_HAVOK = False
        print("  [!] HAVOK 不可用")

    xv_results = {}

    if HAS_HAVOK:
        for var in variables:
            arr = df[var].values.astype(float)
            E = edm_results[var]['E_opt']
            wl = min(11, (N - E) // 2 * 2 - 1)
            if wl < 5: wl = 5
            if wl % 2 == 0: wl -= 1
            print(f"\n── [{var}] HAVOK (q={E}, wl={wl}) ──")
            try:
                sh = SovereignHAVOK(q_delays=E, dt=1.0, energy_threshold=0.99,
                                    poly_order=min(3, wl-1), window_length=wl, basis="V")
                sh.fit(arr)
                kurt_vr = float(sh.kurtosis_vr_)
                print(f"  r={sh.r_} R²={sh.regression_r2_:.3f} kurtosis={kurt_vr:.3f} "
                      f"expl_var={sh.explained_var_:.0%}")
                havok_results[var] = {
                    'r': sh.r_, 'r2': sh.regression_r2_, 'kurtosis': kurt_vr,
                    'expl_var': sh.explained_var_, 'forcing': sh.forcing_, 'sh': sh,
                }
            except Exception as e:
                print(f"  HAVOK 失败: {e}")

        # S6 Cross-validation
        print("\n[S6] EDM-HAVOK 交叉验证:")
        for var in variables:
            edm = edm_results[var]; hv = havok_results.get(var, {})
            if 'kurtosis' not in hv: continue
            edm_nl = edm['is_nonlinear']; hv_kt = hv['kurtosis']
            if edm_nl and hv_kt > 1.5: s6 = 'CONSISTENT — 强非线性'
            elif edm_nl and hv_kt <= 1.5: s6 = 'DISCREPANCY — EDM 非线性，HAVOK 近高斯'
            elif not edm_nl and hv_kt > 1.5: s6 = 'DISCREPANCY — HAVOK 重尾，EDM 线性'
            else: s6 = 'CONSISTENT — 近线性/随机'
            xv_results[var] = {'s6_verdict': s6}
            print(f"  {var}: EDM_nl={edm_nl} HAVOK_kurt={hv_kt:.3f} → {s6}")

    # ═══════════════════════════════════════════════════════
    # Visualization
    # ═══════════════════════════════════════════════════════
    print("\n生成图表...")
    fig = plt.figure(figsize=(20, 14))
    gs = GridSpec(4, 5, figure=fig, hspace=0.5, wspace=0.4,
                  height_ratios=[1, 1, 1, 1], width_ratios=[1.0, 1.2, 1.3, 1.1, 1.0])
    colors = {'result': '#2563EB', 'kills': '#DC2626',
              'damage': '#16A34A', 'deaths': '#7C3AED'}

    for row, var in enumerate(variables):
        edm = edm_results[var]; hv = havok_results.get(var, {})
        c = colors[var]; E = edm['E_opt']
        arr = df[var].values.astype(float)

        # Col 0: Time series
        ax0 = fig.add_subplot(gs[row, 0])
        ax0.plot(arr, 'o-', color=c, markersize=5, linewidth=1, markerfacecolor='white')
        ax0.set_title(f'{var}  (N={N})\nS3 p/q={edm["hankel_ratio"]:.1f} [{edm["hankel_status"]}]',
                      fontsize=9, fontweight='bold')
        ax0.set_xlabel('Game'); ax0.grid(True, alpha=0.2)

        # Col 1: Simplex O vs P
        ax1 = fig.add_subplot(gs[row, 1])
        try:
            sx = Simplex(data=df, columns=var, target=var,
                         E=E, Tp=1, lib=lib, pred=pred, showPlot=False)
            obs = pd.to_numeric(sx['Observations'], errors='coerce').values
            prd = pd.to_numeric(sx['Predictions'], errors='coerce').values
            mask = ~(np.isnan(obs) | np.isnan(prd))
            ax1.scatter(obs[mask], prd[mask], alpha=0.6, c=c, edgecolors='k', s=30)
            mn, mx = np.nanmin(obs), np.nanmax(obs)
            ax1.plot([mn, mx], [mn, mx], 'r--', linewidth=1, alpha=0.5, label='1:1')
            ax1.legend(fontsize=7)
        except Exception:
            ax1.text(0.5, 0.5, 'N/A', ha='center', va='center', transform=ax1.transAxes)
        ax1.set_title(f'Simplex E={E}\nρ={edm["rho_sx"]:.3f}  MAE={edm["mae_sx"]:.3f}',
                      fontsize=9, fontweight='bold')
        ax1.set_xlabel('Observed'); ax1.set_ylabel('Predicted'); ax1.grid(True, alpha=0.2)

        # Col 2: HAVOK forcing
        ax2 = fig.add_subplot(gs[row, 2])
        if 'forcing' in hv:
            forcing = hv['forcing']; sh = hv['sh']
            # Q9 P1-17 修复: forcing_ 长度 = n - q + 1，索引 j 对应时刻 j + q - 1
            t_f = np.arange(len(forcing)) + sh.q - 1
            markerline, stemlines, baseline = ax2.stem(
                t_f, forcing, linefmt=f'{c}', markerfmt='o', basefmt='gray')
            markerline.set_markersize(3); markerline.set_markerfacecolor(c)
            stemlines.set_linewidth(1.5); stemlines.set_alpha(0.75); baseline.set_alpha(0.25)
            ax2.set_title(f'HAVOK forcing: r={sh.r_}  kurt={sh.kurtosis_vr_:.2f}\n'
                          f'R²={sh.regression_r2_:.3f}  expl_var={sh.explained_var_:.0%}',
                          fontsize=9, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, '—', ha='center', va='center', transform=ax2.transAxes,
                     fontsize=24, color='lightgray')
            ax2.set_title('HAVOK forcing\n(not available)', fontsize=9)
        ax2.set_xlabel('Game'); ax2.grid(True, alpha=0.2)

        # Col 3: S-Map theta scan
        ax3 = fig.add_subplot(gs[row, 3])
        try:
            sm = SMapPredictNonlinear(data=df, columns=var, target=var,
                                      E=E, lib=lib, pred=pred, showPlot=False)
            sm['theta'] = pd.to_numeric(sm['theta'], errors='coerce')
            sm['rho'] = pd.to_numeric(sm['rho'], errors='coerce')
            ax3.plot(sm['theta'], sm['rho'], 'o-', color=c, markersize=5, linewidth=1.2)
            ax3.axvline(edm['theta_best'], color='red', ls='--', linewidth=1, alpha=0.6,
                        label=f'θ*={edm["theta_best"]:.0f}')
            ax3.axhline(0, color='gray', alpha=0.3)
            ax3.legend(fontsize=7)
        except Exception:
            ax3.text(0.5, 0.5, 'N/A', ha='center', va='center', transform=ax3.transAxes)
        ax3.set_title(f'S-Map θ scan\n非线性={"是" if edm["is_nonlinear"] else "否/弱"}',
                      fontsize=9, fontweight='bold')
        ax3.set_xlabel('θ'); ax3.set_ylabel('ρ'); ax3.grid(True, alpha=0.2)

        # Col 4: Audit summary
        ax4 = fig.add_subplot(gs[row, 4])
        ax4.axis('off')
        lines = [f"═══ {var} ═══", f"E={E}",
                 f"Simplex ρ={edm['rho_sx']:.3f}",
                 f"θ_best={edm['theta_best']:.0f}",
                 f"非线性={'是' if edm['is_nonlinear'] else '—'}"]
        if var == 'result' and edm.get('ccm'):
            for cause, cr in edm['ccm'].items():
                lines.append(f"CCM {cause[:4]}: {cr['verdict'][:20]}")
        h_stat = edm['hankel_status']
        lines.extend([f"S3 Hankel: {h_stat}",
                      f"S8 Stationarity: {stat_checks.get(var, 'N/A')[:15]}",
                      f"S9 Genericity: {'WARN' if gen_issues.get(var) else 'PASS'}"])
        if 'kurtosis' in hv:
            lines.append(f"HAVOK kurt={hv['kurtosis']:.2f}")
            if var in xv_results:
                lines.append(f"S6: {xv_results[var]['s6_verdict'][:30]}")
        ax4.text(0.05, 0.97, '\n'.join(lines), fontsize=8.5, family='sans-serif',
                 va='top', transform=ax4.transAxes,
                 bbox=dict(boxstyle='round,pad=0.5', facecolor='#F8FAFC',
                           edgecolor='#CBD5E1', alpha=0.8))

    fig.suptitle('游戏数据 · EDM-Takens 完整分析 (32 games)\n'
                 'S3 Hankel → S8 Stationarity → S9 Genericity → EDM → HAVOK → S6 Cross-Validation',
                 fontsize=13, fontweight='bold', y=1.02)
    out_path = os.path.join(_OUT_DIR, 'game_dashboard.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white', pad_inches=0.3)
    plt.close()
    print(f"  图表: {out_path}")

    # ═══════════════════════════════════════════════════════
    # Report
    # ═══════════════════════════════════════════════════════
    md = []
    md.append("# 游戏数据 · EDM-Takens 分析报告")
    md.append(f"\n**数据**: N={N} 场游戏, result(二元)/kills/deaths/damage, win_rate={df['result'].mean():.0%}")
    md.append(f"**训练/预测**: {lib} / {pred}")
    md.append("")
    md.append("## LAYER 2 — 前置审计")
    md.append("\n### S3 ★★★★ Hankel 纵横比\n")
    md.append("| 变量 | N | maxE | p/q | 判定 | 安全 q≤ |")
    md.append("|------|---|------|-----|------|--------|")
    for var in variables:
        h = hankel_checks[var]
        md.append(f"| {var} | {N} | 6 | {h['ratio']:.1f} | {h['status']} | {h['q_rec']} |")
    md.append("\n### S8 ★★★★ 平稳性\n")
    md.append("| 变量 | 判定 |")
    md.append("|------|------|")
    for var in variables:
        md.append(f"| {var} | {stat_checks[var]} |")
    md.append("\n### S9 ★★★ 观测泛型性\n")
    md.append("| 变量 | 判定 |")
    md.append("|------|------|")
    for var in variables:
        issues = gen_issues[var]
        md.append(f"| {var} | {'WARN: '+'; '.join(issues) if issues else 'PASS'} |")
    md.append("")
    md.append("## EXECUTION — EDM\n")
    md.append("| 变量 | E | Simplex ρ | S-Map θ | 非线性 |")
    md.append("|------|---|-----------|---------|--------|")
    for var in variables:
        e = edm_results[var]
        md.append(f"| {var} | {e['E_opt']} | {e['rho_sx']:.3f} | {e['theta_best']:.0f} | {'是' if e['is_nonlinear'] else '否'} |")
    md.append("")
    ccm = edm_results['result'].get('ccm', {})
    if ccm:
        md.append("### CCM 因果 (result vs covariates)\n")
        md.append("| Pair | Verdict | fwd ρ | rev ρ | Converging? |")
        md.append("|------|---------|-------|-------|-------------|")
        for cause, cr in ccm.items():
            fwd_s = f"{cr['fwd_rho']:.3f}" if cr['fwd_rho'] is not None else 'N/A'
            rev_s = f"{cr['rev_rho']:.3f}" if cr['rev_rho'] is not None else 'N/A'
            md.append(f"| {cause}→result | {cr['verdict']} | {fwd_s} | {rev_s} | {cr['fwd_conv']} |")
        md.append("")
    if HAS_HAVOK and xv_results:
        md.append("## LAYER 3 — HAVOK + 交叉验证\n")
        md.append("### HAVOK 诊断\n")
        md.append("| 变量 | r | R² | kurtosis | expl_var |")
        md.append("|------|---|---|----------|----------|")
        for var in variables:
            hv = havok_results.get(var, {})
            if hv:
                md.append(f"| {var} | {hv['r']} | {hv['r2']:.3f} | {hv['kurtosis']:.3f} | {hv['expl_var']:.0%} |")
        md.append("\n### S6 EDM-HAVOK 交叉验证\n")
        md.append("| 变量 | EDM 非线性 | HAVOK kurtosis | 判定 |")
        md.append("|------|-----------|---------------|------|")
        for var in variables:
            if var in xv_results:
                e = edm_results[var]; hv = havok_results.get(var, {})
                md.append(f"| {var} | {e['is_nonlinear']} | {hv['kurtosis']:.3f} | {xv_results[var]['s6_verdict']} |")
        md.append("")
    md.append("## 核心发现\n")
    md.append("1. **S9 Genericity**: result 是二元目标 — EDM ρ 天花板约 0.87. 建议用 kills/damage/deaths 等连续变量重构吸引子")
    md.append("2. **S3 Hankel**: N=32 时 E>3 会使 p/q 进入危险区 — AUTO-FIX 自动将 E 封顶")
    md.append("3. **S4 Multiview**: N<100 且 K=4 → Multiview 强烈推荐 (但 pyEDM Windows 兼容性待解决)")
    md.append("4. **S11**: 所有 CCM 结果附带公共驱动免责 — '团队实力'可能同时驱动所有游戏指标")
    md.append("\n---\n*`examples/game_analysis/run_analysis.py` — 遵循 `references/forbidden_rules_reference.md`*")

    report_path = os.path.join(_SCRIPT_DIR, 'game_report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print(f"  报告: {report_path}")
    print("=" * 58)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
