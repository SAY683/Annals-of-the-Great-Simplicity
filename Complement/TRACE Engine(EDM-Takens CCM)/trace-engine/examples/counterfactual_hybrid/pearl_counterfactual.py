"""
Pearl 反事实推理引擎（从 counterfactual_bridge.py 抽取）
=========================================================
Pearl 三步反事实推理的独立实现 + 线性 SEM 系数估计。

基于线性 SEM: Y = β·T + Σγ_k·pa_k(Y) + U

三步:
  1. Abduction:  U = Y_obs - (β·T_obs + Σγ_k·pa_k(Y_obs))
  2. Action:     do(T = t')
  3. Prediction: Y_cf = β·t' + Σγ_k·pa_k(Y_obs) + U

本模块不维护模块级依赖检查块；sklearn 在 estimate_sem_from_data
内部惰性导入（保持向后兼容的回退行为）。
"""

from typing import Optional

import numpy as np


class PearlCounterfactual:
    """
    Pearl 三步反事实推理的独立实现。
    基于线性 SEM: Y = β·T + Σγ_k·pa_k(Y) + U

    三步:
    1. Abduction:  U = Y_obs - (β·T_obs + Σγ_k·pa_k(Y_obs))
    2. Action:     do(T = t')
    3. Prediction: Y_cf = β·t' + Σγ_k·pa_k(Y_obs) + U
    """

    def __init__(self, sem_coeff: np.ndarray, name_to_idx: dict,
                 rng: np.random.Generator = None):
        """
        Parameters
        ----------
        sem_coeff : (V, V) array
            结构系数矩阵，coeff[i,j] = 变量 i 对 j 的直接因果效应
        name_to_idx : dict
            变量名 → 矩阵索引
        rng : np.random.Generator
        """
        self._coeff = sem_coeff
        self._name_to_idx = name_to_idx
        self._rng = rng if rng is not None else np.random.default_rng(42)

    def query(self, observed, treatment_var, outcome_var,
              control_value=0.0, treatment_value=1.0) -> dict:
        """
        执行 Pearl 三步反事实推理。

        Parameters
        ----------
        observed : np.ndarray
            观测到的所有变量值
        treatment_var : str
        outcome_var : str
        control_value : float
        treatment_value : float

        Returns
        -------
        dict with observed_outcome, counterfactual_outcome, causal_effect, abduction_noise
        """
        ti = self._name_to_idx.get(treatment_var)
        oi = self._name_to_idx.get(outcome_var)

        if ti is None or oi is None:
            return {
                'observed_outcome': float('nan'),
                'counterfactual_outcome': float('nan'),
                'causal_effect': 0.0,
                'abduction_noise': {},
                'error': f'Variable not found: {treatment_var} or {outcome_var}'
            }

        # 直接效应系数
        beta = self._coeff[ti, oi]

        # 其他父节点对 outcome 的效应
        parent_effects = 0.0
        for p in range(len(self._name_to_idx)):
            if p != ti and self._coeff[p, oi] != 0:
                parent_effects += self._coeff[p, oi] * observed[p]

        # Step 1: Abduction
        y_obs = float(observed[oi])
        x_obs = float(observed[ti])
        y_pred_from_model = beta * x_obs + parent_effects
        U = y_obs - y_pred_from_model

        # Step 2 & 3: Action + Prediction
        y_control = beta * control_value + parent_effects + U
        y_treatment = beta * treatment_value + parent_effects + U
        ite = y_treatment - y_control

        return {
            'observed_outcome': y_obs,
            'counterfactual_outcome': float(y_treatment),
            'causal_effect': float(ite),
            'abduction_noise': {'U': float(U)},
        }


def estimate_sem_from_data(adj_matrix, data, concept_names,
                          regularization: Optional[str] = None,
                          alpha: float = 0.01,
                          log_fn=None):
    """
    从数据和因果图（邻接矩阵）估计线性 SEM 的系数。
    对每个子节点 Y，用其所有父节点 X 做回归: Y ~ Σβ_i·X_i

    Parameters
    ----------
    regularization : {None, "ridge", "lasso"}, optional
        None   -> OLS
        ridge -> 岭回归 (稳定小样本/共线数据)
        lasso -> Lasso (稀疏化)
    alpha : float, default 0.01
        正则化强度。
    log_fn : callable, optional
        日志回调（如 TRACE2DoWhy._log），用于记录回归失败而非静默吞异常。
    """
    V = len(concept_names)
    coeff = np.zeros((V, V))

    for j in range(V):
        parents = [i for i in range(V) if adj_matrix[i, j] > 0]
        if not parents:
            continue
        X = data[:, parents]
        y = data[:, j]
        try:
            if regularization == "ridge":
                # β = (X'X + αI)^(-1) X'y
                XtX = X.T @ X
                reg = XtX + alpha * np.eye(len(parents))
                beta = np.linalg.solve(reg, X.T @ y)
            elif regularization == "lasso":
                try:
                    from sklearn.linear_model import Lasso
                except ImportError:
                    # sklearn 不可用时回退到 ridge
                    XtX = X.T @ X
                    reg = XtX + alpha * np.eye(len(parents))
                    beta = np.linalg.solve(reg, X.T @ y)
                else:
                    model = Lasso(alpha=alpha, fit_intercept=False, max_iter=5000)
                    model.fit(X, y)
                    beta = model.coef_
            else:
                # OLS: β = (X'X)^(-1) X'y
                beta = np.linalg.lstsq(X, y, rcond=None)[0]
            for k, pi in enumerate(parents):
                coeff[pi, j] = float(beta[k])
        except np.linalg.LinAlgError as e:
            if log_fn is not None:
                log_fn(f"SEM 估计失败: {e}")

    return coeff
