---
name: edm-takens
description: >
  Empirical Dynamic Modeling + HAVOK (Koopman operator) for nonlinear time series.
  Attractor reconstruction, Simplex/S-Map prediction, CCM causality with convergence
  verification, SovereignHAVOK decomposition (continuous ODE, SG-filtered derivatives,
  adaptive SVD truncation), EDM-HAVOK cross-validation scoring, Multiview embedding
  for data-scarce regimes. Includes a pre-execution firewall auditor enforcing fourteen
  pitfall-avoidance rules (Lyapunov Horizon, CCM Victim Mirror, Hankel Golden Ratio,
  Multiview Embedding, SVD Residual Monitor, Cross-Validation, Arrow Trap, and seven
  additional safeguards documented in `references/forbidden_rules_reference.md`).
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
run_enhanced_validation('examples/game_analysis/data/game_log.csv')

# 5. CCM causality (correct direction — Victim Mirror Principle)
from final_interpretation import ccm_with_convergence
ccm_with_convergence(df, 'kills', 'result', E_opt)
```

## Pipeline Architecture

**Design note — shared embedding dimension**: The pipeline uses a single
embedding dimension (q for HAVOK, E for EDM) for cross-validation consistency.
EDM's optimal E (from Simplex rho peak / FNN threshold) and HAVOK's optimal q
(from Hankel ratio + energy cutoff) are optimized for different objectives and
are NOT guaranteed to coincide mathematically. The shared dimension is a
simplifying assumption that enables fair EDM-vs-HAVOK comparison. For exploratory
analysis this is the correct default; for publication-grade results, consider
running sensitivity scans at E±1 and reporting stability (see
`sensitivity_config.py` and `references/research-rigor.md` #5).

```
 [Raw Data]
      |
 [Environment Check] ── src/environment_check.py
      |
 [Auditor Firewall] ─── src/edm_auditor.py (PRE-EXECUTION GATE)
      |                   Enforces all 14 secrets. Blocks invalid configs.
      |                   NOW INCLUDES: tau selection validation.
 [tau Optimization] ─── src/edm_tau_optimization.py (AMI-based)
      |
 [E Optimization]  ─── pyEDM.EmbedDimension (Simplex rho peak; FNN noted as future)
      |
 +----+----+
 |         |
 v         v
 EDM        HAVOK
 S-Map      SovereignHAVOK (src/sovereign_havok.py)
 Simplex    ├─ SG derivative (auto-capped for small data)
 |          ├─ V-basis regression (Brunton 2017 canonical)
 |          ├─ Adaptive SVD truncation (energy threshold)
 |          ├─ Kurtosis + Koopman eigenvalue diagnostics
 |          └─ S14: Sampling adequacy (auto-checked in fit())
 +----+----+
      |
 [S12: Decay Profile] ── src/sensitivity_config.py (Tp sweep; exp/oscillatory fit)
      |
 [Cross-Validation] ── src/enhanced_cross_validate.py (3 safeguards)
      |                + src/verify_algorithms.py (5-level, 100-pt scored)
      |
 [CCM Causality]  ── ccm_with_convergence() with convergence slope check
      |              + Multiview if N<100 (src/multiview_svd_monitor.py)
      |              + SVD residual monitor for concept drift
      |              + S13: Multi-comparison correction (ccm_batch_test, BH-FDR; batch CCM)
      |              + S11: Common driver disclaimer (auto-appended, ccm_causality.py)
      v
 [Final Diagnosis] ── src/final_interpretation.py
