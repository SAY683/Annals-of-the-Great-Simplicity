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

    # FCI 暂未实现，预留接口（如需支持隐藏混淆因子，可在此处添加 run_fci 方法）

    def _parse_causallearn_graph(self, G) -> list:
        """将 causallearn 的 GeneralGraph 解析为边列表"""
        edges = []
        try:
            graph_edges = G.get_graph_edges()
            for edge in graph_edges:
                i = _node_index(edge.get_node1())
                j = _node_index(edge.get_node2())
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
