"""
音神韵母动力学分析 v3 — 基于 EDM-Takens Skill 完整基础设施
==============================================================
升级 v2: 引入审计防火墙、Surrogate 显著性检验、CCM 因果推断、
        FNN E 选择、配置工件。标签: EXPLORATORY（研究规范原则 7）

方法栈:
  L0: environment_check 环境验证
  L1: edm_auditor 配置审计 (Secret 1/3)
  L2: SovereignHAVOK + IAAFT surrogate 显著性检验
  L3: CCM 韵母间因果关系 (ccm_with_convergence)
  L4: 转移概率矩阵 (经典)
  L5: sensitivity_config 配置工件自动保存
"""
import os, sys, warnings, time
os.environ['MPLBACKEND'] = 'Agg'
os.environ['OMP_NUM_THREADS'] = '1'

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SKILL_SRC = os.path.join(_ROOT, '.skills', 'edm-takens', 'src')
sys.path.insert(0, _SKILL_SRC)

import numpy as np
from collections import Counter, defaultdict

warnings.filterwarnings('ignore')

# ═════════════════════════════════════════════════════════════
# Windows multiprocessing.spawn guard — prevents re-execution
# in pyEDM worker subprocesses (see pipeline.py L89 for context)
# ═════════════════════════════════════════════════════════════
if __name__ != '__main__':
    sys.exit(0)  # silently exit on subprocess re-import (spawn mode)

# ── L0: Environment ────────────────────────────────────────
from environment_check import validate_environment
env = validate_environment(os.path.dirname(_SKILL_SRC))
assert env.ready, f"Environment not ready:\n{env.summary()}"
print(env.summary())

# ── L1: Import skill infrastructure ────────────────────────
from _edm_bridge import (false_nearest_neighbors,
                          multiview_full,
                          EmbedDimension, Simplex, SMapPredictNonlinear, CCM,
                          EDM_AVAILABLE, EDM_BACKEND)
from sovereign_havok import SovereignHAVOK
from edm_auditor import audit_pipeline, classify_hankel_ratio
from surrogate_test import iaaft_surrogates, surrogate_significance_test
from final_interpretation import ccm_with_convergence, estimate_lyapunov_robust
from sensitivity_config import capture_config, save_config
from _paths import data_path
print(f"EDM backend: {EDM_BACKEND}")


# ═════════════════════════════════════════════════════════════
# Data: character → pinyin → rhyme extraction
# ═════════════════════════════════════════════════════════════

CHAR_PINYIN = {
    '提':'ti','米':'mi','丹':'dan','婆':'po','比':'bi','利':'li',
    '坎':'kan','阔':'kuo','诶':'ei','爱':'ai','巴':'ba','德':'de',
    '邸':'di','鹭':'lu','遮':'zhe','鲁':'lu','喜':'xi','凯':'kai',
    '芙':'fu','塔':'ta','希':'xi','詹':'zhan','摩':'mo','苦':'ku',
    '库':'ku','察':'cha','奥':'ao','托':'tuo','勒':'le','修':'xiu',
    '尔':'er','达':'da','密':'mi','梵':'fan','阿':'a','佰':'bai',
    '斯':'si','窟':'ku','差':'cha','钵':'bo','由':'you','维':'wei',
    '伦':'lun','特':'te','喇':'la','沃':'wo','几':'ji','札':'zha',
    '弘':'hong','仆':'pu','格':'ge','姆':'mu','林':'lin','吽':'hong',
    '卜':'bu','哈':'ha','罗':'luo','陀':'tuo','吡':'bi','盎':'ang',
}

def extract_rhyme(pinyin):
    initials = ['zh','ch','sh','z','c','s','b','p','m','f','d','t',
                'n','l','g','k','h','j','q','x','r','y','w']
    for init in initials:
        if pinyin.startswith(init):
            return pinyin[len(init):]
    return pinyin

lines = [
    "提米丹婆，比利坎阔，诶爱巴德",
    "邸鹭遮鲁，比喜丹摩，比凯芙塔",
    "希米詹摩，苦利库察，奥托巴勒",
    "修尔比达，比密梵托，阿利佰斯",
    "邸窟差钵，奥由维塔，库伦米特",
    "爱米巴喇，邸由巴沃，库利几札",
    "弘达芙邸，爱伦爱仆，格伦巴德",
    "修姆邸仆，格林札德，吽托梵卜",
    "希利札哈，米尔特林，几仆几仆",
    "提罗梵陀，吡罗梵陀，盎罗梵德",
]

