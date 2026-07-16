"""
模拟模式类（DoWhy 未安装时的替代）
=================================
（从 counterfactual_bridge.py 抽取）

提供 SimulationEstimand / SimulationEstimate / SimulationRefutation /
SimulationModel 四个类，API 与 DoWhy 0.14 一致，保证管线在
DoWhy 不可用时仍可端到端运行。

依赖说明:
  本模块仅依赖 numpy，不维护模块级依赖检查块。
"""

import numpy as np


class SimulationEstimand:
    def __init__(self, treatment, outcome, identifiable=True):
        self.treatment = treatment
        self.outcome = outcome
        self.identifiable = identifiable
        self.identifier = "backdoor (simulated)"
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
        return SimulationEstimand(
            treatment=self.concept_names[0],
            outcome=self.concept_names[-1],
            identifiable=True,
        )

    def estimate_effect(self, identified_estimand, method_name,
                        confidence_intervals=True):
        ti = self._name_to_idx.get(identified_estimand.treatment, 0)
        oi = self._name_to_idx.get(identified_estimand.outcome, -1)

        direct = self._coeff[ti, oi]
        effect = direct if direct > 0 else self.rng.uniform(0.1, 0.5)
        se = effect * 0.15
        ci_lower = max(0, effect - 1.96 * se)
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
            return SimulationRefutation(placebo, placebo > estimate.value * 0.2, is_placebo=True)
        elif method_name == "data_subset_refuter":
            subset_effect = estimate.value * self.rng.uniform(0.8, 1.1)
            refuted = abs(subset_effect - estimate.value) > estimate.value * 0.3
            return SimulationRefutation(subset_effect, refuted)
        return SimulationRefutation(estimate.value)
