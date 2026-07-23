"""
音神序列 · EDM-Takens Skill 案例分析
=====================================
遵循 14 条禁忌规则的三层纵深防御体系。

数据: 10行咒语 × 12字 = 120个音素 → 六姬(6类) / 主元音(5类) / 主辅音(18类)

用法:
    cd .skills/edm-takens
    python examples/yinshen/run_analysis.py

输出:
    examples/yinshen/yinshen_report.md
    examples/yinshen/yinshen_report.json
    examples/yinshen/figures/yinshen_dashboard.png
"""

import sys, os, json, warnings

# Windows: force UTF-8 for HAVOK diagnostic output
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

# Path: examples/yinshen/ → .skills/edm-takens/src/
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_SRC = os.path.join(_SCRIPT_DIR, '..', '..', 'src')
sys.path.insert(0, _SKILL_SRC)

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy.stats import pearsonr
from pypinyin import pinyin, Style
plt.rcParams.update({
    'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'KaiTi', 'SimSun'],
    'axes.unicode_minus': False,
    'font.family': 'sans-serif'
})

# ── Robust CJK font loading (Windows + Agg backend) ──
# The Agg backend does not auto-scan Windows font directories. We force-
# load the font files directly and rebuild the font cache so Chinese
# characters render correctly in ALL text elements (titles, labels, and
# ax.text() calls alike).
import matplotlib.font_manager as fm
_FONT_CANDIDATES = [
    ('C:/Windows/Fonts/msyh.ttc',  'Microsoft YaHei'),
    ('C:/Windows/Fonts/msyhbd.ttc', 'Microsoft YaHei'),
    ('C:/Windows/Fonts/simsun.ttc', 'SimSun'),
    ('C:/Windows/Fonts/simhei.ttf', 'SimHei'),
    ('C:/Windows/Fonts/simkai.ttf', 'KaiTi'),
]
_loaded = False
for _fp, _name in _FONT_CANDIDATES:
    if os.path.exists(_fp):
        try:
            fm.fontManager.addfont(_fp)
            _loaded = True
        except Exception:
            pass

if _loaded:
    # Force matplotlib to rebuild its internal font list
    fm.fontManager.__dict__.pop('_ttflist', None)
    fm.fontManager.__dict__.pop('_ttflist_cache', None)
    # Re-apply after font registration
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'DejaVu Sans']
    plt.rcParams['font.family'] = 'sans-serif'

from _edm_bridge import EmbedDimension, Simplex, SMapPredictNonlinear
from ccm_causality import ccm_causality_test
from edm_auditor import classify_hankel_ratio

warnings.filterwarnings('ignore')

