---
name: edm-takens
description: >
  Empirical Dynamic Modeling + HAVOK (Koopman operator) for nonlinear time series.
  Attractor reconstruction, Simplex/S-Map prediction, CCM causality with convergence
  verification, SovereignHAVOK decomposition (continuous ODE, SG-filtered derivatives,
  adaptive SVD truncation), EDM-HAVOK cross-validation scoring, Multiview embedding
  for data-scarce regimes. Includes a pre-execution firewall auditor enforcing seven
  pitfall-avoidance rules (Lyapunov Horizon, CCM Victim Mirror, Hankel Golden Ratio,
  Multiview Embedding, SVD Residual Monitor, Cross-Validation, Arrow Trap).
  Handles: binary/discrete data, small-sample libraries, non-stationary attractors,
  synchrony false positives, SG over-smoothing, and Hankel numerical degradation.
  Domain-agnostic: game analytics, ecology, finance, physical systems.
---

# EDM-Takens + SovereignHAVOK Skill

Nonlinear time series analysis toolkit based on Takens Embedding Theorem, pyEDM,
and the SovereignHAVOK engine (Brunton et al., Nature Communications, 2017).

## Quick Start

```python
# 0. Validate environment
from scripts.environment_check import validate_environment
report = validate_environment()
assert report.ready, "Missing dependencies — run: pip install numpy scipy pandas matplotlib pyEDM"

# 1. Audit configuration BEFORE computation
from scripts.edm_auditor import audit_pipeline
audit = audit_pipeline(n=len(data), E=3, target_col='result',
                       columns=['kills','damage','deaths','result'],
                       is_binary=True)
audit.print_report()
if audit.verdict == 'FAIL':
    raise SystemExit("Fix configuration before proceeding")

# 2. Run EDM pipeline
import pyEDM
E_opt = pyEDM.EmbedDimension(...)

# 3. Run HAVOK decomposition
from sovereign_havok import SovereignHAVOK   # project-root import
sh = SovereignHAVOK(q_delays=E_opt).fit(data)
print(sh.report())

# 4. Cross-validate EDM vs HAVOK
# Run: python enhanced_cross_validate.py

# 5. CCM causality (correct direction!)
from final_interpretation import ccm_with_convergence
ccm_with_convergence(df, 'kills', 'result', E_opt)
```

## Pipeline Architecture

```
 [Raw Data]
      |
 [Environment Check] ── scripts/environment_check.py
      |
 [Auditor Firewall] ─── scripts/edm_auditor.py (PRE-EXECUTION GATE)
      |                   Enforces all 7 secrets. Blocks invalid configs.
 [tau Optimization] ─── scripts/edm_tau_optimization.py (AMI-based)
      |
 [E Optimization]  ─── pyEDM.EmbedDimension + FNN cross-check
      |
 +----+----+
 |         |
 v         v
 EDM        HAVOK
 S-Map      SovereignHAVOK (sovereign_havok.py)
 Simplex    ├─ SG derivative (auto-capped for small data)
 |          ├─ V-basis regression (Brunton 2017 canonical)
 |          ├─ Adaptive SVD truncation (energy threshold)
 |          └─ Kurtosis + Koopman eigenvalue diagnostics
 +----+----+
      |
 [Cross-Validation] ── enhanced_cross_validate.py (3 safeguards)
      |                + verify_algorithms.py (5-level, 100-pt scored)
      |
 [CCM Causality]  ── ccm_with_convergence() with slope check
      |              + Multiview if N<100 (multiview_svd_monitor.py)
      |              + SVD residual monitor for concept drift
      v
 [Final Diagnosis] ── final_interpretation.py
```

## Skill File Map

```
.skills/edm-takens/
  SKILL.md                              ← THIS FILE — master entry point
  secret_adoption_audit.md              ← Adoption/deferral status of all 7 secrets
  references/
    takens_embedding_reference.md       ← Mathematical foundations
    forbidden_rules_reference.md        ← Seven forbidden rules (full treatment)
    edge_cases_reference.md             ← Data regime mitigations
  scripts/
    __init__.py                         ← Package init
    environment_check.py                ← Dependency + file integrity validation
    edm_auditor.py                      ← Firewall: 7-secret pre-execution enforcement
    edm_tau_optimization.py             ← AMI-based optimal tau selection
    edm_adaptive_pipeline.py            ← tau -> E -> theta -> CCM pipeline
    edm_havok_integration.py            ← EDM-guided HAVOK (discrete K, legacy)
  agents/
    openai.yaml                         ← Agent configuration
```

### Project-Root Executables (imported by skill, not duplicated)

