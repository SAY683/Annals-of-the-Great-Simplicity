# Counterfactual-DoWhy Hybrid Strategy for TRACE Engine

> Integrates counterfactual reasoning and the DoWhy causal-inference framework
> into TRACE, adding a fifth and sixth validation dimension to the four-in-one
> pipeline.

## Pearl's Ladder of Causation

```
Level 3: Counterfactual   ← "What if X had been different?"
         |
Level 2: Intervention     ← "What happens if I do X?"
         |
Level 1: Association      ← "Are X and Y correlated?"
```

| Component | Causal Level | Method |
|-----------|--------------|--------|
| TRACE ΔNLL | Level 2 (virtual intervention) | `do(x_i = [MASK])` via masking |
| CCM | Level 1–2 | Cross-map convergence |
| EDM | Level 1 | Predictability / temporal structure |
| HAVOK | Level 1–2 | Forcing-term detection |
| **DoWhy** | **Level 2** | do-calculus + formal estimation |
| **Counterfactual** | **Level 3** | Pearl 3-step |

## DoWhy Four-Step Pipeline

```
Model → Identify → Estimate → Refute
  │        │          │          │
  │        │          │          └── Placebo / random common cause / subset
  │        │          └── ATE + 95% CI
  │        └── Identifiability (do-calculus)
  └── DAG + SCM from TRACE adjacency matrix
```

## Hybrid Architecture

```
[Input text]
    │
    ▼
[TRACE] ──→ token-level causal adjacency matrix
    │
    ├──► [Token → Concept aggregation]
    │
    ├──► [DoWhy model]
    │      G = nx.DiGraph(A)
    │
    ├──► [Identify]  ← Layer 4
    │      identifiable? + estimand method
    │
    ├──► [Estimate]  ← Layer 4
    │      ATE + confidence interval
    │
    ├──► [Refute]    ← Layer 4
    │      random common cause / placebo / subset
    │
    └──► [Counterfactual] ← Layer 5
           Abduction → Action → Prediction
```

## Text-Type Sensitivity

| Text Type | TRACE | CCM | EDM | HAVOK | DoWhy+CF |
|-----------|-------|-----|-----|-------|----------|
| Argumentative | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★★★ |
| Narrative | ★★★☆☆ | ★★☆☆☆ | ★★★★☆ | ★★★★☆ | ★★☆☆☆ |
| Descriptive | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ |
| Dialogue/Debate | ★★★★☆ | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★★★ |

## Running the Bridge

### CLI

```bash
python run_cli.py demo
```

### Python API

```python
from counterfactual_bridge import TRACE2DoWhy
from presets import load_presets

p = load_presets('standard')
bridge = TRACE2DoWhy(adj_matrix, tokens, **p.trace2dowhy)
bridge.build_model()
bridge.identify(treatment='算法推荐', outcome='信息茧房')
bridge.estimate()
bridge.refute()
bridge.counterfactual_scan(n_top_edges=5)
print(bridge.report())
```

### Web UI

The Web bridge in `trace-engine-web/py_bridge.py` calls the same modules and
streams JSON Lines via Server-Sent Events. See
[`../../trace-engine-web/README.md`](../../trace-engine-web/README.md).

## Files

```
counterfactual_hybrid/
├── README.md                  ← This file
├── DESIGN_FIVE_IN_ONE.md      ← Engineering design details
├── counterfactual_bridge.py   ← TRACE → DoWhy bridge
├── six_warriors.py            ← Six-in-one orchestrator
├── presets.yaml               ← Unified parameter presets
├── presets.py                 ← Preset loader
├── dowhy_auditor.py           ← 9-rule audit firewall
├── run_cli.py                 ← CLI entry point
└── test_case.py               ← 10-case test suite
```

## Dependencies

```bash
pip install dowhy>=0.14 networkx numpy pandas scipy statsmodels scikit-learn
# optional
pip install causal-learn graphviz jieba
```

If DoWhy is not installed, the bridge falls back to a simulation mode that
preserves the same API surface but uses synthetic statistics instead of formal
do-calculus.

## References

- Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*. Cambridge.
- Sharma, A. & Kiciman, E. (2020). DoWhy: An End-to-End Library for Causal Inference. *arXiv:2011.04216*.
- Math & Lienhart (2026). *Scalable Sample-Level Causal Discovery via Autoregressive Density Estimation*. arXiv:2602.01135.
- Sugihara et al. (2012). *Detecting Causality in Complex Ecosystems*. *Science*, 338(6106), 496-500.
