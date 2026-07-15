"""
TRACE → DoWhy Counterfactual Bridge v2
=======================================
将 TRACE 引擎的因果发现结果桥接到 DoWhy 的正式因果推断框架。
v2 新增: DoWhy 0.14 兼容 + causallearn (PC/FCI/GES) + Graphviz 可视化。

六合一架构:
  Layer 1-2: TRACE Auditor (环境+配置)     ← trace_plus.py
  Layer 3:   CCM Cross-Validation          ← ccm_causality.py
  Layer 4:   DoWhy 识别 + 三层反驳          ← 本模块
  Layer 5:   Counterfactual 反事实查询      ← 本模块
  +:         causallearn 独立验证           ← 本模块 (NEW)

用法:
    from counterfactual_bridge import TRACE2DoWhy

    bridge = TRACE2DoWhy(adj_matrix, token_list)
    bridge.build_model()
    bridge.identify()
    bridge.estimate()
    bridge.refute()
    bridge.counterfactual_scan(n_top_edges=5)
    bridge.causallearn_validate()  # NEW: PC/FCI/GES 独立验证
    bridge.visualize("causal_graph")  # NEW: DAG 可视化
    print(bridge.report())

模拟模式（DoWhy 未安装时自动启用）:
    bridge = TRACE2DoWhy(adj_matrix, token_list, simulation=True)
"""

import sys
import warnings
from collections import Counter
from typing import Optional

import numpy as np

from _token_filters import is_valid_concept, classify_bpe_type, is_unk_token

# ── Dependency checks ─────────────────────────────────────────────────
_DOWHY_AVAILABLE = False
_CAUSALLEARN_AVAILABLE = False
_GRAPHVIZ_AVAILABLE = False
_PANDAS_AVAILABLE = False

try:
    import dowhy
    from dowhy import CausalModel
    _DOWHY_AVAILABLE = True
except ImportError:
    pass

try:
    import causallearn
    from causallearn.search.ConstraintBased.PC import pc as pc_alg
    from causallearn.search.ScoreBased.GES import ges as ges_alg
    _CAUSALLEARN_AVAILABLE = True
except ImportError:
    pass

try:
    import graphviz
    _GRAPHVIZ_AVAILABLE = True
except ImportError:
    pass

try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    pass

try:
    import networkx as nx
except ImportError:
    nx = None


# ══════════════════════════════════════════════════════════════════════
# DoWhy 0.14 API 适配层
# ══════════════════════════════════════════════════════════════════════

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
        orig = abs(estimate.value) + 1e-10
        deviation = abs(refutation.new_effect - estimate.value) / orig

        # 安慰剂反驳: 新效应接近 0 是期望结果，不应判定为 refuted
        if method_name == "placebo_treatment_refuter":
            # 用 |新效应| 与 |原效应| 的比值衡量安慰剂是否成功消失
            placebo_ratio = abs(refutation.new_effect) / orig
            refuted = placebo_ratio > threshold
            display_metric = placebo_ratio
            display_label = "剩余比率"
        else:
            refuted = deviation > threshold
            display_metric = deviation
            display_label = "偏差"

        return {
            'refuted': refuted,
            'deviation': deviation,
            'new_effect': refutation.new_effect,
            'display_metric': display_metric,
            'display_label': display_label,
        }


# ══════════════════════════════════════════════════════════════════════
# Pearl 反事实推理引擎（DoWhy 0.14 base 版无 counterfactual 方法）
# ══════════════════════════════════════════════════════════════════════

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
                          alpha: float = 0.01):
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
        except np.linalg.LinAlgError:
            pass

    return coeff


# ══════════════════════════════════════════════════════════════════════
# causallearn 集成层
# ══════════════════════════════════════════════════════════════════════

