# EDM-Takens Skill — CHANGELOG

All notable changes to the edm-takens skill. Dates are ISO-8601.
This file is a maintainable engineering attachment (P11).

## 2026-07-15 — Round 15 (full audit & bidirectional sync with edm-takens-web)

Comprehensive 5-layer audit (algorithm / bridge / model / info / delivery)
revealed and fixed bidirectional drift between `edm-takens` and
`edm-takens-web`.

### Fixed (P0)
- **`final_interpretation.py` Phase 2 KeyError**: `available_variables` was
  defined but never used — Phase 2 still iterated `columns` and
  `causality_pairs`, causing KeyError when sparse/constant variables were
  skipped in Phase 1. Synced the web version's `usable_pairs` filtering
  and `available_variables` iteration to the skill version. This was a
  known lesson learned (project memory) that had been fixed in the web
  version but never backported.

### Fixed (P1/P2)
- **`pipeline.py` spike output**: Added defensive column-existence check
  for `kills`/`deaths` (synced from web version) — non-game datasets no
  longer raise KeyError on forcing spike printout.
- **`_edm_bridge.py` EmbedDimension**: Added `numProcess=1` to prevent
  Windows multiprocessing deadlock (synced from web version).
- **`_paths.py`**: Added `EDMTAKENS_DATA_DIR` environment variable support
  for deployment flexibility (synced from web version).
- **`pipeline.py`**: Now passes `variables` and `target_col` to
  `run_enhanced_validation()` (synced from web version).
- **`enhanced_cross_validate.py`**: `run_enhanced_validation()` signature
  accepts `variables` and `target_col` parameters; added per-variable
  try/except to prevent single-variable failure from aborting the entire
  cross-validation run.

### Confirmed consistent (no changes needed)
- `_numpy_edm.py`: identical (1090 lines)
- `sovereign_havok.py`: identical (881 lines)
- `ccm_causality.py`: algorithm identical (self-test code differs only in
  constant naming)
- `edm_auditor.py`, `edm_adaptive_pipeline.py`, `edm_tau_optimization.py`,
  `multiview_svd_monitor.py`, `surrogate_test.py`, `verify_algorithms.py`,
  `router.py`, `sensitivity_config.py`: all identical

## 2026-07-12 — Round 13 (follow-up optimization backlog: P5-P12)

Implementation of the remaining optimization proposals identified during the
Round 12 review, focused on cross-layer integration, algorithmic fidelity, and
packaging hygiene.

### Added / Changed

- **P5 — Unified full-analysis entry point**: `pipeline.run_full_analysis()`
  now chains the complete SKILL.md flow (pipeline → enhanced cross-validation
  → dynamical interpretation) in a single call. Both `src/pipeline.py` and the
  top-level `run_pipeline.py` expose a `--full-analysis` CLI flag. Each stage
  is wrapped so a failure in one stage does not abort the others.
- **P6 — Audit verdict in config artifact**: `AnalysisConfig` gained
  `audit_verdict` and `audit_findings_summary` fields, and `pipeline.py` now
  records the pre-/post-execution firewall verdict when saving the
  timestamped config JSON under `results/`.
- **P7 — Full Sugihara-2016 Multiview fallback**: `_edm_bridge.Multiview()`
  falls back to `_numpy_edm.multiview_full()`, which enumerates candidate
  variable combinations and scores each by out-of-sample Simplex rho. This
  replaces the previous PCA-style SVD spatial fallback and gives consistent
  behavior across platforms when pyEDM is unavailable or fails (notably on
  Windows/Python 3.13 multiprocessing paths).
- **P9 — CCM convergence thresholds documented**: the empirical basis for
  `total_rise > 0.05`, `spearman_rho > 0.7`, `final_rho > 0.2`, and the
  bidirectional `delta` cutoff is now recorded in
  `docs/thresholds_and_heuristics.md`.
- **P11/P12 — Packaging and dependency portability**: `requirements.txt` now
  uses lower-bound constraints (`>=`) for broad portability, while
  `requirements-lock.txt` preserves the exact reference-environment manifest.
  This CHANGELOG itself is the maintainable record for P11.

### Verification

- `python run_tests.py --quick`: 89/89 passed.
- `python run_tests.py` (full): 96/96 passed.
- `python run_pipeline.py --full-analysis --q 3 --auto-fix`: all three stages
  report OK and produce the expected artifacts.
- Clean package rebuilt at `../edm-takens.skill` with runtime artifacts
  (`results/`, `figures/`, `__pycache__/`, etc.) excluded per `.gitignore`.

### Runtime environment hardening (Round 13 follow-up)

- **Windows page-file guidance documented**: on a 16 GB RAM Windows host, the
  `ccm_causality.py` module self-test can exhaust virtual memory because pyEDM
  spawns subprocesses that each reload numpy/scipy/pandas. Verified fix:
  allocate a fixed 16 GB page file on a secondary SSD and restart. Documented
  in `docs/TROUBLESHOOTING.md`.
- **Layer 7 self-test timeout extended**: `run_tests.py` subprocess timeout for
  module self-tests raised from 120 s to 300 s, so the heavy CCM self-test is
  not killed prematurely once memory is no longer the bottleneck.
- **`.gitignore` streamlined**: removed the temporary `_sync_verify/` entry
  (folder no longer used).

### Verification (after runtime hardening)

- `python run_tests.py --quick`: 89/89 passed in ~210 s on the reference
  Windows/16 GB machine.
- `python run_pipeline.py --full-analysis --q 3 --auto-fix`: all stages OK.

## 2026-07-09 — Round 12 (full-codebase census: algorithm, functionality, business-layer honesty)

A fresh census pass, explicitly re-checking algorithm correctness, functional
completeness, and business-layer (narrative/reporting) implementation across
the whole codebase — not targeted at any specific secret or module. Found
and fixed issues in three tiers: dead code (cosmetic), a real cross-module
data-validation gap (functional), and — the most significant category —
static/hardcoded narrative text in the interpretation layer that had drifted
out of sync with what the code actually computes (business-layer honesty).

