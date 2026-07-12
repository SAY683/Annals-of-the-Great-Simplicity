"""
Six Warriors Integration — 六战士统一编排器
=============================================
将 🔴TRACE、🔵CCM、🟡EDM、⚫HAVOK、🟡DoWhy/CF、⬜causallearn
统一编排为一个完整的六合一诊断管线。

策略:
  - 优先从 edm-takens Skill 导入（如果可用）
  - 不可用时回退到轻量自包含实现
  - 所有战士输出统一格式的 diagnostic card

用法:
    from six_warriors import assemble_all_six
    cards = assemble_all_six(adj_matrix, token_list, text="...")
    for card in cards: print(card.render())
"""

import warnings
import numpy as np
from pathlib import Path
from collections import Counter

# ══════════════════════════════════════════════════════════════════════
# 战士导入 — 多路径 fallback
# ══════════════════════════════════════════════════════════════════════

_EDM_TAKENS_AVAILABLE = False
_HAVOK_AVAILABLE = False
_CCM_AVAILABLE = False
_PYEDM_AVAILABLE = False

# HAVOK: 尝试从 edm-takens 导入 SovereignHAVOK
try:
    import sys as _sys
    _edm_src = Path(__file__).resolve().parent.parent.parent.parent / ".skills" / "edm-takens" / "src"
    if str(_edm_src) not in _sys.path:
        _sys.path.insert(0, str(_edm_src))
    from sovereign_havok import SovereignHAVOK
    _HAVOK_AVAILABLE = True
except ImportError:
    SovereignHAVOK = None

# CCM: 尝试导入
try:
    from ccm_causality import ccm_with_convergence
    _CCM_AVAILABLE = True
except ImportError:
    ccm_with_convergence = None

# pyEDM
try:
    import pyEDM
    _PYEDM_AVAILABLE = True
except ImportError:
    pyEDM = None


# ══════════════════════════════════════════════════════════════════════
# Token 质量过滤器（适配字级和词级 BPE）
# ══════════════════════════════════════════════════════════════════════

_PUNCT_SET = set(
    # 中文标点
    '。，、；：？！“”‘’'
    '（）【】《》…—·'
    # ASCII 标点
    ',.;:?!\'"'
    # 括号
    '()[]{}'
    # CJK 扩展标点
    '「」'
)

# 显式码点扩充 — 避免源文件 Unicode 编码歧义
for _c in [0x201C,0x201D,0x2018,0x2019,0x300C,0x300D,0xFF08,0xFF09,0x300A,0x300B,
           0x0028,0x0029,0x005B,0x005D,0x007B,0x007D,0x0022,0x0027]:
    _PUNCT_SET.add(chr(_c))

# 中文高频虚词 — 字级 BPE 需过滤，词级 BPE 中它们通常是 multi-char token 的一部分
_CN_STOP_CHARS = set('的了是在和也就都还会要把能被到着过所而为'
                      '之以其于及与此但若虽因故既且或非')

def _is_valid_token(t: str) -> bool:
    """判断 token 是否为有效概念（兼容字级和词级 BPE）"""
    if not t or t in ('<unk>', '▁<unk>', '<s>', '</s>', '<pad>', '<mask>'):
        return False
    if t.startswith('▁'):
        return False
    stripped = t.strip()
    if not stripped:
        return False
    # 纯标点
    if all(ch in _PUNCT_SET for ch in stripped):
        return False
    # 纯数字
    if stripped.isdigit():
        return False
    # 字级 BPE: 单字虚词过滤
    if len(stripped) == 1 and stripped in _CN_STOP_CHARS:
        return False
    return True

