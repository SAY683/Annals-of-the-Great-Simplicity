"""
DoWhy 0.14 API 适配层（从 counterfactual_bridge.py 抽取）
=========================================================
统一 DoWhy 0.14 和模拟模式之间的 API 差异。

DoWhy 0.14 的关键 API 变更（相对于旧版）:
- IdentifiedEstimand 没有 .identifiable 属性 → 用 estimand_type 判断
- CausalRefutation 没有 .refuted / .p_value → 用偏差度判断
- CausalEstimate 没有 .confidence_interval → 用 .get_confidence_intervals()
- CausalModel 没有 .counterfactual() → 用 Pearl 三步手动实现

本模块为纯静态工具类，不维护模块级依赖检查块；
可用性探测由 counterfactual_bridge.py 统一管理。
"""

import numpy as np


class DoWhy14Adapter:
    """
    统一 DoWhy 0.14 和模拟模式之间的 API 差异。

    DoWhy 0.14 的关键 API 变更（相对于旧版）:
    - IdentifiedEstimand 没有 .identifiable 属性 → 用 estimand_type 判断
    - CausalRefutation 没有 .refuted / .p_value → 用偏差度判断
    - CausalEstimate 没有 .confidence_interval → 用 .get_confidence_intervals()
    - CausalModel 没有 .counterfactual() → 用 Pearl 三步手动实现
    """

    @staticmethod
    def is_identifiable(estimand) -> bool:
        """跨版本检查可识别性"""
        if estimand is None:
            return False
        if hasattr(estimand, 'identifiable'):
            return bool(estimand.identifiable)
        # DoWhy 0.14: estimand_type 包含 'nonparametric' 表示可识别
        if hasattr(estimand, 'estimand_type') and estimand.estimand_type is not None:
            et = str(estimand.estimand_type)
            return 'nonparametric' in et.lower()
        return False

    @staticmethod
    def get_confidence_interval(estimate):
        """跨版本获取置信区间"""
        if hasattr(estimate, 'confidence_interval'):
            return estimate.confidence_interval
        if hasattr(estimate, 'get_confidence_intervals'):
            ci = estimate.get_confidence_intervals()
            if ci is not None:
                # 统一处理 [[low, high]] / [low, high] / ndarray 等形态
                ci_arr = np.asarray(ci)
                if ci_arr.size >= 2:
                    if ci_arr.ndim == 2:
                        return [float(ci_arr[0, 0]), float(ci_arr[0, -1])]
                    else:
                        return [float(ci_arr[0]), float(ci_arr[-1])]
        return [float('nan'), float('nan')]

    @staticmethod
    def check_refuted(estimate, refutation, threshold: float = 0.3,
                      method_name: str = None) -> dict:
        """
        跨版本检查反驳状态。
        DoWhy 0.14 的 CausalRefutation 没有 .refuted 属性，
        我们用 new_effect 与原始 estimate.value 的偏差来判断。

        特殊处理:
          - placebo_treatment_refuter: 新效应应接近 0，偏差大反而说明
            原效应不是随机噪声，因此 refuted=False。
          - random_common_cause / data_subset_refuter: 偏差大说明效应不稳健。

        Returns
        -------
        dict: {refuted: bool, deviation: float, new_effect: float}
        """
        # 当原效应接近 0 时，相对偏差会无穷大，改用绝对偏差（阈值 0.01）
        if abs(estimate.value) < 1e-6:
            orig = 1.0
            deviation = abs(refutation.new_effect - estimate.value)
            effective_threshold = 0.01
        else:
            orig = abs(estimate.value)
            deviation = abs(refutation.new_effect - estimate.value) / orig
            effective_threshold = threshold

        # 安慰剂反驳: 新效应接近 0 是期望结果，不应判定为 refuted
        if method_name == "placebo_treatment_refuter":
            # 用 |新效应| 与 |原效应| 的比值衡量安慰剂是否成功消失
            placebo_ratio = abs(refutation.new_effect) / orig
            refuted = placebo_ratio > threshold
            display_metric = placebo_ratio
            display_label = "剩余比率"
        else:
            refuted = deviation > effective_threshold
            display_metric = deviation
            display_label = "偏差"

        return {
            'refuted': refuted,
            'deviation': deviation,
            'new_effect': refutation.new_effect,
            'display_metric': display_metric,
            'display_label': display_label,
        }
