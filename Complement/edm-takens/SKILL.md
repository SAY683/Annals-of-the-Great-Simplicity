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

All Python source is in `src/`. To use, add `src/` to `sys.path`:

```python
import sys; sys.path.insert(0, 'path/to/edm-takens/src')
```

## Quick Start

```python
# 0. Validate environment
from environment_check import validate_environment
report = validate_environment()
assert report.ready, "Missing dependencies — run: pip install -r requirements.txt"

# 1. Audit configuration BEFORE computation
from edm_auditor import audit_pipeline
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
from sovereign_havok import SovereignHAVOK
sh = SovereignHAVOK(q_delays=E_opt).fit(data)
print(sh.report())

# 4. Cross-validate EDM vs HAVOK
from enhanced_cross_validate import run_enhanced_validation
run_enhanced_validation('data/game_log.csv')

# 5. CCM causality (correct direction — Victim Mirror Principle)
from final_interpretation import ccm_with_convergence
ccm_with_convergence(df, 'kills', 'result', E_opt)
```

## Pipeline Architecture

```
 [Raw Data]
      |
 [Environment Check] ── src/environment_check.py
      |
 [Auditor Firewall] ─── src/edm_auditor.py (PRE-EXECUTION GATE)
      |                   Enforces all 7 secrets. Blocks invalid configs.
 [tau Optimization] ─── src/edm_tau_optimization.py (AMI-based)
      |
 [E Optimization]  ─── pyEDM.EmbedDimension + FNN cross-check
      |
 +----+----+
 |         |
 v         v
 EDM        HAVOK
 S-Map      SovereignHAVOK (src/sovereign_havok.py)
 Simplex    ├─ SG derivative (auto-capped for small data)
 |          ├─ V-basis regression (Brunton 2017 canonical)
 |          ├─ Adaptive SVD truncation (energy threshold)
 |          └─ Kurtosis + Koopman eigenvalue diagnostics
 +----+----+
      |
 [Cross-Validation] ── src/enhanced_cross_validate.py (3 safeguards)
      |                + src/verify_algorithms.py (5-level, 100-pt scored)
      |
 [CCM Causality]  ── ccm_with_convergence() with slope check
      |              + Multiview if N<100 (src/multiview_svd_monitor.py)
      |              + SVD residual monitor for concept drift
      v
 [Final Diagnosis] ── src/final_interpretation.py
```

## Skill File Map

```
edm-takens/                          ← Self-contained skill folder
├── SKILL.md                         ← THIS FILE — master entry point
├── DESIGN.md                        ← Design philosophy & business logic
├── requirements.txt                 ← Pip-freeze version manifest
├── secret_adoption_audit.md         ← Adoption/deferral status of all 7 secrets
├── src/                             ← All Python source (14 modules)
│   ├── __init__.py
│   ├── _paths.py                    ← Portable path resolution
│   ├── sovereign_havok.py           ← Core HAVOK engine
│   ├── edm_auditor.py               ← Firewall: 7-secret pre-execution enforcement
│   ├── enhanced_cross_validate.py   ← EDM-HAVOK cross-validation + 3 safeguards
│   ├── verify_algorithms.py         ← 5-level scored verification (100 pts)
│   ├── final_interpretation.py      ← Game data dynamical interpretation
│   ├── multiview_svd_monitor.py     ← Secret 4 (Multiview) + Secret 5 (SVD monitor)
│   ├── pipeline.py                  ← Unified pipeline runner logic
│   ├── environment_check.py         ← Dependency + file integrity validation
│   ├── edm_tau_optimization.py      ← AMI-based optimal tau selection
│   ├── edm_adaptive_pipeline.py     ← tau -> E -> theta -> CCM pipeline
│   └── edm_havok_integration.py     ← EDM-guided HAVOK (discrete K, legacy)
├── tests/
│   └── test_havok.py                ← 9-class HAVOK algorithm test suite
├── examples/
│   └── demo.py                      ← pyEDM reference demonstration
├── data/
│   ├── game_log.csv                 ← 32-game sample dataset
│   └── template.csv                 ← Multivariate data template
└── references/
    ├── takens_embedding_reference.md ← Mathematical foundations
    ├── forbidden_rules_reference.md  ← Seven forbidden rules (full treatment)
    └── edge_cases_reference.md       ← Data regime mitigations
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

## Usage in Other AI VibeCoding Systems

```python
# 1. Add the skill's src/ to path
import sys
sys.path.insert(0, 'path/to/edm-takens/src')

# 2. Validate environment
from environment_check import validate_environment
env = validate_environment('path/to/edm-takens')
assert env.ready

# 3. Use any module directly
from sovereign_havok import SovereignHAVOK
from edm_auditor import audit_pipeline
from enhanced_cross_validate import run_enhanced_validation

