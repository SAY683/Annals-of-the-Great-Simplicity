"""
Causallearn 共享工具模块
========================
统一封装 causallearn GraphNode 的索引提取逻辑，
避免在 counterfactual_bridge.py 和 six_warriors.py 中重复维护。

用法:
    from _causallearn_utils import node_index

    idx = node_index(graph_node)
"""

import re


def node_index(node) -> int:
    """从 causallearn 的 GraphNode 中提取节点索引。

    GraphNode 没有 get_index() 方法，get_name() 返回形如 'X12' 的字符串，
    用正则提取其中的数字部分作为索引。

    Parameters
    ----------
    node : causallearn.graph.GraphNode
        GraphNode 实例

    Returns
    -------
    int
        节点索引；若名字中无数字则返回 0
    """
    name = node.get_name()
    m = re.search(r'\d+', name)
    return int(m.group()) if m else 0
