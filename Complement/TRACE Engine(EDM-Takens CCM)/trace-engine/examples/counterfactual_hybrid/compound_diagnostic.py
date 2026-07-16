"""
Compound Diagnostic Engine — 复合诊断引擎
==========================================
将六战士（TRACE/CCM/EDM/HAVOK/DoWhy/causallearn）的诊断卡片
按 DESIGN_SIX_IN_ONE.md 3.2 节规则矩阵进行跨战士聚合判定，
产出文本类型分类与复合诊断结论。

规则矩阵:
  1. CCM fails + EDM ρ>0.9 + HAVOK linear>80%
     → 叙事文（结构清晰的线性叙事）
  2. CCM converges + EDM ρ moderate + HAVOK nonlinear>30%
     → 论证文（递归逻辑纠缠）
  3. TRACE sparse + CCM fails + EDM ρ intermediate + HAVOK linear>70%
     → 说明文（描述性文本，无深层因果结构）

用法:
    from compound_diagnostic import CompoundDiagnosticEngine

    engine = CompoundDiagnosticEngine()
    result = engine.diagnose(cards)
    print(result['text_type'])        # "叙事文" / "论证文" / "说明文" / "混合/不确定"
    print(result['confidence'])       # 0.0 - 1.0
    print(result['reasoning'])        # 判定依据链
"""

from typing import Optional


def _parse_percentage(s) -> float:
    """从 '85%' 或 '0.85' 等格式提取浮点数

    修复 debt-04 audit：原实现 rstrip('%') 后再判断 '%' in s 永远为 False，
    且对 '0.85' 错误除以 100 返回 0.0085。
    """
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        raw = s.strip()
        has_percent = '%' in raw
        cleaned = raw.rstrip('%').strip()
        try:
            value = float(cleaned)
            # 含 '%' 后缀：除以 100；否则：值已是 [0,1] 区间
            return value / 100.0 if has_percent else value
        except ValueError:
            return 0.0
    return 0.0


def _parse_float(s) -> float:
    """从字符串或数字提取浮点数"""
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