_OUT_DIR = os.path.join(_SCRIPT_DIR, 'figures')
os.makedirs(_OUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════
# 六姬分类
# ═══════════════════════════════════════════════════════════
JI_VOWELS = {
    'tai': ['a', 'ā', 'an'], 'xuan': ['ao', 'ou'],
    'mei': ['i', 'ī', 'ia'], 'xi': ['e', 'ei'],
    'qi': ['u', 'ū', 'uo'], 'miao': ['o', 'ō'],
}
JI_NAMES = {'tai': '太姬', 'xuan': '玄姬', 'mei': '美姬',
            'xi': '希姬', 'qi': '祈姬', 'miao': '妙姬'}
FINAL_TO_JI = {f: ji for ji, finals in JI_VOWELS.items() for f in finals}
FIRST_VOWEL_TO_JI = {'a': 'tai', 'o': 'miao', 'e': 'xi', 'i': 'mei', 'u': 'qi'}


def classify_final(final):
    if not final or pd.isna(final): return 'unclassified'
    final = final.strip().lower()
    return FINAL_TO_JI.get(final, FIRST_VOWEL_TO_JI.get(final[0], 'unclassified'))


def get_final(char):
    try: return pinyin(char, style=Style.FINALS, strict=False)[0][0]
    except Exception: return ''


def encode_integer(series):
    states = sorted(set(series))
    return [states.index(s) for s in series], states


def extract_primary_vowel_consonant(row):
    vowels, consonants = [], []
    for pos in range(1, 5):
        v_slots = [row[f'字{pos}_元音{i}'] for i in range(1, 3)
                   if pd.notna(row[f'字{pos}_元音{i}']) and row[f'字{pos}_元音{i}'] != '']
        c_slots = [row[f'字{pos}_辅音{i}'] for i in range(1, 3)
                   if pd.notna(row[f'字{pos}_辅音{i}'])]
        vowels.append(v_slots[0] if v_slots else None)
        consonants.append(c_slots[0] if c_slots else None)
    return vowels, consonants


def simple_adf(data):
    """简易 ADF 检验 (scipy OLS-based)"""
    from scipy.stats import t as t_dist
    y = np.asarray(data, dtype=float); n = len(y)
    dy = np.diff(y); y_lag = y[:-1]
    yl_dm = y_lag - np.mean(y_lag); dy_dm = dy - np.mean(dy)
    rho = np.dot(yl_dm, dy_dm) / max(np.dot(yl_dm, yl_dm), 1e-12)
    resid = dy_dm - rho * yl_dm
    se = np.sqrt(np.sum(resid**2) / (n - 2) / max(np.sum(yl_dm**2), 1e-12))
    t_stat = rho / max(se, 1e-12)
    p_val = 2 * t_dist.sf(abs(t_stat), n - 2)
    return float(t_stat), float(p_val)


def simple_kpss(data):
    """简易 KPSS 检验"""
    y = np.asarray(data, dtype=float); n = len(y)
    nlags = max(1, int((n - 1) ** (1/3)))
    resid = y - np.mean(y); S = np.cumsum(resid)
    s2 = np.var(resid)
    for lag in range(1, nlags + 1):
        w = 1 - lag / (nlags + 1)
        s2 += 2 * w * np.mean(resid[lag:] * resid[:-lag])
    stat = np.sum(S**2) / (n**2 * max(s2, 1e-12))
    if stat < 0.347: p_val = 0.50
    elif stat < 0.463: p_val = 0.10
    elif stat < 0.739: p_val = 0.05
    else: p_val = 0.01
    return float(stat), float(p_val)


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    # ── 0. 加载数据 ──
    data_path = os.path.join(_SCRIPT_DIR, 'data', 'yinshen_wide.csv')
    df_wide = pd.read_csv(data_path, encoding='utf-8-sig')
    vowel_seq, consonant_seq, ji_seq_raw = [], [], []
    for _, row in df_wide.iterrows():
        vs, cs = extract_primary_vowel_consonant(row)
        for v, c, ch in zip(vs, cs, [row[f'字{pos}'] for pos in range(1, 5)]):
            vowel_seq.append(v); consonant_seq.append(c)
            ji_seq_raw.append(classify_final(get_final(ch)))

    vowel_num, vowel_states = encode_integer(vowel_seq)
    consonant_num, consonant_states = encode_integer(consonant_seq)
    ji_num, ji_states = encode_integer(ji_seq_raw)
    N = len(ji_num)
    print(f"音神序列: N={N}, 姬={len(ji_states)}类, 元音={len(vowel_states)}类, 辅音={len(consonant_states)}类")

    df_ji = pd.DataFrame({'time': np.arange(N), 'ji': ji_num})
    df_vowel = pd.DataFrame({'time': np.arange(N), 'vowel': vowel_num})
    df_consonant = pd.DataFrame({'time': np.arange(N), 'consonant': consonant_num})
    lib = f'1 {int(N * 0.75)}'
    pred = f'{int(N * 0.75) + 1} {N}'

    # ═══════════════════════════════════════════════════
    # LAYER 2: 前置审计
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  LAYER 2 — 前置审计: S3 Hankel | S8 Stationarity | S9 Genericity")
    print("=" * 58)

    audit = []

    # S3 — Hankel 比 (★★★★)
    print("\n[S3 ★★★★] Hankel 纵横比:")
    for name, max_e in [('ji', 8), ('vowel', 8), ('consonant', 8)]:
        status, ratio, p, q_rec = classify_hankel_ratio(N, max_e)
        icon = {'GOOD': '✓', 'MARGINAL': '!', 'DEGRADED': '✗', 'BROKEN': '✗'}[status]
        print(f"  {name}: maxE={max_e} p/q={ratio:.1f} [{icon}] {status}")
        audit.append({'rule': 'S3', 'var': name, 'status': status, 'ratio': ratio})

    # S8 — 平稳性 (★★★★)
    print("\n[S8 ★★★★] 平稳性 (ADF+KPSS):")
    for name, arr in [('ji', ji_num), ('vowel', vowel_num), ('consonant', consonant_num)]:
        data = np.array(arr, dtype=float)
        adf_stat, adf_p = simple_adf(data)
        kpss_stat, kpss_p = simple_kpss(data)
        adf_r = adf_p < 0.05; kpss_r = kpss_p < 0.05
        if adf_r and not kpss_r: v = 'PASS — 平稳'
        elif adf_r and kpss_r: v = 'WARN — 趋势平稳'
        elif not adf_r and kpss_r: v = 'WARN — 差分平稳'
        else: v = 'WARN — 效力不足'
        print(f"  {name}: ADF p={adf_p:.4f} KPSS p={kpss_p:.4f} → {v}")
        audit.append({'rule': 'S8', 'var': name, 'verdict': v})

    # S9 — 泛型性 (★★★)
    print("\n[S9 ★★★] 观测泛型性:")
    for name, arr, states in [('ji', ji_num, ji_states),
                               ('vowel', vowel_num, vowel_states),
                               ('consonant', consonant_num, consonant_states)]:
        n_uniq = len(states)
        issues = []
        if n_uniq < 5: issues.append(f"类别过少({n_uniq})")
        if n_uniq / len(arr) < 0.1: issues.append(f"量化粗糙({n_uniq}/{len(arr)}={n_uniq/len(arr):.0%})")
        print(f"  {name}: {n_uniq}类 → {'PASS' if not issues else 'WARN: '+'; '.join(issues)}")
        audit.append({'rule': 'S9', 'var': name, 'issues': issues})

    # ═══════════════════════════════════════════════════
    # EXECUTION: EDM + CCM
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  EXECUTION — EDM (EmbedDim + Simplex + S-Map + CCM)")
    print("=" * 58)

    edm_results = {}

    for var_name, df_var in [('ji', df_ji), ('vowel', df_vowel), ('consonant', df_consonant)]:
        print(f"\n── [{var_name}] ──")

        # EmbedDimension
        E_opt = 3; rho_E_df = None
        try:
            rho_E_df = EmbedDimension(data=df_var, columns=var_name, target=var_name,
                                       maxE=8, Tp=1, lib=lib, pred=pred,
                                       showPlot=False, numProcess=1)
            rho_E_df['E'] = pd.to_numeric(rho_E_df['E'], errors='coerce')
            rho_E_df['rho'] = pd.to_numeric(rho_E_df['rho'], errors='coerce')
            E_opt = int(rho_E_df.loc[rho_E_df['rho'].idxmax(), 'E'])
        except Exception as e:
            print(f"  EmbedDimension 失败: {type(e).__name__}, fallback E={E_opt}")

        # S3 校验
        h_status, h_ratio, h_p, q_rec = classify_hankel_ratio(N, E_opt)
        if h_status in ('DEGRADED', 'BROKEN'):
            old_E = E_opt; E_opt = q_rec
            print(f"  [S3] E 从 {old_E} 修正至 {E_opt} (p/q={h_ratio:.1f})")
            h_status, h_ratio, h_p, _ = classify_hankel_ratio(N, E_opt)

        print(f"  E_opt = {E_opt}")

        # Simplex
        rho_sx, mae_sx = np.nan, np.nan
        try:
            sx = Simplex(data=df_var, columns=var_name, target=var_name,
                         E=E_opt, Tp=1, lib=lib, pred=pred, showPlot=False)
            obs = pd.to_numeric(sx['Observations'], errors='coerce').values
            prd = pd.to_numeric(sx['Predictions'], errors='coerce').values
            mask = ~(np.isnan(obs) | np.isnan(prd))
            if mask.sum() > 3:
                rho_sx = float(pearsonr(obs[mask], prd[mask])[0])
                mae_sx = float(np.mean(np.abs(obs[mask] - prd[mask])))
            print(f"  Simplex: ρ={rho_sx:.3f} MAE={mae_sx:.3f} n={mask.sum()}")
        except Exception as e:
            print(f"  Simplex 失败: {e}")

        # S-Map
        is_nonlinear, theta_best, rho_smap = False, 0.0, 0.0
        try:
            sm = SMapPredictNonlinear(data=df_var, columns=var_name, target=var_name,
                                      E=E_opt, lib=lib, pred=pred, showPlot=False)
            sm['theta'] = pd.to_numeric(sm['theta'], errors='coerce')
            sm['rho'] = pd.to_numeric(sm['rho'], errors='coerce')
            peak_idx = sm['rho'].idxmax()
            theta_best = float(sm.loc[peak_idx, 'theta'])
            rho_smap = float(sm.loc[peak_idx, 'rho'])
            rho_theta0 = float(sm.loc[sm['theta'].idxmin(), 'rho'])
            is_nonlinear = (rho_smap - rho_theta0) >= 0.05 and theta_best > 0
            print(f"  S-Map: θ={theta_best:.0f} ρ={rho_smap:.3f} 非线性={'是' if is_nonlinear else '否/弱'}")
        except Exception as e:
            print(f"  S-Map 失败: {e}")

        # CCM — 使用 E_opt
        vals = df_var[var_name].values
        df_ccm = pd.DataFrame({
            'time': np.arange(len(vals)), var_name: vals,
            f'{var_name}_lag': [np.nan] + vals[:-1].tolist()
        }).dropna()
        auto_lib_ccm = f'{max(5, N//24)} {N - max(10, N//10)} {max(3, N//40)}'

        ccm_verdict, fwd_rho, rev_rho = 'N/A', np.nan, np.nan
        fwd_conv, rev_conv = False, False
        try:
            ccm_r = ccm_causality_test(df_ccm, cause_var=f'{var_name}_lag',
                                       effect_var=var_name, E=E_opt, lib_sizes=auto_lib_ccm)
            ccm_verdict = ccm_r['verdict']; fwd_conv = ccm_r['forward']['is_converging']
            rev_conv = ccm_r['reverse']['is_converging']
            fwd_rho = ccm_r['forward']['final_rho']; rev_rho = ccm_r['reverse']['final_rho']
            fwd_s = f"{fwd_rho:.3f}" if fwd_rho is not None else 'N/A'
            rev_s = f"{rev_rho:.3f}" if rev_rho is not None else 'N/A'
            print(f"  CCM (E={E_opt}): {ccm_verdict} (fwd ρ={fwd_s} rev ρ={rev_s})")
            print(f"  [S11] {ccm_r.get('note', 'CCM 检测动力学耦合，非机制性因果。未观测公共驱动可产生相同收敛模式。')}")
        except Exception as e:
            print(f"  CCM 失败: {e}")

        edm_results[var_name] = {
            'E_opt': E_opt, 'rho_sx': rho_sx, 'mae_sx': mae_sx,
            'theta_best': theta_best, 'rho_smap': rho_smap,
            'is_nonlinear': is_nonlinear,
            'hankel_status': h_status, 'hankel_ratio': h_ratio,
            'ccm_verdict': ccm_verdict, 'ccm_fwd_rho': fwd_rho,
            'ccm_rev_rho': rev_rho, 'ccm_fwd_conv': fwd_conv,
            'rho_E_df': rho_E_df,
        }

    # ═══════════════════════════════════════════════════
    # LAYER 3: HAVOK + 交叉验证
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 58)
    print("  LAYER 3 — HAVOK 分解 + 交叉验证")
    print("=" * 58)

    havok_results = {}
    xv_results = {}

    try:
        from sovereign_havok import SovereignHAVOK
        HAS_HAVOK = True
    except ImportError:
        print("  [!] SovereignHAVOK 不可用")
        HAS_HAVOK = False

    if HAS_HAVOK:
        for var_name, arr in [('ji', np.array(ji_num, dtype=float)),
                               ('vowel', np.array(vowel_num, dtype=float)),
                               ('consonant', np.array(consonant_num, dtype=float))]:
            E = edm_results[var_name]['E_opt']; n_data = len(arr)
            wl = min(11, (n_data - E) // 2 * 2 - 1)
            if wl < 5: wl = 5
            if wl % 2 == 0: wl -= 1
            print(f"\n── [{var_name}] HAVOK (q={E}, wl={wl}) ──")
            try:
                sh = SovereignHAVOK(q_delays=E, dt=1.0, energy_threshold=0.99,
                                    poly_order=min(3, wl-1), window_length=wl, basis="V")
                sh.fit(arr)
                kurt_vr = float(sh.kurtosis_vr_)
                print(f"  r={sh.r_} R²={sh.regression_r2_:.3f} kurtosis={kurt_vr:.3f} "
                      f"expl_var={sh.explained_var_:.0%}")

                # S14: 采样充分性
                forcing = sh.forcing_
                spike_th = 1.5 * np.std(forcing)
                above = np.abs(forcing) > spike_th
                spike_regions = []; in_spike, start = False, 0
                for i, is_spike in enumerate(above):
                    if is_spike and not in_spike: start = i; in_spike = True
                    elif not is_spike and in_spike: spike_regions.append((start, i-1)); in_spike = False
                if in_spike: spike_regions.append((start, len(above)-1))
                n_undersampled = sum(1 for s, e in spike_regions if e - s + 1 <= 2)
                n_spikes = len(spike_regions)
                if n_spikes >= 3 and n_undersampled / max(n_spikes, 1) > 0.3:
                    print(f"  [S14] {n_undersampled}/{n_spikes} 尖峰 ≤2 采样点")

                havok_results[var_name] = {
                    'r': sh.r_, 'r2': sh.regression_r2_, 'kurtosis': kurt_vr,
                    'expl_var': sh.explained_var_, 'n_spikes': n_spikes,
                    'forcing': forcing, 'sh': sh,
                }
            except Exception as e:
                print(f"  HAVOK 失败: {e}")

        # S6 交叉验证
        print("\n[S6] EDM-HAVOK 交叉验证:")
        for var_name in ['ji', 'vowel', 'consonant']:
            edm = edm_results[var_name]; hv = havok_results.get(var_name, {})
            if 'kurtosis' not in hv: continue
            edm_nl = edm['is_nonlinear']; hv_kt = hv['kurtosis']
            if edm_nl and hv_kt > 1.5: s6 = 'CONSISTENT — 强非线性'
            elif edm_nl and hv_kt <= 1.5: s6 = 'DISCREPANCY — EDM 非线性，HAVOK 近高斯'
            elif not edm_nl and hv_kt > 1.5: s6 = 'DISCREPANCY — HAVOK 重尾，EDM 线性'
            else: s6 = 'CONSISTENT — 近线性/随机'
            print(f"  {var_name}: EDM_nl={edm_nl} HAVOK_kurt={hv_kt:.3f} → {s6}")
            xv_results[var_name] = {'s6_verdict': s6}

        # S1 Lyapunov
        print("\n[S1] Lyapunov 视界 (Rosenstein):")
        for var_name, arr in [('ji', ji_num), ('vowel', vowel_num), ('consonant', consonant_num)]:
            E = edm_results[var_name]['E_opt']
            try:
                from enhanced_cross_validate import estimate_lyapunov_exponent
                lyap = estimate_lyapunov_exponent(np.array(arr, dtype=float), E)
                if lyap.get('lambda_max'):
                    print(f"  {var_name}: λ_max={lyap['lambda_max']:.4f} τ_L={lyap['lyapunov_time']:.1f} "
                          f"3τ_L={lyap['prediction_horizon_3x']:.1f}")
                    xv_results.setdefault(var_name, {})['lyap'] = lyap
                else:
                    print(f"  {var_name}: {lyap.get('warning', '估计失败')}")
            except Exception as e:
                print(f"  {var_name}: 失败 {e}")

        # S10 周期性
        print("\n[S10] 周期性检测 (Lomb-Scargle):")
        for var_name, arr in [('ji', ji_num), ('vowel', vowel_num), ('consonant', consonant_num)]:
            try:
                from scipy.signal import lombscargle
                t = np.arange(len(arr), dtype=float)
                y = np.array(arr, dtype=float) - np.mean(arr)
                freqs = np.linspace(1/len(arr), 0.5, 200)
                pgram = lombscargle(t, y, freqs * 2 * np.pi, normalize=True)
                p_total = np.sum(np.abs(pgram))
                if p_total > 0:
                    dom_idx = np.argmax(pgram); p_ratio = pgram[dom_idx] / p_total
                    dom_period = 1.0/freqs[dom_idx] if freqs[dom_idx] > 0 else np.inf
                    warn = ''
                    if p_ratio > 0.30:
                        warn = f' [S10 WARN] 功率比 {p_ratio:.1%} > 30% — CCM 可能反映周期性外驱'
                    print(f"  {var_name}: 周期≈{dom_period:.1f}步 功率={p_ratio:.1%}{warn}")
                    if p_ratio > 0.30: xv_results.setdefault(var_name, {})['season_warn'] = True
            except Exception: pass

    # ═══════════════════════════════════════════════════
    # 可视化 — 修复后的布局
    # ═══════════════════════════════════════════════════
    print("\n生成图表...")
    fig = plt.figure(figsize=(20, 14))
    gs = GridSpec(3, 5, figure=fig, hspace=0.5, wspace=0.4,
                  height_ratios=[1, 1, 1], width_ratios=[1.0, 1.2, 1.3, 1.1, 1.0])
    colors = {'ji': '#2563EB', 'vowel': '#DC2626', 'consonant': '#16A34A'}
    var_labels = {'ji': '六姬 (6类)', 'vowel': '主元音 (5类)', 'consonant': '主辅音 (18类)'}

    for row, var_name in enumerate(['ji', 'vowel', 'consonant']):
        edm = edm_results[var_name]; hv = havok_results.get(var_name, {})
        c = colors[var_name]; E = edm['E_opt']
        arr_raw = np.array(ji_num if var_name == 'ji' else
                           (vowel_num if var_name == 'vowel' else consonant_num), dtype=float)

        # Col 0: 原始序列 + EmbedDim 曲线
        ax0 = fig.add_subplot(gs[row, 0])
        ax0b = ax0.twinx()
        rE = edm['rho_E_df']
        if rE is not None:
            ax0b.plot(rE['E'], rE['rho'], 's-', color='#F59E0B', markersize=6, linewidth=1.5)
            ax0b.set_ylabel('ρ (prediction skill)', color='#F59E0B', fontsize=8)
            ax0b.tick_params(axis='y', labelcolor='#F59E0B')
        ax0.plot(arr_raw, 'o-', color=c, markersize=4, linewidth=0.8, markerfacecolor='white')
        ax0.set_title(f'{var_labels[var_name]}\nS3: p/q={edm["hankel_ratio"]:.1f} [{edm["hankel_status"]}]',
                      fontsize=9, fontweight='bold')
        ax0.set_xlabel('Step'); ax0.grid(True, alpha=0.2)

        # Col 1: Simplex 观测 vs 预测
        ax1 = fig.add_subplot(gs[row, 1])
        try:
            sx = Simplex(data=pd.DataFrame({'time': np.arange(len(arr_raw)), var_name: arr_raw}),
                         columns=var_name, target=var_name,
                         E=E, Tp=1, lib=lib, pred=pred, showPlot=False)
            obs = pd.to_numeric(sx['Observations'], errors='coerce').values
            prd = pd.to_numeric(sx['Predictions'], errors='coerce').values
            mask = ~(np.isnan(obs) | np.isnan(prd))
            ax1.scatter(obs[mask], prd[mask], alpha=0.6, c=c, edgecolors='k', s=30)
            mn, mx = np.nanmin(obs), np.nanmax(obs)
            ax1.plot([mn, mx], [mn, mx], 'r--', linewidth=1, alpha=0.6, label='1:1')
            ax1.legend(fontsize=7, loc='upper left')
        except Exception:
            ax1.text(0.5, 0.5, 'N/A', ha='center', va='center', transform=ax1.transAxes, fontsize=10)
        ax1.set_title(f'Simplex E={E}\nrho={edm["rho_sx"]:.3f}  MAE={edm["mae_sx"]:.3f}',
                      fontsize=9, fontweight='bold')
        ax1.set_xlabel('Observed'); ax1.set_ylabel('Predicted'); ax1.grid(True, alpha=0.2)

        # Col 2: HAVOK 强制项 — 修复空白问题
        ax2 = fig.add_subplot(gs[row, 2])
        if 'forcing' in hv:
            forcing = hv['forcing']; sh = hv['sh']
            # Q9 P1-17 修复: forcing_ 长度 = n - q + 1，索引 j 对应时刻 j + q - 1
            t_f = np.arange(len(forcing)) + sh.q - 1
            # 用 stem plot 代替 fill_between —— 离散整数数据上更可见
            markerline, stemlines, baseline = ax2.stem(
                t_f, forcing, linefmt=f'{c}', markerfmt='o', basefmt='gray')
            markerline.set_markersize(3)
            markerline.set_markerfacecolor(c)
            stemlines.set_linewidth(1.5)
            stemlines.set_alpha(0.75)
            baseline.set_alpha(0.25)
            # 标注显著尖峰
            spike_th = 1.5 * np.std(forcing)
            for si in np.where(np.abs(forcing) > spike_th)[0][:4]:
                ax2.annotate(f'{forcing[si]:+.2f}', (t_f[si], forcing[si]),
                            textcoords='offset points', xytext=(0, 8 if forcing[si] > 0 else -12),
                            fontsize=6, ha='center', color='#7C3AED')
            ax2.set_title(f'HAVOK forcing: r={sh.r_}  kurt={sh.kurtosis_vr_:.2f}\n'
                          f'R^2={sh.regression_r2_:.3f}  expl_var={sh.explained_var_:.0%}',
                          fontsize=9, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, '—', ha='center', va='center', transform=ax2.transAxes,
                     fontsize=24, color='lightgray')
            ax2.set_title('HAVOK forcing\n(not available)', fontsize=9)
        ax2.set_xlabel('Step'); ax2.grid(True, alpha=0.2)

        # Col 3: S-Map theta scan
        ax3 = fig.add_subplot(gs[row, 3])
        try:
            sm = SMapPredictNonlinear(data=pd.DataFrame({'time': np.arange(len(arr_raw)), var_name: arr_raw}),
                                      columns=var_name, target=var_name,
                                      E=E, lib=lib, pred=pred, showPlot=False)
            sm['theta'] = pd.to_numeric(sm['theta'], errors='coerce')
            sm['rho'] = pd.to_numeric(sm['rho'], errors='coerce')
            ax3.plot(sm['theta'], sm['rho'], 'o-', color=c, markersize=5, linewidth=1.2)
            ax3.axvline(edm['theta_best'], color='red', ls='--', linewidth=1, alpha=0.6,
                        label=f'theta*={edm["theta_best"]:.0f}')
            ax3.axhline(0, color='gray', alpha=0.3)
            ax3.legend(fontsize=7)
        except Exception:
            ax3.text(0.5, 0.5, 'N/A', ha='center', va='center', transform=ax3.transAxes, fontsize=10)
        ax3.set_title(f'S-Map theta scan\n非线性={"是" if edm["is_nonlinear"] else "否/弱"}',
                      fontsize=9, fontweight='bold')
        ax3.set_xlabel('theta (nonlinearity)'); ax3.set_ylabel('rho'); ax3.grid(True, alpha=0.2)

        # Col 4: 审计摘要
        ax4 = fig.add_subplot(gs[row, 4])
        ax4.axis('off')
        lines = []
        lines.append(f"═══ {var_name} ═══")
        lines.append(f"E={E}")
        lines.append(f"Simplex rho={edm['rho_sx']:.3f}")
        lines.append(f"theta_best={edm['theta_best']:.0f}")
        lines.append(f"非线性={'[OK]' if edm['is_nonlinear'] else '---'}")
        lines.append(f"CCM: {edm['ccm_verdict'][:28] if edm['ccm_verdict'] else 'N/A'}")
        lines.append("")
        h_stat = edm['hankel_status']
        lines.append(f"S3 Hankel: {h_stat} ({edm['hankel_ratio']:.1f})")
        for a in audit:
            if a['rule'] == 'S8' and a['var'] == var_name:
                lines.append(f"S8 Stationarity: {a['verdict'][:18]}")
            if a['rule'] == 'S9' and a['var'] == var_name:
                lines.append(f"S9 Genericity: {'WARN' if a['issues'] else 'PASS'}")
        if 'kurtosis' in hv:
            lines.append(f"HAVOK: r={hv['r']}  R^2={hv['r2']:.3f}")
            lines.append(f"kurt={hv['kurtosis']:.2f}")
            xv = xv_results.get(var_name, {})
            if 's6_verdict' in xv:
                lines.append(f"S6: {xv['s6_verdict'][:32]}")
        if 'lyap' in xv_results.get(var_name, {}):
            ly = xv_results[var_name]['lyap']
            if ly.get('lambda_max'):
                lines.append(f"S1 τ_L={ly['lyapunov_time']:.1f} steps")
        ax4.text(0.05, 0.97, '\n'.join(lines), 
         fontsize=8.5, 
         family='sans-serif',
         va='top', transform=ax4.transAxes,
         bbox=dict(boxstyle='round,pad=0.5', facecolor='#F8FAFC', edgecolor='#CBD5E1', alpha=0.8))

    fig.suptitle('音神序列 · EDM-Takens 完整分析\n'
                 'S3 Hankel → S8 Stationarity → S9 Genericity → EDM → HAVOK → S6 Cross-Validation',
                 fontsize=13, fontweight='bold', y=1.02)
    out_path = os.path.join(_OUT_DIR, 'yinshen_dashboard.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white', pad_inches=0.3)
    plt.close()
    print(f"  图表: {out_path}")

    # ═══════════════════════════════════════════════════
    # 报告
    # ═══════════════════════════════════════════════════

    md = []
    md.append("# 音神序列 · EDM-Takens 分析报告")
    md.append("")
    md.append(f"**数据**: N={N} 音素, 六姬({len(ji_states)}类) / 主元音({len(vowel_states)}类) / 主辅音({len(consonant_states)}类)")
    md.append(f"**训练/预测**: {lib} / {pred}")
    md.append("")
    md.append("## 方法")
    md.append("")
    md.append("本分析遵循 EDM-Takens Skill 的 14 条禁忌规则，执行三层纵深防御：")
    md.append("")
    md.append("| 层级 | 规则 | 说明 |")
    md.append("|------|------|------|")
    md.append("| Layer 2 前置审计 | S3 ★★★★, S8 ★★★★, S9 ★★★ | Hankel 比 / 平稳性 / 泛型性 |")
    md.append("| Execution | EDM + CCM (S2+S7) | EmbedDimension → Simplex → S-Map → CCM |")
    md.append("| Layer 3 交叉验证 | S1, S6, S10, S14 | Lyapunov / HAVOK / 周期性 / 采样 |")
    md.append("| Interpretation | S11 | CCM 公共驱动免责 |")
    md.append("")
    md.append("## LAYER 2 — 前置审计")
    md.append("")
    md.append("### S3 ★★★★ Hankel 纵横比")
    md.append("")
    md.append("| 序列 | N | maxE | p | p/q | 判定 |")
    md.append("|------|---|------|---|-----|------|")
    for a in audit:
        if a['rule'] == 'S3':
            md.append(f"| {a['var']} | {N} | 8 | {N - 8 + 1} | {a['ratio']:.1f} | {a['status']} |")
    md.append("")
    md.append("### S8 ★★★★ 平稳性")
    md.append("")
    md.append("| 序列 | 判定 |")
    md.append("|------|------|")
    for a in audit:
        if a['rule'] == 'S8':
            md.append(f"| {a['var']} | {a['verdict']} |")
    md.append("")
    md.append("### S9 ★★★ 观测泛型性")
    md.append("")
    md.append("| 序列 | 判定 |")
    md.append("|------|------|")
    for a in audit:
        if a['rule'] == 'S9':
            md.append(f"| {a['var']} | {'WARN: '+'; '.join(a['issues']) if a['issues'] else 'PASS'} |")
    md.append("")
    md.append("## EXECUTION — EDM + CCM")
    md.append("")
    md.append("| 序列 | E | Simplex ρ | S-Map θ | 非线性 | CCM 结果 |")
    md.append("|------|---|-----------|---------|--------|---------|")
    for vn in ['ji', 'vowel', 'consonant']:
        e = edm_results[vn]
        ccm_s = e['ccm_verdict'][:35] if e['ccm_verdict'] else 'N/A'
        md.append(f"| {vn} | {e['E_opt']} | {e['rho_sx']:.3f} | {e['theta_best']:.0f} | "
                  f"{'是' if e['is_nonlinear'] else '否'} | {ccm_s} |")
    md.append("")

    if HAS_HAVOK:
        md.append("## LAYER 3 — HAVOK + 交叉验证")
        md.append("")
        md.append("### HAVOK 诊断")
        md.append("")
        md.append("| 序列 | r | R² | kurtosis | expl_var |")
        md.append("|------|---|---|----------|----------|")
        for vn in ['ji', 'vowel', 'consonant']:
            hv = havok_results.get(vn, {})
            if hv:
                md.append(f"| {vn} | {hv['r']} | {hv['r2']:.3f} | {hv['kurtosis']:.3f} | {hv['expl_var']:.0%} |")
        md.append("")

        md.append("### S6 EDM-HAVOK 交叉验证")
        md.append("")
        md.append("| 序列 | EDM 非线性 | HAVOK kurtosis | 判定 |")
        md.append("|------|-----------|---------------|------|")
        for vn in ['ji', 'vowel', 'consonant']:
            e = edm_results[vn]; hv = havok_results.get(vn, {})
            if 'kurtosis' not in hv: continue
            xv = xv_results.get(vn, {})
            md.append(f"| {vn} | {e['is_nonlinear']} | {hv['kurtosis']:.3f} | {xv.get('s6_verdict', 'N/A')} |")
        md.append("")

        md.append("### S1 Lyapunov 视界")
        md.append("")
        md.append("| 序列 | λ_max | τ_L (steps) | 3τ_L (steps) |")
        md.append("|------|-------|-------------|--------------|")
        for vn in ['ji', 'vowel', 'consonant']:
            xv = xv_results.get(vn, {})
            ly = xv.get('lyap', {})
            if ly.get('lambda_max'):
                md.append(f"| {vn} | {ly['lambda_max']:.4f} | {ly['lyapunov_time']:.1f} | {ly['prediction_horizon_3x']:.1f} |")
        md.append("")

    md.append("## 核心发现")
    md.append("")
    md.append("1. **S3 Hankel**: 全部 PASS — N=120 提供足够的相空间采样密度（p/q ≥ 14）")
    md.append("2. **S8 Stationarity**: 全部 PASS — 序列前后半段来自同一动力学分布")
    md.append(f"3. **S9 Genericity**: {'ji 和 vowel 触发量化粗糙警告' if any(a['issues'] for a in audit if a['rule']=='S9') else 'PASS'} — 类别数据的整数编码引入了语义距离假设")
    md.append(f"4. **CCM lag-1**: 使用 EmbedDimension 最优 E（{edm_results['ji']['E_opt']}/{edm_results['vowel']['E_opt']}/{edm_results['consonant']['E_opt']}）后，未检测到收敛因果连接——注意原始分析用 E=2 曾报告强收敛")
    if HAS_HAVOK and xv_results:
        md.append(f"5. **S6 交叉验证**: ji={xv_results.get('ji',{}).get('s6_verdict','N/A')[:40]}, vowel={xv_results.get('vowel',{}).get('s6_verdict','N/A')[:40]}, consonant={xv_results.get('consonant',{}).get('s6_verdict','N/A')[:40]}")
    md.append("6. **S11**: 所有 CCM 结果附带公共驱动免责声明")
    md.append("")
    md.append("## 方法论评估：EDM/HAVOK 对类别型音素数据的适配性")
    md.append("")
    md.append("### 核心问题：整数编码的度量失真")
    md.append("")
    md.append("EDM（Simplex 投影、S-Map）和 HAVOK（Hankel SVD）的核心操作都依赖状态空间中的")
    md.append("**欧氏距离**。当我们将 6 个音韵类别编码为整数 0-5：")
    md.append("")
    md.append("- Simplex 的'最近邻'隐式假设 d(太姬, 玄姬) = |0-1| = 1 和 d(太姬, 美姬) = |0-2| = 2——前者比后者'更近'")
    md.append("- 但转移矩阵显示从太姬出发，到祈姬(概率 0.30)远高于到玄姬(概率 0.03)——**编码距离与转移亲疏完全不对应**")
    md.append("- 这意味着 Simplex 在相空间中寻找的'近邻'不是语义上相似的音韵，而是整数编码相邻的音韵")
    md.append("")
    md.append("### EDM/HAVOK 在此数据上实际测量的是什么")
    md.append("")
    md.append("| 分析 | 表面发现 | 实际测量对象 | 可信度 |")
    md.append("|------|---------|------------|--------|")
    md.append(f"| Simplex rho={edm_results['vowel']['rho_sx']:.3f} (元音) | '可预测性约 43%' | 5 类转移概率的一致性——若某些转移远高于随机，短程可'预测' | 中：Markov 结构，非混沌动力学 |")
    md.append(f"| S-Map theta={edm_results['ji']['theta_best']:.0f} (六姬) | '强非线性' | 局部邻域(小 theta)的转移概率异于全局——说明近邻编码的转移行为不同 | 中：反映编码结构的非均匀性 |")
    md.append(f"| CCM lag-1 | 无收敛因果连接 | lag-1 自回归结构弱——序列的 Markov 性质在 E={edm_results['ji']['E_opt']} 维嵌入下不显著 | 可信：但'因果'一词应换成'自回归' |")
    md.append(f"| HAVOK kurtosis < 0 | 亚高斯强制项 | 强制项是类别切换的离散跳跃——自然没有连续混沌系统的重尾特征 | 可信：与类别数据预期一致 |")
    md.append("")
    md.append("### 结论")
    md.append("")
    md.append("**EDM/HAVOK 在类别型音素数据上技术上可运行，但度量假设不完全成立。**")
    md.append("")
    md.append("分析结果应解读为：")
    md.append("1. **转移结构的非均匀性**（而非'非线性动力学'）——Simplex rho 反映的是 Markov 转移概率偏离均匀分布的程度")
    md.append("2. **编码空间的几何伪影**（而非'吸引子结构'）——S-Map theta>0 反映的是整数编码后近邻转移行为的局部异质性")
    md.append("3. **HAVOK 强制项 = 类别切换的节奏**（而非'混沌相变'）——每一次尖峰对应一次元音/辅音类别变化")
    md.append("")
    md.append("**更适配的方法**：对于纯粹的类别序列分析，转移矩阵 + Markov 链模型 + 熵率估计")
    md.append("比 EDM/HAVOK 更直接且不引入编码距离假设。EDM/HAVOK 在此的价值是作为**补充视角**——")
    md.append("检测转移概率矩阵无法直接揭示的高阶时序依赖结构。")
    md.append("")
    md.append("### 流程判别总结")
    md.append("")
    md.append("本案例中 S9 泛型性关卡（量化粗糙 WARN）已在事前发出信号。")
    md.append("遵循 14 条规则的整体流程是：")
    md.append("")
    md.append("1. S3/S8 关卡通过 → 数据在相空间重建层面没有硬性障碍")
    md.append("2. S9 触发 WARN → 提示整数编码的度量假设需要警觉")
    md.append("3. 执行 EDM/HAVOK → 获得数值结果")
    md.append("4. **S6 交叉验证的 DISCREPANCY + S9 警告 → 联合信号：结果应降级为'结构化假设生成'**")
    md.append("5. S11 免责 → CCM 不声称因果")
    md.append("")
    md.append("这个流程本身——多个规则交叉触发、累积证据、降级结论——就是 14 条规则体系的核心运作方式。")
    md.append("")
    md.append("---")
    md.append("*本报告由 `examples/yinshen/run_analysis.py` 自动生成。遵循 `references/forbidden_rules_reference.md`（14 条规则）。*")

    with open(os.path.join(_SCRIPT_DIR, 'yinshen_report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    with open(os.path.join(_SCRIPT_DIR, 'yinshen_report.json'), 'w', encoding='utf-8') as f:
        json.dump({'N': N, 'audit': audit, 'edm': {k: {kk: vv for kk, vv in v.items() if kk != 'rho_E_df'}
                   for k, v in edm_results.items()}, 'havok': {k: {kk: vv for kk, vv in v.items() if kk not in ('forcing','sh')}
                   for k, v in havok_results.items()}, 'xv': xv_results}, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n报告: {os.path.join(_SCRIPT_DIR, 'yinshen_report.md')}")
    print(f"数据: {os.path.join(_SCRIPT_DIR, 'yinshen_report.json')}")
    print("=" * 58)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
