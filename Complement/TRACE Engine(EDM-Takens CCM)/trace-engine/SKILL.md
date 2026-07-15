---
name: trace-engine
description: >
  TRACE causal discovery engine — token-level autoregressive ΔNLL causal
  discovery with six-in-one heterogeneous validation: TRACE + CCM + EDM +
  HAVOK + DoWhy/Counterfactual + causallearn.
---

# TRACE Engine Skill

Token-level causal discovery via autoregressive density estimation, with
EDM-Takens CCM cross-validation, HAVOK decomposition, DoWhy formal causal
inference, Pearl counterfactual reasoning, and causallearn independent
validation.

## Quick Start

### CLI entry point

```bash
cd examples/counterfactual_hybrid

# Demo on simulated data (no model required)
python run_cli.py demo

# Run the 10-case test suite
python test_case.py

# Self-test the whole Skill
python ../../tests/test_skill.py
```

### Python API

```python
import sys
sys.path.insert(0, 'examples/counterfactual_hybrid')

from counterfactual_bridge import TRACE2DoWhy
from presets import load_presets

# Load unified parameter presets
p = load_presets('standard')

# adj_matrix: token-level ΔNLL causal matrix
# tokens: list of tokens
bridge = TRACE2DoWhy(adj_matrix, tokens, **p.trace2dowhy)
bridge.build_model()
bridge.identify(treatment='算法推荐', outcome='信息茧房')
bridge.estimate()
bridge.refute()
bridge.counterfactual_scan(n_top_edges=5)
bridge.causallearn_validate()
print(bridge.report())
```

### Web UI

See [trace-engine-web/README.md](../trace-engine-web/README.md) for the
drag-and-drop Web interface with real-time SSE logs.

## Six-in-One Architecture

```
Layer 1: Environment Validation     → PyTorch, deps, model files
Layer 2: Configuration Audit        → seq_len, threshold, VRAM safety
Layer 3: CCM Cross-Validation       → TRACE vs CCM convergence
Layer 4: DoWhy Formal Inference     → Model → Identify → Estimate → Refute
Layer 5: Pearl Counterfactual       → Abduction → Action → Prediction
Layer 6: causallearn Graph Search   → PC / FCI / GES independent check
```

### 六维诊断矩阵

| # | 代号 | 战士 | Instrument | Algorithm | Measurement | Best For |
|---|------|------|-----------|-----------|-------------|----------|
| 1 | 🔴 | 拓扑先锋 | 探照灯 | TRACE ΔNLL | Token 级因果边 | 任何文本 |
| 2 | 🔵 | 流形力场 | 测谎仪 | CCM | 非线性纠缠验证 | 论证文 (>3 次重复) |
| 3 | 🟡 | 时序节拍器 | 套路探测器 | EDM ρ | 时间结构骨架 | 叙事文 |
| 4 | ⚫ | 混沌暗杀者 | X光机 | HAVOK | 隐藏驱动力 | 因果矩阵 > 50×50 |
| 5 | 🟡 | 反事实造物主 | 思想实验引擎 | DoWhy+Pearl CF | 可识别性+反事实 | 有向路径 |
| 6 | ⬜ | 独立验证者 | 第三人 | PC/FCI/GES | 统计因果发现 | 大数据 (N >> V) |

**核心原则**: 每个组件测量不同物理维度；组件的“失败”也是诊断信号。
六战士合体 = **因果拓扑画像 (Complete Topological Portrait)**。

## Parameter Presets

Unified presets live in [`examples/counterfactual_hybrid/presets.yaml`](examples/counterfactual_hybrid/presets.yaml):

| Preset | Use Case | Threshold | Max Edges | Notes |
|--------|----------|-----------|-----------|-------|
| demo | Simulated data demo | 0.03 | 8 | Zero external deps |
| standard | Standard six-in-one | 0.3 | 8 | General purpose |
| deep | Deep causal analysis | 0.2 | 15 | Stability checks on |
| archival | Archival precision | 0.1 | 20 | Strictest rules |
| llama | Shehui/Shenji-LLaMA | 0.01 | 12 | For overfitted TRACE LLaMA models (27M/469M/470M) with low ΔNLL |

```python
from presets import load_presets
p = load_presets('standard')
```

## Key Files

```
trace-engine/
├── README.md                          ← Root quick-start
├── SKILL.md                           ← This file
├── DESIGN.md                          ← Design philosophy
├── tests/test_skill.py                ← Self-test suite
└── examples/counterfactual_hybrid/
    ├── README.md                      ← DoWhy/CF strategy
    ├── DESIGN_SIX_IN_ONE.md          ← Engineering details
    ├── counterfactual_bridge.py       ← TRACE → DoWhy bridge
    ├── six_warriors.py                ← Six-in-one orchestrator
    ├── presets.yaml / presets.py      ← Parameter presets
    ├── run_cli.py                     ← CLI entry
    └── test_case.py                   ← 10-case suite
```

## Environment Dependencies

### Core (required)

```
torch>=2.0, transformers>=4.40, sentencepiece>=0.2, numpy>=1.24
```

### Causal inference extensions (recommended)

```bash
pip install dowhy networkx pandas statsmodels scikit-learn
```

### Independent validation + visualization (optional)

```bash
pip install causal-learn graphviz jieba
```

### Graphviz system binary

Download from https://graphviz.org/download/ and ensure `dot -V` works.

## References

- TRACE: Math & Lienhart, *Scalable Sample-Level Causal Discovery via Autoregressive Density Estimation*, arXiv:2602.01135
- CCM: Sugihara et al., *Detecting Causality in Complex Ecosystems*, Science 2012
- HAVOK: Brunton et al., *Chaos as an Intermittently Forced Linear System*, Nature Comms 2017
- DoWhy: Sharma & Kiciman, *DoWhy: An End-to-End Library for Causal Inference*, arXiv:2011.04216
- Pearl, *Causality: Models, Reasoning, and Inference*, Cambridge 2009
