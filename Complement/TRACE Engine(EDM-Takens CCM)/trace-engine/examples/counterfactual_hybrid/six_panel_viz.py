"""
Six-Panel Enhanced Dashboard v2 — 六战士合体仪表板
====================================================
v2 修复: 布局重叠、字体大小、生成多云化图谱套件。

输出:
  1. six_panel_dashboard.png   — 六面板合体图
  2. trace_dnl.png             — 🔴 TRACE ΔNLL 分布 (独立)
  3. ccm_coverage.png          — 🔵 CCM 覆盖率 (独立)
  4. edm_rho.png               — 🟡 EDM ρ 分布 (独立)
  5. havok_energy.png          — ⚫ HAVOK 能量分配 (独立)
  6. dowhy_refute.png          — 🟡 DoWhy 反驳 + ITE (独立)
  7. causallearn_compare.png   — ⬜ causallearn 交叉比较 (独立)
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# CJK 字体自动检测
_CJK_FONTS = [f.name for f in fm.fontManager.ttflist
              if any(k in f.name.lower() for k in
                     ['simhei', 'microsoft yahei', 'noto sans cjk'])]
_CJK_FAMILY = _CJK_FONTS[0] if _CJK_FONTS else 'sans-serif'
plt.rcParams['font.family'] = _CJK_FAMILY
# 修复负号显示
plt.rcParams['axes.unicode_minus'] = False

# ═══════════════════════════════════════════════════════════
C = {
    'red':    '#C0392B', 'blue':   '#2980B9', 'yellow': '#D4AC0D',
    'black':  '#2C3E50', 'gold':   '#E67E22', 'silver': '#95A5A6',
    'bg':     '#FAFBFC', 'text':   '#2C3E50', 'grid':   '#D5D8DC',
    'pass':   '#27AE60', 'warn':   '#E67E22', 'fail':   '#C0392B',
}
FT = {'title': 9, 'label': 7.5, 'tick': 6.5, 'annot': 6, 'sm': 5.5}


# ═══════════════════════════════════════════════════════════
# 六面板合体图
# ═══════════════════════════════════════════════════════════

def render_six_panel(bridge, cards: dict, filepath: str, dpi: int = 150) -> str:
    fig = plt.figure(figsize=(24, 15), facecolor=C['bg'])
    gs = fig.add_gridspec(3, 3, hspace=0.50, wspace=0.40,
                          height_ratios=[0.05, 1.0, 1.0])

    # ── 标题 ──
    ax_t = fig.add_subplot(gs[0, :])
    n_e = len(bridge.significant_edges)
    n_r = sum(1 for r in bridge.refutation_results.values()
              if getattr(getattr(r, '_check', None), 'refuted', False))
    ax_t.text(0.5, 0.5,
        f"因 果 战 队 · 六 合 一 诊 断 仪 表 板   |   "
        f"{len([n for n in bridge.concept_names if n != '<other>' and len(n) > 1])} concepts · {n_e} edges · "
        f"{bridge.mode_name} · {n_r}/3 refuted   |   \"不是投票，是测绘\"",
        transform=ax_t.transAxes, ha='center', va='center',
        fontsize=11, fontweight='bold', color=C['text'])
    ax_t.axis('off')

    # Row 1
    _panel_trace(fig.add_subplot(gs[1, 0]), bridge, cards.get('trace'))
    _panel_ccm(fig.add_subplot(gs[1, 1]), cards.get('ccm'))
    _panel_edm(fig.add_subplot(gs[1, 2]), cards.get('edm'))
    # Row 2
    _panel_havok(fig.add_subplot(gs[2, 0]), cards.get('havok'))
    _panel_dowhy(fig.add_subplot(gs[2, 1]), bridge)
    _panel_causallearn(fig.add_subplot(gs[2, 2]), cards.get('causallearn'))

    fig.savefig(filepath, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig)
    return filepath


# ═══════════════════════════════════════════════════════════
# 多云化图谱套件
# ═══════════════════════════════════════════════════════════

def render_chart_suite(bridge, cards: dict, out_dir: str, dpi: int = 150) -> list:
    """生成独立图谱套件 + 合体图"""
    import os
    os.makedirs(out_dir, exist_ok=True)
    paths = []

    # 1. TRACE
    fig, ax = plt.subplots(figsize=(8, 5), facecolor=C['bg'])
    _panel_trace(ax, bridge, cards.get('trace'))
    p = f'{out_dir}/trace_dnl.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 2. CCM
    fig, ax = plt.subplots(figsize=(6, 5), facecolor=C['bg'])
    _panel_ccm(ax, cards.get('ccm'))
    p = f'{out_dir}/ccm_coverage.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 3. EDM
    fig, ax = plt.subplots(figsize=(6, 5), facecolor=C['bg'])
    _panel_edm(ax, cards.get('edm'))
    p = f'{out_dir}/edm_rho.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 4. HAVOK
    fig, ax = plt.subplots(figsize=(7, 4), facecolor=C['bg'])
    _panel_havok(ax, cards.get('havok'))
    p = f'{out_dir}/havok_energy.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 5. DoWhy+CF
    fig, ax = plt.subplots(figsize=(8, 5), facecolor=C['bg'])
    _panel_dowhy(ax, bridge)
    p = f'{out_dir}/dowhy_refute.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 6. causallearn
    fig, ax = plt.subplots(figsize=(7, 5), facecolor=C['bg'])
    _panel_causallearn(ax, cards.get('causallearn'))
    p = f'{out_dir}/causallearn_compare.png'; fig.savefig(p, dpi=dpi, bbox_inches='tight', facecolor=C['bg'])
    plt.close(fig); paths.append(p)

    # 7. 六面板合体
    p = render_six_panel(bridge, cards, f'{out_dir}/six_panel_dashboard.png', dpi=dpi)
    paths.append(p)

    return paths


# ═══════════════════════════════════════════════════════════
# Panel 1: 🔴 TRACE
# ═══════════════════════════════════════════════════════════

def _panel_trace(ax, bridge, card):
    edges = bridge.significant_edges
    if not edges:
        ax.text(0.5, 0.5, "无显著边", ha='center', va='center', fontsize=FT['label'])
        _hdr(ax, "[红] TRACE · 拓扑先锋 (探照灯)")
        return

    n = min(12, len(edges))
    names = [f"{e[0][:6]}→{e[1][:6]}" for e in edges[:n]]
    vals = [e[2] for e in edges[:n]]
    clrs = [C['red'] if v > 1.5 else C['gold'] if v > 0.5 else C['silver'] for v in vals]

    y = range(n)
    ax.barh(y, vals, color=clrs, alpha=0.85, height=0.55)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=FT['tick'])
    ax.invert_yaxis()
    ax.set_xlabel('ΔNLL', fontsize=FT['label'])
    # 值标注在条右侧
    for i, v in enumerate(vals):
        ax.text(v + max(vals)*0.01, i, f'{v:.2f}', va='center',
               fontsize=FT['annot'], color=C['text'])

    unk = getattr(bridge, 'unk_rate', 0)
    st = f'UNK {unk:.0%} · 跨域' if unk > 0.05 else '专域'
    _hdr(ax, f"[红] TRACE · ΔNLL分布 [{st}] · max={max(vals):.1f}")


# ═══════════════════════════════════════════════════════════
# Panel 2: 🔵 CCM
# ═══════════════════════════════════════════════════════════

def _panel_ccm(ax, card):
    if card is None:
        ax.text(0.5, 0.5, "CCM 未运行", ha='center', va='center', fontsize=FT['label'])
        _hdr(ax, "[蓝] CCM · 流形力场 (测谎仪)")
        return

    m = card.metrics
    cov = float(str(m.get('CCM_coverage', '0%')).rstrip('%')) / 100
    eli = int(m.get('eligible_concepts', 0))
    tot = int(m.get('total_unique', 1))
    sparse = max(0, tot - eli)

    # 环形图 (避免标签重叠)
    sizes = [eli, sparse]
    clrs = [C['blue'], C['silver']]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, colors=clrs, autopct='%1.0f%%',
        startangle=90, pctdistance=0.75,
        wedgeprops=dict(width=0.35, edgecolor='white'))
    for at in autotexts:
        at.set_fontsize(FT['title'])
        at.set_fontweight('bold')

    # 图例放在右下角（不重叠）
    ax.legend(wedges, [f'可验证 ({eli})', f'稀疏 ({sparse})'],
             loc='lower right', fontsize=FT['tick'], framealpha=0.8)

    ax.set_title(f'CCM 覆盖 {cov:.0%}\n{card.verdict}', fontsize=FT['label'],
                color=C['text'], pad=2)

    _hdr(ax, "[蓝] CCM · 交叉映射覆盖")


# ═══════════════════════════════════════════════════════════
# Panel 3: 🟡 EDM
# ═══════════════════════════════════════════════════════════

def _panel_edm(ax, card):
    if card is None:
        ax.text(0.5, 0.5, "EDM 未运行", ha='center', va='center', fontsize=FT['label'])
        _hdr(ax, "[黄] EDM · 时序节拍器 (套路探测器)")
        return

    m = card.metrics
    hi = int(m.get('rho_high', 0))
    mi = int(m.get('rho_mid', 0))
    an = int(m.get('analyzed', 1))
    lo = max(0, an - hi - mi)

    cats = ['高ρ (>0.8)', '中ρ (0.4-0.8)', '低ρ (<0.4)']
    vals = [hi, mi, lo]
    clrs = [C['yellow'], C['gold'], C['silver']]

    bars = ax.bar(cats, vals, color=clrs, alpha=0.85, width=0.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.15,
                str(v), ha='center', fontsize=FT['title'], fontweight='bold',
                color=C['text'])
    ax.set_ylabel('概念数', fontsize=FT['label'])
    ax.tick_params(labelsize=FT['tick'])

    # verdict 放在标题中
    vd = card.verdict.replace('_', ' ')[:30]
    _hdr(ax, f"[黄] EDM · ρ分布 [{vd}] · n={an}")


# ═══════════════════════════════════════════════════════════
# Panel 4: ⚫ HAVOK
# ═══════════════════════════════════════════════════════════

def _panel_havok(ax, card):
    if card is None:
        ax.text(0.5, 0.5, "HAVOK 未运行", ha='center', va='center', fontsize=FT['label'])
        _hdr(ax, "[黑] HAVOK · 混沌暗杀者 (X光机)")
        return

    m = card.metrics
    try:
        lin = float(str(m.get('linear_%', '100%')).rstrip('%')) / 100
        nln = float(str(m.get('nonlinear_%', '0%')).rstrip('%')) / 100
    except ValueError:
        lin, nln = 1.0, 0.0
    fcg = float(m.get('max_forcing', 0))

    ax.barh([0], [lin], color=C['black'], alpha=0.85, height=0.4,
            label=f'线性 {lin:.0%}')
    ax.barh([0], [nln], left=[lin], color=C['fail'], alpha=0.5, height=0.4,
            label=f'非线性 {nln:.0%}')
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.legend(fontsize=FT['tick'], loc='upper right', framealpha=0.8)

    # 诊断标注 — 白底黑字确保可读性
    diag_text = f"SVD r={m.get("r","?")}  |  forcing={fcg:.3f}  |  {card.verdict[:35] if card.verdict else ""}"
    ax.text(0.5, 0.50, diag_text, transform=ax.transAxes,
            ha="center", va="center", fontsize=FT["label"], fontweight="bold",
            color=C["text"],
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                     edgecolor=C["grid"], alpha=0.92))
    _hdr(ax, "[黑] HAVOK · 能量分配")


# ═══════════════════════════════════════════════════════════
# Panel 5: 🟡 DoWhy+CF
# ═══════════════════════════════════════════════════════════

def _panel_dowhy(ax, bridge):
    est = bridge.estimate_result
    scan = getattr(bridge, 'scan_results', None)
    ref = bridge.refutation_results

    if not ref:
        ax.text(0.5, 0.5, "DoWhy 数据不足", ha='center', va='center', fontsize=FT['label'])
        _hdr(ax, "[黄] DoWhy+CF · 反事实造物主")
        return

    names = [r.replace('_', ' ')[:10] for r in ref.keys()]
    x = np.arange(len(names))
    w = 0.35
    cf_labels, cf_vals = [], []

    # 颜色: 深蓝(原ATE) vs 亮橙(新效应) — 高对比度
    orig_vals = [est.value] * len(names)
    new_vals = [r.new_effect for r in ref.values()]
    ax.bar(x - w/2, orig_vals, w, color='#1B4F72', alpha=0.85,
           edgecolor='white', linewidth=0.5, label=f'原ATE={est.value:.3f}')
    ax.bar(x + w/2, new_vals, w, color='#E67E22', alpha=0.85,
           edgecolor='white', linewidth=0.5, label='反驳后')

    # ITE 附加柱
    if scan and len(scan) >= 2:
        cf_labels = [f'{r["source"][:4]}→{r["target"][:4]}' for r in scan[:3]]
        cf_vals = [r['ite'] for r in scan[:3]]
        x2 = np.arange(len(cf_labels)) + len(names) + 1
        cf_colors = ['#27AE60' if v > 0 else '#C0392B' for v in cf_vals]
        ax.bar(x2, cf_vals, w*1.2, color=cf_colors, alpha=0.75,
               edgecolor='white', linewidth=0.5, label='ITE')
        for xi, v in zip(x2, cf_vals):
            ax.annotate(f'{v:+.2f}', (xi, v + (0.02 if v >= 0 else -0.06)),
                       ha='center', fontsize=FT['annot'], color=C['text'],
                       fontweight='bold')

    # 统一 x 轴
    all_pos = list(x) + list(range(len(names) + 1, len(names) + 1 + len(cf_labels)))
    all_labels = list(names) + cf_labels
    ax.set_xticks(all_pos)
    ax.set_xticklabels(all_labels, fontsize=FT['tick'], rotation=20, ha='right')
    ax.axhline(y=0, color=C['grid'], lw=0.5, linestyle='--')
    ax.legend(fontsize=FT['sm'], loc='upper right', framealpha=0.9,
             edgecolor=C['grid'])
    ax.tick_params(labelsize=FT['tick'])
    ax.set_ylabel('Effect Size', fontsize=FT['label'], color=C['text'])

    _hdr(ax, f"[黄] DoWhy+CF · {bridge.treatment}→{bridge.outcome}")


# ═══════════════════════════════════════════════════════════
# Panel 6: ⬜ causallearn
# ═══════════════════════════════════════════════════════════

def _panel_causallearn(ax, card):
    if card is None:
        ax.text(0.5, 0.5, "causallearn 未运行", ha='center', va='center',
               fontsize=FT['label'])
        _hdr(ax, "[白] causallearn · 独立验证者 (PC/GES)")
        return

    m = card.metrics if hasattr(card, 'metrics') else {}
    fns = card.findings if hasattr(card, 'findings') else []

    # 用结构化文本替代混乱的 text block
    if m:
        lines = [
            f"PC: {m.get('PC_edges','?')} edges  |  GES: {m.get('GES_edges','?')} edges",
            f"TRACE: {m.get('TRACE_sub','?')} edges  |  共识: {m.get('Agree','?')} edges",
        ]
        if fns:
            lines.append(fns[-1][:60] if fns[-1] else '')
    else:
        lines = fns[:3] if fns else []

    # 分行显示，避免挤压
    for i, line in enumerate(lines[:4]):
        y = 0.75 - i * 0.22
        ax.text(0.5, y, line, transform=ax.transAxes, ha='center', va='center',
               fontsize=FT['label'], color=C['text'])

    ax.text(0.5, 0.05, card.verdict[:50] if card.verdict else '',
            transform=ax.transAxes, ha='center', va='center',
            fontsize=FT['tick'], color=C['silver'], fontstyle='italic')

    ax.axis('off')
    _hdr(ax, "[白] causallearn · 交叉验证")


def _hdr(ax, title):
    ax.set_title(title, fontsize=FT['title'], fontweight='bold', color=C['text'], loc='left')
