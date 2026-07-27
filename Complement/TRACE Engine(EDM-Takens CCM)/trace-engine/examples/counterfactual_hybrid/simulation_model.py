"""
模拟模式类（DoWhy 未安装时的替代）
=================================
（从 counterfactual_bridge.py 抽取）

提供 SimulationEstimand / SimulationEstimate / SimulationRefutation /
SimulationModel 四个类，API 与 DoWhy 0.14 一致，保证管线在
DoWhy 不可用时仍可端到端运行。

D-P0-3 修复 (Round 21 §P0-A): SimulationEstimand 增加 `synthetic` 标记,
`identifiable` 默认 False. 原实现硬编码 identifiable=True, 使模拟模式
(ATE=rng.uniform(0.1, 0.5)) 报告显示"可识别", 用户无法区分真实
do-calculus 与合成值. 现在:
  - SimulationModel.identify_effect() 显式传 identifiable=False, synthetic=True
  - DoWhy14Adapter.is_identifiable 对 synthetic 返回 False
  - 报告渲染层显示"模拟模式 (合成值, 不可识别)"

依赖说明:
  本模块仅依赖 numpy，不维护模块级依赖检查块。
"""

import numpy as np


class SimulationEstimand:
    def __init__(self, treatment, outcome, identifiable=False, synthetic=True):
        """模拟估计量.

        D-P0-3 修复: 默认 identifiable=False, synthetic=True.
        真实 DoWhy 路径请用 DoWhy 的 IdentifiedEstimand, 不要用本类.
        """
        self.treatment = treatment
        self.outcome = outcome
        # synthetic=True 表示 ATE 为合成值, 不来自真实 do-calculus 识别.
        # identifiable 在 synthetic=True 时强制为 False, 防止误报.
        self.synthetic = synthetic
        if synthetic:
            self.identifiable = False
        else:
            self.identifiable = identifiable
        self.identifier = "backdoor (simulated, synthetic)"
        self.estimand_type = "nonparametric-ate"


class SimulationEstimate:
    def __init__(self, value, ci_lower, ci_upper):
        self.value = value
        self._ci = [ci_lower, ci_upper]
        self.confidence_interval = self._ci

    def get_confidence_intervals(self):
        return [self._ci]


class SimulationRefutation:
    def __init__(self, new_effect, refuted=False, is_placebo: bool = False):
        self.new_effect = new_effect
        orig = 1.0  # 模拟模式下原效应归一化参考
        display_metric = abs(new_effect) / orig if is_placebo else 0.0
        display_label = "剩余比率" if is_placebo else "偏差"
        self._check = {
            'refuted': refuted,
            'deviation': 0.0,
            'display_metric': display_metric,
            'display_label': display_label,
        }
        self.refuted = refuted  # backward compat


class SimulationModel:
    """DoWhy 的模拟替代。API 与 DoWhy 0.14 一致。"""

    def __init__(self, graph_edges, concept_names, data, rng):
        self.graph_edges = graph_edges
        self.concept_names = concept_names
        self.data = data
        self.rng = rng

        self.n_vars = len(concept_names)
        self._name_to_idx = {n: i for i, n in enumerate(concept_names)}
        self._coeff = np.zeros((self.n_vars, self.n_vars))
        for src, dst in graph_edges:
            si = self._name_to_idx.get(src)
            di = self._name_to_idx.get(dst)
            if si is not None and di is not None:
                self._coeff[si, di] = rng.uniform(0.3, 0.9)

    def identify_effect(self, proceed_when_unidentifiable=True):
        # D-P0-3 修复: 显式标记 synthetic=True, identifiable 强制 False.
        # 调用方 (DoWhy14Adapter.is_identifiable) 应检查 synthetic 字段.
        return SimulationEstimand(
            treatment=self.concept_names[0],
            outcome=self.concept_names[-1],
            identifiable=False,
            synthetic=True,
        )

    def estimate_effect(self, identified_estimand, method_name,
                        confidence_intervals=True):
        ti = self._name_to_idx.get(identified_estimand.treatment, 0)
        oi = self._name_to_idx.get(identified_estimand.outcome, -1)

        direct = self._coeff[ti, oi]
        effect = direct if direct > 0 else self.rng.uniform(0.1, 0.5)
        se = effect * 0.15
        # P1修复: 移除 CI 下界截断 max(0,...)，置信区间不应被截断
        ci_lower = effect - 1.96 * se
        ci_upper = effect + 1.96 * se

        return SimulationEstimate(effect, ci_lower, ci_upper)

    def refute_estimate(self, identified_estimand, estimate,
                        method_name="random_common_cause"):
        if method_name == "random_common_cause":
            perturbation = self.rng.normal(0, estimate.value * 0.05)
            refuted = abs(perturbation) > estimate.value * 0.3
            return SimulationRefutation(estimate.value + perturbation, refuted)
        elif method_name == "placebo_treatment_refuter":
            placebo = abs(self.rng.normal(0, estimate.value * 0.1))
            # P2修复: 用 abs(estimate.value) 避免负效应时恒 refuted
            return SimulationRefutation(placebo, placebo > abs(estimate.value) * 0.2, is_placebo=True)
        elif method_name == "data_subset_refuter":
            subset_effect = estimate.value * self.rng.uniform(0.8, 1.1)
            refuted = abs(subset_effect - estimate.value) > estimate.value * 0.3
            return SimulationRefutation(subset_effect, refuted)
        return SimulationRefutation(estimate.value)
