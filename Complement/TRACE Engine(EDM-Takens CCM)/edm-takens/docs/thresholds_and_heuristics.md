# CCM Thresholds & Heuristic Constants Documentation (P9/P10)

This attachment documents every "magic number" in the skill that is not a
direct paper formula, with its rationale. Goal: no unexplained threshold.

## CCM Convergence (Secret 2 / Arrow Trap)

**Location**: `ccm_causality.ccm_causality_test()` (canonical implementation,
added Round 9), `edm_auditor.audit_ccm_direction()`, `_numpy_edm.CCM()`.
`final_interpretation.ccm_with_convergence()` and `enhanced_cross_validate.
verify_ccm_direction()` are thin wrappers around `ccm_causality_test()` —
see docs/CHANGELOG.md (Round 9) for why they used to be two independent,
disagreeing implementations and are not anymore.

| Constant | Value | Rationale |
|----------|-------|-----------|
| `total_rise > 0.05` | 0.05 | Minimum absolute rise in cross-map rho across the library-size sweep. Chosen so that "library doubled -> rho up by at least 0.05" qualifies as genuine convergence; below this the signal is indistinguishable from bootstrap noise on N<50 data. Scale-invariant alternative to absolute slope (which depends on library-size range). |
| `spearman_rho > 0.7` | 0.7 | Strong-monotonicity cutoff for rho-vs-libsize. 0.7 = "clearly increasing"; below 0.7 the curve oscillates and Cobey-Baskerville (2016) flags a false positive. |
| `spearman_p < 0.1` | 0.1 | Liberal p (small samples have low power); combined with the rho threshold as a conjunction, not alone. |
| `final_rho > 0.2` | 0.2 | Minimum final cross-map skill (`strong_direction_rho`) to declare a (weak) causal link. Below 0.2 the link is "weak/insufficient" even if technically converging. |
| `delta` bidirectional cutoff | 0.05 | `abs(forward_rho - reverse_rho) < 0.05` (`bidirectional_delta`) is called bidirectional when both directions converge; otherwise the larger side is "dominant". |

**Note**: These are empirical, not from a theorem. They are conservative for
small samples. For N>=200, `total_rise` could be tightened to 0.10. The
conjunction (rise AND monotonicity) is the key safeguard — a single high rho
without convergence is rejected.

**Retired (Round 9)**: `verify_ccm_direction()` previously used a separate,
non-convergence-checked rule (`forward_skill > 0.3 and delta > 0.1` to call
a direction "DRIVES", `both < 0.15` for "no link") based only on the rho at
the largest library size in a fixed `'5 25 5'` sweep. This has been retired
in favor of the single convergence-based verdict above — see
docs/CHANGELOG.md.

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

## HAVOK Discrete-Time Stability (added Round 9)

**Location**: `sovereign_havok.classify_havok_stability()` — single source
of truth, called from `SovereignHAVOK.diagnose()`, `pipeline.py`, and
`enhanced_cross_validate.py`. Before Round 9 these three call sites each
independently re-implemented the same two numbers; they happened to agree,
but nothing enforced that (see docs/CHANGELOG.md).

| Threshold | Classification | Rationale |
|-----------|----------------|-----------|
| `max\|eig_d\| > 1.05` | Divergent (unstable modes) | Discrete-time Koopman eigenvalues with modulus > 1 correspond to growing modes. The 5% margin above the exact stability boundary (1.0) absorbs estimation noise from finite-sample SVD/regression so borderline-stable systems aren't over-flagged as divergent. |
| `max\|eig_d\| < 0.90` | Highly dissipative (fast convergence) | Modes decaying faster than ~10%/step; the system returns to its attractor quickly. |
| otherwise | Near-critical / stable | Between the two margins — neither clearly growing nor clearly fast-decaying. |

Applies to the *discrete-time* eigenvalues (`eigenvalues_d_ = eig(expm(A*dt))`),
not the continuous-time eigenvalues of `A` (`eigenvalues_`), which are used
for spectral analysis only — see Reviewer Improvement #7 in SKILL.md.

## Stationarity Gate (Secret 8, added Round 11)

**Location**: `edm_auditor.Auditor.audit_stationarity()`.

| Threshold | Rationale |
|-----------|-----------|
| ADF/KPSS `alpha=0.05` | `[C]` Fisher's classical convention; both tests use it natively. |
| `N >= 20` to assess | `[D]` ADF/KPSS critical-value tables lose meaningful power below this — below N=20 the gate reports "unassessed", not "passed". |
| Variance ratio `> 3.0` (rolling-window heterogeneity) | `[E]` Engineering operationalization — no theorem specifies this exact multiple. |
| Trend-to-noise ratio `> 0.3` (`\|slope\|/sigma`) | `[E]` Engineering operationalization. |
| Cross-prediction decay ratio `< 0.7` (Schreiber 1997) | `[E]` Engineering operationalization of Schreiber's non-stationarity test. |
| Cross-prediction baseline gate: `rho_self > 0.2` | `[E]` Added after this gate's own self-test showed white noise (rho_self ~ 0.05, no real self-predictive skill) produced a spurious decay-ratio false positive — see docs/CHANGELOG.md (Round 11). Without established self-predictive skill, "decay" isn't a meaningful concept. |

## Observation Genericity Gate (Secret 9, added Round 11)

**Location**: `edm_auditor.Auditor.audit_observation_genericity()`.

