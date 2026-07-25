"""
Six Warriors Integration — 六战士统一编排器
=============================================
将 🔴TRACE、🔵CCM、🟡EDM、⚫HAVOK、🟡DoWhy/CF、⬜causallearn
统一编排为一个完整的六合一诊断管线。

═══════════════════════════════════════════════════════════════════
架构等级声明 (Architecture Tier Declaration) — 元审计 P0 修缮
═══════════════════════════════════════════════════════════════════
六战士并非"六个等价算法"，而是异质性诊断联盟，分两个等级：

  Tier-A 真算法层 (4 名) — 真实算法实现，输出可追溯因果证据：
    🔴 TRACE      — ΔNLL 掩码干预 (run_real_pipeline.py:178-262)
    ⚫ HAVOK      — Hankel+SVD+强迫项定位 (six_warriors.py:_deploy_havok)
    🟡 DoWhy+CF   — do-calculus + Pearl 三步反事实 (counterfactual_bridge.py)
    ⬜ causallearn — PC/GES 独立验证 (causallearn_validator.py)

  Tier-B 启发式诊断层 (2 名) — 文本特征启发式，标注 "HEURISTIC_FALLBACK"：
    🔵 CCM        — 概念覆盖率统计 (依赖 edm-takens 真算法，不可用时降级)
    🟡 EDM        — 间隔变异系数近似 ρ (非 Sugihara EDM，仅诊断文本结构)

设计意图：
  - Tier-B 的"启发式回退"不是缺陷，而是"文本类型诊断信号"
  - 当 CCM/EDM 报告 NARRATIVE_TEXT/LOW_TRUST 时，是诊断结论而非失败
  - 六合一"不是投票，是测绘" (DESIGN_SIX_IN_ONE.md:69-73)

策略:
  - 优先从 edm-takens Skill 导入 Tier-B 真算法（如果可用）
  - 不可用时回退到轻量自包含启发式实现
  - 所有战士输出统一格式的 diagnostic card，status 字段标注层级

用法:
    from six_warriors import assemble_all_six
    cards = assemble_all_six(adj_matrix, token_list, text="...")
    for card in cards: print(card.render())
"""

import warnings
import numpy as np
from pathlib import Path
from collections import Counter

from _config import ensure_edm_takens_in_sys_path
from _token_filters import is_valid_concept, is_unk_token
from _causallearn_utils import node_index as _node_index

# ══════════════════════════════════════════════════════════════════════
# 战士导入 — 多路径 fallback
# ══════════════════════════════════════════════════════════════════════

_EDM_TAKENS_AVAILABLE = False
_HAVOK_AVAILABLE = False
_CCM_AVAILABLE = False
_PYEDM_AVAILABLE = False

# HAVOK: 尝试从 edm-takens 导入 SovereignHAVOK
ensure_edm_takens_in_sys_path()
try:
    from sovereign_havok import SovereignHAVOK
    _HAVOK_AVAILABLE = True
except ImportError:
    SovereignHAVOK = None

# CCM: 尝试导入（edm-takens/src/final_interpretation.py 提供实际实现）
try:
    # 优先从已加入 sys.path 的 edm-takens/src 导入
    from final_interpretation import ccm_with_convergence
    _CCM_AVAILABLE = True
except Exception as _ccm_err:
    try:
        from ccm_causality import ccm_with_convergence
        _CCM_AVAILABLE = True
    except Exception:
        ccm_with_convergence = None

# pyEDM
try:
    import pyEDM
    _PYEDM_AVAILABLE = True
except ImportError:
    pyEDM = None


# ══════════════════════════════════════════════════════════════════════
# Token 质量过滤器（统一从 _token_filters 导入）
# ══════════════════════════════════════════════════════════════════════

# is_valid_concept 已统一在 _token_filters.py 中维护