class CausalLearnValidator:
    """
    使用 causallearn 的 PC、FCI、GES 算法作为独立因果发现方法，
    与 TRACE 的结果进行交叉验证。
    """

    def __init__(self, data: np.ndarray, concept_names: list):
        """
        Parameters
        ----------
        data : (N, V) array
            观测数据矩阵
        concept_names : list[str]
            变量名列表
        """
        self.data = data
        self.concept_names = concept_names
        self._name_to_idx = {n: i for i, n in enumerate(concept_names)}
        self.results: dict = {}

    def run_pc(self, alpha: float = 0.05, **kwargs) -> dict:
        """运行 PC (Peter-Clark) 算法"""
        if not _CAUSALLEARN_AVAILABLE:
            return {'error': 'causallearn not installed', 'edges': []}

        try:
            pc_result = pc_alg(self.data, alpha=alpha, **kwargs)
            edges = self._parse_causallearn_graph(pc_result.G)

            self.results['pc'] = {
                'algorithm': 'PC (constraint-based)',
                'edges': edges,
                'n_edges': len(edges),
                'graph': pc_result.G,
            }
            return self.results['pc']
        except Exception as e:
            return {'error': str(e), 'edges': []}

    def run_ges(self, **kwargs) -> dict:
        """运行 GES (Greedy Equivalence Search) 算法"""
        if not _CAUSALLEARN_AVAILABLE:
            return {'error': 'causallearn not installed', 'edges': []}

        try:
            ges_result = ges_alg(self.data, **kwargs)
            edges = self._parse_causallearn_graph(ges_result['G'])

            self.results['ges'] = {
                'algorithm': 'GES (score-based)',
                'edges': edges,
                'n_edges': len(edges),
                'graph': ges_result['G'],
            }
            return self.results['ges']
        except Exception as e:
            return {'error': str(e), 'edges': []}

    def _parse_causallearn_graph(self, G) -> list:
        """将 causallearn 的 GeneralGraph 解析为边列表"""
        edges = []
        try:
            graph_edges = G.get_graph_edges()
            for edge in graph_edges:
                i = edge.get_node1().get_index()
                j = edge.get_node2().get_index()
                endpoint1 = edge.get_endpoint1()
                endpoint2 = edge.get_endpoint2()

                # ENDPOINT_TAIL = 1, ENDPOINT_ARROW = 2
                tail, arrow = 1, 2
                if endpoint1 == tail and endpoint2 == arrow:
                    direction = '→'
                elif endpoint1 == arrow and endpoint2 == tail:
                    direction = '←'
                elif endpoint1 == arrow and endpoint2 == arrow:
                    direction = '↔'
                elif endpoint1 == tail and endpoint2 == tail:
                    direction = '—'
                else:
                    direction = '?'

                if i < len(self.concept_names) and j < len(self.concept_names):
                    edges.append({
                        'source': self.concept_names[i],
                        'target': self.concept_names[j],
                        'direction': direction,
                    })
        except Exception:
            pass
        return edges

    def compare_with_trace(self, trace_edges: list) -> dict:
        """
        比较 causallearn 发现与 TRACE 发现的边。
        trace_edges: [(src, dst, strength), ...]
        """
        trace_set = {(e[0], e[1]) for e in trace_edges}

        comparison = {}
        for algo_key, algo_result in self.results.items():
            cl_edges = algo_result.get('edges', [])
            cl_undirected = {(e['source'], e['target']) for e in cl_edges}
            cl_undirected |= {(e['target'], e['source']) for e in cl_edges}

            agree = trace_set & cl_undirected
            trace_only = trace_set - cl_undirected
            cl_only = cl_undirected - trace_set

            comparison[algo_key] = {
                'algorithm': algo_result['algorithm'],
                'trace_n_edges': len(trace_set),
                'cl_n_edges': len(cl_undirected),
                'agree': len(agree),
                'trace_only': len(trace_only),
                'cl_only': len(cl_only),
                'agreement_rate': len(agree) / max(len(trace_set), 1),
                'agreed_edges': list(agree),
            }

        self.comparison = comparison
        return comparison


# ══════════════════════════════════════════════════════════════════════
# 最小化 DataFrame（pandas 未安装时的轻量替代）
# ══════════════════════════════════════════════════════════════════════

class _ILocIndexer:
    def __init__(self, data, columns, col_idx):
        self.data = np.asarray(data)
        self.columns = columns
        self._col_idx = col_idx

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return _MinimalRow(self.data[idx], self.columns, self._col_idx)
        if isinstance(idx, tuple):
            row_idx, col_idx = idx
            result = self.data[row_idx]
            if isinstance(col_idx, (slice, list, np.ndarray)):
                return result[..., col_idx]
            return result[col_idx]
        return self.data[idx]


class _MinimalRow:
    def __init__(self, row_data, columns, col_idx):
        self._data = np.asarray(row_data)
        self._col_idx = col_idx

    @property
    def values(self):
        return self._data

    def __repr__(self):
        return str(self._data)

    def to_dict(self):
        return {}


class _MinimalDataFrame:
    def __init__(self, data: np.ndarray, columns: list):
        self.data = np.asarray(data)
        self.columns = list(columns)
        self._col_idx = {c: i for i, c in enumerate(columns)}
        self.iloc = _ILocIndexer(self.data, self.columns, self._col_idx)

    @property
    def values(self):
        return self.data

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.data[:, self._col_idx[key]]
        return self.data[:, key]

    def __len__(self):
        return len(self.data)


# ══════════════════════════════════════════════════════════════════════
# 核心桥接类 v2
# ══════════════════════════════════════════════════════════════════════

