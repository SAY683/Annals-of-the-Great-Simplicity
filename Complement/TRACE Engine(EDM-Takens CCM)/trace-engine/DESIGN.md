# TRACE Engine — Design Philosophy

## Defense in Depth (Six Layers)

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: Environment Validation                            │
│  "Can we even run?"                                         │
│  - PyTorch, transformers, numpy deps                        │
│  - CUDA / CPU fallback                                      │
│  - Model files present and loadable                         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: Configuration Audit (Firewall)                    │
│  "Is this request physically possible?"                     │
│  - Sequence length vs model context                         │
│  - Threshold validity                                       │
│  - VRAM / batch safety                                      │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: CCM Cross-Validation                              │
│  "Do two independent methods agree?"                        │
│  - TRACE ΔNLL vs CCM cross-map convergence                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 4: DoWhy Formal Causal Inference                     │
│  "Is the effect identifiable and robust?"                   │
│  - Model → Identify → Estimate → Refute                     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5: Pearl Counterfactual Query Engine                 │
│  "What if X were different?"                                │
│  - Abduction → Action → Prediction                          │
├─────────────────────────────────────────────────────────────┤
│  LAYER 6: causallearn Independent Validation                │
│  "Do constraint/score-based searches agree?"                │
│  - PC / FCI / GES                                           │
└─────────────────────────────────────────────────────────────┘
```

## Six Instruments, Six Dimensions

> The following instrument metaphors (searchlight / lie detector / metronome /
> X-ray / gavel / mirror / third witness) are not rhetorical fluff. Each one
> maps exactly to the physical dimension that the corresponding algorithm
> measures in the text.

| Algorithm | Instrument | Dimension Measured | Diagnostic Signal |
|-----------|-----------|-------------------|-------------------|
| **TRACE** | 探照灯 (Searchlight) | Causal edge discovery | ΔNLL strength |
| **CCM** | 测谎仪 (Lie Detector) | Nonlinear entanglement | Convergence slope; failure means "no deep logic loops" |
| **EDM** | 节拍器 (Metronome) | Temporal rigidity / structure | ρ predictability of discourse markers |
| **HAVOK** | X光机 (X-ray) | Hidden singularities / forcing | Linear vs nonlinear energy partition |
| **DoWhy + Pearl Counterfactual** | 法槌+反事实镜 (Gavel+Mirror) | Formal identifiability + what-if reasoning | ATE + 95% CI; ITE; Pearl 3-step |
| **causallearn** | 第三人 (Third Witness) | Independent graph search | PC / FCI / GES edges |

## Composite Diagnosis Patterns

A single algorithm's output is a measurement; the **pattern across all six** is
the diagnosis.

```
CCM fails + EDM ρ>0.9 + HAVOK linear>80% + DoWhy refutes
  → tightly-structured linear narrative with turning points
  → text type: narrative

CCM converges + EDM ρ moderate + HAVOK nonlinear>30% + DoWhy passes
  → argumentative text with recursive logical entanglement

TRACE sparse + CCM fails + EDM ρ intermediate + HAVOK linear>70%
  → descriptive text with no deep causal structure
```

## Auto-Correction Philosophy

| Problem Class | Auto-Correct? | Rationale |
|--------------|---------------|-----------|
| Numerical suboptimality (batch too large) | YES | Reduce batch, notify user |
| Data insufficiency (seq_len < 5) | NO (block) | Cannot create data from nothing |
| Domain mismatch (UNK rate > 20%) | NO (warn) | Model cannot learn new vocabulary on the fly |
| Threshold extreme (τ ≤ 0 or τ > 10) | NO (warn) | Requires domain knowledge |
| seq_len > max_pos | YES | Auto-truncate with warning |

## Known Failure Modes

| Failure | Symptom | Fix / Prevention |
|---------|---------|-----------------|
| High UNK rate (>20%) | ΔNLL low/uniform | Train BPE tokenizer on target text; keep UNK < 5% |
| Positional overflow | CUDA index error | Auto-truncate to model max_pos |
| ΔNLL too weak (<1.0) | No edges distinguishable | More epochs, more data, smaller vocab |
| Cross-paragraph contamination | Spurious edges | Paragraph-aligned window sampling |

## Documentation Map

- Quick start & architecture: [`README.md`](README.md)
- Skill entry & presets: [`SKILL.md`](SKILL.md)
- DoWhy + counterfactual bridge: [`examples/counterfactual_hybrid/README.md`](examples/counterfactual_hybrid/README.md)
- Engineering details: [`examples/counterfactual_hybrid/DESIGN_FIVE_IN_ONE.md`](examples/counterfactual_hybrid/DESIGN_FIVE_IN_ONE.md)
