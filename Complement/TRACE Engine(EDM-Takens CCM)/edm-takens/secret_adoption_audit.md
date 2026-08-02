# Secret Adoption Audit: EDM-Takens Skill

Each of the fourteen forbidden rules (expanded from 7 to 14 in the Round 10
reference update — see `references/forbidden_rules_reference.md`) is
assessed for adoption status, implementation strength, and editorial/
firewall treatment.

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ ADOPTED | Fully implemented with code enforcement |
| ⚠️ PARTIAL | Implemented but with known limitations |
| 🔶 DEFERRED | Scientifically valid but data/precondition not met |
| ⬜ SPECIFIED | Round 10: fully specified in the reference doc with concrete algorithms and sourced thresholds, but no code exists yet |
| ❌ REJECTED | Incorrect or inapplicable to this skill |


## Secret 1: Lyapunov Horizon

**Status**: 🔶 DEFERRED (data-conditional)

**Scientific validity**: ✅ CORRECT. The Lyapunov time tau_L = 1/lambda_max is
an absolute physical bound on chaotic predictability. Any prediction beyond
3-5*tau_L is scientifically meaningless.

**Implementation**:
- `edm_auditor.py`: `audit_lyapunov_horizon()` blocks when pred_horizon > 5*tau_L
- `final_interpretation.py`: `estimate_lyapunov_robust()` with R^2 quality check
- Reviewer improvement #1: fit_r2 < 0.5 flags estimate as UNRELIABLE

**Adoption rationale**: The algorithm is fully coded. But for N < 100, lambda_max
estimation is unreliable (Rosenstein method needs dense phase-space sampling).
The auditor correctly SKIPs when lambda_max is unavailable rather than guessing.
This is DEFERRED, not FAILED — it activates automatically when data volume
reaches threshold.

**Firewall treatment**: Advisory (WARN/FAIL when horizon violated, SKIP when
lambda unavailable). Does NOT block execution on insufficient data.

**Editorial note**: The "3*tau_L rule" is a guideline, not a theorem. For
non-chaotic systems (lambda_max ~ 0), tau_L -> infinity and the rule is moot.
The auditor handles this case correctly (SKIP when lambda <= 0).


## Secret 2: CCM Victim Mirror Principle

**Status**: ✅ ADOPTED (fully enforced)

**Scientific validity**: ✅ CORRECT. Sugihara et al. (Science, 2012)
definitively established: if X drives Y, then Y's shadow manifold M_Y encodes
X's dynamics and can cross-map X. The reverse (M_X -> Y) need not hold.

**Implementation**:
- `edm_auditor.py`: `audit_ccm_direction()` verifies direction and convergence
- `ccm_causality.py` (canonical, added Round 9): `ccm_causality_test()`
  implements convergence slope check (Reviewer improvement #2: single rho
  insufficient) — single source of truth
- `final_interpretation.py`: `ccm_with_convergence()` — thin wrapper around
  `ccm_causality_test()`
- `enhanced_cross_validate.py`: `verify_ccm_direction()` — thin wrapper
  around `ccm_causality_test()`; correct pyEDM direction semantics
  (`columns=effect, target=cause` tests cause->effect)

**Round 9 correction**: until 2026-07-08, `verify_ccm_direction()` was an
independent implementation with no convergence check at all (only the rho
at the largest library size), and `pipeline.py`'s post-computation audit
feedback never forwarded convergence data into `audit_ccm_direction()`
either — so despite this section's claim, the convergence requirement was
not actually enforced along that path. Both are now thin wrappers around
`ccm_causality_test()`, and `pipeline.py` forwards the convergence metrics
through. See docs/CHANGELOG.md (Round 9) for the full account.

**Common pitfall (detected and corrected)**:
In pyEDM, `CCM(columns=Y, target=X)` tests X->Y. The skill's original
game_analysis.py had the direction potentially inverted. This is now
documented in every CCM call site.

**Firewall treatment**: WARN when neither direction converges. SKIP when
CCM data unavailable. Does NOT auto-declare causality — always requires
human interpretation of the convergence pattern.

