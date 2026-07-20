"""pytest 共享 fixtures 与 sys.path 配置

将 examples/counterfactual_hybrid 加入 sys.path，使所有测试文件
可直接 ``from counterfactual_bridge import TRACE2DoWhy`` 等导入。
"""
import sys
from pathlib import Path

import numpy as np
import pytest


# ── sys.path 配置 ──────────────────────────────────────────────
# tests/ → trace-engine/ → examples/counterfactual_hybrid/
_SKILL_DIR = Path(__file__).resolve().parent.parent
_COUNTERFACTUAL_DIR = _SKILL_DIR / "examples" / "counterfactual_hybrid"

if str(_COUNTERFACTUAL_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTERFACTUAL_DIR))


# ── 共享 fixtures ─────────────────────────────────────────────

@pytest.fixture
def skill_dir():
    """返回 trace-engine 根目录路径"""
    return _SKILL_DIR


@pytest.fixture
def counterfactual_dir():
    """返回 examples/counterfactual_hybrid 目录路径"""
    return _COUNTERFACTUAL_DIR


@pytest.fixture
def sample_adj_matrix():
    """返回一个 5x5 测试邻接矩阵（上三角，含因果边）"""
    return np.array([
        [0.0, 1.0, 2.0, 0.0, 0.0],
        [0.0, 0.0, 3.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 2.0, 1.0],
        [0.0, 0.0, 0.0, 0.0, 1.5],
        [0.0, 0.0, 0.0, 0.0, 0.0],
    ], dtype=float)


@pytest.fixture
def sample_tokens():
    """返回 5 个测试 token 列表（均为有效中文概念）"""
    return ["算法", "推荐", "信息", "茧房", "极化"]