```
sovereign_havok.py              Production HAVOK class
edm_auditor.py                  Auditor (synced copy in skill scripts/)
enhanced_cross_validate.py      EDM-HAVOK cross-validation + 3 safeguards
verify_algorithms.py            5-level scored verification (100 pts)
multiview_svd_monitor.py        Secret 4 (Multiview) + Secret 5 (SVD monitor)
final_interpretation.py         Game data dynamical interpretation
havok_cross_validate.py         Original cross-validation (legacy)
edm_adaptive_pipeline.py        Adaptive EDM pipeline (synced in skill scripts/)
```

## Seven Enforced Secrets

| # | Secret | Adoption | Firewall | Data Requirement |
|---|--------|----------|----------|------------------|
| 1 | Lyapunov Horizon | 🔶 DEFERRED | WARN/FAIL | N >= 100 |
| 2 | CCM Victim Mirror + Arrow Trap | ✅ ADOPTED | WARN | N >= 30 |
| 3 | Hankel Golden Ratio (p>=10q) | ✅ ADOPTED | FAIL (p/q<3) | Always active |
| 4 | Multiview Embedding | ⚠️ PARTIAL | Advisory | N<100, K>=2 |
| 5 | SVD Residual Monitor | ✅ ADOPTED | FAIL (>2.5x) | N>=50/window |
| 6 | EDM-HAVOK Cross-Validation | ✅ ADOPTED | WARN | Always active |
| 7 | CCM Arrow Trap | ✅ (in #2) | WARN | Always active |

**Adoption rate**: 5/7 fully adopted, 1 partial (env constraint), 1 deferred (data constraint).
Full details in [secret_adoption_audit.md](secret_adoption_audit.md).

## Decision Guide

| Condition | Method | Reason |
|-----------|--------|--------|
| N >= 100 | Full EDM + SovereignHAVOK + Lyapunov | All secrets active |
| N >= 50, continuous | EDM Simplex + S-Map | Sufficient attractor population |
| N >= 50, causal | EDM CCM + convergence check | Library size convergence |
| N < 100, multivariable | Multiview Embedding (Secret 4) | Spatial diversity saves data |
| N < 50 | SovereignHAVOK (small q) | Maintain p/q >= 10 (Secret 3) |
| Binary target | EDM on continuous covariates + HAVOK | Binary rho bounded < 0.87 |
| Need IF + WHEN | EDM + HAVOK cross-validation (Secret 6) | EDM=IF, HAVOK=WHEN |
| Real-time monitoring | SVD Residual Monitor (Secret 5) | Detect attractor deformation |

## Edge Cases

| Case | Mitigation | Reference |
|------|-----------|-----------|
| Binary/Discrete | Accuracy + rho; prefer continuous covariates | edge_cases_reference.md #1 |
| N < 50 | E_max <= N/5; bootstrap; Multiview if possible | edge_cases_reference.md #2 |
| Non-Stationary | Sliding window; adaptive memory fracture (S5) | edge_cases_reference.md #3 |
| High-D (D > 10) | PCA to 3-10 PCs; M-EDM or HAVOK | edge_cases_reference.md #4 |
| Synchrony FPs | Surrogate test (Ebisuzaki); Cobey-Baskerville | edge_cases_reference.md #5 |
| SG Over-smoothing | Auto-cap window at p//4 (Reviewer fix #4) | sovereign_havok.py |
| HAVOK Matrix Degradation | Enforce p/q >= 10 (Secret 3) | edm_auditor.py |

## Reviewer Improvements Incorporated

| # | Improvement | File | Status |
|---|------------|------|--------|
| 1 | Lyapunov R^2 quality check | final_interpretation.py, edm_auditor.py | Done |
| 2 | CCM convergence slope check | final_interpretation.py: ccm_with_convergence() | Done |
| 3 | Hankel ratio audit | Already robust | Confirmed |
| 4 | SG window auto-cap for small data | sovereign_havok.py: _apply_sg_derivative() | Done |
| 5 | Multiview integration | multiview_svd_monitor.py | Done (env-limited) |
| 6 | SVD residual monitoring | multiview_svd_monitor.py: SVDResidualMonitor | Done |

## References

- Brunton, S.L. et al. (2017). Chaos as an intermittently forced linear system. *Nature Communications*.
- Sugihara, G. et al. (2012). Detecting causality in complex ecosystems. *Science*, 338, 496-500.
- Takens, F. (1981). Detecting strange attractors in turbulence. *Lecture Notes in Mathematics*, 898.
- `references/takens_embedding_reference.md` — Mathematical foundations
- `references/forbidden_rules_reference.md` — Seven forbidden rules
- `references/edge_cases_reference.md` — Data regime mitigations
- `secret_adoption_audit.md` — Adoption/deferral decisions for each secret