all_rhymes = []
all_chars = []
for line in lines:
    chars = list(line.replace('，','').replace(',',''))
    pinyins = [CHAR_PINYIN.get(c, '?') for c in chars]
    rhymes = [extract_rhyme(p) for p in pinyins]
    all_chars.append(chars)
    all_rhymes.append(rhymes)

flat_rhymes = [r for t in range(10) for r in all_rhymes[t]]
freq = Counter(flat_rhymes)
unique_rhymes = sorted(set(flat_rhymes) - {'?'})

# ── Vowel categories (音神) ──
VOWEL_CATS = {
    '太姬': {'a','an','ai','ang','ian','uan','iang','eng'},
    '玄姬': {'ao','ou','iao','iou'},
    '美姬': {'i','in','ing','ia','ie','iu','ian','iang','iong'},
    '希姬': {'e','ei','en','er','eng'},
    '祈姬': {'u','uo','ui','un','ong','uai','uan','uang'},
    '妙姬': {'o','ong','uai'},
}
def rhyme_to_cat(r):
    for name, vowels in VOWEL_CATS.items():
        if r in vowels:
            return name
    return '?'

cat_counts = defaultdict(int)
for r in flat_rhymes:
    cat_counts[rhyme_to_cat(r)] += 1
n_total = len(flat_rhymes)

print("=" * 70)
print("  音神韵母动力学分析 v3 (EDM-Takens Skill 完整栈)")
print(f"  数据: {len(lines)} 时刻 × {len(all_rhymes[0])} 字符 = {n_total} 韵母")
print(f"  标签: EXPLORATORY  |  EDM后端: {EDM_BACKEND}")
print("=" * 70)

# ── 韵母分布 ──
print(f"\n{'═'*60}\n  韵母分布\n{'═'*60}")
print(f'  {n_total} 韵母，{len(unique_rhymes)} 种类型')
for r, n in freq.most_common(15):
    print(f'    {r:>5}: {n:3d} ({n/n_total:5.1%})  [{rhyme_to_cat(r)}]')

# ── 音神层级分布 ──
print(f"\n{'═'*60}\n  音神层级分布\n{'═'*60}")
for name in ['美姬','祈姬','太姬','希姬','妙姬','玄姬']:
    pct = cat_counts.get(name, 0) / n_total * 100
    bars = '█' * int(pct/2)
    print(f'    {name:4s}: {cat_counts.get(name, 0):3d} ({pct:5.1f}%) {bars}')


# ═════════════════════════════════════════════════════════════
# Phase A: HAVOK dynamics + IAAFT surrogate significance
# ═════════════════════════════════════════════════════════════

print(f"\n{'═'*60}\n  Phase A: HAVOK 动力学 + IAAFT Surrogate 显著性\n{'═'*60}")

n_points = len(flat_rhymes)  # 120
havok_results = {}

