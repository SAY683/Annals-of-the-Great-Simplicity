"""
管线调用序列共享助手（debt-05: 双轨入口合并）
================================================
抽取 run_cli.py / run_real_pipeline.py 中重复的 TRACE→DoWhy 管线调用序列:
  aggregate_concepts → build_model → identify → estimate → refute → counterfactual_scan

两个入口 (run_cli.py 的 cmd_demo/cmd_real 与 run_real_pipeline.py 的 main)
此前各自内联了同一套 6 步调用，本模块将其合并为单一函数，避免后续维护漂移。

用法:
    from pipeline_helpers import run_full_pipeline
    run_full_pipeline(bridge, preset=p)
    # 诊断信息可在调用后从 bridge 状态读取 (bridge.concept_names /
    # bridge.significant_edges / bridge.estimate_result / bridge.scan_results ...)
"""


def run_full_pipeline(bridge, preset=None, identify_kwargs=None, n_top_edges=None):
    """运行完整的六合一管线核心序列。

    依次执行:
      aggregate_concepts → build_model → identify → estimate → refute → counterfactual_scan

    Parameters
    ----------
    bridge : TRACE2DoWhy
        已构造的桥接实例（尚未运行任何步骤）。
    preset : _DotDict or None
        来自 ``load_presets()`` 的预设对象。若提供且未显式指定 ``n_top_edges``，
        则从 ``preset.counterfactual.scan_top_n`` 推导默认扫描边数。
    identify_kwargs : dict or None
        传给 ``bridge.identify()`` 的关键字参数（如 treatment/outcome）。
        ``None`` 表示用 bridge 默认（取最强边的 source→target）。
    n_top_edges : int or None
        反事实扫描边数。``None`` 时按 preset → 5 的顺序回退。

    Returns
    -------
    TRACE2DoWhy
        运行完管线的 bridge（便于链式调用 / 后续读取状态）。
    """
    bridge.aggregate_concepts()
    bridge.build_model()
    if identify_kwargs:
        bridge.identify(**identify_kwargs)
    else:
        bridge.identify()
    bridge.estimate()
    bridge.refute()

    if n_top_edges is None:
        if preset is not None:
            try:
                n_top_edges = preset.counterfactual.scan_top_n
            except (AttributeError, KeyError):
                n_top_edges = 5
        else:
            n_top_edges = 5

    # 不超过实际显著边数，避免 counterfactual_scan 越界
    n_top_edges = min(n_top_edges, max(len(bridge.significant_edges), 1))
    bridge.counterfactual_scan(n_top_edges=n_top_edges)
    return bridge
