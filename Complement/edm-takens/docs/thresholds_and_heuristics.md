# CCM Thresholds & Heuristic Constants Documentation (P9/P10)

This attachment documents every "magic number" in the skill that is not a
direct paper formula, with its rationale. Goal: no unexplained threshold.

## CCM Convergence (Secret 2 / Arrow Trap)

**Location**: `final_interpretation.ccm_with_convergence()`,
`edm_auditor.audit_ccm_direction()`,
`_numpy_edm.CCM()`.

| Constant | Value | Rationale |
|----------|-------|-----------|
| `total_rise > 0.05` | 0.05 | Minimum absolute rise in cross-map rho across the library-size sweep. Chosen so that "library doubled -> rho up by at least 0.05" qualifies as genuine convergence; below this the signal is indistinguishable from bootstrap noise on N<50 data. Scale-invariant alternative to absolute slope (which depends on library-size range). |
| `spearman_rho > 0.7` | 0.7 | Strong-monotonicity cutoff for rho-vs-libsize. 0.7 = "clearly increasing"; below 0.7 the curve oscillates and Cobey-Baskerville (2016) flags a false positive. |
| `spearman_p < 0.1` | 0.1 | Liberal p (small samples have low power); combined with the rho threshold as a conjunction, not alone. |
| `final_rho > 0.2` | 0.2 | Minimum final cross-map skill to declare a (weak) causal link. Below 0.2 the link is "no signal" even if technically converging. |
| `delta > 0.1` (direction) | 0.1 | Forward vs reverse rho gap required to call a direction dominant. Below 0.1 = bidirectional/ambiguous. |

**Note**: These are empirical, not from a theorem. They are conservative for
small samples. For N>=200, `total_rise` could be tightened to 0.10. The
conjunction (rise AND monotonicity) is the key safeguard — a single high rho
without convergence is rejected.

## Hankel Aspect Ratio (Secret 3)

**Location**: `edm_auditor.classify_hankel_ratio()`.

| Tier | Threshold | Rationale |
|------|-----------|-----------|
| GOOD | p/q >= 10 | Engineering rule of thumb from numerical linear algebra: tall-thin SVD has well-conditioned singular vectors. Not a theorem. |
| MARGINAL | 5 <= p/q < 10 | Mild stiffness possible; acceptable for clean data. |
| DEGRADED | 3 <= p/q < 5 | A-matrix eigenvalues show spurious rigidity. |
| BROKEN | p/q < 3 | SVD numerically broken; results are garbage. |

The 10x "golden ratio" is aspirational. Users with very clean data may safely
use p/q >= 5; the tiered enforcement accommodates this while protecting against
catastrophic failure.

## SVD Residual Monitor (Secret 5) — P10 heuristic note

**Location**: `multiview_svd_monitor.SVDResidualMonitor`,
`edm_auditor.audit_svd_residual()`.

| Constant | Value | Status |
|----------|-------|--------|
| `detection_threshold = 2.5` | 2.5x baseline | Empirical; 2.5 standard deviations of residual ratio above baseline reliably separates regime shifts from noise. |
| `sustained_windows = 3` | 3 consecutive | Prevents single-outlier false alarms. |
| `trigger_adaptive_forgetting`: drop 50% | heuristic | **Explicitly a heuristic, not optimal.** |

**Why the 50% drop is kept as-is (P10 decision: do not "fix")**:
For N < 500, Bai-Perron structural-break tests are themselves unreliable;
the heuristic 50% drop is more robust in the small-sample regime this skill
targets. For N >= 500, replacing with Bai-Perron is a documented TODO.
Forcing the upgrade now would reduce robustness for the primary use case.

**Layering note**: The auditor (`audit_svd_residual`) uses a *single-shot*
2.5x check (FAIL on one violation), while the monitor class requires *3
sustained* windows. This is intentional layering, not inconsistency: the
auditor is a stricter pre-flight gate; the monitor is a stable online alarm.

## Lyapunov Quality (Secret 1)

| Constant | Value | Rationale |
|----------|-------|-----------|
| `fit_r2 < 0.5` -> unreliable | 0.5 | Rosenstein divergence-line fit R^2. Below 0.5 the linear region is too short/noisy to trust lambda_max. |
| `n_expand = min(20, N//3)` | 20 | Divergence tracking horizon; 20 steps captures the exponential regime without running into saturation. |
| horizon tiers 1x/3x/5x | tau_L multiples | From chaotic predictability theory: 1x safe, 3x growing error, 5x meaningless. Guideline, not theorem. |

## Kurtosis Forcing Classification

| Threshold | Classification |
|-----------|----------------|
| > 3.0 | heavy-tailed (strong intermittent) |
| > 1.5 | moderate tails |
| > 0.5 | light tails |
| > -0.5 | near-Gaussian |
| <= -0.5 | sub-Gaussian (bounded) |

The 1.5 cutoff for "nonlinear forcing" is empirical, calibrated against Lorenz
(kurt ~ 5) vs AR(1) (kurt ~ 0). It is the threshold used consistently across
`sovereign_havok`, `edm_auditor`, `verify_algorithms`, and `final_interpretation`.
