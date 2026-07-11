# TRACE Research Rigor — Scientific Validity Guidelines

> 参照: EDM-Takens `references/research-rigor.md`

## Calibration: When is a TRACE finding "real"?

### Confidence Levels

| Level | Criteria | Action |
|-------|----------|--------|
| **HIGH** | TRACE + CCM agree, HAVOK linear > 70% | Trust. Report as finding. |
| **MEDIUM** | TRACE finds edge, CCM inconclusive | Report with caveat: "needs further validation" |
| **LOW** | CCM disagrees, or UNK > 5%, or edge count < 10 | Do NOT report as causal finding |
| **NONE** | Audit BLOCK, or OOM, or NaN in matrix | Results are scientifically meaningless |

### Before publishing / archiving TRACE results:

```
□ Layer 1 (env_check) → PASS
□ Layer 2 (audit) → no BLOCK, no FAIL
□ Layer 3 (CCM) → run if edges > 100
□ Model loss < 0.5 (training converged)
□ UNK rate < 5% (vocab matches)
□ Top-5 edges are semantically interpretable by a human
□ At least 3/4 multi-metric signals converged
□ Edge density < 0.5 (not a complete graph)
□ Verdict includes confidence level
□ Training hyperparameters logged
```

### For publication-grade results, additionally:

```
□ Run 3 independent training seeds → report variance
□ Sensitivity scan at threshold ± 0.1
□ CCM trust > 60% for reported edges
□ HAVOK decomposition stable across matrix sizes (N±5)
□ Compare with baseline model (e.g., Qwen 1.5B) for key edges
□ Ghost baseline enabled for all findings
□ Full parameter log attached to report
```

### What NOT to claim:

```
✗ "TRACE proves A causes B"        → "TRACE finds evidence A→B"
✗ "The causal graph is complete"    → "TRACE recovers partial causal structure"
✗ "This model works for any text"   → "This model works for texts in domain X"
✗ "No validation needed"            → "CCM cross-validation confidence: Y%"
```

## Interpretation Guardrails

### TRACE finds A→B means:

```
✓ A's presence in history makes model predict B more confidently
✓ Informational dependence exists (P(B|A,context) ≠ P(B|context))
✗ Does NOT mean: intervening on A will change B
✗ Does NOT mean: A is the only/most important cause of B
✗ Does NOT mean: A temporally precedes B in the real world
```

TRACE measures **model epistemic causality** — what the model has learned
about predictive relationships. This approximates data-generating causality
but is NOT identical to it. The approximation is better when:
- Training data perfectly matches target text (Instant TRACE)
- Model converges adequately (loss < 0.5)
- CCM independently confirms
