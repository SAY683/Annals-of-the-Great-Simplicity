"""
音神序列 —— 使用新版 edm-takens skill 的 EDM 算法
------------------------------------------
应用 skill 的 _edm_bridge 提供：
- EmbedDimension（寻找最优嵌入维 E）
- Simplex（预测）
- SMapPredictNonlinear / PredictNonlinear（非线性检测）
- CCM（收敛性交叉映射）

输入：outputs/data/yinshen_wide.csv
输出：outputs/reports/yinshen_edm_report.{md,json}
      outputs/figures/yinshen_edm_*.png
"""

import sys
sys.path.insert(0, '.skills/edm-takens/src')

import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import pearsonr
from collections import Counter
from pypinyin import pinyin, Style

from _edm_bridge import EmbedDimension, Simplex, SMapPredictNonlinear
from ccm_causality import ccm_causality_test

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun']
plt.rcParams['axes.unicode_minus'] = False


# ---------------- 六姬分类 ----------------
JI_VOWELS = {
    'tai':   ['a', 'ā', 'an'],
    'xuan':  ['ao', 'ou'],
    'mei':   ['i', 'ī', 'ia'],
    'xi':    ['e', 'ei'],
    'qi':    ['u', 'ū', 'uo'],
    'miao':  ['o', 'ō'],
}
JI_NAME = {
    'tai': '太姬', 'xuan': '玄姬', 'mei': '美姬',
    'xi': '希姬', 'qi': '祈姬', 'miao': '妙姬',
}
JI_ORDER = ['tai', 'xuan', 'mei', 'xi', 'qi', 'miao']
FINAL_TO_JI = {f: ji for ji, finals in JI_VOWELS.items() for f in finals}
FIRST_VOWEL_TO_JI = {'a': 'tai', 'o': 'miao', 'e': 'xi', 'i': 'mei', 'u': 'qi', 'ü': 'qi'}


def classify_final(final):
    if not final or pd.isna(final):
        return 'unclassified'
    final = final.strip().lower()
    if final in FINAL_TO_JI:
        return FINAL_TO_JI[final]
    return FIRST_VOWEL_TO_JI.get(final[0], 'unclassified')


def get_final(char):
    try:
        return pinyin(char, style=Style.FINALS, strict=False)[0][0]
    except Exception:
        return ''


def encode_integer(series):
    states = sorted(set(series))
    mapping = {s: i for i, s in enumerate(states)}
    return [mapping[s] for s in series], mapping


def extract_primary_vowel_consonant(row):
    vowels = []
    consonants = []
    for pos in range(1, 5):
        v_slots = [row[f'字{pos}_元音{i}'] for i in range(1, 3) if pd.notna(row[f'字{pos}_元音{i}']) and row[f'字{pos}_元音{i}'] != '']
        c_slots = [row[f'字{pos}_辅音{i}'] for i in range(1, 3) if pd.notna(row[f'字{pos}_辅音{i}'])]
        vowels.append(v_slots[0] if v_slots else None)
        consonants.append(c_slots[0] if c_slots else None)
    return vowels, consonants