```

## Skill File Map

```
edm-takens/                          ← Self-contained skill folder
├── SKILL.md                         ← THIS FILE — master entry point
├── DESIGN.md                        ← Design philosophy & business logic
├── requirements.txt                 ← Lower-bound deps (portable)
├── requirements-lock.txt            ← [NEW] Pinned manifest (reproducible)
├── secret_adoption_audit.md         ← Adoption/deferral status of all 14 secrets
├── src/                             ← All Python source (21 modules)
│   ├── __init__.py
│   ├── _paths.py                    ← Portable path resolution
│   ├── _numpy_edm.py                ← Pure numpy/scipy EDM: Simplex,
│   │                                     S-Map, CCM, EmbedDim, Multiview
│   ├── _edm_bridge.py               ← Unified import: pyEDM with
│   │                                     graceful numpy fallback
│   ├── sovereign_havok.py           ← Core HAVOK engine (includes Secret 14:
│   │                                     sampling adequacy, auto-checked in fit())
│   ├── edm_auditor.py               ← Firewall: 14-secret pre-execution enforcement
│   │                                     (S1-S3,S5-S10: full checks; includes
│   │                                     stationarity, genericity, seasonality)
│   ├── enhanced_cross_validate.py   ← EDM-HAVOK cross-validation + 3 safeguards
│   ├── verify_algorithms.py         ← 5-level scored verification (100 pts)
│   ├── ccm_causality.py             ← Canonical convergence-aware CCM test —
│   │                                     single source of truth. Includes Secret 11
│   │                                     (common driver disclaimer) and Secret 13
│   │                                     (ccm_batch_test / multi-comparison correction)
│   ├── final_interpretation.py      ← Game data dynamical interpretation
│   │                                     (includes Lyapunov lower bound for N<100)
│   ├── multiview_svd_monitor.py     ← Secret 4 (Multiview) + Secret 5 (SVD monitor)
│   ├── pipeline.py                  ← Unified pipeline runner logic
│   │                                     (auto-saves config artifact)
│   ├── router.py                    ← Data routing engine: grade→target→auto-execute
│   │                                     (routes S10/S12/S13 per activation matrix)
│   ├── environment_check.py         ← Dependency + file integrity validation
│   ├── edm_tau_optimization.py      ← AMI-based optimal tau selection
│   ├── edm_adaptive_pipeline.py     ← Adaptive EDM workflow: tau (AMI) → E (Simplex)
│   │                                     → theta (S-Map sweep) → CCM; small-sample /
│   │                                     binary / non-stationarity aware (run_adaptive_edm)
│   ├── sensitivity_config.py        ← Config capture + sensitivity scan (E+/-1)
│   ├── surrogate_test.py            ← IAAFT surrogate data statistical testing
├── tests/
│   ├── __init__.py                  ← Test package marker
│   ├── test_ccm_canonical.py        ← CCM canonical example validation
│   ├── test_havok.py                ← 9-class HAVOK algorithm test suite (legacy)
│   └── test_sovereign_havok.py      ← [NEW] SovereignHAVOK class unit tests (P3)
├── examples/                           ← Self-contained case studies
│   ├── game_analysis/                  ← Game data case (32 games, binary target)
│   │   ├── README.md
│   │   ├── run_analysis.py
│   │   ├── data/
│   │   │   ├── game_log.csv
│   │   │   └── template.csv
│   │   ├── figures/
│   │   │   └── game_dashboard.png
│   │   └── archive/                    ← Historical scripts
│   └── yinshen/                        ← Yinshen phoneme case (120 chars, categorical)
│       ├── README.md
│       ├── run_analysis.py
│       ├── data/
│       │   ├── yinshen_wide.csv
│       │   └── yinshen_ji_vowel.csv
│       ├── figures/
│       │   └── yinshen_dashboard.png
│       └── reference/                  ← Original pre-Skill scripts
├── references/                       ← Scientific methodology (paper-grounded)
│   ├── takens_embedding_reference.md ← Mathematical foundations
│   ├── forbidden_rules_reference.md  ← Fourteen forbidden rules, all now
│   │                                     implemented (S8-S14 added, see
│   │                                     secret_adoption_audit.md)
│   ├── fourteen_rules_bibliography.md ← Complete annotated bibliography
│   │                                     indexed by rule (39 papers, 14 rules)
│   ├── edge_cases_reference.md       ← Data regime mitigations
│   └── research-rigor.md             ← Research integrity: pre-registration,
│                                         config artifact, sensitivity, controls
└── docs/                             ← Engineering attachments (maintainable)
    ├── ALGORITHM_AUDIT.md            ← Latest algorithm & engineering audit (2026-07-13)
    ├── CHANGELOG.md                  ← Evolution log
    ├── thresholds_and_heuristics.md  ← All magic numbers documented
    ├── edm-takens-skill-intro.md     ← Skill introduction (user-facing)
    └── edm-takens-skill-diff-report.md ← Historical: 7 → 14 rules evolution
    (Historical audit docs `edm-takens_skill_audit.md` and
    `edm-takens_self_inspection_census.md` were superseded by
    `ALGORITHM_AUDIT.md` and removed to avoid stale test counts.)