for rhyme in unique_rhymes:
    data = np.array([r == rhyme for r in flat_rhymes], dtype=float)
    if np.std(data) < 0.01:
        havok_results[rhyme] = {'note': f'constant ({int(data[0])})'}
        continue

    # FNN for optimal E (P8)
    fnn = false_nearest_neighbors(data, max_E=min(8, max(2, len(data)//8)))
    E_fnn = fnn['optimal_E']

    # Auditor pre-check (Secret 3: Hankel)
    hk_status, hk_ratio, p, q_rec = classify_hankel_ratio(len(data), E_fnn)
    if hk_status == 'BROKEN':
        E_opt = q_rec
    else:
        E_opt = E_fnn if hk_status == 'GOOD' else min(E_fnn, q_rec)

    audit = audit_pipeline(n=len(data), E=E_opt, columns=['x'], is_binary=True)
    if audit.verdict == 'FAIL':
        # try smaller E
        E_opt = max(2, E_opt // 2)
        audit = audit_pipeline(n=len(data), E=E_opt, columns=['x'], is_binary=True)

    # HAVOK fit
    wl = min(11, max(5, (len(data)-E_opt)//4))
    if wl % 2 == 0: wl -= 1
    try:
        sh = SovereignHAVOK(q_delays=E_opt, window_length=wl, poly_order=2, basis="V")
        sh.fit(data)
    except Exception as e:
        havok_results[rhyme] = {'note': f'HAVOK fit failed: {type(e).__name__}'}
        continue
    k = sh.kurtosis_vr_
    max_ev_d = float(np.max(np.abs(sh.eigenvalues_d_))) if len(sh.eigenvalues_d_) else 0

    # IAAFT surrogate significance test (Secret 3 / research-rigor #2)
    try:
        surrogates = iaaft_surrogates(data, n_surrogates=99, seed=42)
        def kurt_metric(d):
            sh_s = SovereignHAVOK(q_delays=E_opt, window_length=wl,
                                   poly_order=2, basis="V"); sh_s.fit(d)
            return sh_s.kurtosis_vr_
        surr_test = surrogate_significance_test(data, surrogates, kurt_metric, tail='upper')
        k_sig = surr_test['significant']
        k_pval = surr_test['p_value']
        k_surr_p95 = surr_test['surrogate_95th']
    except Exception:
        k_sig = None; k_pval = None; k_surr_p95 = None

    # Classification
    if k > 3.0:   k_type = "extreme intermittent"
    elif k > 1.5: k_type = "heavy-tailed"
    elif k > 0.5: k_type = "light-tailed"
    elif k > -0.5: k_type = "near-Gaussian"
    else:          k_type = "sub-Gaussian"

    sig_mark = " *SIG*" if k_sig else (" ns" if k_sig is False else " ?")

    print(f'  {rhyme:>5}: freq={freq[rhyme]:3d} r={sh.r_} kurt={k:+6.2f} ({k_type})'
          f' | eig_d|={max_ev_d:.3f} p/q={hk_ratio:.1f} [{hk_status}]'
          f'{sig_mark} p={k_pval if k_pval else "?"}')

    havok_results[rhyme] = {
        'E': E_opt, 'r': sh.r_, 'kurtosis': k, 'kurt_type': k_type,
        'max_eig_d': max_ev_d, 'hk_ratio': hk_ratio, 'hk_status': hk_status,
        'surr_sig': k_sig, 'surr_pval': k_pval, 'surr_p95': k_surr_p95,
        'freq': freq[rhyme], 'is_binary': True,
        'sh': sh,
    }


# ═════════════════════════════════════════════════════════════
# Phase B: CCM causality between rhyme occurrence sequences
# ═════════════════════════════════════════════════════════════

print(f"\n{'═'*60}\n  Phase B: CCM 韵母因果关系 (Victim Mirror)\n{'═'*60}")

# Build a DataFrame with binary rhyme columns
import pandas as pd
ccm_df = pd.DataFrame({'t': np.arange(n_points)})
for r in unique_rhymes:
    ccm_df[r] = [1 if x == r else 0 for x in flat_rhymes]

# Test high-frequency rhyme pairs (top ~6)
top_for_ccm = [r for r, _ in freq.most_common(6) if r in havok_results and
               'note' not in havok_results[r]]
ccm_pairs = []
for i in range(len(top_for_ccm)):
    for j in range(i+1, len(top_for_ccm)):
        ccm_pairs.append((top_for_ccm[i], top_for_ccm[j]))

ccm_results = {}
for cause, effect in ccm_pairs:
    if EDM_AVAILABLE:
        E_ref = havok_results.get(effect, {}).get('E', 3)
        try:
            ccm = ccm_with_convergence(ccm_df, cause, effect, E_ref)
            ccm_results[f'{cause}->{effect}'] = ccm
            if 'No' not in ccm['verdict'] and 'Weak' not in ccm['verdict']:
                print(f'    {cause:>5} -> {effect:5}: {ccm["verdict"]}')
        except Exception:
            pass

# ═════════════════════════════════════════════════════════════
# Phase C: Transition probabilities (classic)
# ═════════════════════════════════════════════════════════════

print(f"\n{'═'*60}\n  Phase C: 转移概率矩阵\n{'═'*60}")
transitions = {}
for i in range(len(flat_rhymes)-1):
    a, b = flat_rhymes[i], flat_rhymes[i+1]
    transitions.setdefault(a, Counter())[b] += 1

for r in sorted(unique_rhymes):
    total = sum(transitions.get(r, {}).values())
    if total < 2: continue
    targets = transitions[r].most_common(3)
    probs = [(t, c/total) for t, c in targets]
    print(f'  {r:>5} -> {", ".join(f"{t}({p:.0%})" for t,p in probs)}')


# ═════════════════════════════════════════════════════════════
# Phase D: Integrated dynamical interpretation
# ═════════════════════════════════════════════════════════════

print(f"\n{'═'*60}\n  Phase D: 综合动力学解读\n{'═'*60}")

# Classify rhyme roles by kurtosis + frequency + CCM
basal = []; event = []; marker = []
for r, d in havok_results.items():
    if 'note' in d: continue
    k = d['kurtosis']
    if k < 1.0 and d['freq'] >= 10:
        basal.append((r, d))
    elif k > 3.0:
        marker.append((r, d))
    elif k > 1.0:
        event.append((r, d))

basal.sort(key=lambda x: -x[1]['freq'])
marker.sort(key=lambda x: -x[1]['kurtosis'])
event.sort(key=lambda x: -x[1]['kurtosis'])

print(f"\n  Layer I — 基底层 (高斯/亚高斯 + 高频):")
for r, d in basal:
    sig = " *SIG*" if d.get('surr_sig') else ""
    print(f'    {r:>5}: kurt={d["kurtosis"]:+6.2f} freq={d["freq"]}{sig}  [{rhyme_to_cat(r)}]')

print(f"\n  Layer II — 事件层 (中度间歇性):")
for r, d in event:
    sig = " *SIG*" if d.get('surr_sig') else ""
    print(f'    {r:>5}: kurt={d["kurtosis"]:+6.2f} freq={d["freq"]}{sig}  [{rhyme_to_cat(r)}]')

print(f"\n  Layer III — 标记层 (极端间歇性爆发):")
for r, d in marker:
    sig = " *SIG*" if d.get('surr_sig') else ""
    print(f'    {r:>5}: kurt={d["kurtosis"]:+6.2f} freq={d["freq"]}{sig}  [{rhyme_to_cat(r)}]')

# CCM highlights
print(f"\n  因果关系 (CCM):")
for key, ccm in ccm_results.items():
    if 'No' not in ccm['verdict'] and 'Weak' not in ccm['verdict']:
        fwd = ccm['forward']
        rev = ccm['reverse']
        print(f"    {key}: fwd_rho={fwd['final_rho']:.3f} (rise={fwd.get('total_rise',0):+.4f}) "
              f"rev_rho={rev['final_rho']:.3f} -> {ccm['verdict']}")

print(f"\n  假设 (待更大样本验证):")
if basal:
    top_basal = basal[0][0]
    print(f"  1. 基底音 '{top_basal}' 构成文本的连续背景流。")
if marker:
    top_marker = marker[0][0]
    print(f"  2. 标记音 '{top_marker}' (k={marker[0][1]['kurtosis']:.1f}) 是韵律终止/转折信号。")
print(f"  3. 韵母转移概率构成的邻接图反映了文本的韵律语法。")
print(f"  4. Surrogate 检验区分了真非线性爆发 vs 随机波动导致的重尾。")
print(f"  5. 以上均为探索性假设 (N=120)，需更大文本样本验证或证伪。")


# ═════════════════════════════════════════════════════════════
# Phase E: Config artifact (reproducibility)
# ═════════════════════════════════════════════════════════════
os.makedirs('results', exist_ok=True)
try:
    flat_arr = np.array([hash(r) % 100 for r in flat_rhymes], dtype=float)
    cfg = capture_config(flat_arr, E=3, analysis_type='exploratory',
                         notes='phonon_v3: rhyme dynamics analysis',
                         target_col='rhyme_hash', columns=['rhyme_hash'])
    cfg_path = save_config(cfg, f'results/phonon_v3_config_{int(time.time())}.json')
    print(f"\n  Config saved: {cfg_path}")
except Exception as e:
    print(f"\n  Config save skipped: {e}")

print(f"\n{'='*60}\n  v3 analysis complete.\n{'='*60}")