# ---------------- EDM 子函数 ----------------
def run_edm_pipeline(df, var, lib='1 90', pred='91 120', maxE=8):
    """对单一变量 DataFrame 跑 EmbedDimension + Simplex + SMapPredictNonlinear"""
    result = {'var': var}

    # 1. EmbedDimension
    try:
        ed = EmbedDimension(data=df, columns=var, target=var, maxE=maxE, Tp=1,
                            lib=lib, pred=pred, showPlot=False)
        ed['E'] = pd.to_numeric(ed['E'], errors='coerce')
        ed['rho'] = pd.to_numeric(ed['rho'], errors='coerce')
        opt_E = int(ed.loc[ed['rho'].idxmax(), 'E'])
        result['embed_dim'] = {'opt_E': opt_E, 'rho_curve': ed[['E', 'rho']].dropna().to_dict(orient='records')}
    except Exception as e:
        result['embed_dim'] = {'error': str(e)}
        opt_E = 2

    # 2. Simplex
    try:
        sx = Simplex(data=df, columns=var, target=var, E=opt_E, Tp=1,
                     lib=lib, pred=pred, showPlot=False)
        obs = pd.to_numeric(sx['Observations'], errors='coerce').values
        prd = pd.to_numeric(sx['Predictions'], errors='coerce').values
        mask = ~(np.isnan(obs) | np.isnan(prd))
        if mask.sum() > 3:
            rho, _ = pearsonr(obs[mask], prd[mask])
            mae = np.mean(np.abs(obs[mask] - prd[mask]))
        else:
            rho = np.nan
            mae = np.nan
        result['simplex'] = {
            'E': opt_E,
            'rho': float(rho),
            'mae': float(mae),
            'n': int(mask.sum()),
            'predictions': pd.DataFrame({'Observations': obs, 'Predictions': prd}).to_dict(orient='records')
        }
    except Exception as e:
        result['simplex'] = {'error': str(e)}

    # 3. SMap / PredictNonlinear
    try:
        sm = SMapPredictNonlinear(data=df, columns=var, target=var, E=opt_E,
                                  lib=lib, pred=pred, showPlot=False)
        sm['theta'] = pd.to_numeric(sm['theta'], errors='coerce')
        sm['rho'] = pd.to_numeric(sm['rho'], errors='coerce')
        peak_idx = sm['rho'].idxmax()
        peak_theta = float(sm.loc[peak_idx, 'theta'])
        peak_rho = float(sm.loc[peak_idx, 'rho'])
        # 非线性判据：rho 随 theta 上升，且峰值在 theta>1
        nonlinear = peak_theta > 1 and peak_rho > 0.2
        result['smap'] = {
            'peak_theta': peak_theta,
            'peak_rho': peak_rho,
            'nonlinear': nonlinear,
            'theta_rho': sm[['theta', 'rho']].dropna().to_dict(orient='records')
        }
    except Exception as e:
        result['smap'] = {'error': str(e)}

    # 4. CCM lag-1 自预测
    try:
        vals = df[var].values
        df_ccm = pd.DataFrame({
            'time': np.arange(len(vals)),
            var: vals,
            f'{var}_lag': [np.nan] + vals[:-1].tolist()
        }).dropna()
        r = ccm_causality_test(df_ccm, cause_var=f'{var}_lag', effect_var=var, E=2,
                               lib_sizes='5 100 3')
        result['ccm'] = {
            'verdict': r['verdict'],
            'forward_rho': r['forward']['final_rho'],
            'forward_converging': r['forward']['is_converging'],
            'reverse_rho': r['reverse']['final_rho'],
            'reverse_converging': r['reverse']['is_converging'],
        }
    except Exception as e:
        result['ccm'] = {'error': str(e)}

    return result


# ---------------- 可视化 ----------------
def plot_edm(result, out_prefix):
    var = result['var']
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    # E vs rho
    ax = axes[0]
    ed = result.get('embed_dim', {})
    if 'rho_curve' in ed:
        curve = pd.DataFrame(ed['rho_curve'])
        ax.plot(curve['E'], curve['rho'], marker='o')
        ax.axvline(ed['opt_E'], color='r', linestyle='--', label=f"E={ed['opt_E']}")
        ax.set_xlabel('嵌入维 E')
        ax.set_ylabel('Pearson rho')
        ax.set_title(f'{var} 嵌入维选择')
        ax.legend()
    else:
        ax.set_title('EmbedDimension 失败')

    # Observations vs Predictions
    ax = axes[1]
    sx = result.get('simplex', {})
    if 'predictions' in sx:
        pred_df = pd.DataFrame(sx['predictions'])
        obs = pred_df['Observations'].values
        prd = pred_df['Predictions'].values
        mask = ~(np.isnan(obs) | np.isnan(prd))
        ax.scatter(obs[mask], prd[mask], alpha=0.7, edgecolors='k')
        mn, mx = np.nanmin(obs), np.nanmax(obs)
        ax.plot([mn, mx], [mn, mx], 'r--', label='1:1')
        ax.set_xlabel('观测值')
        ax.set_ylabel('预测值')
        ax.set_title(f"Simplex E={sx.get('E')} rho={sx.get('rho', 0):.3f}")
        ax.legend()
    else:
        ax.set_title('Simplex 失败')

    # theta vs rho
    ax = axes[2]
    sm = result.get('smap', {})
    if 'theta_rho' in sm:
        tr = pd.DataFrame(sm['theta_rho'])
        ax.plot(tr['theta'], tr['rho'], marker='o')
        ax.axvline(sm['peak_theta'], color='r', linestyle='--',
                   label=f"θ={sm['peak_theta']:.2f}")
        ax.set_xlabel('theta')
        ax.set_ylabel('rho')
        ax.set_title(f"S-Map 非线性检测 ({'非线性' if sm['nonlinear'] else '线性/弱非线性'})")
        ax.legend()
    else:
        ax.set_title('SMap 失败')

    plt.tight_layout()
    plt.savefig(f'{out_prefix}_{var}.png', dpi=150)
    plt.close()


