"""
causallearn 集成层（从 counterfactual_bridge.py 抽取）
======================================================
使用 causallearn 的 PC、GES 算法作为独立因果发现方法，
与 TRACE 的结果进行交叉验证。

依赖说明:
  本模块不维护模块级依赖检查块（_CAUSALLEARN_AVAILABLE 等）。
  可用性标志通过构造参数 ``causallearn_available`` 传入。
  为保持独立可用性，未传该参数时进行惰性探测（非模块级 block）。
  causallearn 的算法实现（pc/ges）在方法内部惰性导入。
"""

import numpy as np

from _causallearn_utils import node_index as _node_index


class CausalLearnValidator:
    """
    使用 causallearn 的 PC、GES 算法作为独立因果发现方法，
    与 TRACE 的结果进行交叉验证。
    """

    def __init__(self, data: np.ndarray, concept_names: list,
                 causallearn_available: bool = None):
        """
        Parameters
        ----------
        data : (N, V) array
            观测数据矩阵
        concept_names : list[str]
            变量名列表
        causallearn_available : bool, optional
            causallearn 是否可用的标志（由调用方传入以避免重复探测）。
            若为 None，则在此惰性探测一次（保持独立可用性）。
        """
        self.data = data
        self.concept_names = concept_names
        self._name_to_idx = {n: i for i, n in enumerate(concept_names)}
        self.results: dict = {}
        self.logs: list[str] = []  # 解析/检查过程中的诊断日志

        if causallearn_available is None:
            try:
                import causallearn  # noqa: F401
                causallearn_available = True
            except ImportError:
                causallearn_available = False
        self._causallearn_available = causallearn_available

    def _log(self, msg: str):
        """记录诊断日志，避免静默吞异常"""
        self.logs.append(msg)

    def run_pc(self, alpha: float = 0.05, **kwargs) -> dict:
        """运行 PC (Peter-Clark) 算法"""
        if not self._causallearn_available:
            return {'error': 'causallearn not installed', 'edges': []}

        try:
            from causallearn.search.ConstraintBased.PC import pc as pc_alg
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
        if not self._causallearn_available:
            return {'error': 'causallearn not installed', 'edges': []}

        try:
            from causallearn.search.ScoreBased.GES import ges as ges_alg
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

    def run_fci(self, alpha: float = 0.05, independence_test_method: str = 'fisherz',
                depth: int = -1, **kwargs) -> dict:
        """运行 FCI (Fast Causal Inference) 算法

        FCI 与 PC 的关键区别: FCI 能够处理潜在混淆因子（latent confounders），
        输出 PAG (Partial Ancestral Graph)，其边类型比 PC 的 CPDAG 更丰富:
          X → Y : X 是 Y 的直接原因（无混淆）
          X ↔ Y : X 和 Y 有共同潜在原因（关联但无直接因果）
          X ⊙→ Y : X 可能是 Y 的原因（存在潜在混淆的不确定性）
          X — Y : 关联方向不确定

        这使得 FCI 在存在未观测混淆因子时仍能给出可靠的因果结论，
        而 PC/GES 在此场景下可能产生虚假的因果方向判定。

        Parameters
        ----------
        alpha : float
            独立性检验显著性水平
        independence_test_method : str
            独立性检验方法 ('fisherz' / 'kci' / 'gsq' 等)
        depth : int
            搜索深度 (-1 = 无限制)
        """
        if not self._causallearn_available:
            return {'error': 'causallearn not installed', 'edges': []}

        try:
            from causallearn.search.ConstraintBased.FCI import fci
            # show_progress=False 避免污染日志输出
            G, edges = fci(self.data, independence_test_method=independence_test_method,
                           alpha=alpha, depth=depth, show_progress=False,
                           node_names=self.concept_names, **kwargs)
            parsed_edges = self._parse_causallearn_graph(G)

            self.results['fci'] = {
                'algorithm': 'FCI (constraint-based, latent-confounder-aware)',
                'edges': parsed_edges,
                'n_edges': len(parsed_edges),
                'graph': G,
                'raw_edges': edges,
                'note': ('FCI 输出 PAG (Partial Ancestral Graph)，可识别潜在混淆。'
                         '↔ 表示存在潜在共同原因，⊙→ 表示可能因果但存在不确定性。'),
            }
            return self.results['fci']
        except Exception as e:
            return {'error': str(e), 'edges': []}

    def _parse_causallearn_graph(self, G) -> list:
        """将 causallearn 的 GeneralGraph 解析为边列表

        端点常量（causallearn.graph.Endpoint）:
          TAIL   = -1  (无箭头，无圆圈)
          ARROW  =  1  (箭头)
          CIRCLE =  2  (圆圈，仅FCI的PAG中出现，表示方向不确定)

        边类型映射:
          PC/GES (CPDAG):
            TAIL→ARROW  = → (直接因果)
            ARROW→TAIL  = ← (反向因果)
            TAIL→TAIL   = — (无方向，马蹄形)
          FCI (PAG) 额外类型:
            CIRCLE→ARROW = ⊙→ (可能因果，存在不确定性)
            ARROW→CIRCLE = ←⊙ (反向可能因果)
            CIRCLE→CIRCLE= ⊙—⊙ (方向完全不确定)
            ARROW→ARROW  = ↔ (潜在共同原因)
            CIRCLE→TAIL  = ⊙— (方向不确定，但非反向)
            TAIL→CIRCLE  = —⊙ (方向不确定，但非正向)

        P1 修缮 (两处bug):
          1. 端点常量错误: 原代码 tail=1, arrow=2，与 causallearn 实际常量
             (TAIL=-1, ARROW=1, CIRCLE=2) 不符，导致 PC/GES 边方向全部判反。
             修复: 直接用 Endpoint 枚举对象比较，不提取 .value。
          2. 节点索引偏移: causallearn 节点名 'X1','X2',... 是 1-based，
             _node_index 返回 1,2,...，但 concept_names 列表是 0-based。
             原代码直接用返回值索引 concept_names，导致所有节点名偏移1位
             (X1→concept_names[1]=Y 而非 concept_names[0]=X)。
             修复: i = _node_index(...) - 1 转为 0-based。
        """
        edges = []
        try:
            from causallearn.graph.Endpoint import Endpoint
            TAIL = Endpoint.TAIL
            ARROW = Endpoint.ARROW
            CIRCLE = Endpoint.CIRCLE

            graph_edges = G.get_graph_edges()
            for edge in graph_edges:
                # 节点索引: causallearn 1-based → Python 0-based
                i = _node_index(edge.get_node1()) - 1
                j = _node_index(edge.get_node2()) - 1
                endpoint1 = edge.get_endpoint1()
                endpoint2 = edge.get_endpoint2()

                # 端点组合 → 方向标记 (直接用 Endpoint 枚举对象比较)
                if endpoint1 == TAIL and endpoint2 == ARROW:
                    direction = '→'
                elif endpoint1 == ARROW and endpoint2 == TAIL:
                    direction = '←'
                elif endpoint1 == TAIL and endpoint2 == TAIL:
                    direction = '—'
                elif endpoint1 == ARROW and endpoint2 == ARROW:
                    direction = '↔'
                elif endpoint1 == CIRCLE and endpoint2 == ARROW:
                    direction = '⊙→'
                elif endpoint1 == ARROW and endpoint2 == CIRCLE:
                    direction = '←⊙'
                elif endpoint1 == CIRCLE and endpoint2 == CIRCLE:
                    direction = '⊙—⊙'
                elif endpoint1 == CIRCLE and endpoint2 == TAIL:
                    direction = '⊙—'
                elif endpoint1 == TAIL and endpoint2 == CIRCLE:
                    direction = '—⊙'
                else:
                    direction = '?'

                if 0 <= i < len(self.concept_names) and 0 <= j < len(self.concept_names):
                    edges.append({
                        'source': self.concept_names[i],
                        'target': self.concept_names[j],
                        'direction': direction,
                    })
                else:
                    self._log(f"节点索引越界: i={i}, j={j}, concept_names长度={len(self.concept_names)}")
        except ImportError:
            # causallearn 不可用时，尝试用整数常量 fallback
            TAIL, ARROW, CIRCLE = -1, 1, 2
            try:
                graph_edges = G.get_graph_edges()
                for edge in graph_edges:
                    i = _node_index(edge.get_node1()) - 1
                    j = _node_index(edge.get_node2()) - 1
                    ep1 = edge.get_endpoint1()
                    ep2 = edge.get_endpoint2()
                    # 提取 .value 用于整数比较
                    v1 = ep1.value if hasattr(ep1, 'value') else ep1
                    v2 = ep2.value if hasattr(ep2, 'value') else ep2
                    if v1 == TAIL and v2 == ARROW:
                        direction = '→'
                    elif v1 == ARROW and v2 == TAIL:
                        direction = '←'
                    elif v1 == TAIL and v2 == TAIL:
                        direction = '—'
                    elif v1 == ARROW and v2 == ARROW:
                        direction = '↔'
                    else:
                        direction = '?'
                    if 0 <= i < len(self.concept_names) and 0 <= j < len(self.concept_names):
                        edges.append({
                            'source': self.concept_names[i],
                            'target': self.concept_names[j],
                            'direction': direction,
                        })
            except Exception as e:
                self._log(f"causallearn 图解析失败(fallback): {e}")
        except Exception as e:
            self._log(f"causallearn 图解析失败: {e}")
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