## Case Studies

Two complementary cases bundled with the Skill. Both follow all 14 forbidden rules and generate self-contained reports.

| Case | Path | N | Data Type | Key Insight |
|------|------|---|-----------|------------|
| **游戏数据** (Game) | `examples/game_analysis/` | 32 | 连续+二元混合 | Baseline: S3 Hankel auto-correction, S9 binary target, S11 common driver |
| **音神序列** (Yinshen) | `examples/yinshen/` | 120 | 类别整数编码 | Boundary: S2 CCM-E consistency, S6 EDM-HAVOK discrepancy, S9 metric distortion |

The two cases are complementary: game data tests the Skill on its native scenario (short continuous time series with binary target),
while Yinshen stress-tests it on categorical data where the metric assumptions of delay embedding are violated.

### Quick Reference

```bash
# Game data (32 games, continuous + binary)
python examples/game_analysis/run_analysis.py

# Yinshen (120 phonemes, categorical)
python examples/yinshen/run_analysis.py
```

Both generate `{case}_report.md` + `figures/{case}_dashboard.png`.

## Forbidden Rules (14 Secrets Enforced)

Full treatment in `references/forbidden_rules_reference.md` (14 rules specified). Adoption status per rule in `secret_adoption_audit.md`. All 14 secrets have working, enforced code in the skill package.

