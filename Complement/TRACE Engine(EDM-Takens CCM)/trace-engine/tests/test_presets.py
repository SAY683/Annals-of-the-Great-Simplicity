"""预设系统 (presets.py / presets.yaml) pytest 测试

覆盖:
  - load_yaml_presets: yaml.safe_load 路径
  - _simple_yaml_parse: 手写解析器
  - load_presets('standard') / ('llama') 加载
  - 未知预设回退 standard
  - 场景预设深合并
"""
import sys
from pathlib import Path

import pytest

# 防御性 sys.path 配置
_COUNTERFACTUAL_DIR = (
    Path(__file__).resolve().parent.parent / "examples" / "counterfactual_hybrid"
)
if str(_COUNTERFACTUAL_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTERFACTUAL_DIR))

import presets as _presets_mod
from presets import (
    load_yaml_presets,
    load_presets,
    _simple_yaml_parse,
    _is_pyyaml_available,
)


_PRESETS_YAML = Path(_presets_mod.__file__).resolve().parent / "presets.yaml"


# ════════════════════════════════════════════════════════════════
# 1. load_yaml_presets — yaml.safe_load 路径
# ════════════════════════════════════════════════════════════════

def test_load_yaml_presets():
    """验证 load_yaml_presets 返回 dict 且包含核心 section

    优先走 ``yaml.safe_load`` 路径；PyYAML 不可用时回退到手写解析器。
    两条路径返回同构 dict。
    """
    raw = load_yaml_presets()
    assert isinstance(raw, dict)
    # 顶层 section
    assert "presets" in raw
    assert "trace2dowhy" in raw
    assert "dowhy" in raw
    assert "counterfactual" in raw
    assert "auditor" in raw
    # presets 下包含 standard / llama 场景
    assert "standard" in raw["presets"]
    assert "llama" in raw["presets"]
    # 顶层 trace2dowhy.threshold 应为 0.03（默认值）
    assert raw["trace2dowhy"]["threshold"] == 0.03

    # 若 PyYAML 可用，验证与 yaml.safe_load 直接调用结果一致
    if _is_pyyaml_available():
        import yaml
        with open(_PRESETS_YAML, "r", encoding="utf-8") as f:
            expected = yaml.safe_load(f)
        assert raw == expected


# ════════════════════════════════════════════════════════════════
# 2. _simple_yaml_parse — 手写解析器
# ════════════════════════════════════════════════════════════════

def test_simple_yaml_parse():
    """验证手写解析器能正确解析 presets.yaml"""
    raw = _simple_yaml_parse(_PRESETS_YAML)
    assert isinstance(raw, dict)
    assert "trace2dowhy" in raw
    assert "presets" in raw
    # 顶层 threshold = 0.03
    assert raw["trace2dowhy"]["threshold"] == 0.03
    # 顶层 concept_min_freq = 2
    assert raw["trace2dowhy"]["concept_min_freq"] == 2
    # standard 场景 threshold = 0.03 (ALG-01修复: 与顶层默认值和模型文档推荐一致, 原0.3疑似笔误)
    assert raw["presets"]["standard"]["trace2dowhy"]["threshold"] == 0.03
    # llama 场景 threshold = 0.01
    assert raw["presets"]["llama"]["trace2dowhy"]["threshold"] == 0.01
    # 布尔值解析：classical_mode = false
    assert raw["trace2dowhy"]["classical_mode"] is False
    # null 解析：sem_regularization = None
    assert raw["counterfactual"]["sem_regularization"] is None


# ════════════════════════════════════════════════════════════════
# 3. load_presets('standard')
# ════════════════════════════════════════════════════════════════

def test_load_presets_standard():
    """验证 standard 预设加载（深合并路径）"""
    p = load_presets("standard")
    # standard 场景覆盖 trace2dowhy.threshold 为 0.03 (ALG-01修复: 与模型文档推荐一致)
    assert p.trace2dowhy.threshold == 0.03
    assert p.trace2dowhy.concept_min_freq == 3
    assert p.trace2dowhy.max_edges_for_dowhy == 8
    # 未被 standard 覆盖的字段保留基础值
    assert p.trace2dowhy.random_state == 42
    # standard 场景覆盖 counterfactual.scan_top_n 为 5
    assert p.counterfactual.scan_top_n == 5
    # dowhy section 未被 standard 覆盖，保留基础值
    assert p.dowhy.estimation_method == "backdoor.linear_regression"


# ════════════════════════════════════════════════════════════════
# 4. load_presets('llama') — threshold=0.01
# ════════════════════════════════════════════════════════════════

def test_load_presets_llama():
    """验证 llama 预设加载：threshold=0.01"""
    p = load_presets("llama")
    assert p.trace2dowhy.threshold == 0.01
    assert p.trace2dowhy.concept_min_freq == 1
    assert p.trace2dowhy.max_edges_for_dowhy == 12
    assert p.trace2dowhy.filter_mode == "topn"
    # counterfactual section 覆盖
    assert p.counterfactual.scan_top_n == 5
    assert p.counterfactual.sem_regularization == "ridge"
    assert p.counterfactual.sem_alpha == 0.01
    # auditor section 覆盖
    assert p.auditor.strict_mode is False
    assert p.auditor.min_n_per_v_ratio == 2.0


# ════════════════════════════════════════════════════════════════
# 5. 未知预设回退 standard
# ════════════════════════════════════════════════════════════════

def test_load_presets_unknown_fallback():
    """验证未知预设回退到 standard 场景"""
    p = load_presets("nonexistent_preset_xyz")
    # load_presets 在预设不存在时返回 raw['presets']['standard']
    # standard 场景 threshold=0.03 (ALG-01修复); 用 concept_min_freq=3 区分顶层默认值 2
    assert p.trace2dowhy.threshold == 0.03
    assert p.trace2dowhy.concept_min_freq == 3


# ════════════════════════════════════════════════════════════════
# 6. 场景预设深合并
# ════════════════════════════════════════════════════════════════

def test_deep_merge():
    """验证场景预设深合并：deep 覆盖多 section 字段，未覆盖字段保留基础值"""
    p = load_presets("deep")
    # deep 场景覆盖 trace2dowhy
    assert p.trace2dowhy.threshold == 0.2
    assert p.trace2dowhy.concept_min_freq == 2
    assert p.trace2dowhy.max_edges_for_dowhy == 15
    assert p.trace2dowhy.filter_mode == "percentile"
    assert p.trace2dowhy.filter_percentile == 80
    # 未被 deep 覆盖的 trace2dowhy.random_state 保留基础值 42
    assert p.trace2dowhy.random_state == 42
    # deep 覆盖 counterfactual
    assert p.counterfactual.scan_top_n == 10
    assert p.counterfactual.sem_regularization == "ridge"
    # deep 覆盖 auditor
    assert p.auditor.strict_mode is True
    # deep 覆盖 visualization
    assert p.visualization.dpi == 300
    # 未被 deep 覆盖的 visualization.format 保留基础值 "png"
    assert p.visualization.format == "png"
