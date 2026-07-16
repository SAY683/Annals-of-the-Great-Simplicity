"""
DoWhy Counterfactual Auditor
=============================
对标 edm-takens/src/edm_auditor.py 的防火墙设计。

在执行 DoWhy 管线时，对每条 Forbidden Rule 进行强制检查。
采纳级别: FAIL (阻断), WARN (警告), ADVISORY (建议), DEFERRED (延后)

Usage:
    from dowhy_auditor import DoWhyAuditor
    auditor = DoWhyAuditor(bridge)
    report = auditor.audit()
    report.print_report()
    if report.verdict == 'FAIL':
        # 修复配置后重试
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class Enforcement(Enum):
    FAIL = "FAIL"        # 阻断 — 不允许继续
    WARN = "WARN"        # 警告 — 继续但标注风险
    ADVISORY = "ADVISORY" # 建议 — 信息性
    DEFERRED = "DEFERRED" # 延后 — 规则已知但未强制执行
    PASS = "PASS"         # 通过


@dataclass
class RuleCheck:
    """单条规则检查结果"""
    rule_id: int
    name: str
    enforcement: Enforcement
    status: Enforcement  # 实际状态
    message: str
    detail: str = ""
    data_requirement: str = ""


@dataclass
class AuditReport:
    """审计报告"""
    checks: list = field(default_factory=list)
    verdict: str = "PASS"  # PASS, WARN, FAIL

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if c.status == Enforcement.FAIL)

    @property
    def n_warn(self) -> int:
        return sum(1 for c in self.checks if c.status == Enforcement.WARN)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.status == Enforcement.PASS)

    @property
    def n_adopted(self) -> int:
        return sum(1 for c in self.checks
                   if c.status in (Enforcement.PASS, Enforcement.WARN,
                                   Enforcement.FAIL, Enforcement.ADVISORY))

    @property
    def n_deferred(self) -> int:
        return sum(1 for c in self.checks if c.status == Enforcement.DEFERRED)

    @property
    def adoption_rate(self) -> float:
        return self.n_adopted / max(len(self.checks), 1)

    def print_report(self):
        """打印人类可读的报告"""
        lines = [
            "=" * 60,
            f"DoWhy + Counterfactual Auditor Report",
            f"Verdict: {self.verdict}  "
            f"(FAIL={self.n_fail}, WARN={self.n_warn}, PASS={self.n_pass}, "
            f"DEFERRED={self.n_deferred})",
            f"Adoption Rate: {self.adoption_rate:.0%} ({self.n_adopted}/{len(self.checks)})",
            "=" * 60,
        ]
        for c in self.checks:
            icon = {'FAIL': '✗', 'WARN': '⚠', 'ADVISORY': 'ℹ',
                    'PASS': '✓', 'DEFERRED': '⏳'}[c.status.value]
            lines.append(f"  {icon} R{c.rule_id} [{c.enforcement.value:8s} → {c.status.value:8s}] {c.name}")
            lines.append(f"     {c.message}")
            if c.detail:
                lines.append(f"     Detail: {c.detail}")
        print("\n".join(lines))


class DoWhyAuditor:
    """
    DoWhy 管线防火墙 — 对标 edm-takens 的 14 Secret Auditor。

    在每一步关键操作前/后进行检查。
    """

    def __init__(self, bridge, **kwargs):
        """
        Parameters
        ----------
        bridge : TRACE2DoWhy
            已完成 build_model() 的桥接实例
        **kwargs : dict
            兼容 presets.yaml 的 auditor 参数（strict_mode, min_n_per_v_ratio 等），
            当前版本忽略未使用的参数，保持向前兼容。
        """
        self.bridge = bridge
        self._strict_mode = kwargs.get('strict_mode', False)
        self._min_n_per_v_ratio = kwargs.get('min_n_per_v_ratio', 5.0)
        self._checks: list[RuleCheck] = []

    def audit(self, stage: str = "post_build") -> AuditReport:
        """
        全量审计。

        Parameters
        ----------
        stage : str
            "post_build" — 构建模型后
            "post_identify" — 识别后
            "post_estimate" — 估计后
            "post_refute" — 反驳后
            "post_counterfactual" — 反事实后
            "full" — 全管线
        """
        self._checks = []

        if stage in ("post_build", "full"):
            self._check_graph_completeness()
            self._check_sparse_graph_sanity()

        if stage in ("post_identify", "full"):
            self._check_identifiability_gate()

        if stage in ("post_estimate", "full"):
            self._check_sem_stability()
            self._check_ci_non_degeneracy()

        if stage in ("post_refute", "full"):
            self._check_refutation_triangulation()
            self._check_placebo_vanishing()

        if stage in ("post_counterfactual", "full"):
            self._check_causal_direction_consistency()
            self._check_extrapolation_guard()

        return self._build_report()

    def _add(self, rule_id, name, enforcement, status, message, detail="",
             data_req=""):
        self._checks.append(RuleCheck(
            rule_id=rule_id, name=name, enforcement=enforcement,
            status=status, message=message, detail=detail,
            data_requirement=data_req,
        ))

    # ── R1: Identifiability Gate ──

    def _check_identifiability_gate(self):
        from counterfactual_bridge import DoWhy14Adapter
        bridge = self.bridge

        if bridge.identified_estimand is None:
            self._add(1, "Identifiability Gate", Enforcement.FAIL,
                      Enforcement.FAIL,
                      "无法识别因果效应 — treatment 到 outcome 没有有向路径。",
                      f"请选择有边的 treatment/outcome 对。"
                      f"Top edge: {bridge.significant_edges[0] if bridge.significant_edges else 'N/A'}",
                      "Treatment→Outcome directed path")
            return

        identifiable = DoWhy14Adapter.is_identifiable(bridge.identified_estimand)
        if identifiable:
            self._add(1, "Identifiability Gate", Enforcement.FAIL,
                      Enforcement.PASS,
                      "因果效应可识别。",
                      f"estimand_type = {bridge.identified_estimand.estimand_type}",
                      "Treatment→Outcome directed path")
        else:
            self._add(1, "Identifiability Gate", Enforcement.FAIL,
                      Enforcement.FAIL,
                      "因果效应不可识别。",
                      f"estimand_type = None。使用 strongest edge 的 source→target。",
                      "Treatment→Outcome directed path")

    # ── R2: Refutation Triangulation ──

    def _check_refutation_triangulation(self):
        bridge = self.bridge
        # _check 是 dict 而非对象，需用键访问而非 getattr
        n_refuted = 0
        for r in bridge.refutation_results.values():
            check = getattr(r, '_check', None)
            refuted = check['refuted'] if isinstance(check, dict) else getattr(r, 'refuted', False)
            if refuted:
                n_refuted += 1

        if not bridge.refutation_results:
            self._add(2, "Refutation Triangulation", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "无反驳数据 — 未运行 refute()。",
                      data_req="N >= 30")
        elif n_refuted >= 2:
            self._add(2, "Refutation Triangulation", Enforcement.WARN,
                      Enforcement.WARN,
                      f"{n_refuted}/3 反驳 — 因果估计不可靠。",
                      f"2+ refuters rejected the estimate.",
                      "N >= 30")
        else:
            self._add(2, "Refutation Triangulation", Enforcement.WARN,
                      Enforcement.PASS,
                      f"{n_refuted}/3 反驳 — 因果估计通过稳健性检查。",
                      data_req="N >= 30")

    # ── R3: SEM Coefficient Stability ──

    def _check_sem_stability(self):
        bridge = self.bridge
        if bridge.sem_coeff is None:
            self._add(3, "SEM Coefficient Stability", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "SEM 系数未估计。",
                      data_req="N >= 50, V < N/5")
            return

        raw = bridge.data_df.values if hasattr(bridge.data_df, 'values') else np.asarray(bridge.data_df)
        N = raw.shape[0]

        # 使用 DoWhy DOT 图中的有效概念数（而非全部概念）
        # 因为 DoWhy 在精简图上运行，SEM 稳定性取决于实际参与建模的变量数
        dot_nodes = set()
        for src, dst, _ in bridge.significant_edges:
            dot_nodes.add(src)
            dot_nodes.add(dst)
        dot_nodes.discard('<other>')
        V_eff = len(dot_nodes)

        if N < 2 * V_eff:
            self._add(3, "SEM Coefficient Stability", Enforcement.WARN,
                      Enforcement.FAIL,
                      f"样本量不足: N={N} < 2*V={2*V_eff}，SEM 系数极不稳定。",
                      f"增加样本或减少变量。",
                      f"N >= {5*V_eff}")
        elif N < 5 * V_eff:
            self._add(3, "SEM Coefficient Stability", Enforcement.WARN,
                      Enforcement.WARN,
                      f"样本量偏低: N={N} < 5*V={5*V_eff}，SEM 系数可能不稳定。",
                      f"建议增加样本量。",
                      f"N >= {5*V_eff}")
        else:
            self._add(3, "SEM Coefficient Stability", Enforcement.WARN,
                      Enforcement.PASS,
                      f"样本量充足: N={N} >= 5*V={5*V_eff}。",
                      data_req="N >= 50, V < N/5")

    # ── R4: Extrapolation Guard ──

    def _check_extrapolation_guard(self):
        bridge = self.bridge
        if not hasattr(bridge, 'scan_results') or not bridge.scan_results:
            self._add(4, "CF Extrapolation Guard", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "无反事实数据 — 未运行 counterfactual_scan()。")
            return

        # 检查观测数据范围
        raw = bridge.data_df.values if hasattr(bridge.data_df, 'values') else np.asarray(bridge.data_df)
        for r in bridge.scan_results[:3]:
            src = r['source']
            si = bridge.concept_idx.get(src)
            if si is not None and si < raw.shape[1]:
                obs_range = (raw[:, si].min(), raw[:, si].max())
                # treatment_value=1.0 is the default in scan
                if 1.0 < obs_range[0] or 1.0 > obs_range[1]:
                    self._add(4, "CF Extrapolation Guard", Enforcement.WARN,
                             Enforcement.WARN,
                             f"反事实查询 {src}→{r['target']} 的 treatment_value=1.0 "
                             f"超出观测范围 [{obs_range[0]:.2f}, {obs_range[1]:.2f}]。",
                             "结果具有推测性。",
                             "treatment_value within observed range")
                    return

        self._add(4, "CF Extrapolation Guard", Enforcement.WARN,
                  Enforcement.PASS,
                  "反事实查询在观测数据范围内。")

    # ── R5: Graph Completeness ──

    def _check_graph_completeness(self):
        bridge = self.bridge
        dot = bridge.dot_graph

        # 只检查在有效边中出现的概念（BPE 碎片已被过滤，不在 DOT 中是正确的）
        edge_concepts = set()
        for src, dst, _ in bridge.significant_edges:
            edge_concepts.add(src)
            edge_concepts.add(dst)

        missing = []
        for name in edge_concepts:
            if name != '<other>' and f'"{name}"' not in dot:
                missing.append(name)

        if not missing:
            self._add(5, "Graph Completeness", Enforcement.FAIL,
                      Enforcement.PASS,
                      f"DOT 图包含所有 {len(edge_concepts)} 个有效边概念节点。")
        else:
            self._add(5, "Graph Completeness", Enforcement.FAIL,
                      Enforcement.FAIL,
                      f"DOT 图缺少 {len(missing)} 个概念节点。",
                      f"Missing: {missing[:5]}...")

    # ── R6: Placebo Vanishing ──

    def _check_placebo_vanishing(self):
        bridge = self.bridge
        placebo = bridge.refutation_results.get('安慰剂处理')
        if placebo is None:
            self._add(6, "Placebo Vanishing", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "未运行安慰剂反驳。")
            return

        check = getattr(placebo, '_check', None)
        refuted = check['refuted'] if check else getattr(placebo, 'refuted', False)

        # refuted=False 表示安慰剂新效应接近 0，原估计未被反驳，是好消息
        if refuted:
            self._add(6, "Placebo Vanishing", Enforcement.WARN,
                      Enforcement.WARN,
                      f"安慰剂处理后效应未消失 (new={placebo.new_effect:.4f}) — "
                      f"原效应可能受混淆驱动。")
        else:
            self._add(6, "Placebo Vanishing", Enforcement.WARN,
                      Enforcement.PASS,
                      f"安慰剂处理后效应接近零 (new={placebo.new_effect:.4f}) — "
                      f"原效应可能是真实的因果效应。")

    # ── R7: CI Non-Degeneracy ──

    def _check_ci_non_degeneracy(self):
        from counterfactual_bridge import DoWhy14Adapter
        bridge = self.bridge

        if bridge.estimate_result is None:
            self._add(7, "CI Non-Degeneracy", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "无估计结果。")
            return

        ci = DoWhy14Adapter.get_confidence_interval(bridge.estimate_result)
        if any(np.isnan(c) or np.isinf(c) for c in ci):
            self._add(7, "CI Non-Degeneracy", Enforcement.WARN,
                      Enforcement.WARN,
                      f"95% CI 退化: [{ci[0]:.4f}, {ci[1]:.4f}]。",
                      "增加样本量或检查数据方差。",
                      "CI must not be NaN/Inf")
        else:
            self._add(7, "CI Non-Degeneracy", Enforcement.WARN,
                      Enforcement.PASS,
                      f"95% CI 正常: [{ci[0]:.4f}, {ci[1]:.4f}]。")

    # ── R8: Causal Direction Consistency ──

    def _check_causal_direction_consistency(self):
        bridge = self.bridge
        if not hasattr(bridge, 'scan_results') or not bridge.scan_results:
            self._add(8, "Causal Direction Consistency", Enforcement.WARN,
                      Enforcement.DEFERRED,
                      "无反事实扫描数据。")
            return

        mismatches = 0
        for r in bridge.scan_results[:5]:
            dnl = r['trace_dnl']
            ite = r['ite']
            if dnl > 0 and ite < -0.1:
                mismatches += 1

        if mismatches > 0:
            self._add(8, "Causal Direction Consistency", Enforcement.WARN,
                      Enforcement.WARN,
                      f"{mismatches} 条边的 TRACE ΔNLL 与 DoWhy ITE 方向不一致。",
                      "ΔNLL 和 ITE 可能测量不同的因果维度。")
        else:
            self._add(8, "Causal Direction Consistency", Enforcement.WARN,
                      Enforcement.PASS,
                      "TRACE ΔNLL 与 DoWhy ITE 方向一致。")

    # ── R9: Sparse Graph Sanity ──

    def _check_sparse_graph_sanity(self):
        bridge = self.bridge
        # 排除 <other> 节点，避免密度被系统性低估
        V = len([n for n in bridge.concept_names if n != '<other>'])
        E = len(bridge.significant_edges)
        max_edges = V * (V - 1)
        density = E / max_edges if max_edges > 0 else 0

        if density > 0.5:
            self._add(9, "Sparse Graph Sanity", Enforcement.ADVISORY,
                      Enforcement.WARN,
                      f"图密度过高: {density:.1%} ({E}/{max_edges})。"
                      f"建议提高阈值 (当前 τ={bridge.threshold})。")
        elif density > 0.3:
            self._add(9, "Sparse Graph Sanity", Enforcement.ADVISORY,
                      Enforcement.ADVISORY,
                      f"图密度偏高: {density:.1%} ({E}/{max_edges})。")
        else:
            self._add(9, "Sparse Graph Sanity", Enforcement.ADVISORY,
                      Enforcement.PASS,
                      f"图密度正常: {density:.1%} ({E}/{max_edges})。")

    # ── 构建报告 ──

    def _build_report(self) -> AuditReport:
        if any(c.status == Enforcement.FAIL for c in self._checks):
            verdict = "FAIL"
        elif any(c.status == Enforcement.WARN for c in self._checks):
            verdict = "WARN"
        else:
            verdict = "PASS"

        return AuditReport(checks=self._checks, verdict=verdict)
