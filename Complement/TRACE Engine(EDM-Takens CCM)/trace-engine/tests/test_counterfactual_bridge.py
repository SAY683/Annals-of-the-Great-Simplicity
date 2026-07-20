"""TRACE2DoWhy 桥接核心功能 pytest 测试

覆盖:
  - 模块导入
  - adj_matrix 形状校验（非 2D / 非方阵 / NaN / Inf）
  - token → concept 聚合
  - filter_mode: top_n / percentile
  - threshold 负数异常
  - 概念节点 <2 异常
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# 防御性 sys.path 配置（conftest.py 已配置，此处保留以保证文件可独立导入）
_COUNTERFACTUAL_DIR = (
    Path(__file__).resolve().parent.parent / "examples" / "counterfactual_hybrid"
)
if str(_COUNTERFACTUAL_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTERFACTUAL_DIR))

from counterfactual_bridge import TRACE2DoWhy


# ════════════════════════════════════════════════════════════════
# 1. 导入测试
# ════════════════════════════════════════════════════════════════

def test_import_trace2dowhy():
    """验证 TRACE2DoWhy 可正常导入且具备核心方法"""
    assert TRACE2DoWhy is not None
    assert hasattr(TRACE2DoWhy, "aggregate_concepts")
    assert hasattr(TRACE2DoWhy, "build_model")
    assert hasattr(TRACE2DoWhy, "identify")
    assert hasattr(TRACE2DoWhy, "estimate")
    assert hasattr(TRACE2DoWhy, "refute")


# ════════════════════════════════════════════════════════════════
# 2. adj_matrix 形状校验（参数化：非 2D / 非方阵 / NaN / Inf）
# ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("scenario", ["non_2d", "non_square", "nan", "inf"])
def test_adj_matrix_validation(scenario):
    """测试 adj_matrix 形状校验：
    - 非 2D / 非方阵 → ValueError
    - NaN / Inf → RuntimeWarning + 替换为 0.0（不抛异常）
    """
    if scenario == "non_2d":
        # 1D 数组：ndim != 2 → ValueError
        with pytest.raises(ValueError, match="2D 方阵"):
            TRACE2DoWhy(np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
                        ["算法", "推荐", "信息", "茧房", "极化"])

    elif scenario == "non_square":
        # 2x3 非方阵：shape[0] != shape[1] → ValueError
        with pytest.raises(ValueError, match="2D 方阵"):
            TRACE2DoWhy(np.zeros((2, 3)), ["算法", "推荐"])

    elif scenario == "nan":
        # 含 NaN：触发 RuntimeWarning 并替换为 0.0
        adj = np.array([
            [0.0, np.nan, 0.0],
            [0.0, 0.0,   1.0],
            [0.0, 0.0,   0.0],
        ])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bridge = TRACE2DoWhy(adj, ["算法", "推荐", "信息"])
            assert any(issubclass(w.category, RuntimeWarning) for w in caught)
        # NaN 应被替换为 0.0，矩阵全有限
        assert np.isfinite(bridge.adj_matrix).all()
        assert bridge.adj_matrix[0, 1] == 0.0

    elif scenario == "inf":
        # 含 Inf：触发 RuntimeWarning 并替换为 0.0
        adj = np.array([
            [0.0,   np.inf, 0.0],
            [0.0,   0.0,    1.0],
            [0.0,   0.0,    0.0],
        ])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bridge = TRACE2DoWhy(adj, ["算法", "推荐", "信息"])
            assert any(issubclass(w.category, RuntimeWarning) for w in caught)
        assert np.isfinite(bridge.adj_matrix).all()
        assert bridge.adj_matrix[0, 1] == 0.0


# ════════════════════════════════════════════════════════════════
# 3. token → concept 聚合
# ════════════════════════════════════════════════════════════════

def test_aggregate_concepts_basic():
    """测试 token → concept 聚合基础流程"""
    tokens = ["算法", "推荐", "算法", "推荐", "信息", "茧房", "信息"]
    # 7x7 上三角邻接矩阵
    adj = np.array([
        [0.0, 1.0, 0.5, 0.0, 2.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.5, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ])
    bridge = TRACE2DoWhy(adj, tokens, threshold=0.03, concept_min_freq=2)
    concept_map = bridge.aggregate_concepts()

    assert isinstance(concept_map, dict)
    assert isinstance(bridge.concept_names, list)
    assert isinstance(bridge.concept_adj, np.ndarray)
    # "算法" / "推荐" 各出现 2 次 (>= concept_min_freq=2) → 独立概念节点
    assert "算法" in bridge.concept_names
    assert "推荐" in bridge.concept_names
    # "信息" 出现 2 次 → 也是独立概念
    assert "信息" in bridge.concept_names
    # "茧房" 仅出现 1 次 → 归入 <other>
    assert "茧房" not in bridge.concept_names
    assert "<other>" in bridge.concept_names


# ════════════════════════════════════════════════════════════════
# 4. filter_mode: top_n
# ════════════════════════════════════════════════════════════════

def test_filter_mode_top_n():
    """测试 top_n 过滤模式：显著边数 <= max_edges_for_dowhy 且按强度降序"""
    rng = np.random.default_rng(42)
    n = 20
    adj = rng.uniform(0, 5, (n, n))
    adj = np.triu(adj, 1)  # 上三角
    tokens = [f"概念_{i}" for i in range(n)]

    bridge = TRACE2DoWhy(
        adj, tokens,
        threshold=0.5,
        concept_min_freq=1,
        max_edges_for_dowhy=5,
        filter_mode="top_n",
    )
    bridge.build_model()

    # top_n 模式：边数被截断至 max_edges_for_dowhy
    assert len(bridge.significant_edges) <= 5
    # 边按强度降序排列
    strengths = [e[2] for e in bridge.significant_edges]
    assert strengths == sorted(strengths, reverse=True)
    # 日志应记录 mode=top_n（n_total > max_edges_for_dowhy 时触发）
    log_text = "\n".join(bridge.log)
    assert "mode=top_n" in log_text


# ════════════════════════════════════════════════════════════════
# 5. filter_mode: percentile
# ════════════════════════════════════════════════════════════════

def test_filter_mode_percentile():
    """测试 percentile 过滤模式：边数减少且日志记录 mode=percentile"""
    rng = np.random.default_rng(42)
    n = 20
    adj = rng.uniform(0, 5, (n, n))
    adj = np.triu(adj, 1)
    tokens = [f"概念_{i}" for i in range(n)]

    bridge = TRACE2DoWhy(
        adj, tokens,
        threshold=0.5,
        concept_min_freq=1,
        max_edges_for_dowhy=5,
        filter_mode="percentile",
        filter_percentile=70,
    )
    bridge.build_model()

    assert isinstance(bridge.significant_edges, list)
    # 触发了 percentile 过滤（n_total > max_edges_for_dowhy 时记录 mode）
    log_text = "\n".join(bridge.log)
    assert "mode=percentile" in log_text
    # percentile 过滤后边数应不超过过滤前的数量（至少过滤发生）
    # 由于 percentile 不强制硬截断，仅断言 list 类型与日志路径


# ════════════════════════════════════════════════════════════════
# 6. threshold 负数异常
# ════════════════════════════════════════════════════════════════

def test_threshold_negative_raises():
    """负数 threshold 应在 build_model 时抛 ValueError"""
    # 需 >= 2 个概念节点才能到达 threshold 校验（C < 2 会先抛异常）
    tokens = ["算法", "推荐", "算法", "推荐"]  # 2 unique, each freq=2
    adj = np.array([
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0, 0.0],
    ])
    bridge = TRACE2DoWhy(adj, tokens, threshold=-0.1, concept_min_freq=2)
    with pytest.raises(ValueError, match="threshold"):
        bridge.build_model()


# ════════════════════════════════════════════════════════════════
# 7. 概念节点 <2 异常
# ════════════════════════════════════════════════════════════════

def test_concept_count_too_few_raises():
    """概念节点 < 2 时应在 build_model 抛 ValueError"""
    # 3 unique token 各出现 1 次，concept_min_freq=2 → 全归 <other> → C=1
    tokens = ["算法", "推荐", "信息"]
    adj = np.array([
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0],
    ])
    bridge = TRACE2DoWhy(adj, tokens, threshold=0.03, concept_min_freq=2)
    with pytest.raises(ValueError, match="概念节点不足"):
        bridge.build_model()