**Editorial note**: The "arrow trap" (Secret 7 in the reference doc) is
merged into Secret 2. Both directions MUST be tested; a single-direction
CCM result is insufficient for causal inference.


## Secret 3: Hankel Golden Aspect Ratio (p >= 10*q)

**Status**: ✅ ADOPTED (fully enforced)

**Scientific validity**: ⚠️ ENGINEERING RULE (not mathematical theorem).
The 10x ratio comes from numerical linear algebra experience: SVD of tall-thin
matrices has well-conditioned singular vectors; square or nearly-square matrices
risk mode coupling. But the exact threshold depends on noise level and signal
structure.

**Implementation**:
- `edm_auditor.py`: `audit_hankel_aspect_ratio()` with 3-tier enforcement:
  - ratio >= 10: PASS (green)
  - 5 <= ratio < 10: WARN (yellow) — marginal, may see stiffness
  - 3 <= ratio < 5: FAIL (red) — A-matrix eigenvalues degraded
  - ratio < 3: FAIL (critical) — SVD BROKEN, results are garbage
- `enhanced_cross_validate.py`: `check_hankel_aspect_ratio()` (same logic)

**Adoption rationale**: Fully adopted with tiered enforcement. The 10x rule is
conservative but safe. For our 32-game data, this correctly identified damage
(E=6, p/q=4.5) as having degraded HAVOK diagnostics, explaining the EDM-HAVOK
disagreement on nonlinearity.