# ---------------- 主流程 ----------------
def main():
    df_wide = pd.read_csv('outputs/data/yinshen_wide.csv', encoding='utf-8-sig')

    vowel_seq = []
    consonant_seq = []
    ji_seq = []

    for _, row in df_wide.iterrows():
        vs, cs = extract_primary_vowel_consonant(row)
        for v, c, ch in zip(vs, cs, [row[f'字{pos}'] for pos in range(1, 5)]):
            vowel_seq.append(v)
            consonant_seq.append(c)
            ji_seq.append(classify_final(get_final(ch)))

    # 编码为整数
    vowel_num, vowel_map = encode_integer(vowel_seq)
    consonant_num, consonant_map = encode_integer(consonant_seq)
    ji_num, ji_map = encode_integer(ji_seq)

    # 仅使用六姬 + 元音 + 辅音序列
    df_ji = pd.DataFrame({'time': np.arange(len(ji_num)), 'ji': ji_num})
    df_vowel = pd.DataFrame({'time': np.arange(len(vowel_num)), 'vowel': vowel_num})
    df_consonant = pd.DataFrame({'time': np.arange(len(consonant_num)), 'consonant': consonant_num})

    N = len(ji_num)
    lib = f'1 {int(N * 0.75)}'
    pred = f'{int(N * 0.75) + 1} {N}'

    results = {}
    for name, df_var in [('ji', df_ji), ('vowel', df_vowel), ('consonant', df_consonant)]:
        print(f"\n正在跑 EDM：{name}")
        res = run_edm_pipeline(df_var, name, lib=lib, pred=pred, maxE=8)
        results[name] = res
        plot_edm(res, 'outputs/figures/yinshen_edm')
        print(f"  Simplex rho = {res.get('simplex', {}).get('rho', 'N/A')}")
        print(f"  SMap peak theta = {res.get('smap', {}).get('peak_theta', 'N/A')}, rho = {res.get('smap', {}).get('peak_rho', 'N/A')}")

    # 保存 JSON（去掉过长的 predictions 列表以控制体积）
    report_json = {}
    for name, res in results.items():
        r = json.loads(json.dumps(res, default=str))
        if 'simplex' in r and 'predictions' in r['simplex']:
            r['simplex']['predictions'] = r['simplex']['predictions'][:5] + r['simplex']['predictions'][-5:]
        report_json[name] = r

    with open('outputs/reports/yinshen_edm_report.json', 'w', encoding='utf-8') as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    md = ["# 音神序列 · EDM 算法预测分析报告", ""]
    md.append("## 说明")
    md.append("本报告使用新版 `edm-takens` skill 的 `_edm_bridge` 接口（底层为 pyEDM）执行：")
    md.append("- `EmbedDimension`：选择最优嵌入维 E")
    md.append("- `Simplex`：状态空间预测")
    md.append("- `SMapPredictNonlinear`：检测系统非线性程度")
    md.append("- `ccm_causality_test`：lag-1 收敛性自预测")
    md.append("")
    md.append(f"样本长度：{N}，训练库：{lib}，预测段：{pred}")
    md.append("")

    for name, label in [('ji', '六姬整数序列'), ('vowel', '主元音整数序列'), ('consonant', '主辅音整数序列')]:
        res = results[name]
        md.append(f"## {label} (`{name}`)")
        md.append("")

        ed = res.get('embed_dim', {})
        if 'opt_E' in ed:
            md.append(f"- 最优嵌入维 E：{ed['opt_E']}")
        else:
            md.append(f"- 嵌入维选择失败：{ed.get('error', '')}")

        sx = res.get('simplex', {})
        if 'rho' in sx:
            md.append(f"- Simplex 预测 rho：{sx['rho']:.3f}（MAE={sx['mae']:.3f}，n={sx['n']}）")
        else:
            md.append(f"- Simplex 失败：{sx.get('error', '')}")

        sm = res.get('smap', {})
        if 'peak_rho' in sm:
            md.append(f"- S-Map 峰值：theta={sm['peak_theta']:.2f}，rho={sm['peak_rho']:.3f}")
            md.append(f"- 非线性判断：{'是' if sm['nonlinear'] else '否 / 弱'}")
        else:
            md.append(f"- SMap 失败：{sm.get('error', '')}")

        ccm = res.get('ccm', {})
        if 'verdict' in ccm:
            fr = ccm['forward_rho']
            fr_str = f"{fr:.3f}" if fr is not None else str(fr)
            md.append(f"- CCM lag-1：{ccm['verdict']}（forward rho={fr_str}，收敛={ccm['forward_converging']}）")
        else:
            md.append(f"- CCM 失败：{ccm.get('error', '')}")

        md.append("")
        md.append(f"![EDM 图](figures/yinshen_edm_{name}.png)")
        md.append("")

    md.append("## 数据科学解读")
    md.append("1. **Simplex rho** 越接近 1，说明该符号序列在重构的状态空间中越可预测。")
    md.append("2. **S-Map** 峰值出现在 theta>1 且 rho 较高，意味着系统具有显著非线性；若峰值在 theta=0 附近，则更接近线性自回归。")
    md.append("3. **CCM lag-1** 收敛且 rho 高，确认序列存在短期记忆结构。")
    md.append("4. 当前数据为符号序列且 N=120，EDM 结果应视为假设生成，而非统计确证。")

    with open('outputs/reports/yinshen_edm_report.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print("\n已保存 EDM 报告：outputs/reports/yinshen_edm_report.md")


if __name__ == '__main__':
    main()
