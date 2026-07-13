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

## Project Layout

```
trace-engine/
├── SKILL.md                          ← Master architecture & quick start
├── DESIGN.md                         ← Design philosophy & six instruments
├── requirements.txt                  ← Python dependencies
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