**Firewall treatment**: FAIL (red) blocks computation for p/q < 3. WARN
(yellow) allows but flags. The recommended q for any dataset is automatically
computed: q_max = max(2, (n+1)//11).

**Editorial note**: The "golden ratio" name is aspirational, not mathematical.
Users with very clean data and high signal-to-noise may safely use p/q >= 5.
The tiered enforcement accommodates this while protecting against catastrophic
degradation.


## Secret 4: Multiview Embedding

**Status**: ✅ ADOPTED (Round 13 — full numpy combinatorial fallback)

**Scientific validity**: ✅ CORRECT. Sugihara et al. (Science, 2016). When
N < 100 and multiple correlated variables exist, spatial embedding (Multiview)
outperforms temporal delay embedding because it doesn't waste data as "delay
padding." This is the single highest-impact secret for short time series.

**Implementation**:
- `multiview_svd_monitor.py`: `run_multiview_analysis()` wraps `_edm_bridge.Multiview()`
- `_edm_bridge.Multiview()`: tries pyEDM first; on failure or absence falls back to
  `_numpy_edm.multiview_full()`, a pure-numpy implementation of the Sugihara-2016
  combinatorial candidate sweep (all C(K-1, E) variable combinations scored by
  out-of-sample Simplex skill, with deterministic `max_combos` cap for large K).
- `edm_auditor.py`: `audit_multiview()` flags when N < 100 with >= 2 variables
- SKILL.md Decision Guide: Multiview recommended for N < 100 multivariable

**Limitation**: pyEDM.Multiview() on Python 3.13 / Windows can fail due to
multiprocessing issues, but the fallback now provides the *same* candidate-model
selection algorithm rather than a PCA-style approximation. Behavior is identical
across platforms when pyEDM is unavailable; when pyEDM is present and works, it
is used for C++ performance.

**Firewall treatment**: Advisory only. Recommends Multiview when feasible
but never blocks execution. The auditor SKIPs when < 2 columns available.


## Secret 5: SVD Reconstruction Residual Monitor

**Status**: ✅ ADOPTED (fully implemented)

**Scientific validity**: ✅ CORRECT. If the underlying dynamical system
undergoes a regime shift (attractor deformation), the original SVD basis
(U_r, V_r) from the Hankel matrix can no longer span the new dynamics.
The normalized reconstruction residual ||H - U_r*S_r*V_r^T||_F / ||H||_F
will spike, providing a real-time alarm.

**Implementation**:
- `multiview_svd_monitor.py`: `SVDResidualMonitor` class with:
  - `compute_residual()`: Frobenius norm reconstruction error
  - `fit_baseline()`: establish baseline from initial data
  - `update()`: sliding-window monitoring with sustained-alarm logic
  - `trigger_adaptive_forgetting()`: drop oldest 50% data on confirmed alarm
- `edm_auditor.py`: `audit_svd_residual()` validates residual against baseline
- Reviewer notes incorporated:
  - 2.5x threshold (not hard-coded, configurable)
  - 3 consecutive windows required (prevents false alarms)
  - F-test alternative documented for future enhancement

**Adoption rationale**: Fully adopted. The sustained-alarm logic (3 consecutive
windows above threshold) prevents false positives from single outliers.

**Firewall treatment**: FAIL when residual > 2.5x baseline sustained for 3+
windows. Triggers adaptive memory fracture. SKIP when no baseline established.

**Editorial note**: The 50% data-drop heuristic is noted as exactly that — a
heuristic. For production use at N > 500, replace with structural break test
(Chow test or Bai-Perron) to find the optimal cut point. This enhancement is
documented as a TODO in the code.


## Secret 6: EDM-HAVOK Cross-Validation

**Status**: ✅ ADOPTED (fully enforced)

**Scientific validity**: ✅ CORRECT. EDM (S-Map, Simplex) and HAVOK (Koopman
operator, SVD decomposition) approach nonlinear detection from completely
independent mathematical foundations. When both agree, diagnosis confidence
is high. When they disagree, at least one is wrong — and the disagreement
itself is a valuable diagnostic signal.

**Implementation**:
- `enhanced_cross_validate.py`: full cross-validation with 3 safeguards
- `verify_algorithms.py`: 5-level scored verification (100-point scale)
- `edm_auditor.py`: `audit_cross_validation()` flags EDM/HAVOK disagreement
- `final_interpretation.py`: integrated dynamical interpretation

**Cross-validation checks**:
  1. Predictability: EDM Simplex rho <-> HAVOK explained variance
  2. Nonlinearity: EDM S-Map theta>0 <-> HAVOK kurtosis > 1.5
  3. Self-consistency: V-basis vs U-basis agreement
  4. Causal direction: CCM vs HAVOK forcing correlation

**Adoption rationale**: Fully adopted. The cross-validation layer is the
difference between two independent analyses and one coherent diagnosis.
The 80/100 verification score on game data correctly reflects data limitations
while confirming algorithmic soundness.

**Firewall treatment**: WARN when EDM and HAVOK disagree on nonlinearity.
Does NOT block — the disagreement itself may indicate data issues (Hankel
ratio, sample size) that are caught by other firewall rules.


## Secret 7: CCM Arrow Trap

**Status**: ✅ ADOPTED (merged into Secret 2)

**Scientific validity**: Implementation note, not a separate mathematical rule.

**Implementation**: The "arrow trap" — explicitly verifying both CCM directions
and using convergence slope to distinguish true causality from spurious
correlation — is fully integrated into Secret 2's implementation:
- `ccm_with_convergence()` runs both directions
- `audit_ccm_direction()` checks convergence slope (not just final rho)
- Decision logic: converging forward + non-converging reverse = forward causal

**Firewall treatment**: Same as Secret 2.


## Secret 8: Stationarity Gate

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT and important. Takens' theorem assumes
the underlying dynamics are stationary; a trending or variance-heterogeneous
series produces delay embeddings that reconstruct the trend's geometry, not
the dynamics' geometry. The reference doc calls this "the largest category
of silent failure in applying EDM/HAVOK".

**Implementation**: `edm_auditor.Auditor.audit_stationarity()`. ADF + KPSS
joint decision matrix (stationary / trend-stationary / difference-stationary
/ underpowered), plus three supplementary checks: rolling-window variance-
heterogeneity ratio, trend-to-noise ratio, and a Schreiber (1997)
cross-prediction-decay test (first-half-predicts-second-half vs first-half-
predicts-itself). Requires `statsmodels` (added to requirements.txt);
gracefully SKIPs (not FAILs) if unavailable. Wired into `run_full_audit()`
and, critically, into `pipeline.py`'s pre-execution audit call — `data` is
now extracted *before* the audit call (previously extracted after, so this
data-dependent gate could never actually fire through the standard pipeline
entry point regardless of whether the data itself was fine).

**Round 11 correction during implementation**: the Schreiber cross-
prediction helper (`_one_nn_cross_pred_rho`) initially produced a false-
positive "non-stationary" verdict on pure white noise, because its
self-prediction baseline (`source is target`) let every query point
trivially match itself at distance 0, producing a spuriously perfect
rho_self=1.0 that any real cross-segment rho then looked like a "decay"
from. Fixed by excluding zero-distance self-matches (same pattern as
`_numpy_edm.py`'s `simplex_predict`), and by requiring rho_self itself to
exceed 0.2 before the decay ratio is treated as meaningful at all (a series
with no real self-predictive skill has nothing for "decay" to mean).

**Firewall treatment**: Advisory (WARN) — never blocks.


## Secret 9: Observation Genericity Gate

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT. Takens' theorem requires the observation
function to be "generic" (injective + immersive). The skill's pre-existing
`is_binary` flag is one special case of this broader gate — this
implementation generalizes it: `Auditor.is_binary=True` (the old manual
flag) still forces the non-injective finding, but the new check *also*
derives it directly from data (unique-value count), and adds boundary-
saturation and coarse-quantization detection that the old flag never
covered. Symmetric folding (|x|, RMS) cannot be auto-detected from a single
series and is surfaced only when the caller explicitly hints at it.

**Implementation**: `edm_auditor.Auditor.audit_observation_genericity()`.
Pure numpy — no new dependency. Wired into `run_full_audit()` and (via the
same `data`-before-audit-call reordering as S8) into `pipeline.py`.

**Firewall treatment**: Advisory (WARN) — never blocks.


## Secret 10: Seasonality / Periodic-Forcing Confound

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT. This is the Cobey & Baskerville (2016)
confound: a shared external periodic driver (daily/weekly/seasonal cycles)
can make CCM report convergent "causality" between two variables that are
each just independently entrained to the same clock.

**Implementation**: `edm_auditor.dominant_periodicity()` (Lomb-Scargle
periodogram per variable — handles irregular sampling natively, no new
dependency: `scipy.signal.lombscargle`) and `edm_auditor.
audit_seasonality_confound()` (cross-checks whether CCM-convergent pairs
share a dominant frequency). Both are module-level functions (not `Auditor`
methods), since S10 is inherently a cross-variable check unlike the
single-series `Auditor` design. Wired into `Router.route()`: added as an
optional "Seasonality Confound Check" step whenever CCM will run and N>=20
— not generically auto-executable via `route_and_execute()` (needs named
multi-variable data + the specific CCM pairs tested, which a routing
decision can't encode), so it's recorded as a plan step for visibility
rather than run automatically, consistent with `pipeline.
run_full_analysis()` being the actual fully-wired orchestrator for that.

**Firewall treatment**: Advisory (WARN) only — never blocks. De-
seasonalized-residual re-analysis is recommended but NOT automated
(deseasonalizing is itself a modeling choice).


## Secret 11: Common Driver / Latent Confounding Disclaimer

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT, and — as the reference doc predicted —
the lowest-cost, highest-payoff item of the seven: zero new computation.
CCM detects dynamical coupling, not Pearl-style mechanistic causation; an
unobserved Z driving both X and Y produces the same convergence signature
as X causing Y. This is a fundamental identifiability limit, not something
a threshold can fix — only honestly disclaimed.

**Implementation**: `ccm_causality.common_driver_disclaimer()`, called
unconditionally inside `ccm_causality_test()` and attached to its return
dict as `result['disclaimer']` — every consumer of the canonical CCM test
(`final_interpretation.py`, `enhanced_cross_validate.py`, `pipeline.py`)
gets it automatically, with no separate wiring needed per call site. The
multi-pair escalation (>=3 convergent pairs) is computed by the caller
(who knows how many pairs were tested) and passed to
`common_driver_disclaimer(n_significant_pairs=...)`.

**Firewall treatment**: Advisory, appended to every CCM output
unconditionally — this is the whole point; confounding doesn't announce
itself, so it can't be shown only when a result "looks suspicious".


## Secret 12: Prediction Decay Profile Analysis

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT; lowest-priority of the seven per the
reference doc's own weight (★). A single Tp=1 skill throws away information
a full decay-shape classification recovers, and cross-checks against
Secret 1's Lyapunov estimate when available.

**Implementation**: `sensitivity_config.decay_profile_scan()`. Sweeps
Tp in [1, min(20, N/3)], fits an exponential decay (R² test), detects
second-difference spikes (sharp cutoff), checks residual lag-1
autocorrelation (oscillatory), and compares rho(Tp=5)/rho(Tp=1) (flat/
linear-dominant) — flat is checked with priority over the exponential fit,
since a nearly-flat curve can spuriously achieve a high R² with a tiny
slope. Wired into `Router.route()` for `predict`/`detect_nl` goals at
N>=30.

**Round 11 correction during implementation**: this function's own
self-test initially used a Lorenz fixture sampled far finer (raw dt=0.01
integration step) than the Tp sweep range could meaningfully capture — 15
raw integration steps is a small fraction of one Lyapunov time (~1.1 time
units for Lorenz), so rho barely decayed across the scanned range and got
(correctly, per the classifier's own logic) labeled "flat" even though the
underlying dynamics are chaotic. This was a test-fixture calibration issue,
not an algorithm bug — replaced with a fast-decorrelating fixture (the
fully chaotic logistic map, Lyapunov exponent ln(2)/step) that properly
exercises the "not flat, exponential decay" classification within a Tp<=15
window. See docs/CHANGELOG.md for the full account, and
verify_algorithms.py's Round 9 logistic-map fix for the *other*, unrelated
logistic-map pitfall (x0=0.5 landing exactly on the r=4 critical point).

**Firewall treatment**: Diagnostic only — no PASS/WARN/FAIL verdict, just
a classification exposed in the returned dict.


## Secret 13: Multiple Comparison Correction for CCM

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT and important once K(K-1)-style pairwise
CCM tests are run routinely — with K=4 variables (6 pairs) the reference
doc calculates a ~26% chance of at least one false-positive "causal" pair
at uncorrected alpha=0.05.

**Implementation**: `ccm_causality.ccm_batch_test()`, with a hand-rolled
Benjamini-Hochberg FDR procedure (`_benjamini_hochberg()` — no
`statsmodels` dependency needed for this one, unlike S8; BH/Bonferroni are
simple enough not to justify it) and Bonferroni correction, selected by
`analysis_label` ('exploratory' -> BH q=0.10, 'confirmatory' -> Bonferroni
alpha/K, 'preregistered' or K<=2 -> no correction). Wired into
`pipeline.py`, replacing the previous manual per-cause CCM loop (which
reported each pair's raw verdict independently, with no correction at all)
— the pipeline's existing 3-candidate-cause CCM check was exactly the K=3
scenario S13 exists for. Also wired into `Router.route()` (optional step
when `ccm_pairs >= 5`, matching the reference doc's routing threshold).
`PipelineConfig` gained an `analysis_type` field (previously hardcoded to
`"exploratory"` in two separate places) so this and the existing config-
artifact capture share one source of truth.

**Round 11 correction during implementation (the most consequential one
this round)**: this function's own self-test surfaced that `spearman_p`
(the p-value being corrected) is not well-calibrated on its own. The
library-size sweep has ~N/3 points; for longer series this gives the
Spearman rank test enough samples that even a practically meaningless
monotonic drift in a near-zero, noisy rho-vs-libsize curve produces an
astronomically small p-value from sample size alone — observed empirically:
p=1e-51 for a pure-noise pair with final_rho=0.03 (no real cross-map skill
at all). Feeding uncorrected, miscalibrated p-values into BH/Bonferroni
defeats the point of correcting them. Fixed with an effect-size gate
(`abs(final_rho) > 0.2`, matching `ccm_causality_test`'s existing
`strong_direction_rho`) applied *before* a pair's p-value is used at all —
and, since this is a property of the underlying convergence test itself,
not just the new batch function, the same gate was added directly to
`ccm_causality_test()`'s core `is_converging` computation (previously
`is_converging` could be spuriously True for a near-zero-rho pair; the
human-readable `verdict` text was never actually misled by this, since it
already applied a separate 0.2 floor before saying "drives" vs "weak
signal" — but `is_converging` itself is a field other code reads directly,
including this new batch function and `pipeline.py`'s printed "converging=
True/False"). See docs/CHANGELOG.md for the full repro and fix.

**Firewall treatment**: Advisory (WARN) at K>=5 uncorrected pairs, per the
reference doc's reliability threshold; the correction itself is always
applied when `ccm_batch_test()` is used, regardless of K.


## Secret 14: Nonlinear Sampling Adequacy

**Status**: ✅ ADOPTED (Round 11)

**Scientific validity**: ✅ CORRECT but the reference doc is explicit that
this rule "rarely triggers" for this skill's actual use case (game-log data
with a natural 1-game sampling interval) and is included mainly for
completeness / future sensor-data use cases where sampling rate is a real
design choice.

**Implementation**: `SovereignHAVOK._check_sampling_adequacy()`, called
automatically at the end of `fit()` and populating `self.sampling_adequacy_`
(also surfaced in `diagnose()`'s output). Scans `forcing_` for contiguous
above-1.5σ regions narrower than 2 samples; flags if that undersampled
fraction exceeds 30% (only meaningful when spike_count >= 3). Pure numpy,
no new dependency. No separate Router step needed — it's unconditionally
part of the existing "HAVOK Decomposition" step.

**Firewall treatment**: Diagnostic only, surfaced in `diagnose()`'s output.

---

**A note on the bibliography**: the reference doc cites all sources by
`[B##]` tag pointing to `references/fourteen_rules_bibliography.md`. That
bibliography file is present in the skill package — a complete annotated
catalog of 39 papers, indexed by rule number across all 14 rules, with
inline author/year/journal citations and per-rule "Role" + "In Skill"
annotations. The `[B##]` tags in `forbidden_rules_reference.md` therefore
resolve correctly to the catalog entries (B01-B39), and the promised
cross-references are no longer dangling.

## Summary Table

| # | Secret | Adoption | Firewall | Blocks Execution? | Data Requirement |
|---|--------|----------|----------|-------------------|------------------|
| 1 | Lyapunov Horizon | 🔶 DEFERRED (N≥100) | WARN/FAIL | Only if violated | N >= 100 |
|   |                    | 🆕 SURROGATE-LB   | Advisory  | No               | N >= 30 |
| 2 | CCM Victim Mirror | ✅ ADOPTED | WARN | No (advisory) | N >= 30 |
|   | (convergence)     | ✅ UPGRADED | WARN | total_rise+Spearman+effect-size | Always |
| 3 | Hankel Ratio | ✅ ADOPTED | FAIL (p/q<3) | Yes (critical) | Always active |
|   | (DRY unified)     | ✅ FIXED | shared classify_hankel_ratio() | | |
| 4 | Multiview | ✅ ADOPTED (Round 13) | Advisory | Never | N < 100, K >= 2 |
|   | (numpy fallback)  | ✅ ADOPTED | Sugihara-2016 combinatorial scan via _edm_bridge | | Always |
| 5 | SVD Residual | ✅ ADOPTED | FAIL (>2.5x) | Yes (sustained) | N >= 50 per window |
| 6 | Cross-Validation | ✅ ADOPTED | WARN | No (diagnostic) | Always active |
| 7 | Arrow Trap | ✅ (merged) | WARN | No (advisory) | Always active |
| 8 | Stationarity Gate | ✅ ADOPTED (Round 11) | WARN | No (advisory) | N >= 20, statsmodels |
| 9 | Observation Genericity | ✅ ADOPTED (Round 11) | WARN | No (advisory) | Always |
| 10 | Seasonality Confound | ✅ ADOPTED (Round 11) | WARN | No (advisory) | N >= 20, CCM runs |
| 11 | Common Driver Disclaimer | ✅ ADOPTED (Round 11) | Advisory | No | CCM runs, automatic |
| 12 | Decay Profile | ✅ ADOPTED (Round 11) | Diagnostic | No | N >= 30 |
| 13 | Multi-Comparison Corr. | ✅ ADOPTED (Round 11) | WARN at K>=5 | No | CCM pairs >= 2 |
| 14 | Sampling Adequacy | ✅ ADOPTED (Round 11) | Diagnostic | No | Automatic in HAVOK.fit() |
| - | Tau Selection     | 🆕 NEW | WARN/FAIL | Window > 50% N | Always active |
| - | Config Artifact   | 🆕 NEW | Auto-save | No | Always active |
| - | pyEDM Fallback    | 🆕 NEW | _edm_bridge | No | Always active |
| - | HAVOK Eigenvalue  | 🆕 FIXED | discrete eig_d | No | Always active |

## Adoption Rates

- **Fully Adopted (S1-S7)**: 7/7 (Secrets 1, 2, 3, 4, 5, 6, 7). Secret 1 is
  data-conditional: its Rosenstein λ_max path auto-activates at N>=100, and for
  N<100 it falls back to the SURROGATE-LB implementation (surrogate-based
  Lyapunov lower bound), so the secret has working, enforced code at every N.
- **Fully Adopted (S8-S14, Round 11)**: 7/7 — all seven newly-specified
  secrets from the Round 10 reference update now have working, tested code.
  Three genuine bugs were found and fixed *during* this implementation work
  (not pre-existing issues, but ones introduced by the implementation
  process itself and caught by each function's own self-test before
  delivery): a trivial self-match inflating S8's cross-prediction-decay
  baseline to a spurious rho=1.0; a too-finely-sampled Lorenz test fixture
  for S12 that made a genuinely chaotic system's decay look "flat" purely
  because the Tp sweep didn't span a meaningful fraction of its Lyapunov
  time; and — the most consequential — S13's own self-test surfacing that
  the core `is_converging` field in `ccm_causality_test()` (used
  everywhere, not just S13) could be spuriously True for a near-zero-rho
  pair, fixed with an effect-size floor added directly to that canonical
  function. See docs/CHANGELOG.md (Round 11) for full repros of all three.
- **Secret 4 Upgraded (Round 13)**: Multiview now has a full Sugihara-2016 numpy
  combinatorial fallback (no longer pyEDM-dependent; replaces the earlier PCA-style
  SVD-spatial fallback)
- **Secret 1 Enhanced**: Surrogate-based lower bound for N<100
- **New Guardians**: Tau selection audit, config artifact auto-save, pyEDM graceful fallback
- **Bug Fixes (Round 9-11)**: HAVOK eigenvalue continuous→discrete, CCM
  convergence scale-invariant + convergence-bypass fix + effect-size floor,
  Hankel DRY, IAAFT end-point matching, `_numpy_edm` weight/value alignment
  (3 sites), `route_and_execute` data-injection (2 rounds — required
  parameter injection in Round 10, optional-keyword injection in Round 11
  for `audit_pipeline`-shaped functions), `sensitivity_scan` near-zero CV
  guard, `ccm_batch_test`'s p-value effect-size gate
- **Rejected**: 0/14

**Overall adoption**: 14/14 secrets now have working, enforced code (Secret 1
is data-conditional and auto-activates at N>=100; its N<100 surrogate lower
bound is also implemented). See docs/CHANGELOG.md (Rounds 11 and 13) for the
full implementation account, including the three bugs found and fixed during
Round 11 and the Round 13 Multiview fallback upgrade.