class CompoundDiagnosticEngine:
    """复合诊断引擎：跨战士聚合判定。

    接受 dict[str, WarriorCard] 输入，按规则矩阵产出复合判定。
    每条规则由若干条件组成，全部满足时触发该规则的判定。
    当多条规则同时触发或均不触发时，返回"混合/不确定"。
    """

    # 规则矩阵: (rule_name, conditions_callable, text_type, confidence)
    # conditions_callable 接收 extracted_metrics dict，返回 bool

    def diagnose(self, cards: dict) -> dict:
        """对六战士卡片做复合诊断。

        Parameters
        ----------
        cards : dict[str, WarriorCard]
            由 assemble_all_six 返回的卡片字典

        Returns
        -------
        dict with keys:
            text_type: str          — 文本类型判定
            confidence: float       — 置信度 0.0-1.0
            reasoning: list[str]    — 判定依据链
            rule_matched: str       — 匹配的规则名（或 "NONE" / "CONFLICT"）
            metrics_extracted: dict — 从各战士提取的指标
        """
        m = self._extract_metrics(cards)

        rules = [
            ("RULE_1_NARRATIVE", self._rule_narrative, "叙事文", 0.85),
            ("RULE_2_ARGUMENTATIVE", self._rule_argumentative, "论证文", 0.85),
            ("RULE_3_DESCRIPTIVE", self._rule_descriptive, "说明文", 0.75),
        ]

        matched = []
        reasoning = []

        for name, cond_fn, text_type, conf in rules:
            if cond_fn(m):
                matched.append((name, text_type, conf))
                reasoning.append(f"✓ {name} 触发 → {text_type}")

        if len(matched) == 1:
            name, text_type, conf = matched[0]
            reasoning.append(f"单一规则匹配，置信度 {conf:.0%}")
            return {
                "text_type": text_type,
                "confidence": conf,
                "reasoning": reasoning,
                "rule_matched": name,
                "metrics_extracted": m,
            }
        elif len(matched) > 1:
            types = [t for _, t, _ in matched]
            reasoning.append(f"⚠ 多规则冲突: {types}，降级为混合判定")
            return {
                "text_type": "混合/不确定",
                "confidence": 0.4,
                "reasoning": reasoning,
                "rule_matched": "CONFLICT",
                "metrics_extracted": m,
            }
        else:
            reasoning.append("无规则完全匹配，标记为混合/不确定")
            # 尝试部分匹配给出倾向性提示
            hints = self._partial_match_hints(m)
            reasoning.extend(hints)
            return {
                "text_type": "混合/不确定",
                "confidence": 0.3,
                "reasoning": reasoning,
                "rule_matched": "NONE",
                "metrics_extracted": m,
            }

    def _extract_metrics(self, cards: dict) -> dict:
        """从 WarriorCard 字典提取复合诊断所需指标

        修复 debt-04 audit：six_warriors.assemble_all_six 产出小写键
        ('trace'/'ccm'/'edm'/'havok')，原实现查找大写键致引擎恒输出默认值。
        现同时支持大小写键。
        """
        m = {
            "trace_edges": 0,
            "trace_sparse": True,
            "ccm_failed": True,
            "ccm_converged": False,
            "edm_rho_high": False,
            "edm_rho_moderate": False,
            "edm_rho_intermediate": False,
            "havok_linear_pct": 0.0,
            "havok_nonlinear_pct": 0.0,
            "havok_available": False,
        }

        def _card(name):
            """大小写兼容取卡片"""
            return cards.get(name) or cards.get(name.lower()) or cards.get(name.upper())

        # TRACE
        trace = _card("TRACE")
        if trace and trace.metrics:
            edges = trace.metrics.get("edges", 0)
            m["trace_edges"] = int(edges) if edges else 0
            m["trace_sparse"] = m["trace_edges"] < 5

        # CCM
        ccm = _card("CCM")
        if ccm:
            # CCM fails: status 为 unavailable 或 fallback 且 verdict 非 VERIFIABLE
            if ccm.status in ("unavailable", "fallback"):
                m["ccm_failed"] = True
                m["ccm_converged"] = False
            elif ccm.status == "deployed" and ccm.verdict == "VERIFIABLE":
                m["ccm_failed"] = False
                m["ccm_converged"] = True
            else:
                m["ccm_failed"] = True
                m["ccm_converged"] = False

        # EDM
        edm = _card("EDM")
        if edm and edm.metrics:
            rho_high = edm.metrics.get("rho_high", 0)
            rho_mid = edm.metrics.get("rho_mid", 0)
            m["edm_rho_high"] = int(rho_high) > 0
            m["edm_rho_moderate"] = int(rho_mid) > 0 and not m["edm_rho_high"]
            m["edm_rho_intermediate"] = int(rho_mid) > 0

        # HAVOK
        havok = _card("HAVOK")
        if havok and havok.metrics and havok.status == "deployed":
            m["havok_available"] = True
            m["havok_linear_pct"] = _parse_percentage(havok.metrics.get("linear_%", "0%"))
            m["havok_nonlinear_pct"] = _parse_percentage(havok.metrics.get("nonlinear_%", "0%"))

        return m

    def _rule_narrative(self, m: dict) -> bool:
        """规则1: CCM fails + EDM ρ>0.9 + HAVOK linear>80% → 叙事文"""
        return (
            m["ccm_failed"]
            and m["edm_rho_high"]
            and m["havok_available"]
            and m["havok_linear_pct"] > 0.80
        )

    def _rule_argumentative(self, m: dict) -> bool:
        """规则2: CCM converges + EDM ρ moderate + HAVOK nonlinear>30% → 论证文"""
        return (
            m["ccm_converged"]
            and m["edm_rho_moderate"]
            and m["havok_available"]
            and m["havok_nonlinear_pct"] > 0.30
        )

    def _rule_descriptive(self, m: dict) -> bool:
        """规则3: TRACE sparse + CCM fails + EDM ρ intermediate + HAVOK linear>70% → 说明文"""
        return (
            m["trace_sparse"]
            and m["ccm_failed"]
            and m["edm_rho_intermediate"]
            and m["havok_available"]
            and m["havok_linear_pct"] > 0.70
        )

    def _partial_match_hints(self, m: dict) -> list:
        """当无规则完全匹配时，给出倾向性提示"""
        hints = []
        if m["ccm_failed"] and m["edm_rho_high"]:
            hints.append("  提示: CCM 失败 + EDM 高 ρ → 偏叙事文特征")
        if m["ccm_converged"] and m["havok_nonlinear_pct"] > 0.30:
            hints.append("  提示: CCM 收敛 + HAVOK 非线性显著 → 偏论证文特征")
        if m["trace_sparse"] and m["ccm_failed"]:
            hints.append("  提示: TRACE 稀疏 + CCM 失败 → 偏说明文特征")
        if not hints:
            hints.append("  提示: 各战士指标不足以做倾向性判定")
        return hints


def render_compound_diagnosis(result: dict) -> str:
    """将复合诊断结果渲染为文本报告章节"""
    lines = [
        "═══ 复合诊断结论 ═══",
        f"文本类型: {result['text_type']}",
        f"置信度: {result['confidence']:.0%}",
        f"匹配规则: {result['rule_matched']}",
        "",
        "判定依据:",
    ]
    for r in result.get("reasoning", []):
        lines.append(f"  {r}")

    m = result.get("metrics_extracted", {})
    if m:
        lines.append("")
        lines.append("提取指标:")
        lines.append(f"  TRACE edges={m.get('trace_edges', 0)} (sparse={m.get('trace_sparse', '?')})")
        lines.append(f"  CCM failed={m.get('ccm_failed', '?')} converged={m.get('ccm_converged', '?')}")
        lines.append(f"  EDM rho_high={m.get('edm_rho_high', '?')} rho_moderate={m.get('edm_rho_moderate', '?')}")
        lines.append(f"  HAVOK linear={m.get('havok_linear_pct', 0):.0%} nonlinear={m.get('havok_nonlinear_pct', 0):.0%}")

    return "\n".join(lines)
