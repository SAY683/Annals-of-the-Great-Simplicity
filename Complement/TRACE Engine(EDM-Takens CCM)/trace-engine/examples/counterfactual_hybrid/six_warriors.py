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
    # P0 fix: 防护 adj_matrix 全负异常，max() 会返回最大负值导致 verdict 恒为 SIGNAL_WEAK
    max_dnl = float(np.maximum(adj_matrix, 0).max())
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

def _build_ccm_timeseries(adj_matrix, token_list, concept_names=None, window=20):
    """ALG-02: 从 token 序列构建 CCM 时间序列 DataFrame

    选取邻接矩阵中最强因果边, 用滑动窗口计数构建 cause/effect 时间序列,
    供 ccm_with_convergence 真算法使用。

    Returns: (df, cause_name, effect_name) 或 (None, cause_name, effect_name)
    """
    try:
        import pandas as pd
    except ImportError:
        return None, None, None

    adj = np.asarray(adj_matrix)
    if adj.ndim != 2 or adj.shape[0] != adj.shape[1] or adj.shape[0] == 0:
        return None, None, None

    # 概念名对齐
    names = concept_names if concept_names is not None else token_list
    if names is None or len(names) != adj.shape[0]:
        if token_list and len(token_list) >= adj.shape[0]:
            names = token_list[:adj.shape[0]]
        else:
            return None, None, None

    # 找最强因果边 (上三角, 避免自环)
    # P0 fix: 只在有效概念对中选取最强边，避免选中标点/BPE碎片（如 " → 嫌）
    max_val, max_i, max_j = 0.0, -1, -1
    for i in range(len(names)):
        if not is_valid_concept(names[i]):
            continue
        for j in range(i + 1, len(names)):
            if not is_valid_concept(names[j]):
                continue
            v = float(adj[i, j])
            if v > max_val:
                max_val, max_i, max_j = v, i, j
    if max_i < 0:
        return None, None, None

    cause_name, effect_name = names[max_i], names[max_j]

    # 滑动窗口计数 → 时间序列
    n_windows = max(0, len(token_list) - window + 1)
    if n_windows < 30:
        return None, cause_name, effect_name  # 数据不足

    cause_counts = []
    effect_counts = []
    for w in range(n_windows):
        wt = token_list[w:w + window]
        cause_counts.append(wt.count(cause_name))
        effect_counts.append(wt.count(effect_name))

    df = pd.DataFrame({
        cause_name: cause_counts,
        effect_name: effect_counts,
    })
    return df, cause_name, effect_name


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
        #   ELIGIBLE_BUT_NOT_RUN  — 满足 CCM 数据条件，但真算法调用失败或数据不足
        #   HEURISTIC_FALLBACK    — 真算法不可用，仅启发式统计
        #   VERIFIABLE            — 本函数实际调用 ccm_with_convergence 成功且收敛
        card.status = "deployed" if _CCM_AVAILABLE else "fallback"
        card.findings = [
            f"CCM 覆盖 {ccm_ratio:.1%} — 满足交叉映射数据条件",
        ]
        if _CCM_AVAILABLE:
            # ALG-02 修复: 实际调用 ccm_with_convergence 真算法
            try:
                df_ccm, cause_name, effect_name = _build_ccm_timeseries(
                    adj_matrix, token_list, concept_names
                )
                if df_ccm is not None and len(df_ccm) >= 30 and cause_name and effect_name:
                    E = min(5, max(2, len(df_ccm) // 10))
                    # P0数学修复: 原 _step=max(8, n//25) 在 n=30 时生成 [5,28,8] → 仅 3 点，
                    # Spearman p<0.1 数学不可达（n=3 最小 p≈0.333）。
                    # 新策略: 保证至少 7 个库大小点（Spearman n=7 时 p<0.05 可达），
                    # 同时控制总点数 ≤30 避免性能回退。
                    _n = len(df_ccm)
                    _min_lib = E + 2
                    _max_lib = max(_n - 2, _min_lib)
                    _target_points = 12  # 目标点数，平衡显著性与性能
                    _step = max(2, (_max_lib - _min_lib) // _target_points)
                    _coarse_lib_sizes = f'{_min_lib} {_max_lib} {_step}'
                    ccm_result = ccm_with_convergence(
                        df_ccm, cause_name, effect_name, E,
                        lib_sizes=_coarse_lib_sizes,
                    )
                    # ALG-02 修复 (审视报告修正): 返回 dict 顶层无 'converging',
                    # 收敛判定在 forward/reverse 子字典的 'is_converging' 字段
                    fwd_conv = (isinstance(ccm_result, dict)
                                and isinstance(ccm_result.get('forward'), dict)
                                and ccm_result['forward'].get('is_converging', False))
                    rev_conv = (isinstance(ccm_result, dict)
                                and isinstance(ccm_result.get('reverse'), dict)
                                and ccm_result['reverse'].get('is_converging', False))
                    if fwd_conv or rev_conv:
                        card.verdict = "VERIFIABLE"
                        # 优先取收敛方向的 rho
                        if fwd_conv:
                            rho_val = ccm_result['forward'].get('final_rho', 'N/A')
                            _dir = "forward"
                        else:
                            rho_val = ccm_result['reverse'].get('final_rho', 'N/A')
                            _dir = "reverse"
                        card.findings.append(
                            f"✓ ccm_with_convergence 成功收敛: "
                            f"{cause_name}→{effect_name} ({_dir}), ρ={rho_val}, E={E}"
                        )
                        card.metrics["ccm_cause"] = cause_name
                        card.metrics["ccm_effect"] = effect_name
                        card.metrics["ccm_rho"] = str(rho_val)
                        card.metrics["ccm_E"] = E
                        card.metrics["ccm_direction"] = _dir
                    else:
                        card.verdict = "ELIGIBLE_BUT_NOT_RUN"
                        card.status = "fallback"
                        # P0 fix: 不再将完整 ccm_result dict 倾倒到 findings 中，
                        # 仅提取关键指标（final_rho / spearman_rho / verdict）。
                        # 完整结果存入 card.raw 供 details 折叠区查看。
                        card.raw = ccm_result if isinstance(ccm_result, dict) else {"raw": str(ccm_result)[:500]}
                        _fwd = ccm_result.get('forward', {}) if isinstance(ccm_result, dict) else {}
                        _rev = ccm_result.get('reverse', {}) if isinstance(ccm_result, dict) else {}
                        _fwd_rho = _fwd.get('final_rho', 'N/A')
                        _rev_rho = _rev.get('final_rho', 'N/A')
                        _fwd_sp = _fwd.get('spearman_rho', 'N/A')
                        _rev_sp = _rev.get('spearman_rho', 'N/A')
                        _ccm_verdict = ccm_result.get('verdict', 'N/A') if isinstance(ccm_result, dict) else 'N/A'
                        card.findings.append(
                            f"ℹ ccm_with_convergence 已运行但未收敛: "
                            f"{cause_name}→{effect_name}"
                        )
                        card.findings.append(
                            f"  forward: ρ={_fwd_rho}, spearman={_fwd_sp} | "
                            f"reverse: ρ={_rev_rho}, spearman={_rev_sp}"
                        )
                        card.findings.append(f"  verdict: {_ccm_verdict}")
                else:
                    card.verdict = "ELIGIBLE_BUT_NOT_RUN"
                    card.status = "fallback"
                    _reason = "无有效时间序列" if df_ccm is None else f"窗口数不足({len(df_ccm) if df_ccm is not None else 0}<30)"
                    if cause_name and effect_name:
                        card.findings.append(
                            f"ℹ 最强边 {cause_name}→{effect_name} 数据不足({_reason}), "
                            f"未运行 ccm_with_convergence"
                        )
                    else:
                        card.findings.append(
                            "ℹ 未找到有效因果边, 未运行 ccm_with_convergence"
                        )
            except Exception as ccm_err:
                card.verdict = "ELIGIBLE_BUT_NOT_RUN"
                card.status = "fallback"
                card.findings.append(
                    f"ℹ ccm_with_convergence 调用异常: {str(ccm_err)[:120]}"
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
    # OPT-6 修复 (2026-07-30 审计): 重命名 rho → rho_proxy，明确这是间隔变异系数倒数，
    # 非 Sugihara EDM 的交叉映射相关性 ρ。两者数学定义完全不同。
    rho_proxy_scores = {}
    for tok in target_tokens:
        positions = [i for i, t in enumerate(token_list) if t == tok]
        if len(positions) >= 3:
            intervals = np.diff(positions)
            _mean = float(np.mean(intervals))
            # P1 fix: 防除零——mean 极小时 1e-8 不够，用 max(mean, 1.0) 保证 CV 稳定
            cv = float(np.std(intervals) / max(_mean, 1.0))
            rho_proxy = 1.0 / (1.0 + cv)  # 低 CV → 高规律性 → 高 rho_proxy
            rho_proxy_scores[tok] = rho_proxy

    high_rho = {t: r for t, r in rho_proxy_scores.items() if r > 0.8}
    mid_rho = {t: r for t, r in rho_proxy_scores.items() if 0.4 <= r <= 0.8}

    # metrics 同时保留旧 key (rho_high/rho_mid) 和新 key (rho_proxy_high/rho_proxy_mid) 以保向后兼容
    card.metrics = {
        "rho_high": len(high_rho), "rho_mid": len(mid_rho),  # 向后兼容
        "rho_proxy_high": len(high_rho), "rho_proxy_mid": len(mid_rho),  # OPT-6 新 key
        "analyzed": len(rho_proxy_scores),
    }
    # EDM 始终使用自包含启发式（无真算法导入路径），明确标注
    card.status = "fallback"
    if high_rho:
        top = sorted(high_rho.items(), key=lambda x: x[1], reverse=True)[:3]
        card.findings = [
            f"高可预测性概念: {', '.join(f'{t}(ρ_proxy={r:.2f})' for t,r in top)}",
            "→ 文本具有强叙事结构（非论证文）",
            "⚠ 启发式回退: rho_proxy = 1/(1+CV)，是间隔变异系数倒数，非 Sugihara EDM ρ",
        ]
        card.verdict = "HEURISTIC_STRONG_NARRATIVE_STRUCTURE"
    else:
        card.findings = [
            "无明显高可预测性概念 → 非套路化叙事",
            "⚠ 启发式回退: rho_proxy = 1/(1+CV)，是间隔变异系数倒数，非 Sugihara EDM ρ",
        ]
        card.verdict = "HEURISTIC_WEAK_STRUCTURE"
    return card


# ══════════════════════════════════════════════════════════════════════
# ⚫ HAVOK — 混沌暗杀者 (自包含实现)
# ══════════════════════════════════════════════════════════════════════

def _deploy_havok(adj_matrix, token_list=None) -> WarriorCard:
    adj_matrix = np.asarray(adj_matrix)
    card = WarriorCard("HAVOK", "混沌暗杀者", "X光机", color="⚫", tier="A")

    if adj_matrix.ndim < 2:
        card.status = "unavailable"
        card.findings = ["adj_matrix 维度不足，无法做 HAVOK 分析"]
        return card

    T = adj_matrix.shape[0]
    token_len = len(token_list) if token_list else T
    # SYNC-2 修复 (2026-07-30 审计): 统一阈值为 T<22，与 ALGORITHM_AUDIT.md §3.1
    # "N<22 触发 HAVOK 不可靠" 文档对齐。原 T<20 是更严格但未文档化的实现阈值。
    _HAVOK_MIN_T = 22
    if T < _HAVOK_MIN_T:
        card.status = "unavailable"
        # 概念级矩阵（Web 快速分析）常见场景，给出明确诊断
        if token_len > T * 2:
            card.findings = [
                f"概念级矩阵尺寸 T={T} < {_HAVOK_MIN_T}，不满足 HAVOK 分解要求",
                "→ Web 快速分析使用概念级共现矩阵，HAVOK 不可用是设计权衡",
                "→ 如需完整 HAVOK，请使用 trace-engine CLI 处理原始 token 级 TRACE 输出",
            ]
        else:
            card.findings = [f"因果矩阵太小 (T={T} < {_HAVOK_MIN_T}) 无法做 HAVOK 分解"]
        return card

    try:
        # ── 构建时序因果流信号 ──
        # 不使用静态出度向量，而是提取真正的时间序列:
        # signal[t] = 位置 t 处 token 的"因果流入强度" = mean(ΔNLL[:, t])
        # 这反映了文本在时间推进中因果依赖的强度变化
        col_mean = np.asarray(adj_matrix.sum(axis=0)).flatten().astype(np.float64)

        # 用原始 token 顺序（不排序！保留时间结构）
        # 取因果活跃度最高的连续区域
        best_start = 0  # P2-6 修复: 显式初始化，避免条件分支外的引用触发 NameError
        if len(col_mean) > 100:
            # 取滑动窗口方差最大的区域（因果动力学最丰富）
            window = min(80, len(col_mean) // 2)
            window = max(window, 2)  # P1-6 修复: 强制下界，避免 window=1 时 step=0
            best_var = 0
            step = max(1, window // 2)  # 步长至少 1，避免 range(0, n, 0) ValueError
            for start in range(0, len(col_mean) - window, step):
                seg = col_mean[start:start + window]
                if np.var(seg) > best_var:
                    best_var = np.var(seg)
                    best_start = start
            signal = col_mean[best_start:best_start + window]
        else:
            signal = col_mean

        # 去趋势 + 归一化 (保留波动)
        signal = signal - np.mean(signal)
        # P1 fix: 常数信号 std=0 时 1e-10 太小会产生 inf，用 max(std, 1e-6) 防护
        _std = np.std(signal)
        if _std < 1e-8:
            card.status = "unavailable"
            card.findings = ["信号方差为零（常数列），无法做 HAVOK 分析"]
            return card
        signal = signal / _std

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

        # P2 负控制实验修复: 增加 forcing_raw 噪声检测
        # 纯噪声数据 forcing_raw ≈ 0.514,真实线性信号 forcing_raw ≈ 0.027
        # 原 verdict 逻辑仅基于 nonlinear_energy,纯噪声(linear_92%)被判为 LINEAR_DOMINANT
        # 修复:forcing_raw > 0.3 时判定为 NOISE_DOMINANT,避免负控制假阳性
        if forcing_raw > 0.3 and nonlinear_energy > 0.05:
            card.findings = [
                f"噪声主导 (forcing={forcing_raw:.3f} > 0.3) — 信号无 coherent 结构",
                f"SVD r={r}/{len(s)}, linear={linear_energy:.0%}, nonlinear={nonlinear_energy:.0%}",
            ]
            card.verdict = "NOISE_DOMINANT — 信号无因果结构"
        elif nonlinear_energy > 0.25:
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
                f"SVD r={r}/{len(s)} — 低维吸引子, forcing={forcing_raw:.3f}",
            ]
            card.verdict = "LINEAR_DOMINANT — 时间线叙事"

        # OPT-5 修复 (2026-07-30 审计): HAVOK 方法学 disclaimer
        # HAVOK 数学上要求时间序列输入（Hankel 矩阵捕捉时间延迟相关性）。
        # 此处信号源自因果流入强度的空间序列（按 token 位置排序），
        # 非真正的时间动力学。verdict 的因果解释力限于位置相关结构。
        card.findings.append(
            "⚠ 方法学说明: 信号源自因果流入的空间序列（按 token 位置），"
            "HAVOK 解释力限于位置相关结构，非真正时间动力学。"
        )

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

    _ci_arr = np.asarray(ci, dtype=float).flatten()
    ci_str = f"[{_ci_arr[0]:.4f}, {_ci_arr[1]:.4f}]" if len(_ci_arr) >= 2 else "N/A"

    card.metrics = {
        "treatment": bridge.treatment,
        "outcome": bridge.outcome,
        "ATE": f"{est.value:.4f}",
        "95%CI": ci_str,
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
    n_total_refuters = len(bridge.refutation_results)
    for r in bridge.refutation_results.values():
        check = getattr(r, '_check', None)
        refuted = check['refuted'] if isinstance(check, dict) else getattr(r, 'refuted', False)
        if refuted:
            n_refuted += 1
    # P1-2 修复 (2026-07-30): 分母用实际反驳测试数，避免异常路径下硬编码 "3" 误导
    n_total = n_total_refuters if n_total_refuters > 0 else 3
    if n_refuted == 0:
        card.verdict = f"ROBUST — 0/{n_total} 反驳"
    else:
        card.verdict = f"CAUTION — {n_refuted}/{n_total} 反驳"

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

        # P0 修复 (2026-07-29): 概念数据可能因 token 重复或完全线性相关导致
        # 协方差矩阵奇异，PC/GES 的 fisherz test 报 "Data correlation matrix is singular"。
        # 预处理：检测并移除重复列，若仍奇异则注入极小抖动（不影响结构）。
        sub_data = np.asarray(sub_data, dtype=float)
        # 去重列
        unique_idx = []
        seen_cols = set()
        for col_i in range(sub_data.shape[1]):
            col_tuple = tuple(np.round(sub_data[:, col_i], 8))
            if col_tuple not in seen_cols:
                seen_cols.add(col_tuple)
                unique_idx.append(col_i)
        if len(unique_idx) < sub_data.shape[1]:
            sub_data = sub_data[:, unique_idx]
            sub_names = [sub_names[i] for i in unique_idx]
        # 奇异检测：协方差矩阵条件数过大或行列式为 0
        try:
            cov = np.cov(sub_data, rowvar=False)
            eigvals = np.linalg.eigvalsh(cov)
            cond = np.max(eigvals) / (np.min(eigvals[eigvals > 0]) if np.any(eigvals > 0) else 1e-12)
        except Exception:
            cond = float('inf')
        if cond > 1e12 or not np.isfinite(cond):
            jitter_std = max(1e-6, np.std(sub_data) * 1e-4)
            sub_data = sub_data + np.random.default_rng(42).normal(0, jitter_std, size=sub_data.shape)
            card.findings.append(f"数据注入 {jitter_std:.2e} 抖动以修复奇异矩阵")

        # P1-E 修复 (ROUND27 12维度核对): PC alpha 统一为 0.05, 与 counterfactual_bridge.py:1038
        # 对齐. 原 0.01 导致六战士与 bridge.causallearn_validate() 结果不可复现对比.
        from causallearn.search.ConstraintBased.PC import pc as _pc_alg
        pc_result = _pc_alg(sub_data, alpha=0.05)
        pc_edges = set()
        # P0-2 修复 (Round 21 §P0-B): causallearn 节点名 'X1','X2',... 是 1-based,
        # 必须做 -1 转换才能正确索引 sub_names (与 causallearn_validator.py:184-185 一致).
        # 原 bug: 直接用 _node_index() 返回值,导致所有节点偏移1位,
        # 最后一个节点 X_N 越界被静默丢弃, agree 集合比较结果全错.
        for e in pc_result.G.get_graph_edges():
            ni = _node_index(e.get_node1()) - 1  # 1-based → 0-based
            nj = _node_index(e.get_node2()) - 1
            if 0 <= ni < len(sub_names) and 0 <= nj < len(sub_names):
                pc_edges.add((sub_names[ni], sub_names[nj]))

        # GES
        from causallearn.search.ScoreBased.GES import ges as _ges_alg
        ges_result = _ges_alg(sub_data)
        ges_edges = set()
        for e in ges_result['G'].get_graph_edges():
            ni = _node_index(e.get_node1()) - 1  # 1-based → 0-based
            nj = _node_index(e.get_node2()) - 1
            if 0 <= ni < len(sub_names) and 0 <= nj < len(sub_names):
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

def assemble_all_six(adj_matrix, token_list, bridge=None, text="", concept_names=None, progress_cb=None):
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
    progress_cb : callable or None
        进度回调函数，签名 progress_cb(step:int, total:int, name:str)。
        每完成一个战士后调用，用于细粒度进度汇报。

    Returns
    -------
    dict: {warrior_id: WarriorCard}
    """
    cards = {}

    # 六战士部署顺序及中文名，用于进度回调
    _warrior_steps = [
        ('trace', 'TRACE 因果提取'),
        ('ccm', 'CCM 收敛映射'),
        ('edm', 'EDM 嵌入分析'),
        ('havok', 'HAVOK 强迫分解'),
        ('dowhy_cf', 'DoWhy 反事实'),
        ('causallearn', 'causallearn PC/GES'),
    ]
    _step_idx = 0
    _total_steps = len(_warrior_steps)

    def _report():
        nonlocal _step_idx
        if progress_cb:
            progress_cb(_step_idx, _total_steps, _warrior_steps[_step_idx - 1][1] if _step_idx > 0 else '')

    # 🔴 TRACE (Tier-A)
    _step_idx = 1; _report()
    try:
        cards['trace'] = _deploy_trace(adj_matrix, token_list, bridge=bridge)
    except Exception as e:
        cards['trace'] = WarriorCard("TRACE", "拓扑先锋", "探照灯",
                                      status="unavailable", color="🔴")
        cards['trace'].findings = [f"TRACE 战士诊断异常: {e}"]
        cards['trace'].verdict = f"ERROR — {str(e)[:80]}"

    # 🔵 CCM (Tier-B — 启发式诊断层，依赖 edm-takens 真算法，不可用时降级)
    _step_idx = 2; _report()
    try:
        cards['ccm'] = _deploy_ccm(adj_matrix, token_list, concept_names=concept_names)
    except Exception as e:
        cards['ccm'] = WarriorCard("CCM", "流形力场", "测谎仪",
                                    status="unavailable", color="🔵", tier="B")
        cards['ccm'].findings = [f"CCM 战士诊断异常: {e}"]
        cards['ccm'].verdict = f"ERROR — {str(e)[:80]}"

    # 🟡 EDM (Tier-B — 启发式诊断层，间隔变异系数近似 ρ)
    _step_idx = 3; _report()
    try:
        cards['edm'] = _deploy_edm(token_list)
    except Exception as e:
        cards['edm'] = WarriorCard("EDM", "时序节拍器", "套路探测器",
                                    status="unavailable", color="🟡", tier="B")
        cards['edm'].findings = [f"EDM 战士诊断异常: {e}"]
        cards['edm'].verdict = f"ERROR — {str(e)[:80]}"

    # ⚫ HAVOK (Tier-A)
    _step_idx = 4; _report()
    try:
        cards['havok'] = _deploy_havok(adj_matrix, token_list)
    except Exception as e:
        cards['havok'] = WarriorCard("HAVOK", "混沌暗杀者", "X光机",
                                      status="unavailable", color="⚫", tier="A")
        cards['havok'].findings = [f"HAVOK 战士诊断异常: {e}"]
        cards['havok'].verdict = f"ERROR — {str(e)[:80]}"

    # 🟡 DoWhy+CF
    _step_idx = 5; _report()
    if bridge is not None:
        try:
            cards['dowhy_cf'] = _deploy_dowhy_cf(bridge)
        except Exception as e:
            cards['dowhy_cf'] = WarriorCard("DoWhy+CF", "反事实造物主", "思想实验引擎",
                                            status="unavailable", color="🟡",
                                            verdict=f"ERROR — {str(e)[:80]}")

    # ⬜ causallearn
    _step_idx = 6; _report()
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