# 4. Or run the unified pipeline
from pipeline import run_pipeline, PipelineConfig
config = PipelineConfig(data_path='your_data.csv', target_col='your_target')
result = run_pipeline(config, auto_fix=True)
```

## Edge Cases

| Case | Mitigation | Reference |
|------|-----------|-----------|
| Binary/Discrete | Accuracy + rho; prefer continuous covariates | edge_cases_reference.md #1 |
| N < 50 | E_max <= N/5; bootstrap; Multiview if possible | edge_cases_reference.md #2 |
| Non-Stationary | Sliding window; adaptive memory fracture (S5) | edge_cases_reference.md #3 |
| High-D (D > 10) | PCA to 3-10 PCs; M-EDM or HAVOK | edge_cases_reference.md #4 |
| Synchrony FPs | Surrogate test (Ebisuzaki); Cobey-Baskerville | edge_cases_reference.md #5 |
| SG Over-smoothing | Auto-cap window at p//4 (Reviewer fix #4) | src/sovereign_havok.py |
| HAVOK Matrix Degradation | Enforce p/q >= 10 (Secret 3) | src/edm_auditor.py |

## Reviewer Improvements Incorporated

| # | Improvement | File | Status |
|---|------------|------|--------|
| 1 | Lyapunov R^2 quality check | src/final_interpretation.py, src/edm_auditor.py | Done |
| 2 | CCM convergence slope check | src/final_interpretation.py: ccm_with_convergence() | Done |
| 3 | Hankel ratio audit | Already robust | Confirmed |
| 4 | SG window auto-cap for small data | src/sovereign_havok.py: _apply_sg_derivative() | Done |
| 5 | Multiview integration | src/multiview_svd_monitor.py | Done (env-limited) |
| 6 | SVD residual monitoring | src/multiview_svd_monitor.py: SVDResidualMonitor | Done |

## Data Readiness Routing

Before applying any method, assess whether the data supports it:

| Data Profile | Recommended Path | Risk if Misapplied |
|-------------|-----------------|-------------------|
| Long, regular, clean (N>100) | Full HAVOK + EDM pipeline | Low |
| Long, regular, moderate noise | HAVOK + EDM with surrogate test | Medium (false nonlinearity) |
| Short, irregular, noisy (N<50) | Bayesian state-space models, NOT HAVOK/EDM | High (fitting noise structure) |
| Unknown SNR, irregular sampling | Surrogate test FIRST; if fails, fall back to Bayesian SSM | High |
| You're unsure if you need prediction or hypothesis generation | Default to "exploratory" labeling; see Divination vs Prediction principle | Reputational (overclaiming) |

### Divination vs Prediction Principle

If the data cannot support rigorous out-of-sample prediction (per the routing above),
do not package the output as "prediction." The honest framing is **structured hypothesis
generation** — using algorithmic rigor to force associations between variables you
wouldn't normally connect, which triggers new hypotheses. Knowing which one you're
doing is more important than pretending you're doing the other.

## Methodological Cross-References

Key insights from the broader nonlinear dynamics methodology ecosystem:

| Principle | Source | Our Implementation |
|-----------|--------|-------------------|
| Gavish-Donoho SVD threshold | Gavish & Donoho (2014) | `SovereignHAVOK(truncation_method="gavish_donoho")` |
| Ridge regression for HAVOK | Brunton/Kutz standard | `SovereignHAVOK(regression_method="ridge")` |
| IAAFT surrogate testing | Theiler et al. (1992) | `src/surrogate_test.py` |
| Sensitivity analysis (E+/-1) | Research rigor | `src/sensitivity_config.py` |
| CCM seasonal protection | Cobey & Baskerville (2016) | `ccm_with_convergence()` slope check |
| Observable selection (Ashby, DPI) | Ashby (1956), Info Theory | Documented in Edge Cases |
| Pre-registration + config artifact | Research rigor | `capture_config()` + `save_config()` |
| Sliding window drift monitoring | EDM/HAVOK best practice | `SVDResidualMonitor` (Secret 5) |
| Exploratory vs confirmatory labeling | Research rigor | `AnalysisConfig.analysis_type` field |
| mrDMD for multi-scale systems | Kutz/Fu/Brunton (2016) | Not implemented (separate method) |

## References

- Brunton, S.L. et al. (2017). Chaos as an intermittently forced linear system. *Nature Communications*.
- Sugihara, G. et al. (2012). Detecting causality in complex ecosystems. *Science*, 338, 496-500.
- Takens, F. (1981). Detecting strange attractors in turbulence. *Lecture Notes in Mathematics*, 898.
- `references/takens_embedding_reference.md` — Mathematical foundations
- `references/forbidden_rules_reference.md` — Seven forbidden rules
- `references/edge_cases_reference.md` — Data regime mitigations
- `secret_adoption_audit.md` — Adoption/deferral decisions for each secret
