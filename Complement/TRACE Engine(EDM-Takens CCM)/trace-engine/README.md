# TRACE Engine

Token-level causal discovery engine with a six-in-one heterogeneous defense
architecture: TRACE (topology), CCM (manifold validation), EDM (temporal
structure), HAVOK (hidden forcing), DoWhy/Counterfactual (formal inference),
and causallearn (independent graph search).

> **因果战队 (Counterfactual Sentai)** — six independent instruments measuring
> different dimensions of the same text, producing a complete causal-topological
> portrait rather than a single vote.

## Two Entry Points

| Entry | Best For | Location |
|-------|----------|----------|
| **CLI / Python API** | Full control, custom models, batch analysis | `examples/counterfactual_hybrid/` |
| **Web UI** | Drag-and-drop text analysis, real-time SSE logs | `../trace-engine-web/` |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
pip install dowhy networkx pandas statsmodels scikit-learn
# optional
pip install causal-learn jieba
```

### 2. Run the built-in demo

```bash
cd examples/counterfactual_hybrid
python run_cli.py demo
```

This runs the full six-in-one pipeline on simulated data and prints the causal
report to `outputs/demo/`.

### 3. Run self-tests

```bash
python tests/test_skill.py
```

### 4. Launch the Web UI

See [trace-engine-web/README.md](../trace-engine-web/README.md).

## Model-Specific Presets

`examples/counterfactual_hybrid/presets.yaml` now includes a `llama` preset tuned for the over-fitted Shehui/Shenji-LLaMA V4 models (~470M params / ~1.8GB weights):

```bash
cd examples/counterfactual_hybrid
python run_cli.py --text "..." --preset llama
```

Key differences from the Qwen-oriented defaults:

| Parameter | Qwen-oriented default | `llama` preset | Reason |
|-----------|----------------------|----------------|--------|
| `threshold` | 0.3–0.5 | **0.01** | V4 ΔNLL range is ~0–0.16 |
| `window_size` | 8–64 | **128** | V4 was trained with seq_len=1024 |
| `max_segments` | 4 | **3** | Limits runtime on consumer GPUs |
| `concept_min_freq` | 2–3 | **1** | Domain tokens are sparse |
| `classical_mode` | false | false (toggleable) | Keep `true` for Shenji classical Chinese |

Use `classical_mode=true` when analysing Shenji-style classical Chinese texts so that function words such as 之/乎/者/也 are retained as concepts.

### Filter Modes

The `filter_mode` parameter controls how candidate causal edges are filtered before entering DoWhy:

| Mode | Behaviour |
|------|-----------|
| `topn` (default) | Keep the top-N strongest edges by ΔNLL |
| `percentile` | Keep edges above the configured percentile |
| `adaptive` | Auto-select: percentile for dense graphs (>30% density), top-N otherwise |

VRAM budget: the 470M models need about **3.0GB+ free GPU memory**. The Web SUPER mode automatically attempts FP16 loading and falls back to FP32; set `TRACE_MODEL_DTYPE=fp32` to force FP32.

> Known model issue: current Shehui-LLaMA weights appear insensitive to TRACE mask interventions and may report `0` non-zero causal edges even with `threshold=0.01`. Shenji-LLaMA usually returns edges under the same preset. This is a model-weight/training observation, not a code or threshold bug.

## Project Layout

```
trace-engine/
├── SKILL.md                          ← Master architecture & quick start
├── DESIGN.md                         ← Design philosophy & six instruments
├── README.md                         ← This file
├── requirements.txt                  ← Python dependencies
├── health_check.py                   ← Standalone health check
├── build_bridge_schema.py            ← Generate bridge parameter schema from presets.yaml
├── tests/
│   └── test_skill.py                 ← Self-test suite
├── examples/
│   ├── counterfactual_hybrid/        ← ★ Six-in-one CLI + bridge
│   │   ├── README.md                 ← DoWhy/CF hybrid strategy
│   │   ├── DESIGN_FIVE_IN_ONE.md     ← Engineering design details
│   │   ├── counterfactual_bridge.py  ← TRACE → DoWhy bridge
│   │   ├── six_warriors.py           ← Six-in-one orchestrator
│   │   ├── presets.yaml              ← Unified parameter presets
│   │   ├── run_cli.py                ← CLI entry point
│   │   └── test_case.py              ← 10-case test suite
│   └── zhihu_consensus/              ← Narrative-text case study
└── references/                       ← Research-rigor notes
```

## Six-in-One Diagnostic Matrix

| # | Warrior | Instrument | Algorithm | Measures | Best For |
|---|---------|------------|-----------|----------|----------|
| 1 | TRACE | 探照灯 (Searchlight) | ΔNLL masked intervention | Token-level causal edges | Any text |
| 2 | CCM | 测谎仪 (Lie Detector) | Convergent cross-mapping | Nonlinear entanglement | Argumentative (>3 repeats) |
| 3 | EDM | 节拍器 (Metronome) | Simplex projection ρ | Temporal rigidity | Narrative |
| 4 | HAVOK | X光机 (X-ray) | Koopman decomposition | Hidden forcing terms | Large causal matrices |
| 5 | DoWhy+CF | 反事实镜 (Mirror) | do-calculus + Pearl 3-step | Identifiability + what-if | Directed paths |
| 6 | causallearn | 第三人 (Third Witness) | PC/FCI/GES | Independent graph search | Sufficient samples |

A component's **failure** is itself a diagnostic signal: CCM failing on a text
with high EDM ρ and linear HAVOK structure strongly suggests a narrative rather
than an argumentative text.

## Core Design Principle

**Heterogeneous defense**: each algorithm measures a different physical dimension
of the text. We do not ensemble six similar models; we use six different
instruments and compare their readings.

## Documentation Map

- Architecture overview & quick start: [`SKILL.md`](SKILL.md)
- Design philosophy & instrument metaphor: [`DESIGN.md`](DESIGN.md)
- DoWhy + counterfactual bridge: [`examples/counterfactual_hybrid/README.md`](examples/counterfactual_hybrid/README.md)
- Engineering details, parameters, file map: [`examples/counterfactual_hybrid/DESIGN_FIVE_IN_ONE.md`](examples/counterfactual_hybrid/DESIGN_FIVE_IN_ONE.md)

## References

- TRACE: Math & Lienhart, *Scalable Sample-Level Causal Discovery via Autoregressive Density Estimation*, arXiv:2602.01135
- CCM: Sugihara et al., *Detecting Causality in Complex Ecosystems*, Science 2012
- HAVOK: Brunton et al., *Chaos as an Intermittently Forced Linear System*, Nature Comms 2017
- DoWhy: Sharma & Kiciman, *DoWhy: An End-to-End Library for Causal Inference*, arXiv:2011.04216
- Pearl, *Causality: Models, Reasoning, and Inference*, Cambridge 2009
