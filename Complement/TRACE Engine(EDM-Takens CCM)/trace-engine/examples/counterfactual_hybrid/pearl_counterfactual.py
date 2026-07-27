"""
Pearl 反事实推理引擎（从 counterfactual_bridge.py 抽取）
=========================================================
Pearl 三步反事实推理的独立实现 + 线性 SEM 系数估计。

基于线性 SEM: Y = β·T + Σγ_k·pa_k(Y) + U

三步:
  1. Abduction:  U = Y_obs - (β·T_obs + Σγ_k·pa_k(Y_obs))
  2. Action:     do(T = t')
  3. Prediction: Y_cf = β·t' + Σγ_k·pa_k(Y_obs) + U

D-P0-1 修复 (Round 21 §P0-A): 显式拓扑排序 + 环检测.
原实现假设 `_coeff` 矩阵变量索引顺序即拓扑序, 但实际从 graph_edges
构建的 _coeff 通常不是拓扑序, 导致中介变量在反事实传播时回退到观测值,
计算的是 CDE (受控直接效应) 而非 Y(t') (反事实结果). 本修复:
  1. 从 _coeff 邻接矩阵计算 Kahn 拓扑序
  2. 检测环 (SEM 不可逆时回退到原行为并返回警告)
  3. 按拓扑序做反事实传播, 保证每个变量的父节点已计算反事实值

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

    @staticmethod
    def _topological_sort(coeff: np.ndarray):
        """Kahn 算法拓扑排序.

        Returns
        -------
        (order, has_cycle) : (list[int], bool)
            order: 拓扑序的变量索引列表; has_cycle=True 时返回偏序.
            has_cycle: 检测到环则为 True, 调用方应回退到保守行为.
        """
        n = coeff.shape[0]
        # in_degree[v] = v 的父节点数 (即 coeff[:, v] 中非零项数)
        in_degree = [0] * n
        adj = [[] for _ in range(n)]  # adj[p] = p 的子节点列表
        for v in range(n):
            for p in range(n):
                if coeff[p, v] != 0:
                    in_degree[v] += 1
                    adj[p].append(v)
        # 从入度 0 的节点出发
        queue = [v for v in range(n) if in_degree[v] == 0]
        order = []
        while queue:
            v = queue.pop(0)
            order.append(v)
            for child in adj[v]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        has_cycle = len(order) < n
        return order, has_cycle

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

        # D-P0-1 修复: 显式拓扑排序, 不再假设 _coeff 已按拓扑序可计算.
        topo_order, has_cycle = self._topological_sort(self._coeff)

        n_vars = len(self._name_to_idx)
        noise = {}

        # Step 1: Abduction — 推断所有外生噪声 U_X = X_obs - f(parents_obs)
        # 拓扑序保证父节点的 noise 已计算 (此处用 observed[p], 与观测对齐).
        # 注意: 带环时 topo_order 是偏序, 环中节点不在 topo_order 中,
        # 我们对环中节点也计算 noise (用 observed), 但后续 predict_cf 会
        # 对环中节点用 observed 作为兜底 (无法定义反事实传播).
        for v in topo_order:
            v_obs = float(observed[v])
            pred_obs = 0.0
            for p in range(n_vars):
                if self._coeff[p, v] != 0:
                    pred_obs += self._coeff[p, v] * float(observed[p])
            noise[v] = v_obs - pred_obs

        # 带环兜底: 环中节点不在 topo_order, 用 observed 计算 noise 并标记.
        if has_cycle:
            in_order = set(topo_order)
            for v in range(n_vars):
                if v not in in_order:
                    v_obs = float(observed[v])
                    pred_obs = 0.0
                    for p in range(n_vars):
                        if self._coeff[p, v] != 0:
                            pred_obs += self._coeff[p, v] * float(observed[p])
                    noise[v] = v_obs - pred_obs

        # Step 2: Action — do(T = treatment_value / control_value)
        # Step 3: Prediction — 按拓扑序传播反事实值
        # treatment 变量被干预, 其他变量由反事实父节点值 + 噪声计算.
        # 拓扑序保证 v 的父节点已写入 cf_values.
        # 带环场景: 环中节点不在 topo_order 中, predict_cf 不会处理它们,
        # 若 outcome 在环中则返回 NaN + warning (无法定义反事实).
        def predict_cf(t_val):
            cf_values = {}
            for v in topo_order:
                if v == ti:
                    cf_values[v] = float(t_val)
                else:
                    pred = 0.0
                    for p in range(n_vars):
                        if self._coeff[p, v] != 0:
                            # 父节点必已在 cf_values 中 (拓扑序保证)
                            pred += self._coeff[p, v] * cf_values[p]
                    cf_values[v] = pred + noise[v]
            # 环中节点 (不在 topo_order): 无法定义反事实, 用 observed 兜底
            if len(cf_values) < n_vars:
                for v in range(n_vars):
                    if v not in cf_values:
                        cf_values[v] = float(observed[v])
            return cf_values.get(oi, float('nan'))

        y_treatment = predict_cf(treatment_value)
        y_control = predict_cf(control_value)
        ite = y_treatment - y_control

        # 兼容旧字段
        beta = self._coeff[ti, oi]
        y_obs = float(observed[oi])

        result = {
            'observed_outcome': y_obs,
            'counterfactual_outcome': float(y_treatment) if not np.isnan(y_treatment) else None,
            'causal_effect': float(ite) if not np.isnan(ite) else 0.0,
            'abduction_noise': {f'U_{k}': float(v) for k, v in noise.items()},
        }
        if has_cycle:
            # 检测到环: SEM 不可逆, 反事实传播基于偏序, 结果应谨慎解读.
            result['warning'] = (
                'cycle_detected_in_sem: topological order is partial; '
                'counterfactual values for nodes in cycle fall back to observed.'
            )
        return result


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
        # P1修复: 数据中心化以消除截距吸收偏差（等价于带 intercept 的回归）
        X_centered = X - X.mean(axis=0)
        y_centered = y - y.mean()
        try:
            if regularization == "ridge":
                # β = (X'X + αI)^(-1) X'y (中心化数据)
                XtX = X_centered.T @ X_centered
                reg = XtX + alpha * np.eye(len(parents))
                beta = np.linalg.solve(reg, X_centered.T @ y_centered)
            elif regularization == "lasso":
                try:
                    from sklearn.linear_model import Lasso
                except ImportError:
                    # sklearn 不可用时回退到 ridge
                    XtX = X_centered.T @ X_centered
                    reg = XtX + alpha * np.eye(len(parents))
                    beta = np.linalg.solve(reg, X_centered.T @ y_centered)
                else:
                    # P1修复: fit_intercept=True 让 sklearn 处理截距
                    model = Lasso(alpha=alpha, fit_intercept=True, max_iter=5000)
                    model.fit(X, y)
                    beta = model.coef_
            else:
                # OLS: β = (X'X)^(-1) X'y (中心化数据，等价于带 intercept)
                beta = np.linalg.lstsq(X_centered, y_centered, rcond=None)[0]
            for k, pi in enumerate(parents):
                coeff[pi, j] = float(beta[k])
        except np.linalg.LinAlgError as e:
            if log_fn is not None:
                log_fn(f"SEM 估计失败: {e}")

    return coeff
