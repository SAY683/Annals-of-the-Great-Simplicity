# EDM-Takens Skill — CHANGELOG

All notable changes to the edm-takens skill. Dates are ISO-8601.
This file is a maintainable engineering attachment (P11).

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

See `docs/edm-takens_self_inspection_census.md` and
`docs/edm-takens_skill_audit.md` for the full audit trail.