class TRACE2DoWhy:
    """
    将 TRACE 因果邻接矩阵转换为 DoWhy 因果模型，
    提供识别、估计、反驳、反事实查询的完整管线。

    v2 新增:
    - DoWhy 0.14 API 兼容层
    - causallearn (PC/FCI/GES) 独立验证
    - Graphviz DAG 可视化
    - Pearl 三步反事实推理（独立实现，不依赖 dowhy-gcm）
    """

    def __init__(
        self,
        adj_matrix: np.ndarray,
        token_list: list,
        tokenizer=None,
        threshold: float = 0.5,
        concept_min_freq: int = 2,
        simulation: bool = False,
        random_state: int = 42,
        max_edges_for_dowhy: int = 20,
        filter_mode: str = "top_n",
        filter_percentile: float = 90,
        sem_regularization: Optional[str] = None,
        sem_alpha: float = 0.01,
        min_concept_len: Optional[int] = None,
        classical_mode: bool = False,
        max_concepts: int = 0,
    ):
        self.adj_matrix = np.asarray(adj_matrix)
        self.token_list = list(token_list)
        self.tokenizer = tokenizer
        self.threshold = threshold
        self.concept_min_freq = concept_min_freq
        self.simulation = simulation or not _DOWHY_AVAILABLE
        self.rng = np.random.default_rng(random_state)

        # v3: 自适应过滤参数
        self.max_edges_for_dowhy = max_edges_for_dowhy
        # 统一 filter_mode 命名：presets.yaml / Web 使用 'topn'，bridge 内部使用 'top_n'
        self.filter_mode = "top_n" if filter_mode == "topn" else filter_mode
        self.filter_percentile = filter_percentile

        # v9: 最大概念数上限（0 表示不限制）。用于 SUPER 模式 token-level 图防止概念爆炸。
        self.max_concepts = max(0, int(max_concepts))

        # v3.5: SEM 正则化参数
        self.sem_regularization = sem_regularization
        self.sem_alpha = sem_alpha

        # v7: 概念最小长度（自动探测：字级 BPE 保留单字，词级 BPE 过滤单字碎片）
        self.min_concept_len = min_concept_len

        # v8: 古汉语模式（Shenji 古文保留之/乎/者/也等虚词）
        self.classical_mode = classical_mode

        # 管线状态
        self.concept_map: dict = {}
        self.concept_adj: np.ndarray = None
        self.concept_names: list = []
        self.concept_idx: dict = {}
        self.causal_graph = None
        self.model = None
        self.identified_estimand = None
        self.estimate_result = None
        self.refutation_results: dict = {}
        self.counterfactual_result = None
        self.scan_results: list = []
        self.significant_edges: list = []

        # v2 新增状态
        self.sem_coeff: np.ndarray = None       # 线性 SEM 系数矩阵
        self.pearl_cf: PearlCounterfactual = None
        self.cl_validator: CausalLearnValidator = None
        self.cl_comparison: dict = {}
        self.bpe_type: str = "unknown"           # v6: BPE 类型检测
        self.unk_rate: float = 0.0               # v6: UNK 率

        # 诊断日志
        self.log: list[str] = []

    def _log(self, msg: str):
        self.log.append(msg)

    @property
    def mode_name(self) -> str:
        if self.simulation:
            return "模拟模式 (SEM)"
        return "DoWhy 0.14 正式 do-calculus"

    # ── 步骤 0: Token → Concept 聚合 ─────────────────────────────────

    def aggregate_concepts(self) -> dict:
        """
        将 token 级因果图聚合到概念级。

        策略:
        1. 出现 >= concept_min_freq → 独立概念节点
        2. 低频 token → 归入 "<other>"
        3. token 间 ΔNLL → 概念间聚合 ΔNLL
        4. 单字 BPE 碎片过滤：词级 BPE 默认只保留长度 >= 2 的概念
        """
        T = len(self.token_list)
        token_counter = Counter(self.token_list)

        # ── v7: BPE 类型与最小概念长度自动探测 ──
        self.bpe_type = classify_bpe_type(self.token_list)
        if self.min_concept_len is not None:
            min_len = self.min_concept_len
        else:
            # 启发式：即使 BPE 被判定为字级，只要有效 token 中有一定比例多字词，
            # 也按词级处理（过滤单字碎片）。这能避免词级模型在跨域文本上产生
            # 大量 "永"/"恒"/"目" 等无意义单字概念。
            valid_tokens = [t for t in self.token_list if is_valid_concept(t, classical_mode=self.classical_mode)]
            total_valid = max(len(valid_tokens), 1)
            multi_char_ratio = sum(1 for t in valid_tokens if len(t.strip()) >= 2) / total_valid
            if multi_char_ratio > 0.15:
                min_len = 2
                self._log(f"BPE类型: {self.bpe_type}, 多字词占比={multi_char_ratio:.1%} -> 按词级过滤单字碎片")
            elif self.bpe_type == "character":
                min_len = 1
                self._log("BPE类型: 字级. 概念将以单字为主. 建议: Instant TRACE 训练词级 BPE.")
            else:
                min_len = 2
                self._log(f"BPE类型: {self.bpe_type} -> 过滤单字碎片")


        high_freq = {t for t, c in token_counter.items()
                     if c >= self.concept_min_freq
                     and is_valid_concept(t, classical_mode=self.classical_mode)
                     and len(t.strip()) >= min_len}

        # v9: 如果概念数超过上限，仅保留频率最高的前 N 个 token 作为独立概念
        if self.max_concepts > 0 and len(high_freq) > self.max_concepts:
            sorted_tokens = sorted(
                high_freq,
                key=lambda t: token_counter[t],
                reverse=True,
            )
            high_freq = set(sorted_tokens[:self.max_concepts])
            self._log(f"概念数超过上限 {self.max_concepts}，已按频率截断至 {len(high_freq)} 个高频概念")

        concept_map = {}
        for i, tok in enumerate(self.token_list):
            # 高频 token 仍需通过 is_valid_concept 与长度过滤才能成为独立概念节点
            if tok in high_freq:
                concept_map[i] = tok
            else:
                concept_map[i] = "<other>"

        unique_concepts = sorted(set(concept_map.values()))
        C = len(unique_concepts)
        concept_idx = {name: j for j, name in enumerate(unique_concepts)}

        self.concept_adj = np.zeros((C, C))
        concept_counts = np.zeros((C, C))

        for i in range(T):
            for j in range(T):
                if i >= j:
                    continue
                ci = concept_idx[concept_map[i]]
                cj = concept_idx[concept_map[j]]
                if ci == cj:
                    continue
                self.concept_adj[ci, cj] += self.adj_matrix[i, j]
                concept_counts[ci, cj] += 1

        mask = concept_counts > 0
        self.concept_adj[mask] /= concept_counts[mask]

        self.concept_map = concept_map
        self.concept_names = unique_concepts
        self.concept_idx = concept_idx

        # ── v6: UNK 率感知 + 阈值自适应建议 ──
        unk_count = sum(1 for t in self.token_list if is_unk_token(t))
        unk_rate = unk_count / max(T, 1)
        n_unique = len(set(self.token_list))
        self.unk_rate = unk_rate
        self._log(f"Token {T} → Concept {C} "
                  f"(高频={len(high_freq)}, "
                  f"低频={sum(1 for i in range(T) if self.token_list[i] not in high_freq)})")

        if unk_rate > 0.2:
            self._log(f"⚠ UNK rate={unk_rate:.1%} (严重跨域). "
                      f"强烈建议: 使用 Instant TRACE 训练专属模型. "
                      f"当前 τ={self.threshold} 可能过高, 建议 τ≤0.05.")
        elif unk_rate > 0.05:
            self._log(f"⚠ UNK rate={unk_rate:.1%} (中度跨域). "
                      f"建议: 降低阈值 τ≤0.1 以捕获弱信号.")
        elif unk_rate > 0.01:
            self._log(f"UNK rate={unk_rate:.1%} (正常).")

        # 叙事文启发式: token 种类少 + 段落多 → 叙事文 → 建议低 τ
        if n_unique < T * 0.15 and T > 500:
            self._log(f"文本类型推测: 叙事文 (unique tokens={n_unique}/{T}={n_unique/T:.1%}). "
                      f"建议 τ=0.05-0.15.")

        return concept_map

    # ── 步骤 1: 构建因果模型 ─────────────────────────────────────────

    def build_model(self, data_df=None):
        """
        从概念邻接矩阵构建因果模型。
        如果 DoWhy 可用，创建正式的 CausalModel；
        否则使用模拟模式。

        v2 改进: 同时估计线性 SEM 系数，用于 Pearl 反事实推理。
        """
        if self.concept_adj is None:
            self.aggregate_concepts()

        C = len(self.concept_names)

        # 提取显著边
        edges = []
        for ci in range(C):
            for cj in range(C):
                if self.concept_adj[ci, cj] > self.threshold:
                    edges.append((self.concept_names[ci],
                                  self.concept_names[cj],
                                  self.concept_adj[ci, cj]))
        edges.sort(key=lambda e: e[2], reverse=True)

        # ── v3: 自适应边过滤 ──
        # 真实 TRACE 数据可能有数千条边，DoWhy 无法处理。
        # 策略: 过滤 BPE 碎片 + top-N 最强边
        # (is_valid_concept 统一从 _token_filters 导入)

        edges_filtered = [e for e in edges if is_valid_concept(e[0], classical_mode=self.classical_mode) and is_valid_concept(e[1], classical_mode=self.classical_mode)]

        n_total = len(edges_filtered)
        if n_total > self.max_edges_for_dowhy:
            if self.filter_mode == "percentile":
                threshold_val = np.percentile(
                    [e[2] for e in edges_filtered], self.filter_percentile)
                edges_filtered = [e for e in edges_filtered if e[2] >= threshold_val]
            elif self.filter_mode == "adaptive":
                # adaptive: 根据图密度自动选择 percentile 或 top-N
                density = n_total / max(C * (C - 1), 1)
                if density > 0.3:
                    threshold_val = np.percentile(
                        [e[2] for e in edges_filtered], self.filter_percentile)
                    edges_filtered = [e for e in edges_filtered if e[2] >= threshold_val]
                    self._log(f"adaptive 模式: 图密度 {density:.1%} > 30%, 使用 percentile 过滤")
                else:
                    self._log(f"adaptive 模式: 图密度 {density:.1%} ≤ 30%, 使用 top-N 过滤")
            else:
                # Default: top-N
                edges_filtered = edges_filtered[:self.max_edges_for_dowhy]

        if n_total > self.max_edges_for_dowhy:
            self._log(f"边过滤: {n_total} → {len(edges_filtered)} "
                      f"(mode={self.filter_mode}, max={self.max_edges_for_dowhy})")
        self.significant_edges = edges_filtered
        self._log(f"显著边: {len(edges_filtered)}/{C*C} (ΔNLL > {self.threshold})")

        # DOT 图 — 只包含有效边中出现的节点（否则 DoWhy 在大图上极慢/崩溃）
        dot_nodes = set()
        for src, dst, _ in edges_filtered:
            if is_valid_concept(src, classical_mode=self.classical_mode) and is_valid_concept(dst, classical_mode=self.classical_mode):
                dot_nodes.add(src)
                dot_nodes.add(dst)
        dot_lines = ["digraph {"]
        for node in sorted(dot_nodes):
            dot_lines.append(f'  "{node}";')
        for src, dst, _ in edges_filtered:
            dot_lines.append(f'  "{src}" -> "{dst}";')
        dot_lines.append("}")
        self.dot_graph = "\n".join(dot_lines)

        # 数据矩阵
        if data_df is None:
            data_df = self._simulate_data(C)

        # 估计 SEM 系数（用于 Pearl 反事实）
        raw_data = data_df.values if hasattr(data_df, 'values') else np.asarray(data_df)
        # 构建二值邻接矩阵
        bin_adj = np.zeros((C, C))
        for src, dst, _ in edges_filtered:
            si = self.concept_idx.get(src)
            di = self.concept_idx.get(dst)
            if si is not None and di is not None:
                bin_adj[si, di] = 1
        self.sem_coeff = estimate_sem_from_data(
            bin_adj, raw_data, self.concept_names,
            regularization=self.sem_regularization,
            alpha=self.sem_alpha,
        )

        # 初始化 Pearl 反事实引擎
        name_to_idx = {n: i for i, n in enumerate(self.concept_names)}
        self.pearl_cf = PearlCounterfactual(self.sem_coeff, name_to_idx, self.rng)

        # 构建模型 — v6: 概念规模自适应降级
        DOT_NODES = len(dot_nodes)
        if not self.simulation and DOT_NODES > 50:
            self.simulation = True
            self._log(f"⚠ 概念节点过多 ({DOT_NODES} > 50), DoWhy do-calculus 极慢 → 自动降级为模拟模式")
        elif not self.simulation and DOT_NODES > 30:
            self._log(f"⚠ 概念节点较多 ({DOT_NODES} > 30), DoWhy 可能较慢. 建议降低 max_edges_for_dowhy.")

        if self.simulation:
            self.model = SimulationModel(
                graph_edges=[(e[0], e[1]) for e in edges_filtered],
                concept_names=self.concept_names,
                data=data_df,
                rng=self.rng,
            )
            self._log(f"模型: SimulationMode")
        else:
            # DoWhy 0.14: 使用最强边的 source→target（保证有有向路径）
            if edges_filtered:
                default_treatment = edges_filtered[0][0]
                default_outcome = edges_filtered[0][1]
            else:
                valid_names = [n for n in self.concept_names
                              if n != "<other>" and len(n) > 1]
                default_treatment = valid_names[0] if valid_names else self.concept_names[0]
                default_outcome = valid_names[-1] if len(valid_names) > 1 else self.concept_names[-1]

            # 精简数据: 只包含 DOT 图中出现的列（否则 DoWhy 在大数据上失败）
            dot_cols = sorted(dot_nodes)
            reduced_data = data_df[dot_cols] if hasattr(data_df, '__getitem__') else data_df

            self.model = CausalModel(
                data=reduced_data,
                treatment=default_treatment,
                outcome=default_outcome,
                graph=self.dot_graph,
            )
            self._log(f"模型: DoWhy 0.14 CausalModel (精简图: {len(dot_cols)} 节点)")

        self.data_df = data_df
        return self.model

    def _simulate_data(self, n_concepts: int, n_samples: int = 1000):
        """
        从邻接矩阵模拟生成观测数据（SEM 数据生成过程）。

        使用拓扑排序确保按 DAG 结构生成数据，避免原实现中
        'for i in range(j)' 对任意排序邻接矩阵的索引错误。
        如果检测到环，则使用 5 次迭代近似。
        """
        data = np.zeros((n_samples, n_concepts))
        # σ=1.0 增强外生噪声，避免 OLS 设计矩阵接近奇异
        noise = self.rng.normal(0, 1.0, (n_samples, n_concepts))
        data[:] = noise[:]

        # 收集所有显著边 (父节点 -> 子节点)
        edges = []
        for i in range(n_concepts):
            for j in range(n_concepts):
                if self.concept_adj[i, j] > self.threshold:
                    edges.append((i, j, self.concept_adj[i, j] / 10.0))

        # 尝试拓扑排序
        in_degree = [0] * n_concepts
        adjacency = [[] for _ in range(n_concepts)]
        for i, j, eff in edges:
            adjacency[i].append((j, eff))
            in_degree[j] += 1

        queue = [i for i in range(n_concepts) if in_degree[i] == 0]
        topo_order = []
        while queue:
            node = queue.pop(0)
            topo_order.append(node)
            for child, _ in adjacency[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(topo_order) == n_concepts:
            # 无环：按拓扑顺序应用父节点效应
            generated = set()
            for node in topo_order:
                generated.add(node)
                for child, eff in adjacency[node]:
                    data[:, child] += eff * data[:, node]
        else:
            # 有环：使用迭代近似
            self._log(f"模拟数据: 检测到环 ({len(topo_order)}/{n_concepts} 节点可拓扑排序)，使用迭代近似。")
            for _ in range(5):
                for i, j, eff in edges:
                    data[:, j] += eff * data[:, i]

        if _PANDAS_AVAILABLE:
            return pd.DataFrame(data, columns=self.concept_names)
        return _MinimalDataFrame(data, self.concept_names)

    # ── 步骤 2: 识别因果效应 ─────────────────────────────────────────

    def identify(self, treatment: str = None, outcome: str = None):
        """
        使用 do-calculus 识别因果效应是否可以从观测数据中估计。

        DoWhy 0.14 兼容: 使用 estimand_type 判断可识别性。
        """
        if self.model is None:
            self.build_model()

        # 选择有效的 treatment/outcome（排除 <other> 和单字语法 token）
        # 默认使用最强边的 source→target（保证有向路径）
        if treatment is None and self.significant_edges:
            treatment = self.significant_edges[0][0]
        if outcome is None and self.significant_edges:
            outcome = self.significant_edges[0][1]

        if treatment is None or outcome is None:
            valid_names = [n for n in self.concept_names
                           if n != "<other>" and len(n) > 1]
            if treatment is None:
                treatment = valid_names[0] if valid_names else self.concept_names[0]
            if outcome is None:
                outcome = valid_names[-1] if valid_names else self.concept_names[-1]

        self.treatment = treatment
        self.outcome = outcome

        try:
            self.identified_estimand = self.model.identify_effect(
                proceed_when_unidentifiable=True,
            )
            identifiable = DoWhy14Adapter.is_identifiable(self.identified_estimand)
        except Exception as e:
            self._log(f"识别失败: {e}")
            self.identified_estimand = SimulationEstimand(treatment, outcome, identifiable=False)
            identifiable = False

        self._log(f"识别: {treatment} → {outcome}")
        if hasattr(self.identified_estimand, 'identifier'):
            method = (self.identified_estimand.identifier
                      if isinstance(self.identified_estimand.identifier, str)
                      else str(self.identified_estimand.identifier))
            self._log(f"  估计方法: {method}")
        self._log(f"  可识别: {identifiable}")
        return self.identified_estimand

    # ── 步骤 3: 估计因果效应 ─────────────────────────────────────────

    def estimate(self, method: str = "backdoor.linear_regression",
                 confidence_intervals: bool = True):
        """
        估计因果效应的大小和置信区间。

        Parameters
        ----------
        method : str
            DoWhy 估计方法名。
        confidence_intervals : bool
            是否计算置信区间。关闭可显著加速 LIGHT 模式。

        DoWhy 0.14 兼容: 使用 get_confidence_intervals() 获取 CI。
        注意: 如果 identify() 回退到 SimulationEstimand，estimate() 也会
        自动回退到 SimulationModel，保证管线不会中断。
        """
        if self.identified_estimand is None:
            self.identify()

        # Fallback: 如果 DoWhy identify 失败导致 estimand 是模拟的，
        # 需要同步切换 model 为 SimulationModel
        if isinstance(self.identified_estimand, SimulationEstimand) and not isinstance(self.model, SimulationModel):
            self._log("DoWhy 识别失败，自动回退到模拟模式")
            self.simulation = True
            self.model = SimulationModel(
                graph_edges=[(e[0], e[1]) for e in self.significant_edges],
                concept_names=self.concept_names,
                data=self.data_df,
                rng=self.rng,
            )

        # 过滤 statsmodels 在条件数计算中产生的无害 divide-by-zero warning
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="divide by zero encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )
            self.estimate_result = self.model.estimate_effect(
                self.identified_estimand,
                method_name=method,
                confidence_intervals=confidence_intervals,
            )

        ci = DoWhy14Adapter.get_confidence_interval(self.estimate_result)
        self._log(f"估计方法: {method}")
        self._log(f"  效应量: {self.estimate_result.value:.4f}")
        self._log(f"  95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
        return self.estimate_result

    # ── 步骤 4: 反驳测试 ─────────────────────────────────────────────

    def refute(self) -> dict:
        """
        三层反驳测试。DoWhy 0.14 兼容: 用偏差度判断 refuted。
        """
        if self.estimate_result is None:
            self.estimate()

        self.refutation_results = {}
        refuters = [
            ("random_common_cause", "随机共因"),
            ("placebo_treatment_refuter", "安慰剂处理"),
            ("data_subset_refuter", "数据子集"),
        ]

        # 过滤 statsmodels 在 bootstrap/refuter 内部产生的无害 warning
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="divide by zero encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="invalid value encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )

            for method_name, label in refuters:
                try:
                    result = self.model.refute_estimate(
                        self.identified_estimand,
                        self.estimate_result,
                        method_name=method_name,
                    )
                    check = DoWhy14Adapter.check_refuted(
                        self.estimate_result, result, method_name=method_name)
                    result._check = check  # 附加自定义判断
                    self.refutation_results[label] = result
                    self._log(f"反驳-{label}: 新效应={result.new_effect:.4f}, "
                              f"偏差={check['deviation']:.1%}, "
                              f"{'⚠️ 反驳' if check['refuted'] else '✓ 稳健'}")
                except Exception as e:
                    self._log(f"反驳-{label}: 失败 ({e})")

        return self.refutation_results

    # ── 步骤 5: 反事实查询 ───────────────────────────────────────────

    def counterfactual(
        self,
        observed_sample: np.ndarray = None,
        treatment_var: str = None,
        control_value: float = 0.0,
        treatment_value: float = 1.0,
        outcome_var: str = None,
    ) -> dict:
        """
        Pearl 三步反事实推理。

        v2: 使用独立的 PearlCounterfactual 引擎（基于估计的 SEM 系数），
        不依赖 DoWhy 的 counterfactual 方法（DoWhy 0.14 base 版无此方法）。
        """
        if treatment_var is None:
            treatment_var = self.treatment
        if outcome_var is None:
            outcome_var = self.outcome
        if observed_sample is None:
            observed_sample = self.data_df.iloc[0].values

        self._log(f"反事实查询: do({treatment_var}={treatment_value}) "
                  f"vs do({treatment_var}={control_value}) → {outcome_var}")

        # 使用 PearlCounterfactual 引擎
        result = self.pearl_cf.query(
            observed=observed_sample,
            treatment_var=treatment_var,
            outcome_var=outcome_var,
            control_value=control_value,
            treatment_value=treatment_value,
        )

        self.counterfactual_result = result
        if 'error' not in result:
            self._log(f"  观测结果: {result['observed_outcome']:.4f}")
            self._log(f"  反事实结果: {result['counterfactual_outcome']:.4f}")
            self._log(f"  个体因果效应 (ITE): {result['causal_effect']:+.4f}")
        else:
            self._log(f"  错误: {result['error']}")

        return result

    # ── 批量反事实扫描 ────────────────────────────────────────────────

    def counterfactual_scan(self, n_top_edges: int = 5) -> list[dict]:
        """对 ΔNLL 最强的 N 条边逐个执行反事实查询"""
        if not self.significant_edges:
            self.build_model()

        results = []
        for src, dst, strength in self.significant_edges[:n_top_edges]:
            try:
                cf = self.counterfactual(
                    treatment_var=src,
                    outcome_var=dst,
                    control_value=0.0,
                    treatment_value=1.0,
                )
                results.append({
                    "source": src,
                    "target": dst,
                    "trace_dnl": strength,
                    "ite": cf.get("causal_effect", float('nan')),
                    "observed": cf.get("observed_outcome", float('nan')),
                    "counterfactual": cf.get("counterfactual_outcome", float('nan')),
                })
            except Exception as e:
                self._log(f"反事实扫描 [{src}→{dst}]: 失败 ({e})")

        self.scan_results = results
        return results

    # ── v2 新增: causallearn 独立验证 ─────────────────────────────────

    def causallearn_validate(self, run_pc: bool = True, run_ges: bool = True,
                             compare: bool = True) -> dict:
        """
        使用 causallearn 的 PC 和 GES 算法进行独立因果发现，
        并与 TRACE 的结果交叉验证。

        这是六合一架构中的第六验证维度:
        - TRACE (探照灯): token 级因果发现
        - CCM (测谎仪): 非线性交叉映射
        - EDM (节拍器): 时间结构骨架
        - HAVOK (X光机): 隐藏驱动力
        - DoWhy (第五维): 识别+估计+反驳
        - causallearn (第六维): 独立图搜索算法验证

        Returns
        -------
        dict: 比较结果
        """
        if self.concept_adj is None:
            self.build_model()

        # 准备数据（排除 <other> 列）
        raw_data = self.data_df.values if hasattr(self.data_df, 'values') else np.asarray(self.data_df)

        # 只使用非 <other> 的概念
        valid_idx = [i for i, n in enumerate(self.concept_names) if n != "<other>"]
        valid_names = [self.concept_names[i] for i in valid_idx]
        valid_data = raw_data[:, valid_idx]

        if len(valid_names) < 3:
            self._log("causallearn 验证跳过: 有效概念 < 3")
            return {'error': 'too few concepts', 'n_concepts': len(valid_names)}

        self.cl_validator = CausalLearnValidator(valid_data, valid_names)

        if run_pc:
            result_pc = self.cl_validator.run_pc(alpha=0.05)
            n = result_pc.get('n_edges', 0)
            err = result_pc.get('error', '')
            self._log(f"causallearn PC: {'失败' if err else f'{n} edges'}")

        if run_ges:
            result_ges = self.cl_validator.run_ges()
            n = result_ges.get('n_edges', 0)
            err = result_ges.get('error', '')
            self._log(f"causallearn GES: {'失败' if err else f'{n} edges'}")

        if compare:
            # 只比较非 <other> 概念之间的边
            trace_valid_edges = [
                (s, d, w) for s, d, w in self.significant_edges
                if s != "<other>" and d != "<other>"
            ]
            self.cl_comparison = self.cl_validator.compare_with_trace(trace_valid_edges)

        return self.cl_comparison

    # ── v2 新增: DAG 可视化 ────────────────────────────────────────────

    def visualize(self, filename: str = "causal_graph", format: str = "png",
                  view: bool = False, graphviz_bin_dir: str = None) -> str:
        """
        使用 graphviz 渲染因果 DAG。

        Windows 上需要指定 graphviz 二进制路径。

        Parameters
        ----------
        filename : str
            输出文件名（不含扩展名）
        format : str
            输出格式 (png, pdf, svg, dot)
        view : bool
            是否自动打开查看
        graphviz_bin_dir : str or None
            graphviz bin 目录路径。如果为 None，使用 _config.get_graphviz_bin_dir()。
            不再扫描任何磁盘绝对路径，保持可移植性。

        Returns
        -------
        str: 输出文件路径，或错误信息
        """
        if not _GRAPHVIZ_AVAILABLE:
            return "[graphviz 未安装] pip install graphviz"

        if not self.significant_edges:
            self.build_model()

        # Windows: 确保 graphviz bin 在 PATH 中（仅通过参数或环境变量）
        import os as _os
        from _config import get_graphviz_bin_dir
        bin_dirs_to_try = []
        if graphviz_bin_dir:
            bin_dirs_to_try.append(graphviz_bin_dir)
        env_bin = get_graphviz_bin_dir()
        if env_bin is not None:
            bin_dirs_to_try.append(str(env_bin))

        for bin_dir in bin_dirs_to_try:
            if _os.path.isdir(bin_dir):
                current_path = _os.environ.get('PATH', '')
                if bin_dir not in current_path:
                    _os.environ['PATH'] = f"{bin_dir};{current_path}"
                break

        try:
            dot = graphviz.Digraph(
                name='TRACE_DoWhy_Causal_Graph',
                comment='Causal DAG discovered by TRACE + DoWhy',
            )
            dot.attr(rankdir='LR')
            dot.attr('node', shape='ellipse', style='filled',
                     fillcolor='#E8F0FE', fontname='SimHei')
            dot.attr('edge', fontname='SimHei', fontsize='10')

            for src, dst, strength in self.significant_edges:
                if src == "<other>" or dst == "<other>":
                    continue
                # 边宽度与因果强度成正比
                penwidth = max(0.5, min(5.0, strength / 3.0))
                dot.edge(src, dst, label=f'{strength:.1f}',
                        penwidth=str(penwidth))

            output_path = dot.render(filename=filename, format=format,
                                     cleanup=True, view=view)
            self._log(f"DAG 可视化: {output_path}")
            return output_path
        except Exception as e:
            self._log(f"DAG 可视化失败: {e}")
            return f"[可视化失败] {e}"

    # ── 综合报告 ─────────────────────────────────────────────────────

    def report(self) -> str:
        """生成 Markdown 格式的六合一（+六维）诊断报告"""
        n_edges = len(self.significant_edges)
        n_concepts = len(self.concept_names)
        n_refuted = sum(
            1 for r in self.refutation_results.values()
            if getattr(getattr(r, '_check', None), 'refuted',
                       getattr(r, 'refuted', False))
        )

        lines = [
            "# TRACE + DoWhy + Counterfactual 综合诊断报告",
            "",
            "## 1. 因果图摘要",
            f"- 概念节点: {n_concepts}",
            f"- 显著边 (ΔNLL > {self.threshold}): {n_edges}",
            f"- 运行模式: {self.mode_name}",
            f"- causallearn: {'可用' if _CAUSALLEARN_AVAILABLE else '未安装'}",
            f"- Graphviz: {'可用' if _GRAPHVIZ_AVAILABLE else '未安装'}",
            "",
        ]

        if self.significant_edges:
            lines.append("### Top-5 因果边 (TRACE ΔNLL)")
            lines.append("| 原因 | 结果 | ΔNLL |")
            lines.append("|------|------|------|")
            for src, dst, strength in self.significant_edges[:5]:
                lines.append(f"| {src} | {dst} | {strength:.2f} |")
            lines.append("")

        if self.identified_estimand is not None:
            identifiable = DoWhy14Adapter.is_identifiable(self.identified_estimand)
            lines.append("## 2. 因果效应识别")
            lines.append(f"- 处理变量: {self.treatment}")
            lines.append(f"- 结果变量: {self.outcome}")
            lines.append(f"- 可识别: {identifiable}")
            if hasattr(self.identified_estimand, 'identifier'):
                ident_str = str(self.identified_estimand.identifier)
                lines.append(f"- 识别方法: {ident_str}")
            lines.append("")

        if self.estimate_result is not None:
            ci = DoWhy14Adapter.get_confidence_interval(self.estimate_result)
            lines.append("## 3. 因果效应估计")
            lines.append(f"- 效应量 (ATE): {self.estimate_result.value:.4f}")
            lines.append(f"- 95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
            lines.append("")

        if self.refutation_results:
            lines.append("## 4. 反驳测试")
            lines.append(f"- 结论: {n_refuted}/3 被反驳 "
                         f"({'⚠️ 效应不稳定' if n_refuted >= 2 else '✓ 效应稳健'})")
            lines.append("")
            lines.append("| 反驳方法 | 原始效应 | 新效应 | 指标 | 判定 |")
            lines.append("|---------|---------|--------|------|------|")
            orig = self.estimate_result.value if self.estimate_result else 0
            for name, result in self.refutation_results.items():
                new_eff = result.new_effect
                check = getattr(result, '_check', None)
                refuted = check['refuted'] if check else False
                deviation = check['deviation'] if check else abs(new_eff - orig) / (abs(orig) + 1e-10)
                display_metric = check['display_metric'] if check else deviation
                display_label = check['display_label'] if check else "偏差"

                # 安慰剂反驳: 新效应接近 0 是支持因果性的证据
                if name == "安慰剂处理":
                    if refuted:
                        verdict = "⚠️ 安慰剂仍有效应"
                    else:
                        verdict = "✓ 安慰剂效应消失（支持因果性）"
                else:
                    verdict = "⚠️ 反驳" if refuted else "✓ 稳健"

                lines.append(f"| {name} | {orig:.4f} | {new_eff:.4f} "
                             f"| {display_label}={display_metric:.1%} | {verdict} |")
            lines.append("")

        if self.counterfactual_result:
            cf = self.counterfactual_result
            lines.append("## 5. 反事实查询")
            lines.append(f"- 观测结果: {cf.get('observed_outcome', 'N/A')}")
            lines.append(f"- 反事实结果: {cf.get('counterfactual_outcome', 'N/A')}")
            lines.append(f"- 个体因果效应 (ITE): {cf.get('causal_effect', 'N/A')}")
            lines.append("")

        if self.scan_results:
            lines.append("## 6. 反事实扫描（Top 边）")
            lines.append("| 原因 → 结果 | TRACE ΔNLL | ITE | 观测 | 反事实 |")
            lines.append("|------------|-----------|-----|------|--------|")
            for r in self.scan_results:
                lines.append(
                    f"| {r['source']} → {r['target']} "
                    f"| {r['trace_dnl']:.2f} "
                    f"| {r['ite']:+.4f} "
                    f"| {r['observed']:.4f} "
                    f"| {r['counterfactual']:.4f} |"
                )
            lines.append("")

        if self.cl_comparison:
            lines.append("## 7. causallearn 独立验证")
            lines.append("| 算法 | TRACE 边 | CL 边 | 一致 | 一致率 |")
            lines.append("|------|---------|-------|------|--------|")
            for algo_key, comp in self.cl_comparison.items():
                lines.append(
                    f"| {comp['algorithm']} "
                    f"| {comp['trace_n_edges']} "
                    f"| {comp['cl_n_edges']} "
                    f"| {comp['agree']} "
                    f"| {comp['agreement_rate']:.0%} |"
                )
            lines.append("")

        lines.append("## 诊断日志")
        for log_entry in self.log:
            lines.append(f"- {log_entry}")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 模拟模式类（DoWhy 未安装时的替代）
# ══════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════
# 便捷工厂函数
# ══════════════════════════════════════════════════════════════════════

def from_trace_output(trace_result: dict, threshold: float = 0.5,
                      concept_min_freq: int = 2, **kwargs) -> TRACE2DoWhy:
    """从 TRACE 引擎的标准输出字典创建桥接实例"""
    return TRACE2DoWhy(
        adj_matrix=trace_result["adj_matrix"],
        token_list=trace_result["token_list"],
        tokenizer=trace_result.get("tokenizer"),
        threshold=threshold,
        concept_min_freq=concept_min_freq,
        **kwargs,
    )


def quick_analysis(adj_matrix, token_list, threshold=0.5):
    """一键运行完整的六合一管线并返回 bridge"""
    bridge = TRACE2DoWhy(adj_matrix, token_list, threshold=threshold)
    bridge.build_model()
    bridge.identify()
    bridge.estimate()
    bridge.refute()
    bridge.counterfactual_scan(n_top_edges=5)
    return bridge