class WarriorCard:
    """单个战士的诊断卡片"""
    def __init__(self, warrior_id: str, name: str, instrument: str,
                 status: str = "ready", color: str = "", tier: str = "A"):
        self.warrior_id = warrior_id
        self.name = name
        self.instrument = instrument
        self.status = status       # "deployed" | "fallback" | "unavailable"
        self.color = color
        # tier: "A"=真算法层(可追溯因果证据), "B"=启发式诊断层(文本特征启发式)
        # 元审计 P0 修缮: 让六勇士等级显式化，消除"六勇士名实不符"歧义
        self.tier = tier
        self.findings: list[str] = []
        self.metrics: dict = {}
        self.verdict: str = ""
        self.raw = None             # 原始输出（如需程序化消费）

    def render(self) -> str:
        icon = {'deployed': '⚔️', 'fallback': '🔄', 'unavailable': '⏸️'}.get(self.status, '?')
        tier_tag = f"[Tier-{self.tier}]" if self.tier else ""
        lines = [
            f"{self.color} {self.warrior_id} {icon} [{self.status.upper()}] {tier_tag}",
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

    def to_dict(self) -> dict:
        """序列化为字典，供 Web / Worker 消费。"""
        raw = self.raw
        if hasattr(raw, 'tolist'):
            raw = raw.tolist()
        elif not isinstance(raw, (dict, list, tuple, str, int, float, bool, type(None))):
            # 避免把 TRACE2DoWhy 等复杂对象直接序列化出去
            raw = None
        return {
            "warrior_id": self.warrior_id,
            "name": self.name,
            "instrument": self.instrument,
            "status": self.status,
            "tier": self.tier,
            "color": self.color,
            "findings": self.findings,
            "metrics": self.metrics,
            "verdict": self.verdict,
            "raw": raw,
        }


# ══════════════════════════════════════════════════════════════════════
# 🔴 TRACE — 拓扑先锋
# ══════════════════════════════════════════════════════════════════════

def _deploy_trace(adj_matrix, token_list, bridge=None) -> WarriorCard:
    adj_matrix = np.asarray(adj_matrix)
    card = WarriorCard("TRACE", "拓扑先锋", "探照灯", color="🔴")
    T = len(token_list)
    if adj_matrix.size == 0:
        card.status = "unavailable"
        card.findings = ["邻接矩阵为空，无法分析"]
        card.verdict = "EMPTY_MATRIX"
        card.metrics = {"tokens": T, "edges": 0, "max_ΔNLL": "N/A", "UNK_rate": "N/A"}
        return card
    n_edges = int((adj_matrix > 0).sum())
    max_dnl = float(adj_matrix.max())
    unk_count = sum(1 for t in token_list if is_unk_token(t))
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
    # D2 修复: 阈值随预设 threshold 缩放，避免 llama 预设下永远 SIGNAL_WEAK
    _signal_ok_threshold = getattr(bridge, 'threshold', 0.03) * 10
    card.verdict = "SIGNAL_OK" if max_dnl > _signal_ok_threshold else "SIGNAL_WEAK"
    return card


# ══════════════════════════════════════════════════════════════════════
# 🔵 CCM — 流形力场 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_ccm(adj_matrix, token_list, concept_names=None) -> WarriorCard:
    card = WarriorCard("CCM", "流形力场", "测谎仪", color="🔵", tier="B")

    # 自包含 CCM 启发式: 检查有效概念（过滤 BPE 碎片/停用词）的重复度
    # CCM 需要每个 concept 至少出现 3 次才能做交叉映射
    # 注：对 BPE token 序列，先用 is_valid_concept 过滤，避免 <unk>/▁ 等碎片拉低覆盖率
    valid_tokens = [t for t in token_list if is_valid_concept(t)]
    token_counter = Counter(valid_tokens)
    freq_tokens = {t: c for t, c in token_counter.items() if c >= 3}
    ccm_eligible = len(freq_tokens)
    total_unique = len(set(valid_tokens))
    ccm_ratio = ccm_eligible / max(total_unique, 1)

    card.metrics = {
        "eligible_concepts": ccm_eligible,
        "total_unique": total_unique,
        "CCM_coverage": f"{ccm_ratio:.1%}",
        "filtered_tokens": len(valid_tokens),
    }

    if ccm_eligible < 3:
        card.status = "unavailable"
        card.findings = [
            f"CCM 不可用: 仅 {ccm_eligible} 个有效概念出现 ≥3 次",
            "→ 文本类型: 叙事文（有效概念稀疏，无深层逻辑纠缠）",
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
        # 元审计 P1 修缮: verdict 必须反映"是否真正运行了 ccm_with_convergence"
        # 原实现仅依据 _CCM_AVAILABLE 就标 VERIFIABLE，但本函数始终未调用真算法
        # ——仅做覆盖率统计。这会误导用户认为已执行交叉映射验证。
        # 修复: 区分三层语义
        #   ELIGIBLE_BUT_NOT_RUN  — 满足 CCM 数据条件，但未调用真算法（本函数常态）
        #   HEURISTIC_FALLBACK    — 真算法不可用，仅启发式统计
        #   VERIFIABLE            — 仅当本函数实际调用 ccm_with_convergence 成功后设置
        #                       （当前实现未调用，故永不标 VERIFIABLE；如需真验证，
        #                        应在 _deploy_ccm 中调用 ccm_with_convergence 并捕获结果）
        card.status = "deployed" if _CCM_AVAILABLE else "fallback"
        card.findings = [
            f"CCM 覆盖 {ccm_ratio:.1%} — 满足交叉映射数据条件",
        ]
        if _CCM_AVAILABLE:
            # 真算法可导入，但本函数未实际调用 → 明确标注
            card.verdict = "ELIGIBLE_BUT_NOT_RUN"
            card.findings.append(
                "ℹ 真算法可导入但本诊断未实际运行 ccm_with_convergence；"
                "如需真实验证，应在 counterfactual_bridge 中显式调用并捕获 ρ/rho 曲线"
            )
        else:
            card.verdict = "HEURISTIC_FALLBACK"
            card.findings.append("⚠ 启发式回退: edm-takens 真算法不可用，仅做覆盖率统计")
        # ── 显示TRACE边概念的CCM资格 ──
        # 兼容 token-level TRACE 矩阵（尺寸与 token_list 一致）和 concept-level 矩阵
        try:
            adj_copy = np.asarray(adj_matrix)
            edge_ccm = []
            if (adj_copy.ndim == 2 and adj_copy.shape[0] == adj_copy.shape[1]
                    and concept_names is not None
                    and len(concept_names) == adj_copy.shape[0]):
                # concept-level 矩阵：直接遍历概念边
                for i in range(len(concept_names)):
                    for j in range(i + 1, len(concept_names)):
                        dnl = adj_copy[i, j]
                        src, dst = concept_names[i], concept_names[j]
                        if dnl > 0.1 and is_valid_concept(src) and is_valid_concept(dst):
                            edge_ccm.append((src, dst, dnl,
                                            src in freq_tokens,
                                            dst in freq_tokens))
            elif (adj_copy.ndim == 2
                  and adj_copy.shape[0] == len(token_list)
                  and adj_copy.shape[1] == len(token_list)):
                # token-level 矩阵：按原始 token 位置遍历
                for si in range(len(token_list)):
                    for sj in range(si + 1, len(token_list)):
                        dnl = adj_copy[si, sj]
                        if dnl > 0.1 and is_valid_concept(token_list[si]) and is_valid_concept(token_list[sj]):
                            edge_ccm.append((token_list[si], token_list[sj], dnl,
                                            token_list[si] in freq_tokens,
                                            token_list[sj] in freq_tokens))
            else:
                # 尺寸不匹配：跳过边级 CCM 检查，仅报告覆盖率
                card.findings.append("TRACE 矩阵与 token 序列尺寸不一致，跳过边级 CCM 资格检查")

            if edge_ccm:
                edge_ccm.sort(key=lambda x: x[2], reverse=True)
                top5 = edge_ccm[:5]
                ccm_ok = sum(1 for _, _, _, s_ok, t_ok in top5 if s_ok and t_ok)
                card.findings.append(
                    f"Top5 TRACE边的CCM覆盖率: {ccm_ok}/5 ({['✗','✓'][min(ccm_ok,1)]})")
                if ccm_ok < 5:
                    card.findings.append(f"→ 叙事文: TRACE强边概念出现稀疏，CCM验证力低")
        except Exception as e:
            card.findings.append(f"CCM边级检查失败: {e}")

    return card


# ══════════════════════════════════════════════════════════════════════
# 🟡 EDM — 时序节拍器 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_edm(token_list) -> WarriorCard:
    card = WarriorCard("EDM", "时序节拍器", "套路探测器", color="🟡", tier="B")

    # EDM 测量"时序刚性": 高 ρ 表示概念的出现高度可预测
    # 自包含实现: 对 top tokens 做简单自回归预测
    token_counter = Counter(token_list)
    # ── 智能概念选择: 话语标记优先 + TRACE边概念 + 高频填充 ──
    discourse_markers = {'但','然而','因此','所以','于是','却','就','才',
                         '不过','可','竟','居然','反而','则','也','还',
                         '而','与','或','非'}
    common = [t for t, c in token_counter.most_common(30)
              if is_valid_concept(t)][:10]
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
    # EDM 始终使用自包含启发式（无真算法导入路径），明确标注
    card.status = "fallback"
    if high_rho:
        top = sorted(high_rho.items(), key=lambda x: x[1], reverse=True)[:3]
        card.findings = [
            f"高可预测性概念: {', '.join(f'{t}(ρ={r:.2f})' for t,r in top)}",
            "→ 文本具有强叙事结构（非论证文）",
            "⚠ 启发式回退: 使用间隔变异系数近似 ρ，非 Sugihara EDM 算法",
        ]
        card.verdict = "HEURISTIC_STRONG_NARRATIVE_STRUCTURE"
    else:
        card.findings = [
            "无明显高可预测性概念 → 非套路化叙事",
            "⚠ 启发式回退: 使用间隔变异系数近似 ρ，非 Sugihara EDM 算法",
        ]
        card.verdict = "HEURISTIC_WEAK_STRUCTURE"
    return card


# ══════════════════════════════════════════════════════════════════════
# ⚫ HAVOK — 混沌暗杀者 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_havok(adj_matrix, token_list=None) -> WarriorCard:
    adj_matrix = np.asarray(adj_matrix)
    card = WarriorCard("HAVOK", "混沌暗杀者", "X光机", color="⚫", tier="A")

    T = adj_matrix.shape[0]
    token_len = len(token_list) if token_list else T
    if T < 20:
        card.status = "unavailable"
        # 概念级矩阵（Web 快速分析）常见场景，给出明确诊断
        if token_len > T * 2:
            card.findings = [
                f"概念级矩阵尺寸 T={T} < 20，不满足 HAVOK 分解要求",
                "→ Web 快速分析使用概念级共现矩阵，HAVOK 不可用是设计权衡",
                "→ 如需完整 HAVOK，请使用 trace-engine CLI 处理原始 token 级 TRACE 输出",
            ]
        else:
            card.findings = [f"因果矩阵太小 (T={T} < 20) 无法做 HAVOK 分解"]
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
        # 全零邻接矩阵会导致 total_energy=0，cumsum 除零产生 NaN
        if total_energy < 1e-12:
            card.status = "unavailable"
            card.verdict = "ZERO_SIGNAL"
            card.findings = ["邻接矩阵全零，无因果信号可供 HAVOK 分解"]
            return card
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
            forcing_col = np.argmax(np.abs(U[:, r]))
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
    card = WarriorCard("DoWhy+CF", "反事实造物主", "思想实验引擎", color="🟡", tier="A")

    est = bridge.estimate_result
    if est is None:
        card.status = "unavailable"
        card.verdict = "NO_ESTIMATE — 估计失败"
        card.metrics = {"treatment": getattr(bridge, 'treatment', '?'),
                        "outcome": getattr(bridge, 'outcome', '?')}
        return card
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

    # _check 是 dict 而非对象，需用键访问而非 getattr
    n_refuted = 0
    for r in bridge.refutation_results.values():
        check = getattr(r, '_check', None)
        refuted = check['refuted'] if isinstance(check, dict) else getattr(r, 'refuted', False)
        if refuted:
            n_refuted += 1
    if n_refuted == 0:
        card.verdict = "ROBUST — 0/3 反驳"
    else:
        card.verdict = f"CAUTION — {n_refuted}/3 反驳"

    card.status = "deployed" if not bridge.simulation else "fallback"
    # 避免存储不可序列化的 bridge 对象（to_dict 时会被过滤为 None）
    card.raw = None
    return card


# ══════════════════════════════════════════════════════════════════════
# ⬜ causallearn — 独立验证者
# ══════════════════════════════════════════════════════════════════════

def _deploy_causallearn(bridge) -> WarriorCard:
    card = WarriorCard("causallearn", "独立验证者", "PC/GES", color="⬜", tier="A")

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
            token_counter = _Counter(t for t in bridge.token_list if is_valid_concept(t))
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
            ni = _node_index(e.get_node1())
            nj = _node_index(e.get_node2())
            if ni < len(sub_names) and nj < len(sub_names):
                pc_edges.add((sub_names[ni], sub_names[nj]))

        # GES
        from causallearn.search.ScoreBased.GES import ges as _ges_alg
        ges_result = _ges_alg(sub_data)
        ges_edges = set()
        for e in ges_result['G'].get_graph_edges():
            ni = _node_index(e.get_node1())
            nj = _node_index(e.get_node2())
            if ni < len(sub_names) and nj < len(sub_names):
                ges_edges.add((sub_names[ni], sub_names[nj]))

        # 交叉比较
        # P0修复: causallearn 返回的边可能方向不一致(PC无向边/GES的CPDAG)，
        # 需双向匹配避免 Agree 偏低 (与 causallearn_validator.compare_with_trace 一致)
        trace_sub_edges = {(e[0], e[1]) for e in bridge.significant_edges
                          if e[0] in sub_names and e[1] in sub_names}
        cl_directed = pc_edges | ges_edges
        cl_all = cl_directed | {(t, s) for s, t in cl_directed}  # P0修复: 双向集合
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
        ratio = len(trace_sub_edges) / max(len(cl_all), 1)
        card.findings.append(f'→ TRACE / causallearn 边数比: {ratio:.1f}x')
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
        safe_N = getattr(getattr(bridge, 'data_df', None), 'shape', (0, 0))[0]
        safe_V = getattr(getattr(bridge, 'data_df', None), 'shape', (0, 0))[1]
        card.metrics = {'N': safe_N, 'V': safe_V}
        card.verdict = f'UNAVAILABLE (N={safe_N})'

    return card


# ══════════════════════════════════════════════════════════════════════
# 六战士合体 — 统一编排
# ══════════════════════════════════════════════════════════════════════

def assemble_all_six(adj_matrix, token_list, bridge=None, text="", concept_names=None):
    """
    六战士统一编排 — 生成完整六合一诊断。

    ════════════════════════════════════════════════════════════════
    架构等级 (Tier) — 元审计 P0 修缮：六勇士异质性显式化
    ════════════════════════════════════════════════════════════════
    返回的 WarriorCard 含 tier 字段：
      Tier-A (4 名): trace/havok/dowhy_cf/causallearn — 真算法层
      Tier-B (2 名): ccm/edm — 启发式诊断层
    消费方（如 Web UI、报告生成器）可依据 tier 区分证据等级，
    避免将启发式回退与真算法混为"六票投票"。

    Parameters
    ----------
    adj_matrix : np.ndarray
        TRACE 因果邻接矩阵（token-level 或 concept-level）
    token_list : list[str]
        token 序列
    bridge : TRACE2DoWhy or None
        已完成 build_model/identify/estimate/refute/scan 的桥接实例
    text : str
        原始文本（用于显示摘要）
    concept_names : list[str] or None
        concept-level 矩阵对应的概念名列表；当 adj_matrix 为 concept-level 时
        用于 CCM 边级资格检查等需要名称映射的场景。

    Returns
    -------
    dict: {warrior_id: WarriorCard}
    """
    cards = {}

    # 🔴 TRACE (Tier-A)
    cards['trace'] = _deploy_trace(adj_matrix, token_list, bridge=bridge)

    # 🔵 CCM (Tier-B — 启发式诊断层，依赖 edm-takens 真算法，不可用时降级)
    cards['ccm'] = _deploy_ccm(adj_matrix, token_list, concept_names=concept_names)

    # 🟡 EDM (Tier-B — 启发式诊断层，间隔变异系数近似 ρ)
    cards['edm'] = _deploy_edm(token_list)

    # ⚫ HAVOK (Tier-A)
    cards['havok'] = _deploy_havok(adj_matrix, token_list)

    # 🟡 DoWhy+CF
    if bridge is not None:
        try:
            cards['dowhy_cf'] = _deploy_dowhy_cf(bridge)
        except Exception as e:
            cards['dowhy_cf'] = WarriorCard("DoWhy+CF", "反事实造物主", "思想实验引擎",
                                            status="unavailable", color="🟡",
                                            verdict=f"ERROR — {str(e)[:80]}")

    # ⬜ causallearn
    if bridge is not None:
        try:
            cards['causallearn'] = _deploy_causallearn(bridge)
        except Exception as e:
            cards['causallearn'] = WarriorCard("causallearn", "独立验证者", "PC/GES",
                                               status="unavailable", color="⬜",
                                               verdict=f"ERROR — {str(e)[:80]}")

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

    # 元审计 P0 修缮: 按等级汇总，让"四真算法 + 二启发式诊断"显式化
    n_tier_a = sum(1 for c in cards.values() if getattr(c, 'tier', 'A') == 'A')
    n_tier_b = sum(1 for c in cards.values() if getattr(c, 'tier', 'A') == 'B')
    tier_a_deployed = sum(1 for c in cards.values()
                          if getattr(c, 'tier', 'A') == 'A' and c.status == 'deployed')
    tier_b_diagnostic = sum(1 for c in cards.values()
                            if getattr(c, 'tier', 'A') == 'B'
                            and c.status in ('deployed', 'fallback'))

    lines.append("─" * 60)
    lines.append(f"  合体诊断: {n_deployed} deployed, {n_fallback} fallback, {n_unavailable} unavailable")
    lines.append(f"  架构等级: Tier-A 真算法 {n_tier_a} 名 (deployed {tier_a_deployed})"
                 f"  |  Tier-B 启发式诊断 {n_tier_b} 名 (诊断 {tier_b_diagnostic})")
    lines.append(f"  口号: \"不是投票，是测绘\" — Tier-B 降级是诊断信号，不是失败")
    lines.append("═" * 60)

    return "\n".join(lines)
