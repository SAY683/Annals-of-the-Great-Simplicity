"""六勇士 (six_warriors.py) pytest 测试

覆盖:
  - WarriorCard.tier 字段存在性
  - _deploy_trace 的 D2 修复：阈值随 bridge.threshold 缩放
  - assemble_all_six 返回 6 个 warrior card
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# 防御性 sys.path 配置
_COUNTERFACTUAL_DIR = (
    Path(__file__).resolve().parent.parent / "examples" / "counterfactual_hybrid"
)
if str(_COUNTERFACTUAL_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTERFACTUAL_DIR))

from six_warriors import (
    WarriorCard,
    assemble_all_six,
    _deploy_trace,
)
from counterfactual_bridge import TRACE2DoWhy


# ════════════════════════════════════════════════════════════════
# 1. WarriorCard.tier 字段
# ════════════════════════════════════════════════════════════════

def test_warrior_card_tier_field():
    """验证 WarriorCard 实例含 tier 字段（元审计 P0 修缮：等级显式化）"""
    # 显式指定 tier="A"
    card_a = WarriorCard("TEST_A", "测试勇士A", "测试工具", tier="A")
    assert hasattr(card_a, "tier")
    assert card_a.tier == "A"

    # 显式指定 tier="B"
    card_b = WarriorCard("TEST_B", "测试勇士B", "测试工具", tier="B")
    assert card_b.tier == "B"

    # 默认 tier 应为 "A"（按 WarriorCard.__init__ 签名）
    card_default = WarriorCard("TEST_D", "测试勇士D", "测试工具")
    assert card_default.tier == "A"

    # to_dict 应包含 tier 字段
    d = card_a.to_dict()
    assert "tier" in d
    assert d["tier"] == "A"


# ════════════════════════════════════════════════════════════════
# 2. _deploy_trace 的 D2 修复：阈值缩放
# ════════════════════════════════════════════════════════════════

def test_deploy_trace_signal_ok_threshold():
    """验证 D2 修复后 _deploy_trace 使用 bridge.threshold * 10 作为 SIGNAL_OK 阈值

    场景: max_dnl=0.2 的中等强度信号
      - llama 预设 threshold=0.01 → _signal_ok_threshold=0.1 → 0.2 > 0.1 → SIGNAL_OK
      - 默认预设 threshold=0.03 → _signal_ok_threshold=0.3 → 0.2 < 0.3 → SIGNAL_WEAK

    若未做 D2 修复（固定阈值 0.3），llama 预设下 0.2 永远 SIGNAL_WEAK（误判）。
    """
    # 构造 adj 使 max_dnl=0.2
    adj = np.array([
        [0.0, 0.2, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ])
    tokens = ["算法", "推荐", "信息", "茧房"]

    # llama 预设：threshold=0.01 → _signal_ok_threshold=0.1 → 0.2 > 0.1 → SIGNAL_OK
    bridge_llama = TRACE2DoWhy(adj, tokens, threshold=0.01)
    card_llama = _deploy_trace(adj, tokens, bridge=bridge_llama)
    assert card_llama.verdict == "SIGNAL_OK", (
        f"llama 预设下 max_dnl=0.2 应判 SIGNAL_OK，实际 {card_llama.verdict}"
    )

    # 默认预设：threshold=0.03 → _signal_ok_threshold=0.3 → 0.2 < 0.3 → SIGNAL_WEAK
    bridge_default = TRACE2DoWhy(adj, tokens, threshold=0.03)
    card_default = _deploy_trace(adj, tokens, bridge=bridge_default)
    assert card_default.verdict == "SIGNAL_WEAK", (
        f"默认预设下 max_dnl=0.2 应判 SIGNAL_WEAK，实际 {card_default.verdict}"
    )

    # 验证 bridge.threshold 通过 getattr 读取（None bridge 时回退 0.03）
    card_no_bridge = _deploy_trace(adj, tokens, bridge=None)
    # bridge=None → getattr(None, 'threshold', 0.03) = 0.03 → 0.3 阈值 → 0.2 < 0.3 → WEAK
    assert card_no_bridge.verdict == "SIGNAL_WEAK"


# ════════════════════════════════════════════════════════════════
# 3. assemble_all_six 返回 6 个 warrior card
# ════════════════════════════════════════════════════════════════

def test_assemble_all_six_returns_dict():
    """验证 assemble_all_six 返回 dict 且包含 6 个 warrior card"""
    rng = np.random.default_rng(42)
    n = 12
    adj = rng.uniform(0, 5, (n, n))
    adj = np.triu(adj, 1)
    tokens = [f"概念_{i}" for i in range(n)]

    # 构造已完成 build_model 的桥接实例，使 dowhy_cf / causallearn 战士可部署
    bridge = TRACE2DoWhy(adj, tokens, threshold=0.5, concept_min_freq=1)
    bridge.build_model()

    cards = assemble_all_six(adj, tokens, bridge=bridge)

    # 返回 dict
    assert isinstance(cards, dict)
    # 6 个战士：trace / ccm / edm / havok / dowhy_cf / causallearn
    assert len(cards) == 6, f"应返回 6 个 warrior card，实际 {len(cards)}"
    expected_keys = {"trace", "ccm", "edm", "havok", "dowhy_cf", "causallearn"}
    assert set(cards.keys()) == expected_keys, (
        f"keys 应为 {expected_keys}，实际 {set(cards.keys())}"
    )
    # 每个 card 都是 WarriorCard 实例
    for key, card in cards.items():
        assert isinstance(card, WarriorCard), (
            f"{key} 应为 WarriorCard 实例，实际 {type(card)}"
        )
        # 每个 card 都有 tier 字段（D2/元审计 P0 修缮）
        assert hasattr(card, "tier")