| Threshold | Rationale |
|-----------|-----------|
| `n_unique < 5` -> non-injective | `[E]` Engineering floor; combined with the pre-existing `is_binary` flag (n_unique=2 is the extreme case this subsumes). |
| Boundary saturation `> 5%` of points at max or min | `[E]` Engineering operationalization — no theorem specifies this exact fraction. |
| Quantization ratio `n_unique/N < 10%` | `[E]` Engineering operationalization. |

## Seasonality Confound (Secret 10, added Round 11)

**Location**: `edm_auditor.dominant_periodicity()`, `edm_auditor.audit_seasonality_confound()`.

| Threshold | Rationale |
|-----------|-----------|
| `N >= 20` to assess | `[E]` Lomb-Scargle frequency resolution ~1/(t_max-t_min); N=20 resolves ~10 usable bins. |
| Power fraction `> 0.30` -> "high seasonality" | `[D]` The underlying mechanism (Cobey & Baskerville 2016) is well-established, but that paper doesn't specify a power threshold; 0.30 is this project's operationalization for its typical N in [20,100] regime. |
| Frequency match relative tolerance `15%` | `[E]` Handles periodogram bin discretization, not an exact-equality test. |

## Prediction Decay Profile (Secret 12, added Round 11)

**Location**: `sensitivity_config.decay_profile_scan()`.

| Threshold | Rationale |
|-----------|-----------|
| `Tp` sweep range `[1, min(20, N/3)]` | `[E]` Engineering operationalization; the concept traces to Farmer & Sidorowich (1987), Casdagli (1989), Sugihara & May (1990), but none specify this exact range. |
| Exponential fit `R^2 > 0.85` -> chaotic-consistent | `[E]` Engineering operationalization. |
| Sharp cutoff: `\|d2 rho\| > 2*sigma_d2` | `[E]` Engineering operationalization (2-sigma spike detection). |
| Oscillatory: residual lag-1 autocorrelation `> 0.5` | `[E]` Engineering operationalization. |
| Flat: `rho(Tp=5)/rho(Tp=1) > 0.8` | `[E]` "5 steps and still 80% of Tp=1 skill" = minimal decay. Checked with PRIORITY over the exponential fit, since a nearly-flat curve can spuriously achieve high R^2 with a tiny slope (see `decay_profile_scan`'s docstring). |
| Lyapunov consistency: `lambda_fit/lambda_lyap` in `[0.5, 3.0]` | `[E]` Engineering operationalization for cross-checking against Secret 1. |

**Note on test-fixture calibration** (added during Round 11 implementation,
not a threshold change): a decay-shape classifier's verdict depends on
whether the *scanned Tp range* actually spans a meaningful fraction of the
system's own Lyapunov time — a genuinely chaotic system sampled far finer
than its own timescale will correctly show as "flat" within a short Tp
window, because there simply hasn't been enough time for decorrelation yet.
This is a property of the scan range relative to the system's timescale,
not a flaw in the flat/exponential logic itself. See docs/CHANGELOG.md.

## Multiple Comparison Correction (Secret 13, added Round 11)

**Location**: `ccm_causality.ccm_batch_test()`, `ccm_causality._benjamini_hochberg()`.

| Threshold | Rationale |
|-----------|-----------|
| Benjamini-Hochberg `q=0.05` (exploratory) | `[C]` Standard FDR convention (Benjamini & Hochberg 1995); ROUND26 P1-3 修复: 原 q=0.10 偏宽松，改为 0.05 与 single-test α=0.05 一致，减少假阳性。 |
| Bonferroni `alpha/K` (confirmatory) | `[C]` Classical family-wise error control (Bonferroni 1936). |
| No correction (preregistered, or `K<=2`) | `[D]` Standard practice: pre-specified hypotheses don't inflate search space; 2 or fewer comparisons is not meaningfully "multiple" testing. |
| Warn threshold `K >= 5` pairs (exploratory) | `[E]` Reference doc's own reliability concern: FWER exceeds ~23% at K=5 under uncorrected alpha=0.05. |
| Effect-size gate: `abs(final_rho) > 0.2` before a p-value counts at all | `[E]` **Added after this function's own self-test surfaced a real issue**: the library-size sweep has ~N/3 points, so on longer series a practically meaningless monotonic drift in a near-zero rho-vs-libsize curve can produce an astronomically small `spearman_p` from sample size alone (observed: p=1e-51 for a pure-noise pair with final_rho=0.03). Multiple-comparison correction assumes its input p-values are properly calibrated under the null; without this gate, BH/Bonferroni would be correcting p-values that don't mean what they're supposed to mean. This same gate was added directly to `ccm_causality_test()`'s core `is_converging` computation, not just this batch function — see docs/CHANGELOG.md (Round 11) for the full repro. |

## Nonlinear Sampling Adequacy (Secret 14, added Round 11)

**Location**: `sovereign_havok.SovereignHAVOK._check_sampling_adequacy()`,
called automatically at the end of `fit()`.

| Threshold | Rationale |
|-----------|-----------|
| Spike threshold `1.5 sigma` of `forcing_` | `[E]` Matches the existing spike-detection threshold already used in `diagnose()` — reused rather than introducing a second, possibly-drifting definition of "spike". |
| Undersampled-spike width `< 2` samples | `[E]` Engineering operationalization: a forcing spike resolved by fewer than 2 samples cannot have its shape (rise/fall time) characterized. |
| Undersampled fraction `> 30%` -> WARN | `[E]` Engineering operationalization; only evaluated when `spike_count >= 3` (fewer spikes isn't enough to estimate a meaningful "fraction undersampled"). |