| # | Secret | Adoption | Firewall | Data Requirement |
|---|--------|----------|----------|------------------|
| 1 | Lyapunov Horizon | ✅ ADOPTED | WARN/FAIL | N >= 100 (SURROGATE-LB for N<100) |
| 2 | CCM Victim Mirror + Arrow Trap | ✅ ADOPTED | WARN | N >= 30 |
| 3 | Hankel Golden Ratio (p>=10q) | ✅ ADOPTED | FAIL (p/q<3) | Always active |
| 4 | Multiview Embedding | ✅ ADOPTED | Advisory | N<100, K>=2 (numpy fallback, Round 13) |
| 5 | SVD Residual Monitor | ✅ ADOPTED | FAIL (>2.5x) | N>=50/window |
| 6 | EDM-HAVOK Cross-Validation | ✅ ADOPTED | WARN | Always active |
| 7 | CCM Arrow Trap | ✅ (in #2) | WARN | Always active |
| 8 | Stationarity Gate | ✅ ADOPTED | WARN/FAIL | statsmodels (optional) |
| 9 | Observation Genericity | ✅ ADOPTED | WARN | Always active |
| 10 | Seasonality Confound | ✅ ADOPTED | WARN | Lomb-Scargle |
| 11 | Common Driver Disclaimer | ✅ ADOPTED | WARN | ccm_causality.py |
| 12 | Decay Profile | ✅ ADOPTED | WARN | sensitivity_config.py |
| 13 | Multi-Comparison Correction | ✅ ADOPTED | WARN | ccm_batch_test (BH-FDR) |
| 14 | Sampling Adequacy | ✅ ADOPTED | WARN | SovereignHAVOK.fit() |

**Adoption rate**: 14/14 fully adopted (Secret 1 is data-conditional with SURROGATE-LB fallback for N<100; Secret 4 has full numpy combinatorial fallback since Round 13).
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

## Command-Line Usage

The Skill can be run entirely from the shell without writing Python code.
All paths are resolved relative to the skill root, so the package is
portable across machines.

```bash
# Full SKILL.md flow: pipeline + cross-validation + interpretation
python run_pipeline.py --full-analysis --q 3 --auto-fix

# Run only the unified pipeline on custom data
python run_pipeline.py --data your_data.csv --target your_target --auto-fix

# Auto-detect embedding dimension and just show environment report
python run_pipeline.py --report-only

# Run the test suite
python run_tests.py --quick   # 89 checks, fast
python run_tests.py           # 96 checks, full
```

CLI flags for `run_pipeline.py` / `src/pipeline.py`:

| Flag | Meaning |
|------|---------|
| `--data PATH` | CSV data file (default: `examples/game_analysis/data/game_log.csv`) |
| `--target COL` | Target column name (default: `result`) |
| `--q E` | Embedding dimension (auto-detect if omitted) |
| `--max-e N` | Maximum embedding dimension to search (default: 8) |
| `--auto-fix` | Auto-correct numerically suboptimal configurations |
| `--report-only` | Print environment report and skip computation |
| `--full-analysis` | Chain pipeline → cross-validation → interpretation |

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
| 2 | CCM convergence slope → total_rise + Spearman | src/final_interpretation.py: ccm_with_convergence() | Done |
| 2b | CCM convergence audit unification | src/edm_auditor.py: audit_ccm_direction() | Done |
| 3 | Hankel ratio DRY (shared classify_hankel_ratio) | src/edm_auditor.py, src/enhanced_cross_validate.py | Done |
| 4 | SG window auto-cap for small data | src/sovereign_havok.py: _apply_sg_derivative() | Done |
| 5 | Multiview integration | src/multiview_svd_monitor.py | Done (env-limited) |
| 6 | SVD residual monitoring | src/multiview_svd_monitor.py: SVDResidualMonitor | Done |
| 7 | HAVOK eigenvalue stability (continuous→discrete) | src/sovereign_havok.py: eigenvalues_d_ via expm(A*dt) | Done |
| 8 | Tau selection audit (was dead parameter) | src/edm_auditor.py: audit_tau_selection() | Done |
| 9 | q/E shared-dimension documented | SKILL.md | Done |
| 10 | Tau audit FAIL/WARN status was a fragile substring match (`"0.5" in message`) that could never actually reach FAIL — replaced with an explicit boolean | src/edm_auditor.py: audit_tau_selection() | Done |
| 11 | IAAFT surrogates had no end-point matching, so non-cyclic real data produced spurious high-kurtosis surrogates (FFT periodicity artifact) that masked genuine chaos | src/surrogate_test.py: iaaft_surrogates() | Done |
| 12 | CCM verdict logic was independently duplicated in 2 files with different convergence rules and library-size ranges; pipeline.py's audit feedback never populated the convergence fields, silently disabling the auditor's Secret 2/7 protection | src/ccm_causality.py (new canonical module), src/final_interpretation.py, src/enhanced_cross_validate.py, src/pipeline.py | Done |
| 13 | HAVOK stability tiering (1.05/0.90 thresholds) was independently re-implemented in 3 files | src/sovereign_havok.py: classify_havok_stability() | Done |
| 14 | Degenerate-data explained_var_ could silently become NaN (0/0) instead of a diagnosable 0.0 | src/sovereign_havok.py: fit(), _auto_truncate() | Done |
| 15 | Logistic-map ground-truth test used x0=0.5, the exact r=4.0 critical point, collapsing to a constant-0 orbit (NaN downstream) | src/verify_algorithms.py: _test_logistic() | Done |
| 16 | run_tests.py never actually invoked each module's own self-test — added Layer 7 to run them as subprocesses | run_tests.py | Done |

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
| Sensitivity analysis (E+/-1) | Research rigor | `src/sensitivity_config.py` / `references/research-rigor.md` #5 |
| CCM seasonal protection | Cobey & Baskerville (2016) | `ccm_with_convergence()` slope check |
| Observable selection (Ashby, DPI) | Ashby (1956), Info Theory | Documented in Edge Cases |
| Pre-registration + config artifact | Research rigor | `capture_config()` + `save_config()` / `references/research-rigor.md` #3-#4 |
| Sliding window drift monitoring | EDM/HAVOK best practice | `SVDResidualMonitor` (Secret 5) |
| Exploratory vs confirmatory labeling | Research rigor | `AnalysisConfig.analysis_type` field / `references/research-rigor.md` #7 |
| mrDMD for multi-scale systems | Kutz/Fu/Brunton (2016) | Not implemented (separate method) |

## References

- Brunton, S.L. et al. (2017). Chaos as an intermittently forced linear system. *Nature Communications*.
- Sugihara, G. et al. (2012). Detecting causality in complex ecosystems. *Science*, 338, 496-500.
- Takens, F. (1981). Detecting strange attractors in turbulence. *Lecture Notes in Mathematics*, 898.
- `references/takens_embedding_reference.md` — Mathematical foundations
- `references/forbidden_rules_reference.md` — Fourteen forbidden rules
- `references/edge_cases_reference.md` — Data regime mitigations
- `secret_adoption_audit.md` — Adoption/deferral decisions for each secret