### Fixed — dead code / import hygiene

Confirmed via static analysis + manual verification (not removed on the
static analysis's say-so alone, since it has false positives — each
candidate was grep-confirmed to have zero real usages before removal):
`matplotlib.pyplot as plt` (sovereign_havok.py, self-test block only),
`sys` (enhanced_cross_validate.py, verify_algorithms.py,
final_interpretation.py), `os`/`json` (router.py — `.json` was a false
positive: only the string extension in an f-string, not the module),
`Any`/`Tuple` (router.py, edm_auditor.py, environment_check.py),
`SovereignHAVOK` (multiview_svd_monitor.py — `SVDResidualMonitor` is
self-contained and never actually instantiates it). Also removed two
redundant local `try: import pyEDM` availability probes
(enhanced_cross_validate.py, multiview_svd_monitor.py) that duplicated
what `_edm_bridge.py` already does canonically — each computed a local
flag (`_PYEDM_AVAILABLE` / `_PYEDM`) that was set but never read; the flag
genuinely used throughout both files is `_edm_bridge`'s own
`EDM_AVAILABLE`. No behavior change; these were pure dead weight (one had
the side effect of printing a redundant warning on import).

### Fixed — non-finite (Inf) value handling gap (found via edge-case census)

Testing every Round 11 (S8-S14) function against a battery of pathological
inputs (empty, single-point, all-NaN, all-same-value, all-zero, partial-NaN,
Inf/-Inf) surfaced that `audit_stationarity()`, `audit_observation_
genericity()`, and `dominant_periodicity()` each filtered NaN but not
+/-Inf before proceeding — inherited from copying the same (incomplete)
filter idiom (`data[~np.isnan(data)]`) across all three. Concretely: an
Inf value was silently counted as a legitimate "unique value" in
`audit_observation_genericity()` (inflating n_unique and corrupting the
boundary-saturation min/max), and propagated into `dominant_periodicity()`'s
Lomb-Scargle power computation as NaN, which then silently evaluated
`is_high_seasonality = nan > 0.30` as `False` (NaN comparisons are always
False in Python) — reporting "assessable: True, no seasonality" for a
result that was actually just NaN, not a real "no" answer. All three fixed
to filter `np.isfinite` instead of `~np.isnan`. `audit_observation_
genericity()`'s fix required a follow-up correction: the non-finite-value
count is now surfaced as an informational note in its message (for
legibility) without itself flipping PASS to WARN — that's the general Data
Quality Check's job, not genericity's, and conflating them would have
double-reported the same underlying issue under two different secrets.

This also surfaced a genuine architectural gap, not just a filtering bug:
`edm_auditor.Auditor.audit_data_quality()` — the FIRST check `run_full_
audit()` runs, specifically because pre-execution gates are supposed to
catch reachable problems before expensive computation — was based only on
`self.n` (a plain sample-size count) and never looked at `self.data`'s
actual values at all. NaN/Inf contamination was previously only ever
caught later, inside `SovereignHAVOK.fit()`'s own `np.isfinite` guard —
meaning a user could see "audit PASSED" printed, then have the actual
computation fail (or, worse, degrade silently) on the exact same data.
Fixed: `audit_data_quality()` now checks `self.data` for non-finite values
when available and FAILs (not just WARNs) if any are found.

