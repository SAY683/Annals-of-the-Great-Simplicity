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
    def __init__(self, new_effect, refuted=False, is_placebo: bool = False,
                 original_effect: float = None):
        # P1-1 修复 (2026-07-30): 移除硬编码 orig=1.0/deviation=0.0，
        # 改为基于真实原效应计算偏差，避免报告恒显"0% 偏差"误导用户。
        self.new_effect = new_effect
        orig = original_effect if original_effect is not None and original_effect != 0 else 1.0
        if is_placebo:
            display_metric = abs(new_effect) / max(abs(orig), 1e-10)
            deviation = 0.0  # placebo 用剩余比率，不报偏差
        else:
            deviation = abs(new_effect - orig) / max(abs(orig), 1e-10)
            display_metric = deviation
        display_label = "剩余比率" if is_placebo else "偏差"
        self._check = {
            'refuted': refuted,
            'deviation': deviation,
            'display_metric': display_metric,
            'display_label': display_label,
        }
        self.refuted = refuted  # backward compat


class SimulationModel:
    """DoWhy 的模拟替代。API 与 DoWhy 0.14 一致。"""

    def __init__(self, graph_edges, concept_names, data, rng,
                 refutation_deviation_threshold: float = 0.3):
        # SYNC-4 修复 (2026-07-30 审计): 接受 refutation_deviation_threshold 参数，
        # 与 presets.yaml dowhy.refutation_deviation_threshold: 0.3 对齐。
        # 原 simulation_model.py:138/146/154 各自硬编码 0.3/0.2/0.3，未从 preset 读取。
        self.graph_edges = graph_edges
        self.concept_names = concept_names
        self.data = data
        self.rng = rng
        self.refutation_deviation_threshold = float(refutation_deviation_threshold)

        self.n_vars = len(concept_names)
        self._name_to_idx = {n: i for i, n in enumerate(concept_names)}
        self._coeff = np.zeros((self.n_vars, self.n_vars))
        # P0修复: SEM 系数应允许负值（抑制效应），符合 DoWhy 符号约定
        # 原代码 rng.uniform(0.3, 0.9) 强制正系数，导致抑制型因果边被误报为促进型
        for src, dst in graph_edges:
            si = self._name_to_idx.get(src)
            di = self._name_to_idx.get(dst)
            if si is not None and di is not None:
                self._coeff[si, di] = rng.uniform(-0.7, 0.7)

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
        # P0修复: 保留 SEM 系数符号（支持抑制效应 direct<0）；
        # 仅在无直接边(direct==0)时回退到对称随机值，避免破坏可重复性
        if direct != 0:
            effect = direct
        else:
            # 无直接因果路径时，使用确定性的小效应（基于图结构的函数）
            # 避免每次调用返回不同值，破坏因果估计可重复性
            effect = 0.05 * (1 if (ti + oi) % 2 == 0 else -1)
        se = abs(effect) * 0.15
        # P1修复: 移除 CI 下界截断 max(0,...)，置信区间不应被截断
        ci_lower = effect - 1.96 * se
        ci_upper = effect + 1.96 * se

        return SimulationEstimate(effect, ci_lower, ci_upper)

    def refute_estimate(self, identified_estimand, estimate,
                        method_name="random_common_cause"):
        # P0修复: 所有 std 计算使用 abs(estimate.value)，避免负效应时
        # numpy.random.normal(scale<0) 抛 ValueError
        abs_eff = abs(estimate.value)
        if method_name == "random_common_cause":
            # P0修复: 扰动 std 从 0.05*|effect| 提到 0.15*|effect|，
            # 使阈值 0.3*|effect| 对应 2σ，触发率约 4.6%（原 6σ ~ 2e-9）
            perturbation = self.rng.normal(0, abs_eff * 0.15)
            # SYNC-4: 阈值从 preset 读取（默认 0.3）
            refuted = abs(perturbation) > abs_eff * self.refutation_deviation_threshold
            return SimulationRefutation(estimate.value + perturbation, refuted,
                                         original_effect=estimate.value)
        elif method_name == "placebo_treatment_refuter":
            # P0修复: placebo 应从与原效应无关的噪声分布采样，
            # 而非按原效应量级缩放（违背 placebo "应趋近0" 的语义）
            placebo = self.rng.normal(0, 0.05)
            # P2修复: effect=0 时 placebo 阈值 abs_eff*0.2=0 恒反驳，跳过
            # SYNC-4: placebo 阈值为偏差阈值的 2/3（更敏感，因 placebo 应趋近0）
            placebo_threshold = self.refutation_deviation_threshold * (2.0 / 3.0)
            refuted = abs(placebo) > abs_eff * placebo_threshold if abs_eff > 1e-6 else False
            return SimulationRefutation(placebo, refuted, is_placebo=True,
                                         original_effect=estimate.value)
        elif method_name == "data_subset_refuter":
            # P0修复: uniform(0.8, 1.1) 使 |U-1|<=0.2 < 阈值 0.3，数学上恒不反驳。
            # 改为对称区间 uniform(0.6, 1.4) 使 |U-1| 可达 0.4 > 阈值 0.3
            scale = self.rng.uniform(0.6, 1.4)
            subset_effect = estimate.value * scale
            # SYNC-4: 阈值从 preset 读取（默认 0.3）
            refuted = abs(subset_effect - estimate.value) > abs_eff * self.refutation_deviation_threshold
            return SimulationRefutation(subset_effect, refuted,
                                         original_effect=estimate.value)
        return SimulationRefutation(estimate.value, original_effect=estimate.value)