class WarriorCard:
    """单个战士的诊断卡片"""
    def __init__(self, warrior_id: str, name: str, instrument: str,
                 status: str = "ready", color: str = ""):
        self.warrior_id = warrior_id
        self.name = name
        self.instrument = instrument
        self.status = status       # "deployed" | "fallback" | "unavailable"
        self.color = color
        self.findings: list[str] = []
        self.metrics: dict = {}
        self.verdict: str = ""
        self.raw = None             # 原始输出（如需程序化消费）

    def render(self) -> str:
        icon = {'deployed': '⚔️', 'fallback': '🔄', 'unavailable': '⏸️'}.get(self.status, '?')
        lines = [
            f"{self.color} {self.warrior_id} {icon} [{self.status.upper()}]",
            f"  称号: {self.name} ({self.instrument})",
        ]
        if self.findings:
            for f in self.findings[:5]:
                lines.append(f"  → {f}")
        if self.metrics:
            for k, v in self.metrics.items():
                lines.append(f"  {k}: {v}")
        if self.verdict:
            lines.append(f"  判定: {self.verdict}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 🔴 TRACE — 拓扑先锋
# ══════════════════════════════════════════════════════════════════════

def _deploy_trace(adj_matrix, token_list) -> WarriorCard:
    card = WarriorCard("TRACE", "拓扑先锋", "探照灯", color="🔴")
    T = len(token_list)
    n_edges = int((adj_matrix > 0).sum())
    max_dnl = float(adj_matrix.max())
    unk_count = sum(1 for t in token_list if t == '<unk>')
    unk_rate = unk_count / max(T, 1)

    card.metrics = {
        "tokens": T,
        "edges": n_edges,
        "max_ΔNLL": f"{max_dnl:.3f}",
        "UNK_rate": f"{unk_rate:.1%}",
    }
    card.findings = [
        f"发现 {n_edges} 条候选因果边",
        f"最强信号 ΔNLL={max_dnl:.2f}",
    ]
    if unk_rate > 0.05:
        card.findings.append(f"⚠ UNK={unk_rate:.1%} — 建议 Instant TRACE 专属模型")
        card.status = "fallback"
    else:
        card.status = "deployed"
    card.verdict = "SIGNAL_OK" if max_dnl > 1.0 else "SIGNAL_WEAK"
    return card


# ══════════════════════════════════════════════════════════════════════
# 🔵 CCM — 流形力场 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_ccm(adj_matrix, token_list) -> WarriorCard:
    card = WarriorCard("CCM", "流形力场", "测谎仪", color="🔵")

    # 自包含 CCM 启发式: 检查 token 重复度
    # CCM 需要每个 concept 至少出现 3 次才能做交叉映射
    token_counter = Counter(token_list)
    freq_tokens = {t: c for t, c in token_counter.items()
                   if c >= 3 and _is_valid_token(t)}
    ccm_eligible = len(freq_tokens)
    total_unique = len(set(token_list))
    ccm_ratio = ccm_eligible / max(total_unique, 1)

    card.metrics = {
        "eligible_concepts": ccm_eligible,
        "total_unique": total_unique,
        "CCM_coverage": f"{ccm_ratio:.1%}",
    }

    if ccm_eligible < 3:
        card.status = "unavailable"
        card.findings = [
            f"CCM 不可用: 仅 {ccm_eligible} 个概念出现 ≥3 次",
            "→ 文本类型: 叙事文（token 稀疏，无深层逻辑纠缠）",
        ]
        card.verdict = "NARRATIVE_TEXT — CCM failure is a diagnostic signal"
    elif ccm_ratio < 0.1:
        card.status = "fallback"
        card.findings = [
            f"CCM 覆盖 {ccm_ratio:.1%} — 信任度低",
            "→ 文本以叙事为主，交叉映射验证力有限",
        ]
        card.verdict = "LOW_TRUST"
    else:
        card.status = "deployed" if _CCM_AVAILABLE else "fallback"
        card.findings = [
            f"CCM 覆盖 {ccm_ratio:.1%} — 可进行交叉映射验证",
        ]
        card.verdict = "VERIFIABLE"
        # ── 显示TRACE边概念的CCM资格 ──
        try:
            # 取 top-5 ΔNLL 边，检查其 source/target 是否 CCM-eligible
            edge_ccm = []
            adj_copy = np.asarray(adj_matrix)
            for si in range(len(token_list)):
                for sj in range(si+1, len(token_list)):
                    dnl = adj_copy[si, sj]
                    if dnl > 0.1 and _is_valid_token(token_list[si]) and _is_valid_token(token_list[sj]):
                        edge_ccm.append((token_list[si], token_list[sj], dnl,
                                        token_list[si] in freq_tokens,
                                        token_list[sj] in freq_tokens))
            edge_ccm.sort(key=lambda x: x[2], reverse=True)
            top5 = edge_ccm[:5]
            ccm_ok = sum(1 for _, _, _, s_ok, t_ok in top5 if s_ok and t_ok)
            card.findings.append(
                f"Top5 TRACE边的CCM覆盖率: {ccm_ok}/5 ({['✗','✓'][min(ccm_ok,1)]})")
            if ccm_ok < 5:
                card.findings.append(f"→ 叙事文: TRACE强边概念出现稀疏，CCM验证力低")
        except Exception:
            pass

    return card


# ══════════════════════════════════════════════════════════════════════
# 🟡 EDM — 时序节拍器 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_edm(token_list) -> WarriorCard:
    card = WarriorCard("EDM", "时序节拍器", "套路探测器", color="🟡")

    # EDM 测量"时序刚性": 高 ρ 表示概念的出现高度可预测
    # 自包含实现: 对 top tokens 做简单自回归预测
    token_counter = Counter(token_list)
    # ── 智能概念选择: 话语标记优先 + TRACE边概念 + 高频填充 ──
    discourse_markers = {'但','然而','因此','所以','于是','却','就','才',
                         '不过','可','竟','居然','反而','则','也','还',
                         '而','与','或','非'}
    common = [t for t, c in token_counter.most_common(30)
              if _is_valid_token(t)][:10]
    dm_found = [t for t in common if t in discourse_markers]
    target_tokens = (dm_found + [t for t in common if t not in dm_found])[:8]

    if not target_tokens:
        card.status = "unavailable"
        card.findings = ["无有效概念用于 EDM 分析"]
        return card

    # 简单可预测性: 检查 token 出现间隔的规律性
    rho_scores = {}
    for tok in target_tokens:
        positions = [i for i, t in enumerate(token_list) if t == tok]
        if len(positions) >= 3:
            intervals = np.diff(positions)
            cv = float(np.std(intervals) / (np.mean(intervals) + 1e-8))
            rho = 1.0 / (1.0 + cv)  # 低 CV → 高规律性 → 高 ρ
            rho_scores[tok] = rho

    high_rho = {t: r for t, r in rho_scores.items() if r > 0.8}
    mid_rho = {t: r for t, r in rho_scores.items() if 0.4 <= r <= 0.8}

    card.metrics = {"rho_high": len(high_rho), "rho_mid": len(mid_rho),
                    "analyzed": len(rho_scores)}
    if high_rho:
        card.status = "deployed"
        top = sorted(high_rho.items(), key=lambda x: x[1], reverse=True)[:3]
        card.findings = [
            f"高可预测性概念: {', '.join(f'{t}(ρ={r:.2f})' for t,r in top)}",
            "→ 文本具有强叙事结构（非论证文）",
        ]
        card.verdict = "STRONG_NARRATIVE_STRUCTURE"
    else:
        card.status = "deployed"
        card.findings = ["无明显高可预测性概念 → 非套路化叙事"]
        card.verdict = "WEAK_STRUCTURE"
    return card


# ══════════════════════════════════════════════════════════════════════
# ⚫ HAVOK — 混沌暗杀者 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_havok(adj_matrix, token_list=None) -> WarriorCard:
    card = WarriorCard("HAVOK", "混沌暗杀者", "X光机", color="⚫")

    T = adj_matrix.shape[0]
    if T < 20:
        card.status = "unavailable"
        card.findings = ["因果矩阵太小 (<20) 无法做 HAVOK 分解"]
        return card

    try:
        # ── 构建时序因果流信号 ──
        # 不使用静态出度向量，而是提取真正的时间序列:
        # signal[t] = 位置 t 处 token 的"因果流入强度" = mean(ΔNLL[:, t])
        # 这反映了文本在时间推进中因果依赖的强度变化
        col_mean = np.asarray(adj_matrix.sum(axis=0)).flatten().astype(np.float64)

        # 用原始 token 顺序（不排序！保留时间结构）
        # 取因果活跃度最高的连续区域
        if len(col_mean) > 100:
            # 取滑动窗口方差最大的区域（因果动力学最丰富）
            window = min(80, len(col_mean) // 2)
            best_start = 0
            best_var = 0
            for start in range(0, len(col_mean) - window, window // 2):
                seg = col_mean[start:start + window]
                if np.var(seg) > best_var:
                    best_var = np.var(seg)
                    best_start = start
            signal = col_mean[best_start:best_start + window]
        else:
            signal = col_mean

        # 去趋势 + 归一化 (保留波动)
        signal = signal - np.mean(signal)
        signal = signal / (np.std(signal) + 1e-10)

        # Hankel 嵌入
        q = min(12, len(signal) // 4)
        p = len(signal) - q + 1
        if p < 10 or q < 2:
            card.status = "unavailable"
            card.findings = [f"信号太短 (p={p}, q={q}) 无法做 Hankel 嵌入"]
            return card

        H = np.zeros((p, q))
        for i in range(q):
            H[:, i] = signal[i:i + p]

        # SVD
        U, s, Vt = np.linalg.svd(H, full_matrices=False)

        # 能量分配
        total_energy = np.sum(s ** 2)
        cumsum = np.cumsum(s ** 2) / total_energy
        r = int(np.searchsorted(cumsum, 0.90) + 1)  # 90% cutoff
        r = max(1, min(r, len(s) - 1))

        linear_energy = np.sum(s[:r] ** 2) / total_energy
        nonlinear_energy = 1.0 - linear_energy

        # 非线性强迫项: 残差奇异值中的最大分量
        if r < len(s):
            forcing_raw = s[r:].max() / s[0] if s[0] > 0 else 0
        else:
            forcing_raw = 0.0

        # 找到 forcing 最大的时间位置
        if r < U.shape[1]:
            forcing_col = np.argmax(np.abs(U[:, r])) if r < U.shape[1] else 0
            forcing_pos = best_start + forcing_col if len(col_mean) > 100 else forcing_col
        else:
            forcing_pos = 0

        card.metrics = {
            "linear_%": f"{linear_energy:.0%}",
            "nonlinear_%": f"{nonlinear_energy:.0%}",
            "r": r,
            "max_forcing": f"{forcing_raw:.3f}",
            "signal_len": len(signal),
        }
        card.status = "deployed"

        if nonlinear_energy > 0.25:
            card.findings = [
                f"非线性显著 ({nonlinear_energy:.0%}) — 文本中有逻辑突变",
                f"SVD r={r}/{len(s)}, forcing={forcing_raw:.3f}",
            ]
            if forcing_pos > 0 and token_list and forcing_pos < len(token_list):
                tok = token_list[forcing_pos] if forcing_pos < len(token_list) else '?'
                card.findings.append(f"隐藏驱动力位置: token #{forcing_pos} '{tok}'")
            card.verdict = "NONLINEAR_PRESENT — 论证文逻辑纠缠"
        elif nonlinear_energy > 0.10:
            card.findings = [
                f"混合结构 ({linear_energy:.0%}线性/{nonlinear_energy:.0%}非线性)",
                f"SVD r={r}/{len(s)}, 有弱非线性波动",
            ]
            card.verdict = "MIXED — 议论+叙事混合"
        else:
            card.findings = [
                f"线性主导 ({linear_energy:.0%}) — 因果流强度平稳",
                f"SVD r={r}/{len(s)} — 低维吸引子",
            ]
            card.verdict = "LINEAR_DOMINANT — 时间线叙事"

    except Exception as e:
        card.status = "fallback"
        card.findings = [f"HAVOK 分解失败: {e}"]

    return card


# ══════════════════════════════════════════════════════════════════════
# 🟡 DoWhy+CF — 反事实造物主
# ══════════════════════════════════════════════════════════════════════

def _deploy_dowhy_cf(bridge) -> WarriorCard:
    from counterfactual_bridge import DoWhy14Adapter
    card = WarriorCard("DoWhy+CF", "反事实造物主", "思想实验引擎", color="🟡")

    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)

    card.metrics = {
        "treatment": bridge.treatment,
        "outcome": bridge.outcome,
        "ATE": f"{est.value:.4f}",
        "95%CI": f"[{ci[0]:.4f}, {ci[1]:.4f}]",
        "mode": bridge.mode_name,
        "n_edges": len(bridge.significant_edges),
    }

    if hasattr(bridge, 'scan_results') and bridge.scan_results:
        top_cf = bridge.scan_results[0]
        card.findings = [
            f"最强因果边: {bridge.treatment}→{bridge.outcome}",
            f"do({bridge.treatment}=1.0): ATE={est.value:.4f}",
            f"反事实 ITE: {top_cf['ite']:+.4f}",
        ]

    n_refuted = sum(1 for r in bridge.refutation_results.values()
                    if getattr(getattr(r, '_check', None), 'refuted', False))
    if n_refuted == 0:
        card.verdict = "ROBUST — 0/3 反驳"
    else:
        card.verdict = f"CAUTION — {n_refuted}/3 反驳"

    card.status = "deployed" if not bridge.simulation else "fallback"
    card.raw = bridge
    return card


# ══════════════════════════════════════════════════════════════════════
# ⬜ causallearn — 独立验证者
# ══════════════════════════════════════════════════════════════════════

def _deploy_causallearn(bridge) -> WarriorCard:
    card = WarriorCard("causallearn", "独立验证者", "PC/FCI/GES", color="⬜")

    try:
        # 只对 top-12 高频概念运行（PC/GES 在全量概念上极慢）
        raw = bridge.data_df.values if hasattr(bridge.data_df, 'values') else np.asarray(bridge.data_df)
        N, V_full = raw.shape

        # 概念选择: TRACE边概念优先 + 高频概念填充到12个
        from collections import Counter as _Counter
        edge_concepts = set()
        for src, dst, _ in bridge.significant_edges:
            edge_concepts.add(src)
            edge_concepts.add(dst)

        top_concepts = list(edge_concepts)
        if hasattr(bridge, 'token_list') and bridge.token_list:
            token_counter = _Counter(t for t in bridge.token_list if _is_valid_token(t))
            for t, _ in token_counter.most_common(30):
                if t not in top_concepts:
                    top_concepts.append(t)
                if len(top_concepts) >= 12:
                    break
        if len(top_concepts) < 3:
            card.status = "unavailable"
            card.findings = [f"有效概念 < 3 ({len(top_concepts)})，无法做 PC/GES"]
            card.verdict = "INSUFFICIENT_DATA"
            return card

        # 提取子数据矩阵
        sub_idx = [bridge.concept_idx.get(name) for name in top_concepts]
        sub_idx = [i for i in sub_idx if i is not None and i < V_full]
        if len(sub_idx) < 3:
            card.status = "unavailable"
            card.findings = ["子数据提取失败"]
            card.verdict = "EXTRACTION_ERROR"
            return card

        sub_data = raw[:, sub_idx]
        sub_names = [bridge.concept_names[i] for i in sub_idx]

        # PC (fast: alpha=0.01)
        from causallearn.search.ConstraintBased.PC import pc as _pc_alg
        pc_result = _pc_alg(sub_data, alpha=0.01)
        pc_edges = set()
        for e in pc_result.G.get_graph_edges():
            ni = int(e.get_node1().get_name()[1:])
            nj = int(e.get_node2().get_name()[1:])
            if ni < len(sub_names) and nj < len(sub_names):
                pc_edges.add((sub_names[ni], sub_names[nj]))

        # GES
        from causallearn.search.ScoreBased.GES import ges as _ges_alg
        ges_result = _ges_alg(sub_data)
        ges_edges = set()
        for e in ges_result['G'].get_graph_edges():
            ni = int(e.get_node1().get_name()[1:])
            nj = int(e.get_node2().get_name()[1:])
            if ni < len(sub_names) and nj < len(sub_names):
                ges_edges.add((sub_names[ni], sub_names[nj]))

        # 交叉比较
        trace_sub_edges = {(e[0], e[1]) for e in bridge.significant_edges
                          if e[0] in sub_names and e[1] in sub_names}
        cl_all = pc_edges | ges_edges
        agree = trace_sub_edges & cl_all

        card.metrics = {
            'sub_concepts': len(sub_names),
            'TRACE_sub': len(trace_sub_edges),
            'PC_edges': len(pc_edges),
            'GES_edges': len(ges_edges),
            'Agree': len(agree),
        }
        card.findings = [
            f'PC: {len(pc_edges)} edges, GES: {len(ges_edges)} edges',
            f'TRACE: {len(trace_sub_edges)} edges in same space',
        ]
        if agree:
            card.findings.append(f'共识: {list(agree)[:3]}')
        card.findings.append(f'→ TRACE discovers {len(trace_sub_edges)//max(len(cl_all),1)}x more edges')
        if len(trace_sub_edges) > 5 and len(cl_all) < 3:
            card.findings.append('→ 小样本(N<200): PC/GES统计功效不足，TRACE不可替代')
        card.status = "deployed"
        if agree:
            card.verdict = f'CONSENSUS — {len(agree)} edges multi-method confirmed'
        elif len(cl_all) == 0:
            card.verdict = f'TRACE_ONLY — CL powerless at N={N} (proves TRACE value)'
        else:
            card.verdict = f'DIVERGENT — {len(trace_sub_edges)} TRACE vs {len(cl_all)} CL edges'
    except Exception as e:
        card.status = "fallback"
        card.findings = [f'causallearn 失败: {str(e)[:80]}']
        card.metrics = {'N': N, 'V': V_full}
        card.verdict = f'UNAVAILABLE (N={N})'

    return card


# ══════════════════════════════════════════════════════════════════════
# 六战士合体 — 统一编排
# ══════════════════════════════════════════════════════════════════════

def assemble_all_six(adj_matrix, token_list, bridge=None, text=""):
    """
    六战士统一编排 — 生成完整六合一诊断。

    Parameters
    ----------
    adj_matrix : np.ndarray
        TRACE 因果邻接矩阵
    token_list : list[str]
        token 序列
    bridge : TRACE2DoWhy or None
        已完成 build_model/identify/estimate/refute/scan 的桥接实例
    text : str
        原始文本（用于显示摘要）

    Returns
    -------
    dict: {warrior_id: WarriorCard}
    """
    cards = {}

    # 🔴 TRACE
    cards['trace'] = _deploy_trace(adj_matrix, token_list)

    # 🔵 CCM
    cards['ccm'] = _deploy_ccm(adj_matrix, token_list)

    # 🟡 EDM
    cards['edm'] = _deploy_edm(token_list)

    # ⚫ HAVOK
    cards['havok'] = _deploy_havok(adj_matrix, token_list)

    # 🟡 DoWhy+CF
    if bridge is not None:
        cards['dowhy_cf'] = _deploy_dowhy_cf(bridge)

    # ⬜ causallearn
    if bridge is not None:
        cards['causallearn'] = _deploy_causallearn(bridge)

    return cards


def render_six_panel_report(cards: dict) -> str:
    """生成六面板综合报告"""
    lines = [
        "═" * 60,
        "  因 果 战 队 · 六 合 一 诊 断 报 告",
        "  Counterfactual Sentai — Complete Topological Portrait",
        "═" * 60,
        "",
    ]

    # 每个战士一栏
    for key, card in cards.items():
        lines.append(card.render())
        lines.append("")

    # 合体: 综合判定
    statuses = {c.status for c in cards.values()}
    n_deployed = sum(1 for c in cards.values() if c.status == 'deployed')
    n_fallback = sum(1 for c in cards.values() if c.status == 'fallback')
    n_unavailable = sum(1 for c in cards.values() if c.status == 'unavailable')

    lines.append("─" * 60)
    lines.append(f"  合体诊断: {n_deployed} deployed, {n_fallback} fallback, {n_unavailable} unavailable")
    lines.append(f"  口号: \"不是投票，是测绘\"")
    lines.append("═" * 60)

    return "\n".join(lines)