**Deeper consequence found while verifying the fix end-to-end**:
`pipeline.run_pipeline()`'s Layer 2 auto-E-detection (`EmbedDimension`, a
real pyEDM/KDTree computation) runs *before* the audit gate — a genuine
chicken-and-egg ordering constraint, since the full audit needs `config.q`
as an input and that's exactly what auto-detection determines when the
caller doesn't specify it. This means the newly-strengthened `audit_data_
quality()` FAIL could never actually protect the default pipeline path:
Inf-contaminated data crashed uncaught inside pyEDM's KDTree construction
with a confusing low-level traceback, entirely bypassing the audit firewall
whose whole point is to catch exactly this before fragile computation runs.
Fixed with a minimal, `E`-independent early sanity gate — extract the
target column and check `np.isfinite` immediately after loading the
DataFrame, before Layer 2 touches it, with a clear, actionable message
instead of a crash. `run_full_analysis()`'s other two stages (cross-
validation, interpretation) are each already wrapped in their own
try/except at that level, so they degrade to a reported "stage failed"
rather than crashing the whole multi-stage call, but do not get this
same clear early message — acceptable (non-crashing, honestly reported)
but not as polished; noted rather than further expanded, to keep this
fix scoped to the concrete crash-bypassing-the-firewall bug found.

### Fixed — static/hardcoded narrative in the interpretation layer (business-layer honesty)

The most significant findings this round, in `final_interpretation.
interpret_game_data()` (the game-specific demo narration layer — its
sibling `interpret_data()`, the domain-agnostic reusable core, was checked
and found already clean: all its narrative text is dynamically built from
computed values). Found while testing the `data_path_override` fix below,
which made this reachable in a way it effectively wasn't before:

- **`run_full_analysis()`'s Stage 3 called `interpret_game_data()` with
  zero arguments** — silently ignoring whatever `data_path`/`target_col`
  the caller had configured for Stages 1-2 (via `PipelineConfig`) and
  always analyzing the bundled demo dataset instead. Concretely
  reproduced: pointing Stage 1 at a deliberately Inf-corrupted CSV
  correctly failed that stage, while Stage 3 silently produced a full,
  confident-looking narrative report — about the clean *default* dataset,
  not the one the user actually configured. `interpret_game_data()` gained
  an optional `data_path_override` parameter (defaulting to the current
  bundled-file behavior, so nothing changes for existing callers), and
  `run_full_analysis()` now passes `config.data_path` through. Documented
  explicitly in the new parameter's docstring that this function's
  narrative logic is schema-specific (result/kills/damage/deaths columns)
  — NOT a generic "point this at any CSV" entry point the way `pipeline.
  run_pipeline()` or `interpret_data()` are; fully generalizing the
  ~500-line narrative function to arbitrary schemas would be a rewrite,
  not a bug fix, and is out of scope here.
- **The PNG chart's summary panel, and several console print statements,
  were static text describing the ORIGINAL bundled demo dataset's specific
  findings — not derived from the current run's actual computed results.**
  This was true before `data_path_override` existed too, just harder to
  notice: the "CRITICAL INSIGHT" paragraph unconditionally asserted
  `'result' (win/loss) DRIVES kills and deaths`, the PNG's "CAUSALITY"
  section unconditionally listed 4 specific fixed cause->effect claims,
  the "FORCING" section unconditionally claimed "NO heavy tails in any
  variable", "32 games" and "Hankel ratio 4.5" were literal hardcoded
  numbers instead of the already-available `n` and `all_data[v]
  ['hk_ratio']` variables, and the final "Key takeaway" line unconditionally
  said "Stable dynamics, consistent player". **Concretely demonstrated to
  already be wrong, even on the unmodified default dataset**: re-running
  the actual CCM computation showed `kills --drives--> result` (the
  OPPOSITE direction from the hardcoded "result -> kills" claim) — CCM's
  `sample` parameter is a stochastic bootstrap (see ccm_causality.py), so
  this isn't even a one-time authoring mistake, it can differ run to run.
  Similarly the eigenvalue-based stability classification came back
  "Divergent" (driven by `damage`'s max|eig_d|=1.45, consistent with its
  already-known Hankel-ratio numerical-reliability warning) rather than
  the hardcoded "Highly dissipative... all eigenvalues < 0.2" claim. Fixed
  by rebuilding all of the above from the actual values already computed
  earlier in the function (`all_data`, the CCM verdicts from the causality
  loop, `heavy_tailed_vars` from kurtosis) — including passing the CCM
  results and Lyapunov-reliability list through to `_plot_interpretation()`
  (a separate function; needed new parameters to receive them) so the PNG
  panel can be built from them too. When no variable/pair triggers a given
  claim, the text now says so explicitly (e.g. "None of the N tested pairs
  showed a convergent causal link this run") rather than omitting the
  section or leaving stale text in its place.
- **`interpret_game_data()` never returned a value at all** (no `return`
  statement — purely side-effecting via `print()`), which meant `run_full_
  analysis()`'s own status-summary line (`'OK' if results['interpretation']
  else 'skipped/issue'`) always reported "skipped/issue" for this stage
  even on complete success, since `None` is falsy. Unrelated to the fixes
  above except being found while testing them. Fixed: now returns a dict
  (n_games, stability_tier, heavy_tailed_variables, ccm_results,
  n_ccm_significant, lyapunov_reliable_variables, output_path) — both a
  correctness fix (status summary is now accurate) and a small API
  improvement (callers can now consume the interpretation's findings
  programmatically, not just read console output).

### Verification

Every fix in this round was verified by executing the affected code with
the specific pathological input that exposed it (Inf-contaminated real
data through the full `pipeline.run_pipeline()` and `run_full_analysis()`
paths, not just unit-level checks), not merely by code review. Full test
suite (94 checks across Layers 1-7) re-run clean after every fix in this
round, not just once at the end.

## 2026-07-08 — Round 11 (implement Secrets 8-14 + cross-layer wiring)

Round 10 synced an externally-provided, substantially expanded rules
reference (7 -> 14 secrets) and gave an honest cost/priority assessment for
the seven newly-specified secrets (S8-S14) without implementing them,
pending scope confirmation. This round implements all seven, wires them
into the existing cross-layer architecture (Router -> Auditor -> Pipeline
-> Interpretation), and — consistent with every prior round's practice of
verifying via actual execution, not just code review — each new function's
own self-test surfaced three genuine, non-trivial bugs *introduced by this
round's own implementation work*, all found and fixed before delivery.

### Added — Secrets 8-14

- **Secret 8 (Stationarity Gate)**: `edm_auditor.Auditor.audit_stationarity()`.
  ADF + KPSS joint decision matrix (stationary / trend-stationary /
  difference-stationary / underpowered) plus three supplementary checks:
  rolling-window variance-heterogeneity ratio, trend-to-noise ratio, and a
  Schreiber (1997) cross-prediction-decay test. Requires `statsmodels`
  (added to requirements.txt as an optional dependency); gracefully SKIPs
  if unavailable, matching this project's existing graceful-degradation
  philosophy (cf. pyEDM -> `_numpy_edm` fallback).
- **Secret 9 (Observation Genericity Gate)**: `edm_auditor.Auditor.
  audit_observation_genericity()`. Generalizes the pre-existing manual
  `is_binary` flag (which required the caller to already know and declare
  it) into a data-derived check: unique-value count, boundary-saturation
  fraction, and quantization coarseness, all computed directly from the
  data. Symmetric folding (|x|, RMS) cannot be auto-detected from a single
  series and is surfaced only as an advisory when explicitly hinted.
- **Secret 10 (Seasonality / Periodic-Forcing Confound)**: `edm_auditor.
  dominant_periodicity()` (Lomb-Scargle periodogram per variable — handles
  irregular sampling natively; `scipy.signal.lombscargle`, no new
  dependency) and `edm_auditor.audit_seasonality_confound()` (cross-checks
  whether CCM-convergent pairs share a dominant frequency). Module-level
  functions, not `Auditor` methods, since this is inherently a
  cross-variable check unlike the single-series `Auditor` design.
- **Secret 11 (Common Driver / Latent Confounding Disclaimer)**:
  `ccm_causality.common_driver_disclaimer()`, called unconditionally
  inside `ccm_causality_test()` and attached to its result as
  `result['disclaimer']` — every consumer of the canonical CCM test
  (`final_interpretation.py`, `enhanced_cross_validate.py`, `pipeline.py`)
  gets it automatically with no separate per-call-site wiring. Zero new
  computation, as the reference doc predicted would be the cheapest,
  highest-payoff item of the seven.
- **Secret 12 (Prediction Decay Profile Analysis)**: `sensitivity_config.
  decay_profile_scan()`. Sweeps Tp in [1, min(20, N/3)], classifies the
  decay shape (exponential / sharp-cutoff / flat / oscillatory — flat
  checked with priority over the exponential fit, since a nearly-flat
  curve can spuriously achieve high R^2 with a tiny slope), and
  cross-checks the fitted decay rate against an independent Lyapunov
  estimate (Secret 1) when supplied.
- **Secret 13 (Multiple Comparison Correction for CCM)**: `ccm_causality.
  ccm_batch_test()`, with a hand-rolled Benjamini-Hochberg FDR procedure
  (`_benjamini_hochberg()` — deliberately not dependent on `statsmodels`,
  unlike Secret 8's ADF/KPSS: BH/Bonferroni are simple enough not to
  justify a hard dependency for them) and Bonferroni correction, selected
  by `analysis_label` ('exploratory' -> BH q=0.10, 'confirmatory' ->
  Bonferroni alpha/K, 'preregistered' or K<=2 -> none).
- **Secret 14 (Nonlinear Sampling Adequacy)**: `sovereign_havok.
  SovereignHAVOK._check_sampling_adequacy()`, called automatically at the
  end of `fit()`, populating `self.sampling_adequacy_` (surfaced in
  `diagnose()`'s output too). Scans `forcing_` for contiguous above-1.5σ
  regions narrower than 2 samples; flags if the undersampled fraction
  exceeds 30% (only meaningful when spike_count >= 3). Pure numpy, no new
  dependency, no separate Router step needed.

### Cross-layer wiring

- **`pipeline.py`**: `data` is now extracted from the DataFrame *before*
  the pre-execution `audit_pipeline()` call, not after. Previously the
  call happened first and `data = df[target_col].values...` came later in
  Layer 3 — meaning Secret 8/9 (both data-dependent) could never fire
  through the standard pipeline entry point, regardless of whether the
  data itself was actually fine. The manual 3-candidate-cause CCM
  quick-check loop was replaced with a single `ccm_batch_test()` call
  (Secret 13) — this loop was exactly the K=3 pairwise scenario Secret 13
  exists for, and previously reported each candidate's raw, uncorrected
  verdict independently. `PipelineConfig` gained an `analysis_type` field
  (`'exploratory'` default) — previously hardcoded to `"exploratory"` in
  two separate places (the config-artifact capture, and now also needed
  by `ccm_batch_test`'s correction-method selection); both now read the
  same field.
- **`router.py`**: `Router.route()` gained three new optional plan steps —
  Seasonality Confound Check (Secret 10, when CCM will run and N>=20),
  Multi-Comparison Correction (Secret 13, when `ccm_pairs >= 5` — `Router`
  gained a `ccm_pairs` constructor parameter, defaulting to
  `n_variables - 1`), and Decay Profile Scan (Secret 12, for `predict`/
  `detect_nl` goals at N>=30) — matching the reference doc's own routing
  pseudocode. Secrets 8/9/11/14 deliberately do NOT get separate plan
  steps: 8 and 9 already run automatically inside the existing
  "Configuration Audit" step whenever `data` is available; 11 is
  unconditional inside `ccm_causality_test()` itself; 14 is unconditional
  inside the existing "HAVOK Decomposition" step. `route_and_execute()`'s
  generic executor (`_call_step`) gained a second argument-injection rule:
  previously it only injected `data` into functions with exactly one
  *required* positional parameter (Round 10's fix) — but `audit_pipeline`
  has zero required parameters (every one, including `data`, has a
  default), so that rule never fired for it, meaning Secret 8/9 silently
  never ran through `route_and_execute` even after the Round 10 fix and
  even after the pipeline.py reordering above. The new rule: if a function
  has zero required parameters but one of them is literally named `data`,
  inject it there too. Confirmed via this module's own self-test
  (Scenario G2) that `audit_pipeline`, called the way `route_and_execute`
  actually calls it, now genuinely exercises Secret 8/9 rather than just
  returning "OK" vacuously.

### Fixed — bugs found during this round's own implementation work

Each of these was caught by the new function's own self-test before
delivery, not discovered after the fact — consistent with every prior
round's practice of verifying via execution.

- **Secret 8's Schreiber cross-prediction helper self-matched trivially**:
  `_one_nn_cross_pred_rho(source, target)` with `source is target` (the
  "self-prediction" baseline) let every query point find *itself* as its
  own nearest neighbor at distance 0, producing a spuriously perfect
  rho_self=1.0 on pure white noise — not because the noise had any real
  self-predictive structure, but from the trivial self-match alone. This
  made the cross-prediction-decay check produce a false-positive
  "non-stationary" WARN on genuinely stationary (if unpredictable) data.
  Fixed by excluding zero-distance self-matches (same exclusion pattern
  already used in `_numpy_edm.py`'s `simplex_predict`), and by requiring
  rho_self itself to exceed 0.2 before treating the decay ratio as
  meaningful at all — a series with no real self-predictive skill has
  nothing for "decay" to be measured against.
- **Secret 12's self-test used a Lorenz fixture sampled too finely for its
  own Tp sweep to capture real decay**: at the raw dt=0.01 integration
  step, 15 raw steps is a small fraction of Lorenz's own Lyapunov time
  (~1.1 time units), so rho barely decayed across the scanned range and
  was (correctly, per the classifier's own "flat" definition) reported as
  flat — even though the underlying dynamics are genuinely chaotic. This
  was a test-fixture calibration issue, not an algorithm bug: whether a
  decay profile looks "flat" or "exponential" depends on whether the
  *scanned Tp range* spans a meaningful fraction of the system's own
  timescale, not on whether the system is chaotic in some timescale-
  independent sense. Replaced with the fully chaotic logistic map
  (r=4.0, Lyapunov exponent ln(2)/step — much faster decorrelation,
  properly exercised within a Tp<=15 window regardless of subsampling).
  x0=0.2 (not 0.5) avoids the r=4 critical-point degeneracy already fixed
  in Round 9's `verify_algorithms.py` logistic test.
- **Secret 13's own self-test surfaced a real gap in the CORE convergence
  logic, not just the new batch function** (the most consequential fix
  this round): `ccm_batch_test()`'s p-value correction is only meaningful
  if its input p-values are properly calibrated under the null. Testing it
  on a batch that mixed a genuinely-coupled pair with pure-noise "null"
  pairs revealed that `ccm_causality_test()`'s `spearman_p` is not
  well-calibrated on its own — the library-size sweep has ~N/3 points, so
  on a N=400 series (~130 sweep points) even a practically meaningless
  monotonic drift in a near-zero, noisy rho-vs-libsize curve produces an
  astronomically small p-value from sample size alone (observed: p=1e-51
  for a pure-noise pair with final_rho=0.03 — no real cross-map skill at
  all). Worse, this same near-zero-rho pair satisfied ALL THREE existing
  `is_converging` conjuncts (total_rise=0.052 > 0.05, spearman_rho=0.96 >
  0.7, spearman_p=2e-57 < 0.1) — meaning `ccm_causality_test()`'s own
  `is_converging` field (used throughout the codebase: `pipeline.py`'s
  printed "converging=True/False", and now `ccm_batch_test()`) could be
  spuriously True for a pair with no real causal signal. The
  human-readable `verdict` text was never actually misled by this, since
  it already applied a separate 0.2 effect-size floor before saying
  "drives" vs "weak signal" further down in the same function — but
  `is_converging` itself is a field other code reads directly, and without
  a floor there it could mislead. Fixed at the root: `is_converging`'s
  definition in `ccm_causality_test()` now also requires
  `abs(final_rho) > strong_direction_rho` (0.2, the same threshold already
  used for the verdict-text branching) — not just patched in the new
  `ccm_batch_test()`, though that function additionally gates on the same
  effect size before treating a raw p-value as usable input to correction
  at all (forcing it to 1.0 otherwise, so a miscalibrated tiny p-value
  can never "leak through" BH/Bonferroni). This is the third instance of
  the same underlying pattern this project has now found and fixed —
  a statistic that is scale-invariant or large-sample-powerful in a way
  that can mask a near-zero *absolute* effect size (previously: CCM
  `total_rise` vs raw slope in an earlier round; `sensitivity_scan`'s
  coefficient-of-variation near a zero mean, Round 10) — which is worth
  naming explicitly as a recurring class of bug this codebase is prone to,
  not three unrelated coincidences.

### Also fixed (unrelated to the S8-S14 work directly)

- `docs/thresholds_and_heuristics.md` had a leftover formatting defect
  from Round 9's edit: the Kurtosis Forcing Classification table's final
  row (`<= -0.5 | sub-Gaussian (bounded)`) and its explanatory paragraph
  had been orphaned below the *following* section (HAVOK Discrete-Time
  Stability) instead of staying with their own table — the same class of
  str_replace boundary mistake caught and fixed in `secret_adoption_
  audit.md` during Round 10 (a missing "## Summary Table" heading).
  Fixed while adding the new Secret 8-14 threshold sections.

### Changed

- `requirements.txt` / `requirements-lock.txt`: added `statsmodels>=0.14`
  (optional — Secret 8 only). The lock-file entry (0.14.6) is noted as
  provisional: it reflects what was verified working in this round's
  environment, not a fresh `pip freeze` of the original pinned Windows
  reference environment, which this assistant does not have access to.
- `secret_adoption_audit.md`: all seven S8-S14 entries updated from
  ⬜ SPECIFIED to ✅ ADOPTED, with the three bugs above documented inline
  under each relevant secret. Summary table and adoption-rate counts
  updated (13/14 secrets now have working code; Secret 4 remains
  architecturally "partial" by design, not by omission).
- `docs/thresholds_and_heuristics.md`: six new sections (Secrets 8, 9, 10,
  12, 13, 14), each threshold tagged `[C]`/`[D]`/`[E]` per this project's
  existing provenance convention.

## 2026-07-08 — Round 10 (deeper audit of previously-unreviewed modules + 14-rule reference integration)

Continuation of Round 9's independent audit, extended into modules not yet
scrutinized (`_numpy_edm.py`, `router.py`, `sensitivity_config.py`,
`edm_tau_optimization.py`), plus integration of a substantially expanded
rules reference document (7 → 14 rules) provided this round.

### Fixed
- **`_numpy_edm.py` weight/value misalignment (3 sites)**: `simplex_predict()`,
  `SMapPredictNonlinear()`, and `multiview_full()`'s candidate-combo scan
  each computed a distance-based weight vector `w` for k nearest neighbors,
  then dropped neighbors whose future value fell past the end of the series
  (`future_pos >= n`) — but re-aligned the surviving values against `w` via
  a naive prefix slice (`w[:len(future_vals)]`) instead of tracking which
  neighbor index `j` each surviving value came from. Confirmed via direct
  repro on a realistic N=40 series: 5/38 (~13%) of prediction points had a
  *non-trailing* neighbor dropped, silently pairing the wrong weight with
  the wrong value in each case. Two other near-identical prediction loops
  in the same file (`CCM()`'s cross-map step, `Multiview()`'s spatial
  prediction) already used the correct "append weight alongside value,
  inside the same conditional" pattern — this fix brings the other three
  in line with that existing correct pattern. Verified fix: on a clean
  N=1000 synthetic Lorenz series, the fixed `_numpy_edm.Simplex()` now
  matches `pyEDM.Simplex()` to 4 decimal places (rho agreement 0.9981 vs
  0.9981, 0.9987 vs 0.9987, etc.) where the pre-fix version already
  happened to agree closely on this particular clean/large-N case (the bug
  is boundary-driven, so its aggregate effect on rho scales with how many
  prediction points sit near data boundaries relative to N).
- **`router.route_and_execute()` was silently non-functional for nearly
  all real work**: `RouteStep.args` never actually contained a `'data'`
  key (no `RouteStep(...)` call site ever set it — `Router` itself doesn't
  even receive `data`, only `route_and_execute` does), so the check
  `if data is not None and 'data' in step.args` was dead code and always
  False. Every step needing `data` — Tau Optimization, HAVOK Decomposition,
  EDM Embedding, Sensitivity Scan — failed with a raw "missing required
  positional argument" TypeError, silently recorded as a generic `SKIP`
  indistinguishable from an intentional data-insufficiency skip. Only the
  two steps needing zero positional data (Environment Validation,
  Configuration Audit) ever actually ran. This function had **no test
  coverage anywhere** in the codebase before this round — confirmed by
  actually calling it, not by inspection. Fixed via signature-aware
  argument injection (`inspect.signature`): `data` is now passed
  positionally to any step function with exactly one unfulfilled required
  parameter (fixes Tau Optimization and, via new class-instantiation
  handling for dotted `Class.method` paths, HAVOK Decomposition). Steps
  needing genuinely more context than a routing decision can encode
  generically (a DataFrame + column name, a metric callable) now report a
  clear `NOT_AUTO_EXECUTABLE: <reason>` instead of a confusing raw
  TypeError, and point to `pipeline.run_full_analysis()` as the correctly-
  wired full orchestrator. Also fixed the "Save Analysis Config" step's
  result entry, which was permanently stuck at a misleading SKIP/
  NOT_AUTO_EXECUTABLE even though the config genuinely was being saved by
  a separate, correctly-wired call after the loop — the entry now reflects
  the real outcome. Added a new self-test scenario (Scenario G) exercising
  this end-to-end, since none existed.
- **`sensitivity_config.sensitivity_scan()`'s CV-based stability metric
  inverted severity near zero**: coefficient of variation
  (`std/|mean|`) is scale-invariant, which backfires when the neighbor
  values hover near zero — a metric with no real signal at any E (e.g.
  rho = 0.01, -0.02, 0.015) produced `cv ≈ 9` and was classified
  "UNSTABLE — conclusion is parameter-fragile", while a metric with a
  large, scientifically real swing (0.40 to 0.90) produced `cv ≈ 0.31`
  and got the milder "MARGINAL" label — the exact inverse of what a reader
  should be warned about. This is the same class of scale-dependence
  problem the project already fixed once for CCM convergence (switching
  from absolute slope to `total_rise`, Reviewer improvement #2). Fixed the
  same way: when the absolute spread of neighbor values (`neighbor_range`)
  is below a small threshold (0.05, matching the CCM `total_rise`
  threshold), the scan now reports "no signal" rather than "unstable",
  regardless of what CV says. Also fleshed out this function's docstring,
  which had been left as a literal `"""...\n"""` stub.
- **`edm_tau_optimization.py` undocumented magic numbers**: `find_first_
  local_min()`'s 5% "not a trivial fluctuation" confirmation margin, and
  `optimal_tau()`'s `first_min > 1` (reject an AMI local minimum sitting
  exactly at lag 1) and `first_min < max_lag * 0.9` (reject a local
  minimum in the last 10% of the scanned range) guards had zero inline
  explanation and no entry in `docs/thresholds_and_heuristics.md`, unlike
  the project's general practice. Added inline rationale comments; no
  behavior change.

### Added — reference document integration
- **`references/forbidden_rules_reference.md` replaced** (151 lines, 3-4
  rules → 1128 lines, 14 rules) with an externally-provided, substantially
  more rigorous version: every threshold now carries an explicit
  provenance tag (`[C]` canonical/from-paper, `[D]` derived/paper-grounded-
  but-operationalized, `[E]` engineering-judgment), a data-profile-based
  activation matrix (which rules apply at which N, which analysis goal),
  and — notably — the new document's own "current implementation status"
  annotations for Secrets 1-7 accurately reflect this project's actual
  code as of Round 9, including citing this changelog's own Round 9 CCM
  convergence-bypass fix by name. Secrets 8-14 are newly specified
  (Stationarity Gate, Observation Genericity Gate, Seasonality Confound,
  Common Driver Disclaimer, Prediction Decay Profile, Multiple-Comparison
  Correction for CCM, Nonlinear Sampling Adequacy) with full algorithms
  and sourced thresholds, but **no corresponding code exists yet** — see
  `secret_adoption_audit.md`, updated this round with an honest per-secret
  implementation-cost/priority assessment for all seven. None of them were
  implemented this round pending a scope/priority decision — implementing
  all seven is a substantial undertaking (one, S8, needs a new dependency;
  most need new audit functions, new tests, and Router/pipeline wiring),
  materially larger than the bug-fix-sized changes elsewhere in this file.
- `SKILL.md` and `secret_adoption_audit.md` updated from "seven forbidden
  rules" to "fourteen" throughout, with S8-S14 marked with a new ⬜
  SPECIFIED status distinct from ✅/⚠️/🔶/❌ (fully specified with sourced
  algorithms, but genuinely no code yet — distinct from a partial or
  deferred implementation).

### Known gap
- The new reference document cites all sources via `[B##]` tags pointing
  to `references/fourteen_rules_bibliography.md` (claimed: 39 papers,
  indexed by rule). That bibliography file was not provided alongside the
  rules document this round and does not exist in the package — the
  `[B##]` tags are currently dangling. Each rule entry also carries inline
  author/year/journal citations, so this doesn't block using the document,
  but the promised catalog file itself is still missing.

## 2026-07-08 — Round 9 (independent audit + fix)

This round was an independent re-audit that did not start from the prior
audit's findings list — every issue below was found by actually executing
the code (running each module's own `__main__` self-test, and in several
cases writing additional targeted repros) rather than by re-reading the
prior audit reports. Two of the four bugs below were self-tests that were
already present in the codebase and already failing/borderline before this
round; they had simply never been run by `run_tests.py` (see the Layer 7
entry below).

### Fixed
- **`edm_auditor.audit_tau_selection()`**: the FAIL-vs-WARN status was
  decided by searching the rendered issue text for the literal substring
  `"0.5"` (`any("0.5" in i for i in issues)`). The `>0.5`-window-fraction
  branch's message renders the *actual* percentage (e.g. `"75%"`), which
  never contains `"0.5"`, so this path could never reach FAIL — it always
  silently downgraded to WARN. The module's own self-test asserted FAIL
  and failed with "got WARN" (confirmed by running `python
  src/edm_auditor.py` directly). Replaced with an explicit boolean flag.
- **`surrogate_test.iaaft_surrogates()`**: no end-point matching was
  applied before the FFT-based phase randomization step. Real (non-cyclic)
  time series almost never start and end at the same value; the FFT's
  implicit periodicity assumption sees this as a discontinuity, and phase
  randomization smears it into spurious broadband high-frequency energy.
  On a 1000-point Lorenz-x segment (endpoint jump = 57% of the data range)
  this pushed some surrogates' HAVOK-kurtosis to 3-5x the real value (max
  observed 16.5 vs a real value of 3.4), masking the genuine chaotic
  signal. Fixed via end-point matching (Theiler & Prichard, 1996): subtract
  the linear ramp connecting the first/last sample before the FFT step,
  run IAAFT on the detrended series, add the ramp back after. Also fixed
  `surrogate_significance_test()`'s significance boundary from strict `<
  0.05` to `<= 0.05` (the standard convention for exact rank-based
  p-values, where the achievable values are `{1/(n+1), ..., 1}` — at
  `n_surrogates=19` the minimum achievable p is exactly `0.05`, which a
  strict `<` can never satisfy no matter how extreme the real value is),
  and bumped the module's own Lorenz self-test from 19 to 99 surrogates so
  the assertion has real headroom instead of sitting exactly on the
  boundary.
- **CCM verdict duplication / convergence-bypass** (the most consequential
  fix this round, spanning 4 files): `final_interpretation.
  ccm_with_convergence()` and `enhanced_cross_validate.
  verify_ccm_direction()` were two independently maintained
  implementations of the same CCM causal test. They agreed on the
  direction convention but disagreed on two things: (a)
  `ccm_with_convergence` required the cross-map skill to demonstrably
  converge (total_rise > 0.05, Spearman rho > 0.7, Spearman p < 0.1)
  before declaring a verdict; `verify_ccm_direction` had no convergence
  check at all, only the skill at the largest library size; (b) the two
  used different, hardcoded library-size sweeps (`'5 {n-2} 3'` vs
  `'5 25 5'`), so "final rho" implicitly meant a different library size in
  each. Worse, `pipeline.py`'s post-computation audit feedback used a
  *third*, forward-only CCM call (`'5 {n-2} 5'`) and fed only the bare
  final-rho values into `edm_auditor.audit_pipeline()`, never populating
  `ccm_forward_total_rise` / `ccm_forward_spearman_rho`. Since
  `audit_ccm_direction()` treats missing convergence data as "assume
  converged" by default, this silently disabled the exact protection the
  auditor's own docstring claims to provide — a high-but-non-converging
  (spurious) rho could sail through the firewall with a clean PASS. Fixed
  by extracting a single canonical implementation into the new
  `src/ccm_causality.py` (`ccm_causality_test()`), with a data-length-
  scaled default library-size sweep; `ccm_with_convergence()` and
  `verify_ccm_direction()` are now thin wrappers around it, and
  `pipeline.py`'s audit feedback now computes and forwards the
  convergence metrics. **Confirmed working end-to-end**: re-running
  `python src/pipeline.py` on the sample game data now produces `[!!]
  Secret 2: CCM Victim Mirror: ... Reverse rho high (rev=0.558) but NOT
  converging. Possible false positive` — a warning that was silently
  swallowed before this fix.
- **`sovereign_havok.fit()` / `_auto_truncate()`**: when the normalized
  Hankel matrix has ~zero total singular-value energy (e.g. the input
  degenerates to an exactly-constant series), `explained_var_` computed
  as `0/0 = NaN` and propagated silently into downstream reports/audits,
  defeating numeric comparisons like `explained_var_ > 0.7` without any
  visible explanation. Now reports an explicit `0.0` in this case instead
  (the pre-existing near-constant-input warning already flags the data as
  untrustworthy; this just keeps the failure loud instead of silent, per
  the same philosophy as the existing P2 input-validation guard).
- **`verify_algorithms._test_logistic()`**: the chaotic (r=4.0) branch used
  initial condition `x0=0.5`, which is the logistic map's exact critical
  point at r=4: `x1 = 4*0.5*0.5 = 1.0`, then `x2 = 4*1*(1-1) = 0.0`
  exactly, and every iterate after that is `0` forever. In exact real
  arithmetic almost no other starting point ever lands exactly on 0, but
  `0.5` and `1.0` are both exactly representable in binary floating point,
  so this measure-zero degenerate orbit was hit deterministically. The
  resulting series was constant, not chaotic, and `explained_var_` came
  out as NaN (before the guard above existed), making this "chaotic" test
  case fail every check for a reason that had nothing to do with EDM/HAVOK
  correctness. Fixed by using `x0=0.2`, the standard textbook starting
  value for exactly this reason.

### Added
- `src/ccm_causality.py`: canonical convergence-aware CCM test, single
  source of truth for `final_interpretation.py` and
  `enhanced_cross_validate.py` (see "Fixed" above). Includes its own
  self-test that verifies both wrappers still delegate to it (via source
  inspection, since pyEDM's CCM bootstrap sampling uses its own internal
  RNG and isn't reproducible via `np.random.seed` — confirmed empirically
  — so exact-value comparison across independent calls isn't a meaningful
  test).
- `sovereign_havok.classify_havok_stability()`: shared HAVOK
  divergent/dissipative/near-critical classifier (1.05/0.90 thresholds).
  `diagnose()`, `pipeline.py`, and `enhanced_cross_validate.py` had each
  independently re-implemented the same thresholds; the three copies
  happened to agree, but nothing enforced that. Consolidated the same way
  `classify_hankel_ratio` was in an earlier round.
- `run_tests.py` **Layer 7 (Module Self-Tests)**: runs every module's own
  `if __name__ == '__main__':` self-test as a subprocess and checks its
  exit code. Before this layer existed, `run_tests.py` never invoked any
  of them — it only re-implemented separate checks in Layers 1-6. That gap
  is precisely why the tau-selection and Lorenz-surrogate bugs above
  survived: both modules "passed their own self-tests" was never actually
  checked by the test runner.

### Changed
- `enhanced_cross_validate.verify_ccm_direction()`'s default `lib_sizes`
  changed from the fixed `'5 25 5'` to `None` (defers to
  `ccm_causality_test`'s data-length-scaled default `'5 {n-2} 3'`). This
  is a deliberate behavior change, not just a refactor: for datasets with
  `n > ~27`, the two ranges previously covered a different maximum library
  size, so reported rho values will shift slightly (typically closer to
  the true asymptotic cross-map skill, since the sweep now reaches nearer
  the full library). Pass an explicit `lib_sizes=` string to reproduce the
  old fixed-range behavior if needed.
- `sovereign_havok.K_d_` (the first-order Euler discrete-operator
  approximation, superseded by the exact `F_ = expm(A*dt)` in an earlier
  round): left in place for backward compatibility but now carries an
  explicit docstring comment marking it legacy/diagnostic-only, since
  nothing in the codebase reads it anymore and a future contributor could
  otherwise mistake it for the operator actually used in prediction.

## 2026-07-07 — Round 6-8 (audit + fix + optimization)

### Fixed
- `final_interpretation.interpret_game_data()`: resolved `NameError` (pyEDM
  used but never imported) by routing through `_edm_bridge`. The main
  interpretation entry was previously non-functional and untested.
- `verify_algorithms.InternalConsistencyTests.max_score`: 16 -> 20 (sub-check
  maxima sum to 8+4+4+4=20; previously displayed 20/16).
- `multiview_svd_monitor.run_multiview_analysis`: now routes through
  `_edm_bridge.Multiview`, so the numpy SVD fallback is reachable when pyEDM
  is unavailable (previously returned `{"error": ...}`).
- `pipeline.py`: added post-computation audit feedback (HAVOK kurtosis +
  CCM fwd/rev) so Secrets 2 & 6 are actually enforceable after computation.
- `router.route_and_execute`: resolves dotted function names like
  `SovereignHAVOK.fit` instead of crashing; unresolvable steps SKIP.
- `edm_adaptive_pipeline.py`: removed duplicate imports; routed through bridge.
- `edm_tau_optimization.py`: moved top-level `import pyEDM` into `__main__`.
- `enhanced_cross_validate.py`: routed all pyEDM calls through bridge.
- `tests/test_havok.py`: guarded `import pyEDM`; EmbedDim test SKIPs if absent.
- `final_interpretation._plot_interpretation`: ensured `results/` directory
  exists before `savefig` (FileNotFoundError on fresh checkouts).

### Added (optimization potentials P1-P12)
- `interpret_data()` (P1): domain-agnostic interpretation core; game-specific
  narration remains in `interpret_game_data()` wrapper.
- `SovereignHAVOK.fit` input validation (P2): rejects NaN/Inf, warns on
  near-constant data.
- `tests/test_sovereign_havok.py` (P3): 7-test suite for the SovereignHAVOK
  class (fit, V/U basis, predict, SG cap, NaN rejection, constant warning,
  eigenvalue stability).
- `run_tests.py` Layer 6 (P4): end-to-end interpretation test (slow, skipped
  in `--quick`).
- `pipeline.run_full_analysis()` (P5): chains pipeline -> cross-validation ->
  interpretation in one call.
- `AnalysisConfig.audit_verdict` / `audit_findings_summary` (P6): config
  artifact now records the firewall verdict for full provenance.
- `_numpy_edm.multiview_full()` (P7): full Sugihara-2016 combinatorial
  candidate scan, exposed via `_edm_bridge`.
- `_numpy_edm.false_nearest_neighbors()` (P8): Kennel-1992 FNN E-selection,
  exposed via `_edm_bridge` as a complementary second opinion to Simplex rho.
- `requirements-lock.txt` (P12): pinned manifest; `requirements.txt` now
  lower-bound for portability.
- `docs/` subfolder (P9/P10/P11): engineering attachments (this CHANGELOG,
  threshold documentation, audit/optimization reports).

### Removed
- `src/edm_havok_integration.py`: deprecated, unreferenced, hard-dependent on
  pyEDM. Superseded by `sovereign_havok.py` + `edm_adaptive_pipeline.py`.

### Changed
- `SKILL.md`: module count 19 -> 17 (after removing deprecated module);
  "FNN cross-check" claim corrected to "future" (now implemented as P8).
- `secret_adoption_audit.md`: Secret 4 status unified to PARTIAL (was
  ADOPTED in summary table but PARTIAL in body); stale 82/100 -> 80/100.

## 2026-07-07 — Round 1-5 (prior audits)

Historical audit records for these rounds were consolidated into
`docs/ALGORITHM_AUDIT.md` (2026-07-13). The standalone historical audit files
were removed to avoid stale test counts; refer to `ALGORITHM_AUDIT.md` for the
latest audit conclusions and to this CHANGELOG for per-round implementation
details.
