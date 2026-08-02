"""
EDM Pipeline Auditor — The Firewall Layer
==========================================
Pre-execution validation for ALL EDM + HAVOK pipeline steps.
Called before any computation to prevent invalid configurations
from propagating and producing garbage results.

Each forbidden rule (Secrets 1-10) is enforced by a dedicated
audit function with clear PASS/WARN/FAIL verdicts.

Usage:
    from edm_auditor import Auditor
    auditor = Auditor(data=my_data, config=my_config)
    report = auditor.run_full_audit()
    report.print_report()
    if report.verdict == 'FAIL':
        raise SystemExit("Configuration invalid — see report above")
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import warnings

# P2-1 修复: 统一硬编码 eps 为单一真相源常量
from _numeric_constants import EPS_DISTANCE, EPS_PROB


def _one_nn_cross_pred_rho(source: np.ndarray, target: np.ndarray,
                            E: int = 3, tau: int = 1) -> Optional[float]:
    """
    Minimal 1-nearest-neighbor delay-embedding cross-prediction skill,
    used only by Secret 8's Schreiber (1997) non-stationarity check:
    embed `target` in delay-coordinates, for each embedded point find its
    nearest neighbor in `source`'s embedding, predict one step ahead using
    that neighbor's continuation, and correlate against the true
    continuation. When source is target, this is a (weak) self-prediction
    skill; when source and target are different segments of the same
    series, the ratio of cross- to self-skill is Schreiber's
    non-stationarity diagnostic (see audit_stationarity).

    This is intentionally NOT a call into `_numpy_edm.simplex_predict` —
    it needs one series to build the library and a *different* series to
    query, which `simplex_predict`'s single-series lib/pred-range API
    doesn't directly support. Kept deliberately minimal (1-NN, not the
    full E+1-neighbor simplex) since this is a lightweight stationarity
    diagnostic, not a general-purpose prediction engine — reusing the
    real EDM engines here would be a heavier and less transparent
    dependency for a single-purpose sanity check.
    """
    from scipy.spatial import KDTree
    from scipy.stats import pearsonr

    def embed(s):
        m = len(s) - (E - 1) * tau
        if m < 2:
            return None, None
        X = np.array([s[i:i + (E - 1) * tau + 1:tau] for i in range(m)])
        return X, m

    Xs, ms = embed(source)
    Xt, mt = embed(target)
    if Xs is None or Xt is None or ms < E + 2 or mt < 2:
        return None

    # Library: source embedded vectors with a valid 1-step future value
    lib_X = Xs[:-1]
    lib_future = source[(E - 1) * tau + 1:(E - 1) * tau + 1 + len(lib_X)]
    if len(lib_X) < E + 1:
        return None
    tree = KDTree(lib_X)

    # When source and target overlap (the "self-prediction" baseline case:
    # source is target), each query point is ALSO in the library, and
    # k=1 nearest-neighbor search trivially matches every point to
    # itself (distance 0), producing a spuriously perfect rho that
    # reflects nothing about actual predictive skill — confirmed via
    # this module's self-test: white noise produced rho_self=1.0 before
    # this fix, purely from self-matching, not genuine structure. Query
    # k=2 and skip a zero-distance match, mirroring the same "exclude
    # self" pattern already used in _numpy_edm.py's simplex_predict
    # (`good = dists > 1e-15`) — single source of truth for this
    # exclusion idea, reapplied here since this helper deliberately does
    # NOT call into _numpy_edm (see docstring).
    same_source = source is target or (
        len(source) == len(target) and np.array_equal(source, target))
    k = 2 if same_source else 1

    preds, obs = [], []
    query_X = Xt[:-1]
    future_pos_base = (E - 1) * tau + 1
    for i in range(len(query_X)):
        future_idx = future_pos_base + i
        if future_idx >= len(target):
            break
        dist, idx = tree.query(query_X[i], k=k)
        if k == 2:
            dist = np.atleast_1d(dist); idx = np.atleast_1d(idx)
            nonself = dist > EPS_DISTANCE
            if nonself.any():
                idx = idx[nonself][0]
            else:
                idx = idx[-1]  # all matched (degenerate); fall back
        preds.append(lib_future[idx])
        obs.append(target[future_idx])

    if len(preds) < 5:
        return None
    obs = np.asarray(obs)
    preds = np.asarray(preds)
    if np.std(obs) < EPS_DISTANCE or np.std(preds) < EPS_DISTANCE:
        return None
    return float(pearsonr(obs, preds)[0])


@dataclass
class AuditFinding:
    """Single audit check result.

    severity field (debt-18): orthogonal to status, drives the new 5-tier
    verdict cascade in AuditReport.finalize(). Default MINOR; clean PASS
    findings (no recommendation) are auto-downgraded to INFO in
    __post_init__ so a fully clean audit yields verdict=PASS, not
    PASS_WITH_NOTES.
    """
    check_name: str
    secret_ref: str         # e.g., "Secret 1: Lyapunov Horizon"
    status: str             # "PASS", "WARN", "FAIL", "SKIP"
    message: str
    recommendation: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = "MINOR"  # INFO / MINOR / MAJOR / CRITICAL (default MINOR)

    def __post_init__(self):
        # Clean PASS findings (no recommendation) are auto-downgraded to
        # INFO severity so they do not trigger PASS_WITH_NOTES in finalize().
        # PASS findings WITH a recommendation stay at MINOR (the default),
        # correctly surfacing as advisory notes in the verdict cascade.
        # Explicitly-provided severities (CRITICAL/MAJOR/INFO) are preserved
        # — the guard `self.severity == "MINOR"` only rewrites the default.
        if (self.status == "PASS" and not self.recommendation
                and self.severity == "MINOR"):
            self.severity = "INFO"


@dataclass
class AuditReport:
    """Complete audit report with all findings.

    verdict tiers (debt-18): PASS / PASS_WITH_NOTES / WARN / FAIL / BLOCKED,
    plus INCONCLUSIVE when >50% of checks were SKIPped. Legacy string values
    'PASS'/'WARN'/'FAIL' remain valid verdicts and are still comparable
    (e.g. ``report.verdict == 'FAIL'``), preserving backward compatibility.
    """
    findings: List[AuditFinding] = field(default_factory=list)
    verdict: str = "PASS"        # PASS, PASS_WITH_NOTES, WARN, FAIL, BLOCKED, INCONCLUSIVE
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    skipped: int = 0

    def add(self, finding: AuditFinding):
        self.findings.append(finding)
        self.total_checks += 1
        if finding.status == "PASS":
            self.passed += 1
        elif finding.status == "WARN":
            self.warnings += 1
        elif finding.status == "FAIL":
            self.failures += 1
        elif finding.status == "SKIP":
            self.skipped += 1

    def finalize(self):
        # 5-tier + INCONCLUSIVE verdict cascade (debt-18):
        #   CRITICAL severity → BLOCKED      (hard stop, must not proceed)
        #   FAIL status       → FAIL         (hard stop, cannot auto-correct)
        #   WARN status       → WARN         (advisory, proceed with caution)
        #   >50% skipped      → INCONCLUSIVE (insufficient evidence to decide)
        #   MINOR severity    → PASS_WITH_NOTES (advisory notes, OK to proceed)
        #   otherwise         → PASS         (clean, all INFO-severity passes)
        #
        # Legacy 'PASS'/'WARN'/'FAIL' string values are preserved as valid
        # verdicts — existing callers comparing ``verdict == 'FAIL'`` etc.
        # keep working. 'BLOCKED', 'PASS_WITH_NOTES', 'INCONCLUSIVE' are new.
        has_critical = any(f.severity == "CRITICAL" for f in self.findings)
        has_minor = any(f.severity == "MINOR" for f in self.findings)
        if has_critical:
            self.verdict = "BLOCKED"
        elif self.failures > 0:
            self.verdict = "FAIL"
        elif self.warnings > 0:
            self.verdict = "WARN"
        elif (self.total_checks > 0
              and self.skipped / self.total_checks > 0.5):
            self.verdict = "INCONCLUSIVE"
        elif has_minor:
            self.verdict = "PASS_WITH_NOTES"
        else:
            self.verdict = "PASS"

    def print_report(self):
        icon = {"PASS": "[OK]", "WARN": "[!!]", "FAIL": "[XX]", "SKIP": "[--]"}
        print("\n" + "=" * 70)
        print(f"  PIPELINE AUDIT REPORT — Verdict: {self.verdict}")
        print("=" * 70)
        for f in self.findings:
            print(f"  {icon[f.status]} {f.secret_ref}: {f.check_name}")
            print(f"      {f.message}")
            if f.recommendation:
                print(f"      => {f.recommendation}")
        print(f"\n  Summary: {self.passed} passed, {self.warnings} warnings, "
              f"{self.failures} failures, {self.skipped} skipped")
        print("=" * 70)


class Auditor:
    """
    Pre-execution auditor for EDM + HAVOK pipelines.

    Validates configuration before computation to prevent:
    - Lyapunov horizon violations (predicting beyond physical limit)
    - CCM direction errors (testing wrong causal direction)
    - Hankel aspect ratio degradation (unstable SVD)
    - Missing Multiview opportunity (short multivariable data)
    - SVD residual instability (attractor deformation)
    - EDM-HAVOK cross-validation mismatch
    """

    def __init__(self, data: np.ndarray = None, df=None,
                 n: int = None, q: int = None, E: int = None,
                 tau: int = None, lib: str = None, pred: str = None,
                 target_col: str = None, columns: List[str] = None,
                 pred_horizon: int = None, is_binary: bool = False,
                 lyap_lambda: float = None, havok_r: int = None,
                 p_steps: int = None,
                 ccm_forward_rho: float = None,
                 ccm_forward_total_rise: float = None,
                 ccm_forward_spearman_rho: float = None,
                 ccm_forward_spearman_p: float = None,
                 ccm_reverse_rho: float = None,
                 ccm_reverse_total_rise: float = None,
                 ccm_reverse_spearman_rho: float = None,
                 ccm_reverse_spearman_p: float = None,
                 svd_residual: float = None,
                 svd_baseline: float = None,
                 edm_nonlinear: bool = None,
                 havok_kurtosis: float = None):
        """
        Parameters can be passed individually or derived from existing analysis.

        CCM convergence parameters (Secret 2/7 upgrade):
          ccm_forward_total_rise: total rise in rho across library sizes
          ccm_forward_spearman_rho: Spearman rank correlation (monotonicity)
          ccm_forward_spearman_p: Spearman p-value (monotonicity significance)
          (same for reverse)
        """
        self.data = data
        self.df = df
        self.n = n or (len(data) if data is not None else None)
        self.q = q or E  # q (HAVOK) and E (EDM) are the same embedding dimension
        self.E = E or q
        self.tau = tau
        self.lib = lib
        self.pred = pred
        self.target_col = target_col
        self.columns = columns or []
        self.pred_horizon = pred_horizon
        self.is_binary = is_binary
        self.lyap_lambda = lyap_lambda
        self.havok_r = havok_r
        self.p_steps = p_steps or (self.n - self.q + 1 if self.n and self.q else None)
        self.p = self.p_steps
        self.ccm_forward_rho = ccm_forward_rho
        self.ccm_forward_total_rise = ccm_forward_total_rise
        self.ccm_forward_spearman_rho = ccm_forward_spearman_rho
        self.ccm_forward_spearman_p = ccm_forward_spearman_p
        self.ccm_reverse_rho = ccm_reverse_rho
        self.ccm_reverse_total_rise = ccm_reverse_total_rise
        self.ccm_reverse_spearman_rho = ccm_reverse_spearman_rho
        self.ccm_reverse_spearman_p = ccm_reverse_spearman_p
        self.svd_residual = svd_residual
        self.svd_baseline = svd_baseline
        self.edm_nonlinear = edm_nonlinear
        self.havok_kurtosis = havok_kurtosis

    # ── Secret 1: Lyapunov Horizon ──────────────────────────

    def audit_lyapunov_horizon(self) -> AuditFinding:
        """Check prediction horizon against Lyapunov time."""
        if self.lyap_lambda is None or self.pred_horizon is None:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "SKIP", "Missing lambda_max or prediction horizon",
            )
        if self.lyap_lambda <= 0:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "SKIP", "lambda_max <= 0 (non-chaotic or estimation failed)",
            )

        tau_L = 1.0 / self.lyap_lambda
        pred_max = 5 * tau_L

        if self.pred_horizon <= tau_L:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "PASS",
                f"Prediction horizon ({self.pred_horizon}) <= tau_L ({tau_L:.1f}). Safe.",
                details={"tau_L": tau_L, "pred_horizon": self.pred_horizon}
            )
        elif self.pred_horizon <= 3 * tau_L:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "WARN",
                f"Prediction horizon ({self.pred_horizon}) in [tau_L, 3*tau_L] "
                f"({tau_L:.1f}, {3*tau_L:.1f}). Errors grow exponentially.",
                f"Use with caution. Errors expand by factor e^({self.pred_horizon/tau_L:.1f}).",
                details={"tau_L": tau_L, "pred_horizon": self.pred_horizon}
            )
        elif self.pred_horizon <= 5 * tau_L:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "WARN",
                f"Prediction horizon ({self.pred_horizon}) in [3*tau_L, 5*tau_L] "
                f"({3*tau_L:.1f}, {5*tau_L:.1f}). Near physical limit.",
                "Predictions beyond 3*tau_L are increasingly unreliable.",
                details={"tau_L": tau_L, "pred_horizon": self.pred_horizon}
            )
        else:
            return AuditFinding(
                "Lyapunov Horizon Check", "Secret 1: Lyapunov Horizon",
                "FAIL",
                f"Prediction horizon ({self.pred_horizon}) > 5*tau_L "
                f"({5*tau_L:.1f}). BEYOND PHYSICAL LIMIT!",
                f"Reduce prediction horizon to <= {int(5*tau_L)}. "
                f"Predicting beyond this is scientifically meaningless.",
                details={"tau_L": tau_L, "pred_horizon": self.pred_horizon},
                severity="CRITICAL"
            )

    # ── Secret 2: CCM Victim Mirror + Arrow Trap ────────────

    def audit_ccm_direction(self) -> AuditFinding:
        """Verify CCM causal direction follows Victim Mirror Principle.

        Uses BOTH static final rho AND convergence metrics (total rise,
        Spearman rank correlation) — MUST agree with ccm_with_convergence()
        in final_interpretation.py. The convergence check prevents false
        positives where rho is high but never actually converges with
        increasing library size.
        """
        if self.ccm_forward_rho is None or self.ccm_reverse_rho is None:
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "SKIP", "Missing CCM cross-map values",
            )

        fwd = self.ccm_forward_rho
        rev = self.ccm_reverse_rho
        delta = fwd - rev

        # Convergence checks (only if convergence metrics provided).
        # These thresholds MUST match the canonical ccm_causality_test()
        # defaults (rise > 0.05, spearman_rho > 0.7, spearman_p < 0.1,
        # abs(final_rho) > 0.2). Using only total_rise + spearman_rho here
        # left a gap: a non-converging or near-zero-rho direction could
        # still be treated as "converged" by the firewall. See
        # docs/ALGORITHM_AUDIT.md and docs/CHANGELOG.md (Round 11/13).
        # 默认值改为 None：缺失收敛数据时不再静默假定收敛通过，
        # 而是在下方高 rho 分支降级为 WARN（convergence undetermined）。
        fwd_converges = None
        rev_converges = None
        if (self.ccm_forward_total_rise is not None
                and self.ccm_forward_spearman_rho is not None):
            fwd_converges = (self.ccm_forward_total_rise > 0.05
                          and self.ccm_forward_spearman_rho > 0.7)
            if self.ccm_forward_spearman_p is not None:
                fwd_converges = fwd_converges and self.ccm_forward_spearman_p < 0.1
            if self.ccm_forward_rho is not None:
                fwd_converges = fwd_converges and abs(self.ccm_forward_rho) > 0.2
        if (self.ccm_reverse_total_rise is not None
                and self.ccm_reverse_spearman_rho is not None):
            rev_converges = (self.ccm_reverse_total_rise > 0.05
                          and self.ccm_reverse_spearman_rho > 0.7)
            if self.ccm_reverse_spearman_p is not None:
                rev_converges = rev_converges and self.ccm_reverse_spearman_p < 0.1
            if self.ccm_reverse_rho is not None:
                rev_converges = rev_converges and abs(self.ccm_reverse_rho) > 0.2

        if fwd < 0.15 and rev < 0.15:
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "WARN",
                f"No detectable causal link (fwd={fwd:.3f}, rev={rev:.3f})",
                "Both cross-map skills are near zero. No causation detectable.",
                details={"forward": fwd, "reverse": rev}
            )
        elif fwd > 0.3 and rev > 0.3 and abs(delta) <= 0.1:
            # P0-2: bidirectional causation — both directions show high rho
            # with small delta. This is a distinct diagnostic signal
            # (genuine bidirectional causation, or strong common driver)
            # that was previously lumped into the catch-all else branch.
            fwd_ok = fwd_converges is None or fwd_converges
            rev_ok = rev_converges is None or rev_converges
            if fwd_converges and rev_converges and fwd_ok and rev_ok:
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Bidirectional: both forward (fwd={fwd:.3f}) and reverse "
                    f"(rev={rev:.3f}) show high, converging CCM skill "
                    f"(delta={delta:+.3f}). This suggests either genuine "
                    f"bidirectional causation or a strong common driver "
                    f"(see Secret 11).",
                    "Check for common external driver (Secret 10/11). "
                    "If bidirectional is genuine, both directions are real.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "fwd_converges": fwd_converges, "rev_converges": rev_converges}
                )
            else:
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Bidirectional signal (fwd={fwd:.3f}, rev={rev:.3f}, "
                    f"delta={delta:+.3f}) but convergence evidence is "
                    f"incomplete.",
                    "Run CCM with full library size sweep for both directions.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "fwd_converges": fwd_converges, "rev_converges": rev_converges}
                )
        elif fwd > 0.3 and delta > 0.1:
            if fwd_converges is None:
                # 缺失收敛数据：不再静默假定收敛通过，降级为 WARN。
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Forward rho high (fwd={fwd:.3f}) but convergence "
                    f"undetermined (no convergence metrics provided).",
                    "Run CCM with full library size sweep to confirm "
                    "convergence — high rho without convergence evidence "
                    "may be spurious.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "fwd_converges": fwd_converges}
                )
            if not fwd_converges:
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Forward rho high (fwd={fwd:.3f}) but NOT converging. "
                    f"Possible false positive — rho may be spurious.",
                    "Run CCM with full library size sweep. "
                    "High rho without convergence is suspicious.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "fwd_converges": fwd_converges}
                )
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "PASS",
                f"Forward convergent (fwd={fwd:.3f} > rev={rev:.3f}, "
                f"delta={delta:+.3f}). Causal direction confirmed.",
                details={"forward": fwd, "reverse": rev, "delta": delta,
                         "fwd_converges": fwd_converges}
            )
        elif rev > 0.3 and delta < -0.1:
            if rev_converges is None:
                # 缺失收敛数据：不再静默假定收敛通过，降级为 WARN。
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Reverse rho high (rev={rev:.3f}) but convergence "
                    f"undetermined (no convergence metrics provided).",
                    "Run CCM with full library size sweep to confirm "
                    "convergence — high rho without convergence evidence "
                    "may be spurious.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "rev_converges": rev_converges}
                )
            if not rev_converges:
                return AuditFinding(
                    "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                    "WARN",
                    f"Reverse rho high (rev={rev:.3f}) but NOT converging. "
                    f"Possible false positive.",
                    "Run CCM with full library size sweep.",
                    details={"forward": fwd, "reverse": rev, "delta": delta,
                             "rev_converges": rev_converges}
                )
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "PASS",
                f"Reverse convergent (rev={rev:.3f} > fwd={fwd:.3f}, "
                f"delta={delta:+.3f}). Causal direction confirmed (reverse).",
                details={"forward": fwd, "reverse": rev, "delta": delta,
                         "rev_converges": rev_converges}
            )
        else:
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "WARN",
                f"Ambiguous direction (fwd={fwd:.3f}, rev={rev:.3f}, "
                f"delta={delta:+.3f})",
                "Explicitly verify both directions. May be bidirectional or spurious.",
                details={"forward": fwd, "reverse": rev, "delta": delta}
            )

    # ── Secret 3: Hankel Golden Aspect Ratio ────────────────

    def audit_hankel_aspect_ratio(self) -> AuditFinding:
        """Check HAVOK Hankel matrix p/q ratio for SVD stability.

        Delegates to shared classify_hankel_ratio() for tier thresholds.
        """
        if self.q is None or self.n is None:
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "SKIP", "Missing q or n",
            )

        status, ratio, p, q_recommended = classify_hankel_ratio(self.n, self.q)

        if status == 'GOOD':
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "PASS",
                f"p/q = {ratio:.1f} >= 10. SVD numerically stable.",
                details={"p": p, "q": self.q, "ratio": ratio}
            )
        elif status == 'MARGINAL':
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "WARN",
                f"p/q = {ratio:.1f} in [5, 10). Marginal SVD quality.",
                f"Reduce q to <= {q_recommended} for p/q >= 10. "
                f"Current q={self.q} may cause mild numerical stiffness.",
                details={"p": p, "q": self.q, "ratio": ratio, "q_recommended": q_recommended}
            )
        elif status == 'DEGRADED':
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "FAIL",
                f"p/q = {ratio:.1f} < 5. SVD significantly degraded!",
                f"CRITICAL: reduce q to <= {q_recommended}. "
                f"A-matrix eigenvalues will have spurious rigidity.",
                details={"p": p, "q": self.q, "ratio": ratio, "q_recommended": q_recommended},
                severity="MAJOR"
            )
        else:  # BROKEN
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "FAIL",
                f"p/q = {ratio:.1f} < 3. SVD is NUMERICALLY BROKEN!",
                f"STOP. Reduce q to <= {q_recommended} immediately. "
                f"Results with this configuration are garbage.",
                details={"p": p, "q": self.q, "ratio": ratio, "q_recommended": q_recommended},
                severity="CRITICAL"
            )

    # ── Secret 4: Multiview Embedding ───────────────────────

    def audit_multiview(self) -> AuditFinding:
        """Check if Multiview embedding should be used instead of delay embedding."""
        if self.n is None or self.columns is None:
            return AuditFinding(
                "Multiview Feasibility Check", "Secret 4: Multiview Embedding",
                "SKIP", "Missing n or column list",
            )

        n_cols = len(self.columns)
        if n_cols < 2:
            return AuditFinding(
                "Multiview Feasibility Check", "Secret 4: Multiview Embedding",
                "SKIP", "Only 1 variable — Multiview not applicable",
            )

        if self.n < 100 and n_cols >= 2:
            return AuditFinding(
                "Multiview Feasibility Check", "Secret 4: Multiview Embedding",
                "PASS",
                f"N={self.n} < 100 with {n_cols} variables. "
                f"Multiview strongly recommended!",
                f"Use pyEDM.Multiview(columns={self.columns}) "
                f"instead of single-variable delay embedding. "
                f"Saves {self.q or 'E'}*{self.n} data-efficiency loss.",
                details={"n": self.n, "n_cols": n_cols,
                        "recommended": "Multiview over Simplex"}
            )
        elif self.n < 50 and n_cols >= 3:
            return AuditFinding(
                "Multiview Feasibility Check", "Secret 4: Multiview Embedding",
                "PASS",
                f"CRITICAL: N={self.n} < 50 with {n_cols} variables. "
                f"Delay embedding will starve!",
                f"Multiview is the ONLY viable approach. "
                f"Use pyEDM.Multiview() immediately.",
                details={"n": self.n, "n_cols": n_cols}
            )
        else:
            return AuditFinding(
                "Multiview Feasibility Check", "Secret 4: Multiview Embedding",
                "PASS",
                f"N={self.n} >= 100. Delay embedding is viable. "
                f"Multiview still worth trying for comparison.",
                details={"n": self.n, "n_cols": n_cols}
            )

    # ── Secret 5: SVD Reconstruction Residual ──────────────

    def audit_svd_residual(self) -> AuditFinding:
        """Monitor SVD reconstruction residual for attractor deformation."""
        if self.svd_residual is None:
            return AuditFinding(
                "SVD Residual Check", "Secret 5: SVD Residual Monitor",
                "SKIP", "No residual data provided",
            )

        baseline = self.svd_baseline or 0.0
        ratio = self.svd_residual / (baseline + EPS_PROB)

        if ratio < 1.5:
            return AuditFinding(
                "SVD Residual Check", "Secret 5: SVD Residual Monitor",
                "PASS",
                f"Residual ratio = {ratio:.2f}x baseline. Stable.",
                details={"residual": self.svd_residual, "baseline": baseline,
                        "ratio": ratio}
            )
        elif ratio < 2.5:
            return AuditFinding(
                "SVD Residual Check", "Secret 5: SVD Residual Monitor",
                "WARN",
                f"Residual ratio = {ratio:.2f}x baseline. Elevated.",
                "Monitor closely. If sustained for 3+ windows, consider "
                "adaptive memory fracture (drop oldest 50% of Hankel data).",
                details={"residual": self.svd_residual, "baseline": baseline,
                        "ratio": ratio}
            )
        else:
            return AuditFinding(
                "SVD Residual Check", "Secret 5: SVD Residual Monitor",
                "FAIL",
                f"Residual ratio = {ratio:.2f}x baseline! "
                f"Attractor deformation detected!",
                "TRIGGER adaptive memory fracture: drop oldest 50% of Hankel "
                "matrix rows, re-fit SVD on remaining data. The old U/V basis "
                "can no longer span the current dynamics.",
                details={"residual": self.svd_residual, "baseline": baseline,
                        "ratio": ratio},
                severity="MAJOR"
            )

    # ── Secret 6: EDM-HAVOK Cross-Validation ────────────────

    def audit_cross_validation(self) -> AuditFinding:
        """Check EDM-HAVOK cross-validation consistency."""
        if self.edm_nonlinear is None or self.havok_kurtosis is None:
            return AuditFinding(
                "Cross-Validation Check", "Secret 6: EDM-HAVOK Cross-Validation",
                "SKIP", "Missing EDM nonlinearity or HAVOK kurtosis",
            )

        edm_nl = self.edm_nonlinear
        havok_ht = self.havok_kurtosis > 1.5

        if edm_nl == havok_ht:
            return AuditFinding(
                "Cross-Validation Check", "Secret 6: EDM-HAVOK Cross-Validation",
                "PASS",
                f"EDM nonlinear={edm_nl}, HAVOK heavy-tail={havok_ht}. "
                f"Both agree. Diagnosis confident.",
                details={"edm_nonlinear": edm_nl, "havok_heavy_tailed": havok_ht}
            )
        elif edm_nl and not havok_ht:
            return AuditFinding(
                "Cross-Validation Check", "Secret 6: EDM-HAVOK Cross-Validation",
                "WARN",
                f"EDM says nonlinear but HAVOK says near-Gaussian. "
                f"DISCREPANCY. Check Hankel ratio and data size.",
                f"If p/q < 10: HAVOK may be degraded. If N < 50: EDM S-Map "
                f"may be overfitting. Trust neither alone.",
                details={"edm_nonlinear": edm_nl, "havok_heavy_tailed": havok_ht}
            )
        else:
            return AuditFinding(
                "Cross-Validation Check", "Secret 6: EDM-HAVOK Cross-Validation",
                "WARN",
                f"HAVOK says heavy-tailed but EDM says linear. "
                f"DISCREPANCY. Possible spurious kurtosis.",
                f"Check for outliers, non-stationarity, or data artifacts.",
                details={"edm_nonlinear": edm_nl, "havok_heavy_tailed": havok_ht}
            )

    # ── Secret 9: Observation Genericity Gate ───────────────

    def audit_observation_genericity(
        self,
        n_unique_threshold: int = 5,
        saturation_threshold: float = 0.05,
        quantization_threshold: float = 0.1,
        symmetric_folding_hint: bool = False,
    ) -> AuditFinding:
        """
        Secret 9: check whether the observation function is "generic" in
        the Takens (1981) sense — injective and immersive. Four classes of
        violation, all checkable directly from the data:

          1. Multi-to-one (non-injective): binary/ordinal targets collapse
             the phase space into discrete sheets, corrupting nearest-
             neighbor relationships. `self.is_binary` is a manual,
             caller-supplied special case of this; this check derives the
             same signal (and more) directly from the data, so it doesn't
             require the caller to know or declare it in advance.
          2. Boundary saturation: sensor/measurement ceiling or floor
             creates an artificial attractor "wall" the trajectory bounces
             off of.
          3. Coarse quantization: heavily rounded/truncated measurements
             create spurious plateau structure in phase space.
          4. Symmetric folding (|x|, RMS, variance): different underlying
             states become indistinguishable in the measurement. This
             cannot be auto-detected from a single series (a value of 2
             could be an honest measurement of 2, or |−2| folded from −2)
             — it requires domain knowledge, so it's surfaced only as an
             Advisory when the caller explicitly hints at it.

        Thresholds are engineering operationalizations `[E]` of Takens
        (1981) / Sauer, Yorke & Casdagli (1991)'s genericity condition —
        see docs/thresholds_and_heuristics.md and
        references/forbidden_rules_reference.md (Secret 9).
        """
        if self.data is None:
            return AuditFinding(
                "Observation Genericity Check", "Secret 9: Observation Genericity",
                "SKIP", "No data provided")

        data_raw = np.asarray(self.data).ravel()
        if np.issubdtype(data_raw.dtype, np.floating):
            # Filter NaN AND +/-Inf, not just NaN. Before this fix, only
            # NaN was excluded — an Inf/-Inf value was silently counted as
            # a legitimate "unique value" (inflating n_unique and even
            # participating in the boundary-saturation min/max), so a
            # series contaminated with Inf could sail through this check
            # reporting "no issues detected". Found via a full-codebase
            # edge-case census (empty/NaN/Inf/constant inputs across all
            # Secret 8-14 functions) — Secret 8's own ADF/KPSS calls would
            # have raised on the same data, so this wasn't "safe by
            # accident", just uncaught here specifically. See
            # docs/CHANGELOG.md.
            finite_mask = np.isfinite(data_raw)
            n_nonfinite = int(np.sum(~finite_mask))
            data = data_raw[finite_mask]
        else:
            n_nonfinite = 0
            data = data_raw
        n_total = len(data)
        if n_total == 0:
            return AuditFinding(
                "Observation Genericity Check", "Secret 9: Observation Genericity",
                "SKIP", "No valid (finite) data")

        n_unique = len(np.unique(data))
        issues = []
        info_notes = []  # informational only — does NOT drive PASS/WARN
        details = {"n_unique": n_unique, "n_total": n_total,
                   "n_nonfinite_excluded": n_nonfinite}
        if n_nonfinite > 0:
            info_notes.append(
                f"{n_nonfinite} non-finite (NaN/Inf) value(s) were excluded "
                f"before this check (see the general Data Quality Check for "
                f"the full non-finite-value report — that's a FAIL-level "
                f"issue in its own right). Not counted as a genericity "
                f"violation here; noted only so this check's counts are "
                f"legible.")

        # 1. Multi-to-one / non-injective
        if n_unique < n_unique_threshold or self.is_binary:
            issues.append(
                f"Only {n_unique} unique value(s) — multi-to-one observation "
                f"function; empirically ρ ceilings around ~0.87 for binary "
                f"targets. Phase space collapses into discrete sheets.")
            details["non_injective"] = True
        else:
            details["non_injective"] = False

        # 2. Boundary saturation
        vmax, vmin = np.max(data), np.min(data)
        frac_max = float(np.mean(data == vmax))
        frac_min = float(np.mean(data == vmin))
        details["frac_at_max"] = frac_max
        details["frac_at_min"] = frac_min
        if frac_max > saturation_threshold or frac_min > saturation_threshold:
            issues.append(
                f"Boundary saturation: {frac_max:.1%} of points at max, "
                f"{frac_min:.1%} at min — the reconstructed attractor's "
                f"boundary may be a measurement artifact (sensor ceiling/"
                f"floor), not real dynamics.")
            details["boundary_saturated"] = True
        else:
            details["boundary_saturated"] = False

        # 3. Quantization coarseness
        quant_ratio = n_unique / n_total
        details["quantization_ratio"] = quant_ratio
        if quant_ratio < quantization_threshold:
            issues.append(
                f"Coarse quantization: only {quant_ratio:.1%} unique values "
                f"relative to N — discretization may create spurious "
                f"near-neighbor degeneracy in phase space.")
            details["coarsely_quantized"] = True
        else:
            details["coarsely_quantized"] = False

        # 4. Symmetric folding (cannot be auto-detected; Advisory only)
        if symmetric_folding_hint:
            issues.append(
                "Symmetric-folding measurement flagged by caller (e.g. |x|, "
                "RMS, variance) — different underlying states may be "
                "indistinguishable in this measurement. No automatic fix; "
                "domain knowledge required.")
            details["symmetric_folding_flagged"] = True

        if not issues:
            msg = (f"{n_unique} unique values, no saturation/quantization "
                   f"issues detected — observation function appears generic.")
            if info_notes:
                msg += " " + " ".join(info_notes)
            return AuditFinding(
                "Observation Genericity Check", "Secret 9: Observation Genericity",
                "PASS", msg, details=details)
        else:
            warn_msg = " ".join(issues)
            if info_notes:
                warn_msg += " " + " ".join(info_notes)
            return AuditFinding(
                "Observation Genericity Check", "Secret 9: Observation Genericity",
                "WARN", warn_msg,
                "Does not block execution — genericity violations may still "
                "carry usable (if degraded) signal. See Secret 4 (Multiview): "
                "when the target's genericity is poor, using continuous "
                "covariates via Multiview becomes a recommendation, not "
                "just an option.",
                details=details)

    # ── Secret 8: Stationarity Gate ──────────────────────────

    def audit_stationarity(
        self,
        alpha: float = 0.05,
        min_n: int = 20,
        variance_ratio_threshold: float = 3.0,
        trend_signal_threshold: float = 0.3,
        cross_pred_decay_threshold: float = 0.7,
    ) -> AuditFinding:
        """
        Secret 8: Takens' theorem assumes stationary dynamics — a fixed
        governing equation and an invariant attractor. A trending or
        variance-heterogeneous series gets its *trend's* geometry
        reconstructed, not its *dynamics'* geometry (a driftless random
        walk with a linear trend can produce EDM Simplex rho > 0.6 purely
        from trend inertia). The reference doc calls this the largest
        category of silent failure in applying EDM/HAVOK, since standard
        pyEDM workflows never check it.

        ADF + KPSS joint decision matrix (complementary null hypotheses —
        ADF H0: unit root; KPSS H0: stationary):

          reject ADF, fail to reject KPSS -> stationary
          reject ADF, reject KPSS         -> trend-stationary (WARN: detrend)
          fail ADF,   reject KPSS         -> difference-stationary (WARN: diff)
          fail ADF,   fail KPSS           -> underpowered (WARN: N too small)

        Requires `statsmodels` (optional dependency — see requirements.txt).
        Gracefully SKIPs (not FAILs) if unavailable, consistent with this
        project's general graceful-degradation philosophy for optional
        dependencies (cf. pyEDM -> _numpy_edm fallback).

        Thresholds: `p<0.05` is `[C]` Fisher's classical convention (both
        ADF and KPSS use it natively); `N>=20` is `[D]` (ADF/KPSS critical-
        value tables lose meaningful power below this); the variance-ratio,
        trend-signal, and cross-prediction-decay thresholds are `[E]`
        engineering operationalizations — see
        docs/thresholds_and_heuristics.md and
        references/forbidden_rules_reference.md (Secret 8).
        """
        if self.data is None:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                "SKIP", "No data provided")

        data = np.asarray(self.data, dtype=float).ravel()
        # Filter NaN AND +/-Inf (same fix as audit_observation_genericity /
        # dominant_periodicity — found in the same edge-case census; see
        # docs/CHANGELOG.md). Filtering only NaN previously happened to be
        # "safe" for the ADF/KPSS branch specifically, since statsmodels
        # raises on Inf-contaminated input and that raise is already
        # caught below — but the three supplementary checks (variance
        # heterogeneity, trend-to-noise, cross-prediction decay) run on
        # this same `data` array independently of whether ADF/KPSS raised,
        # and `np.var`/`np.polyfit` do NOT raise on Inf — they silently
        # return NaN/Inf results that could have passed through uncaught.
        data = data[np.isfinite(data)]
        n = len(data)

        if n < min_n:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                "WARN",
                f"N={n} < {min_n} — ADF/KPSS have severely degraded power "
                f"at this sample size; stationarity cannot be reliably "
                f"assessed. Treat as unknown, not as passed.",
                "Report explicitly that stationarity is unassessed at this N.",
                details={"n": n, "assessable": False})

        try:
            from statsmodels.tsa.stattools import adfuller, kpss
        except ImportError:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                "SKIP",
                "statsmodels not installed — ADF/KPSS unavailable. "
                "pip install statsmodels to enable this gate.",
                "Add statsmodels to your environment (see requirements.txt) "
                "to enable Secret 8.")

        details = {"n": n, "assessable": True}
        issues = []
        verdict_status = "PASS"

        # ── ADF + KPSS joint matrix ──
        try:
            adf_stat, adf_p, *_ = adfuller(data, autolag='AIC')
            with warnings.catch_warnings():
                # statsmodels warns when the KPSS statistic falls outside
                # its tabulated p-value range; the p-value returned is
                # still the correct clipped boundary value, so we use it.
                warnings.simplefilter("ignore")
                kpss_stat, kpss_p, *_ = kpss(data, regression='c', nlags='auto')
        except Exception as e:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                "SKIP", f"ADF/KPSS computation failed: {e}")

        details["adf_p"] = float(adf_p)
        details["kpss_p"] = float(kpss_p)
        adf_rejects = adf_p < alpha         # rejects unit-root null -> no unit root
        kpss_rejects = kpss_p < alpha       # rejects stationarity null -> not stationary

        if adf_rejects and not kpss_rejects:
            details["stationarity_verdict"] = "stationary"
        elif adf_rejects and kpss_rejects:
            details["stationarity_verdict"] = "trend_stationary"
            issues.append(
                f"ADF+KPSS jointly indicate TREND-STATIONARY (ADF p={adf_p:.3f} "
                f"rejects unit root, KPSS p={kpss_p:.3f} rejects stationarity) "
                f"— detrend before embedding.")
            verdict_status = "WARN"
        elif not adf_rejects and kpss_rejects:
            details["stationarity_verdict"] = "difference_stationary"
            issues.append(
                f"ADF+KPSS jointly indicate DIFFERENCE-STATIONARY (ADF "
                f"p={adf_p:.3f} fails to reject unit root, KPSS p={kpss_p:.3f} "
                f"rejects stationarity) — difference the series and re-test "
                f"before embedding.")
            verdict_status = "WARN"
        else:
            details["stationarity_verdict"] = "underpowered"
            issues.append(
                f"ADF (p={adf_p:.3f}) and KPSS (p={kpss_p:.3f}) both fail to "
                f"reject their nulls — inconclusive, likely underpowered at "
                f"N={n}. Do not treat as confirmed stationary.")
            verdict_status = "WARN"

        # ── Supplementary check 1: variance heterogeneity ──
        # Split into ~5 rolling windows (or fewer if data is short) and
        # compare the widest spread of window variances.
        n_windows = max(2, min(5, n // 10))
        window_size = n // n_windows
        if window_size >= 4:
            window_vars = [
                np.var(data[i * window_size:(i + 1) * window_size])
                for i in range(n_windows)
            ]
            window_vars = [v for v in window_vars if v > EPS_DISTANCE]
            if len(window_vars) >= 2:
                var_ratio = max(window_vars) / min(window_vars)
                details["variance_ratio"] = float(var_ratio)
                if var_ratio > variance_ratio_threshold:
                    issues.append(
                        f"Variance heterogeneity: {var_ratio:.1f}x spread across "
                        f"{n_windows} rolling windows (> {variance_ratio_threshold}x) "
                        f"— substantial heteroscedasticity.")
                    verdict_status = "WARN" if verdict_status == "PASS" else verdict_status

        # ── Supplementary check 2: trend-to-noise ratio ──
        t = np.arange(n)
        if n >= 4:
            slope = float(np.polyfit(t, data, 1)[0])
            sigma = float(np.std(data))
            trend_ratio = abs(slope) / max(sigma, EPS_DISTANCE)
            details["trend_signal_ratio"] = trend_ratio
            if trend_ratio > trend_signal_threshold:
                issues.append(
                    f"Trend-to-noise ratio {trend_ratio:.2f} (> "
                    f"{trend_signal_threshold}) — linear trend may dominate "
                    f"delay-vector geometry.")
                verdict_status = "WARN" if verdict_status == "PASS" else verdict_status

        # ── Supplementary check 3: cross-prediction decay (Schreiber 1997) ──
        # Split data in half; fit Simplex-style 1-NN cross-prediction of
        # the second half from the first half vs self-prediction within
        # the first half. A large drop indicates the dynamics changed
        # between segments (non-stationary in the dynamical, not just
        # statistical, sense).
        if n >= 40:
            try:
                half = n // 2
                first, second = data[:half], data[half:half + half]
                rho_self = _one_nn_cross_pred_rho(first, first)
                rho_cross = _one_nn_cross_pred_rho(first, second)
                # Guard: only meaningful if the series has established
                # SOME real self-predictive skill to begin with. Pure
                # white noise has no deterministic structure at all, so
                # `rho_self` is itself just noise-level and unstable —
                # measuring a cross/self ratio against an unstable,
                # near-zero baseline produces false-positive "decay"
                # verdicts on genuinely stationary (if unpredictable)
                # data. 0.2 matches this project's existing "weak
                # signal" floor used elsewhere (e.g. ccm_causality.py's
                # strong_direction_rho). Confirmed via this module's own
                # self-test: pure white noise triggered a false-positive
                # WARN before this guard was added — see docs/CHANGELOG.md.
                if (rho_self is not None and rho_cross is not None
                        and rho_self > 0.2):
                    decay_ratio = rho_cross / rho_self
                    details["cross_pred_decay_ratio"] = float(decay_ratio)
                    if decay_ratio < cross_pred_decay_threshold:
                        issues.append(
                            f"Cross-prediction decay: rho(first->second)="
                            f"{rho_cross:.3f} vs self rho={rho_self:.3f} "
                            f"(ratio={decay_ratio:.2f} < {cross_pred_decay_threshold}) "
                            f"— first- and second-half dynamics may differ "
                            f"(Schreiber 1997 non-stationarity test).")
                        verdict_status = "WARN" if verdict_status == "PASS" else verdict_status
                elif rho_self is not None:
                    details["cross_pred_decay_ratio"] = None
                    details["cross_pred_decay_note"] = (
                        f"self rho={rho_self:.3f} too weak (<=0.2) for the "
                        f"decay ratio to be meaningful — series may simply "
                        f"lack deterministic structure to predict, which "
                        f"is not itself evidence of non-stationarity.")
            except Exception as _decay_err:
                # ROUND27 P2 修复: 原 `except: pass` 完全静默吞错, 导致 cross-prediction
                # decay 检查失败时无任何痕迹, 妨碍调试. 现记录到 details 供审计回溯,
                # 核心稳态判决 (ADF/KPSS) 仍不受影响 (best-effort supplementary check).
                details["cross_pred_decay_error"] = (
                    f"cross-prediction decay supplementary check failed: "
                    f"{type(_decay_err).__name__}: {_decay_err}")

        if not issues:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                "PASS",
                f"ADF+KPSS jointly indicate stationary (ADF p={adf_p:.3f}, "
                f"KPSS p={kpss_p:.3f}); no variance heterogeneity, trend "
                f"dominance, or cross-prediction decay detected.",
                details=details)
        else:
            return AuditFinding(
                "Stationarity Check", "Secret 8: Stationarity Gate",
                verdict_status, " ".join(issues),
                "Advisory only — does not block execution (sliding-window "
                "analysis of non-stationary data can still carry useful "
                "information). Output MUST explicitly flag: 'data is "
                "non-stationary — reconstructed attractor may not be an "
                "invariant set.' If trend-stationary, consider first-"
                "differencing and re-routing.",
                details=details)

    # ── Additional: Data Quality Checks ─────────────────────

    def audit_data_quality(self) -> AuditFinding:
        """
        Basic data quality validation.

        Includes an explicit non-finite (NaN/Inf) check on `self.data`
        when available (added during a full-codebase census after this
        gap was found): previously this — the FIRST check run by
        `run_full_audit()`, specifically because pre-execution gates are
        supposed to catch reachable problems before expensive computation
        — was based only on `self.n` (a plain sample-size count) and
        never looked at the actual data values at all. NaN/Inf
        contamination was only ever caught later, inside
        `SovereignHAVOK.fit()`'s own `np.isfinite` check — meaning a user
        could see "audit PASSED" printed, then have the actual computation
        fail (or, worse in the case of Secret 9/10 below, silently
        degrade) on the exact same data. See docs/CHANGELOG.md.
        """
        if self.n is None:
            return AuditFinding("Data Quality Check", "General",
                              "SKIP", "No data length provided")

        issues = []
        if self.n < 20:
            issues.append(f"N={self.n} is critically small")
        if self.is_binary and self.target_col:
            issues.append(f"Binary target '{self.target_col}' — prefer "
                         "continuous covariates for EDM")

        non_finite_count = 0
        if self.data is not None:
            arr = np.asarray(self.data, dtype=float).ravel()
            if arr.size > 0:
                non_finite_count = int(np.sum(~np.isfinite(arr)))
                if non_finite_count > 0:
                    frac = non_finite_count / arr.size
                    issues.append(
                        f"{non_finite_count} non-finite value(s) "
                        f"({frac:.1%} of N) — NaN/Inf will corrupt Hankel "
                        f"matrix construction and every downstream "
                        f"statistic silently (e.g. a single Inf can turn "
                        f"an entire SVD into NaN). Clean or impute before "
                        f"proceeding.")

        if not issues:
            return AuditFinding("Data Quality Check", "General",
                              "PASS", f"N={self.n}, data format OK")
        else:
            status = "FAIL" if non_finite_count > 0 else "WARN"
            return AuditFinding("Data Quality Check", "General",
                              status, "; ".join(issues),
                              "See edge_cases_reference.md for mitigations",
                              severity=("CRITICAL" if non_finite_count > 0
                                        else "MINOR"))

    def audit_embedding_dimension(self) -> AuditFinding:
        """Validate embedding dimension against sample size.

        S1 修复 (科研严谨性审查): 添加 Takens 充分条件 disclaimer.
        Takens 1981 嵌入定理的充分条件是 E >= 2D+1 (D 为吸引子盒维数),
        但代码中未估计 D (如 Grassberger-Procaccia 关联维数), 因此无法
        验证 E 是否满足嵌入条件. 当前 E 的选择基于 Simplex 预测技能 ρ 的
        峰值 (Sugihara-May 1990), 这是预测最优性判据, 不等同于 Takens
        嵌入条件. 结果: 相空间重构可能不是忠实嵌入 (faithful embedding),
        但对 EDM 预测和 CCM 因果推断仍有效——二者不依赖严格嵌入, 只需
        流形局部邻域结构得到保持 (Sauer 1991 "embedology" 的弱条件).
        """
        if self.E is None or self.n is None:
            return AuditFinding("Embedding Dimension Check", "General",
                              "SKIP", "Missing E or n")

        max_safe_E = max(2, self.n // 5)
        # S1 修复: Takens 充分条件 disclaimer — 无法验证 E >= 2D+1
        takens_disclaimer = (
            "NOTE: Takens sufficient condition E>=2D+1 (D=attractor dimension) "
            "cannot be verified — attractor dimension D is not estimated. "
            "E is selected by Simplex prediction skill (Sugihara-May 1990), "
            "which optimizes predictability but does not guarantee faithful "
            "embedding. EDM/CCM remain valid under weaker Sauer 1991 conditions."
        )
        if self.E <= max_safe_E:
            return AuditFinding("Embedding Dimension Check", "General",
                              "PASS",
                              f"E={self.E} <= max_safe={max_safe_E} (N/5). "
                              f"Attractor can be populated. {takens_disclaimer}",
                              details={"E": self.E, "max_safe_E": max_safe_E,
                                       "takens_sufficient_condition": "unverified"})
        else:
            return AuditFinding("Embedding Dimension Check", "General",
                              "WARN",
                              f"E={self.E} > max_safe={max_safe_E} (N/5). "
                              f"Attractor may be sparse. {takens_disclaimer}",
                              f"Reduce E to <= {max_safe_E} or accept sparse coverage.",
                              details={"E": self.E, "max_safe_E": max_safe_E,
                                       "takens_sufficient_condition": "unverified"})

    # ── Tau Selection Audit ─────────────────────────────────

    def audit_tau_selection(self) -> AuditFinding:
        """Validate time delay tau selection.

        Checks:
          - tau is specified (not None)
          - tau == 1 without AMI evidence (may be unoptimized default)
          - tau * (E-1) does not exceed reasonable fraction of data length
            (too large a delay window makes embedding vectors nearly independent)
        """
        if self.tau is None:
            return AuditFinding(
                "Tau Selection Check", "Time Delay Validation",
                "SKIP", "Tau not specified — cannot audit delay selection",
                "Run edm_tau_optimization.optimal_tau() to compute AMI-based tau."
            )

        issues = []
        critical = False   # True => FAIL; set explicitly, never inferred
                            # from message text (see fix note below).

        # tau == 1 is commonly the unoptimized default
        if self.tau == 1:
            issues.append(
                "tau=1 may be an unoptimized default. "
                "AMI-based optimization (edm_tau_optimization.optimal_tau) "
                "is recommended for nonlinear systems.")

        # Embedding window too large relative to data
        if self.E is not None and self.n is not None:
            window_span = self.tau * (self.E - 1)
            window_fraction = window_span / max(self.n, 1)
            if window_fraction > 0.5:
                critical = True
                issues.append(
                    f"Embedding window span (tau * (E-1) = {window_span}) "
                    f"covers {window_fraction:.0%} of data length ({self.n}). "
                    f"Embedding vectors may approach statistical independence. "
                    f"Reduce tau or E."
                )
            elif window_fraction > 0.3:
                issues.append(
                    f"Embedding window span ({window_span}) covers "
                    f"{window_fraction:.0%} of data. Marginal — monitor.")
            elif window_span <= 0:
                issues.append("tau * (E-1) <= 0 — check tau and E values.")

        if not issues:
            return AuditFinding(
                "Tau Selection Check", "Time Delay Validation",
                "PASS",
                f"tau={self.tau}, E={self.E}, "
                f"window_span={self.tau * (self.E - 1) if self.E else 'N/A'}"
            )
        else:
            # FAIL iff the >50%-of-data-length condition fired (tracked via
            # the explicit `critical` flag above). The previous version
            # inferred this by searching the rendered message text for the
            # substring "0.5" (`any("0.5" in i for i in issues)`), which
            # only matches if window_fraction happens to format to exactly
            # "50%" — a coincidence, not a check. In practice the >0.5
            # branch's message shows the *actual* percentage (e.g. "75%"),
            # which never contains "0.5", so this path could never reach
            # FAIL and always silently downgraded to WARN. Confirmed via
            # this module's own self-test at the bottom of this file,
            # which asserted FAIL and failed with "got WARN" before this
            # fix. See docs/CHANGELOG.md.
            status = "FAIL" if critical else "WARN"
            return AuditFinding(
                "Tau Selection Check", "Time Delay Validation",
                status, "; ".join(issues),
                "Compute tau via AMI (edm_tau_optimization.optimal_tau) "
                "and ensure tau * (E-1) << N.",
                severity="MAJOR" if critical else "MINOR"
            )

    # ── Full Audit ─────────────────────────────────────────

    def run_full_audit(self) -> AuditReport:
        """Run all applicable audit checks and produce a report."""
        report = AuditReport()

        # Always run data quality and embedding check
        report.add(self.audit_data_quality())
        report.add(self.audit_embedding_dimension())
        report.add(self.audit_tau_selection())

        # Secret 8: Stationarity Gate [G] ★★★★ — pre-execution gate,
        # same tier as Secret 3 (Hankel). Runs early since a stationarity
        # violation calls the validity of everything downstream into
        # question (see references/forbidden_rules_reference.md interaction
        # diagram: S8 sits in the PRE-EXECUTION GATES layer alongside S3/S9).
        report.add(self.audit_stationarity())

        # Secret 9: Observation Genericity Gate [G] ★★★ — pre-execution gate.
        report.add(self.audit_observation_genericity())

        # Secret 1: Lyapunov Horizon
        report.add(self.audit_lyapunov_horizon())

        # Secret 2: CCM Victim Mirror
        report.add(self.audit_ccm_direction())

        # Secret 3: Hankel Golden Ratio
        report.add(self.audit_hankel_aspect_ratio())

        # Secret 4: Multiview Embedding
        report.add(self.audit_multiview())

        # Secret 5: SVD Residual
        report.add(self.audit_svd_residual())

        # Secret 6: EDM-HAVOK Cross-Validation
        report.add(self.audit_cross_validation())

        report.finalize()
        return report


# ================================================================
# Convenience function
# ================================================================

def audit_pipeline(df=None, data=None, n=None, q=None, E=None,
                   tau=None, pred_horizon=None, lyap_lambda=None,
                   havok_r=None, ccm_forward=None, ccm_reverse=None,
                   ccm_forward_total_rise=None, ccm_forward_spearman_rho=None,
                   ccm_forward_spearman_p=None,
                   ccm_reverse_total_rise=None, ccm_reverse_spearman_rho=None,
                   ccm_reverse_spearman_p=None,
                   svd_residual=None, svd_baseline=None,
                   edm_nonlinear=None, havok_kurtosis=None,
                   target_col=None, columns=None, is_binary=False):
    """
    One-shot audit of an EDM+HAVOK pipeline configuration.

    Returns AuditReport. Call report.print_report() for readable output.

    CCM convergence parameters (added for Secret 2/7 upgrade):
      ccm_forward_total_rise, ccm_forward_spearman_rho,
      ccm_forward_spearman_p,
      ccm_reverse_total_rise, ccm_reverse_spearman_rho,
      ccm_reverse_spearman_p
      — required for convergence-based CCM validation.
    """
    auditor = Auditor(
        data=data, df=df, n=n, q=q or E, E=E or q, tau=tau,
        pred_horizon=pred_horizon, lyap_lambda=lyap_lambda,
        havok_r=havok_r, ccm_forward_rho=ccm_forward,
        ccm_forward_total_rise=ccm_forward_total_rise,
        ccm_forward_spearman_rho=ccm_forward_spearman_rho,
        ccm_forward_spearman_p=ccm_forward_spearman_p,
        ccm_reverse_rho=ccm_reverse,
        ccm_reverse_total_rise=ccm_reverse_total_rise,
        ccm_reverse_spearman_rho=ccm_reverse_spearman_rho,
        ccm_reverse_spearman_p=ccm_reverse_spearman_p,
        svd_residual=svd_residual, svd_baseline=svd_baseline,
        edm_nonlinear=edm_nonlinear, havok_kurtosis=havok_kurtosis,
        target_col=target_col, columns=columns or [],
        is_binary=is_binary,
    )
    return auditor.run_full_audit()


# ================================================================
# Shared utility: Hankel aspect ratio tier classification
# Used by both edm_auditor.py and enhanced_cross_validate.py
# to ensure consistent thresholds across all audit layers.
# ================================================================

def classify_hankel_ratio(n: int, q: int):
    """
    Classify Hankel matrix aspect ratio p/q for SVD numerical stability.

    Returns (status, ratio, p, q_recommended) where status is one of:
      'GOOD'       — p/q >= 10, numerically stable
      'MARGINAL'   — 5 <= p/q < 10, may see stiffness
      'DEGRADED'   — 3 <= p/q < 5, A-matrix eigenvalues degraded
      'BROKEN'     — p/q < 3, SVD numerically broken

    Recommendation: q_recommended = max(2, (n+1)//11) ensures p/q >= 10.
    This is the single source of truth for Hankel ratio thresholds.
    """
    p = n - q + 1
    ratio = p / q
    q_recommended = max(2, (n + 1) // 11)

    if ratio >= 10:
        status = 'GOOD'
    elif ratio >= 5:
        status = 'MARGINAL'
    elif ratio >= 3:
        status = 'DEGRADED'
    else:
        status = 'BROKEN'

    return status, ratio, p, q_recommended


# ================================================================
# Secret 10: Seasonality / Periodic-Forcing Confound
# ================================================================

def dominant_periodicity(series, times=None, min_n=20, power_threshold=0.30):
    """
    Secret 10 building block: Lomb-Scargle periodogram dominant frequency
    and its normalized power fraction for one series. Lomb-Scargle (not
    a plain FFT periodogram) handles irregular/missing sampling natively,
    which matters for game-log-style data where "time" may be measured in
    games played rather than a strictly uniform clock.

    Returns dict with: assessable, f_dom (dominant frequency), period_dom
    (1/f_dom, in the same units as `times`), power_fraction (P_dom /
    P_total), is_high_seasonality (power_fraction > power_threshold).

    Thresholds: `N>=20` is `[E]` (Lomb-Scargle frequency resolution
    ~1/(t_max-t_min); N=20 resolves ~10 usable bins — the practical floor
    for a dominant-frequency estimate to mean anything).
    `power_fraction > 0.30` is `[D]` — the underlying mechanism (a
    periodic external driver inflates CCM convergence, Cobey & Baskerville
    2016) is well-established, but that paper does not specify a power
    threshold; 0.30 is this project's engineering operationalization for
    its typical N in [20, 100] regime — see
    docs/thresholds_and_heuristics.md and
    references/forbidden_rules_reference.md (Secret 10).
    """
    series = np.asarray(series, dtype=float).ravel()
    # Filter NaN AND +/-Inf, not just NaN (same fix, same root cause, as
    # audit_observation_genericity — found in the same edge-case census;
    # see docs/CHANGELOG.md). Without this, a single Inf value propagates
    # into `lombscargle`'s power computation as NaN (`invalid value
    # encountered in reduce`), and `is_high_seasonality = power_fraction
    # > power_threshold` silently evaluates to False for `nan > 0.30`
    # (NaN comparisons are always False in Python) — reporting
    # "assessable: True, no strong seasonality" for a result that is
    # actually just NaN, not a real "no" answer.
    series = series[np.isfinite(series)]
    n = len(series)
    if n < min_n:
        return {"assessable": False,
                "note": f"N={n} < {min_n} — periodogram resolution insufficient"}

    if times is None:
        times = np.arange(n, dtype=float)
    else:
        times = np.asarray(times, dtype=float)

    t_span = float(times[-1] - times[0])
    if t_span <= 0:
        return {"assessable": False, "note": "degenerate/non-increasing time span"}

    series_c = series - np.mean(series)
    if np.std(series_c) < EPS_DISTANCE:
        return {"assessable": False, "note": "series has ~zero variance"}

    from scipy.signal import lombscargle
    f_min = 1.0 / t_span
    f_max = n / (2.0 * t_span)  # ~Nyquist for the mean sampling rate
    if f_max <= f_min:
        return {"assessable": False, "note": "insufficient frequency range"}
    freqs = np.linspace(f_min, f_max, max(50, n))
    angular_freqs = 2 * np.pi * freqs
    power = lombscargle(times, series_c, angular_freqs, normalize=True)

    total_power = float(np.sum(power))
    if total_power < EPS_DISTANCE:
        return {"assessable": False, "note": "no periodogram power detected"}

    dom_idx = int(np.argmax(power))
    f_dom = float(freqs[dom_idx])
    power_fraction = float(power[dom_idx] / total_power)

    return {
        "assessable": True,
        "f_dom": f_dom,
        "period_dom": (1.0 / f_dom) if f_dom > EPS_DISTANCE else None,
        "power_fraction": power_fraction,
        "is_high_seasonality": power_fraction > power_threshold,
    }


def audit_seasonality_confound(
    data_dict: Dict[str, np.ndarray],
    ccm_pairs,
    times=None,
    min_n: int = 20,
    power_threshold: float = 0.30,
    freq_match_rel_tol: float = 0.15,
) -> AuditFinding:
    """
    Secret 10: check whether CCM-convergent pairs share a dominant
    periodic driver (Cobey & Baskerville 2016 confound) — a shared
    external clock (daily/weekly/seasonal cycle) can make CCM report
    convergent "causality" between two variables that are each just
    independently entrained to it.

    Parameters
    ----------
    data_dict : {variable_name: series}
        All variables that appear in `ccm_pairs`, keyed by name.
    ccm_pairs : iterable of (cause, effect) or (cause, effect, converged)
        CCM pairs to cross-check. Only pairs CCM already reported as
        convergent are worth checking — a seasonality confound only
        matters if CCM already claimed a causal verdict. 2-tuples are
        treated as converged=True (caller has already filtered).
    freq_match_rel_tol : float
        Two dominant frequencies are considered "shared" if they're
        within this relative tolerance of each other (handles periodogram
        bin discretization, not an exact-equality test).

    Firewall treatment: Advisory (WARN) only — never blocks. De-
    seasonalized-residual re-analysis is recommended but NOT automated
    (deseasonalizing is itself a modeling choice, not something to run
    silently — see references/forbidden_rules_reference.md, Secret 10).
    """
    if not data_dict or not ccm_pairs:
        return AuditFinding(
            "Seasonality Confound Check", "Secret 10: Seasonality Confound",
            "SKIP", "No data / no CCM pairs provided")

    periodicity = {}
    for name, series in data_dict.items():
        periodicity[name] = dominant_periodicity(
            series, times=times, min_n=min_n, power_threshold=power_threshold)

    issues = []
    checked_any = False
    for pair in ccm_pairs:
        if len(pair) == 3:
            cause, effect, converged = pair
        else:
            cause, effect = pair
            converged = True
        if not converged:
            continue
        if cause not in periodicity or effect not in periodicity:
            continue
        pc, pe = periodicity[cause], periodicity[effect]
        if not (pc.get("assessable") and pe.get("assessable")):
            continue
        checked_any = True
        if pc["is_high_seasonality"] and pe["is_high_seasonality"]:
            f1, f2 = pc["f_dom"], pe["f_dom"]
            if f1 > EPS_DISTANCE and abs(f1 - f2) / f1 < freq_match_rel_tol:
                issues.append(
                    f"'{cause}' and '{effect}' both have strong periodic "
                    f"components (power fractions {pc['power_fraction']:.0%} "
                    f"and {pe['power_fraction']:.0%}) at matching frequency "
                    f"(period≈{pc['period_dom']:.1f}). CCM convergence "
                    f"between them may reflect shared external periodic "
                    f"forcing, not one driving the other. Re-run CCM on "
                    f"de-seasonalized residuals as a control.")

    if not checked_any:
        return AuditFinding(
            "Seasonality Confound Check", "Secret 10: Seasonality Confound",
            "SKIP",
            "No convergent CCM pair had both variables' periodicity "
            "assessable (insufficient N, or no convergent pairs supplied).",
            details={"periodicity": periodicity})

    if not issues:
        return AuditFinding(
            "Seasonality Confound Check", "Secret 10: Seasonality Confound",
            "PASS",
            "No convergent CCM pair shares a dominant periodic driver.",
            details={"periodicity": periodicity})
    else:
        return AuditFinding(
            "Seasonality Confound Check", "Secret 10: Seasonality Confound",
            "WARN", " ".join(issues),
            "Advisory only — does not block. Consider re-running CCM on "
            "de-seasonalized residuals (e.g. subtract a fitted periodic "
            "component) as a control; do not run this automatically, since "
            "the deseasonalization method is itself a modeling choice.",
            details={"periodicity": periodicity})


def audit_prediction_decay(
    data: np.ndarray,
    E: int,
    max_tp: int = None,
    lyap_lambda: Optional[float] = None,
    n_min: int = 30,
) -> AuditFinding:
    """
    Secret 12: Prediction Decay Profile Analysis — 审计层接口（占位+适配）。

    S12 的核心算法实现位于 sensitivity_config.py:decay_profile_scan()，
    通过 router.py 路由执行（当 N>=30 且分析目标为 predict/detect_nl 时
    激活）。此函数为 S12 在 edm_auditor 审计层提供统一接口：调用
    decay_profile_scan 并将其诊断结果转换为 AuditFinding，使 S12 可在
    audit_pipeline 流程中以与其他 Secret 一致的方式暴露结论。

    性质: [D] 诊断，权重 ★（解释追加）
    触发条件: N>=30
    防火墙处置: Advisory（WARN）—— 不阻断，仅累积证据

    参数
    ----------
    data : np.ndarray
        时间序列数据（单变量）。
    E : int
        嵌入维度（与 q/E 约定一致）。
    max_tp : int, optional
        最大预测步数。默认 None 由 decay_profile_scan 自动选择
        （min(20, N//3)）。
    lyap_lambda : float, optional
        Secret 1 估计的 Lyapunov 指数，用于交叉验证衰减时间尺度。
    n_min : int
        最小数据量要求（默认 30，与 reference 文档一致）。

    Returns
    -------
    AuditFinding
        status 为 PASS/WARN/SKIP，details 包含衰减曲线分类结果
        （shape: exponential/flat/cutoff/oscillatory）。
    """
    # 延迟导入避免循环依赖（sensitivity_config 可能间接引用 edm_auditor）
    from sensitivity_config import decay_profile_scan

    series = np.asarray(data, dtype=float).ravel()
    n = len(series)

    # 前置条件检查：N>=30 才能可靠分类衰减形状
    if n < n_min:
        return AuditFinding(
            "Prediction Decay Profile", "Secret 12: Prediction Decay Profile",
            "SKIP",
            f"N={n} < {n_min}，衰减形状分类需要 N>=30 才有统计意义。",
        )

    try:
        result = decay_profile_scan(
            series, E=E, max_tp=max_tp, lyap_lambda=lyap_lambda)
    except Exception as e:
        return AuditFinding(
            "Prediction Decay Profile", "Secret 12: Prediction Decay Profile",
            "SKIP",
            f"decay_profile_scan 执行失败：{type(e).__name__}: {e}",
        )

    if not result.get("assessable", False):
        return AuditFinding(
            "Prediction Decay Profile", "Secret 12: Prediction Decay Profile",
            "SKIP",
            f"衰减形状不可评估：{result.get('note', '未知原因')}",
            details=result,
        )

    shape = result.get("shape", "unknown")
    # 构建诊断消息
    msg_parts = [f"衰减形状: {shape}"]
    if "exp_r2" in result:
        msg_parts.append(f"指数拟合 R^2={result['exp_r2']:.3f}")
    if "lambda_fit" in result and result.get("lambda_fit") is not None:
        msg_parts.append(f"拟合 lambda={result['lambda_fit']:.4f}")
    if "lyapunov_consistency" in result:
        msg_parts.append(f"Lyapunov 一致性: {result['lyapunov_consistency']}")

    # 防火墙处置：S12 为 Advisory，仅 WARN 不阻断
    # 当衰减形状与 Lyapunov 估计不一致时升级为 WARN
    status = "PASS"
    recommendation = ""
    if result.get("lyapunov_consistency") == "inconsistent":
        status = "WARN"
        recommendation = (
            "衰减时间尺度与 Secret 1 的 Lyapunov 估计不一致——"
            "可能 lambda_max 被低估，或系统存在与混沌发散无关的特征时间尺度。"
        )
    elif shape == "flat":
        status = "WARN"
        recommendation = (
            "衰减曲线平坦——线性/随机过程主导，非线性结构较弱。"
            "后续 HAVOK/CCM 解释应谨慎。"
        )

    return AuditFinding(
        "Prediction Decay Profile", "Secret 12: Prediction Decay Profile",
        status, "；".join(msg_parts), recommendation, details=result)


# ================================================================
# Self-test: verify every audit function fires correctly
# ================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("  edm_auditor.py — Self-Test")
    print("=" * 70)

    # Test each audit function independently

    # Secret 1: Should FAIL for horizon way beyond tau_L
    a1 = Auditor(n=100, q=5, lyap_lambda=0.1, pred_horizon=200)
    r1 = a1.audit_lyapunov_horizon()
    assert r1.status == "FAIL", f"Expected FAIL, got {r1.status}"
    print(f"  [OK] Lyapunov horizon: FAIL when horizon >> 5*tau_L")

    # Secret 1: Should PASS for safe horizon
    a1b = Auditor(n=100, q=5, lyap_lambda=0.1, pred_horizon=5)
    r1b = a1b.audit_lyapunov_horizon()
    assert r1b.status == "PASS", f"Expected PASS, got {r1b.status}"
    print(f"  [OK] Lyapunov horizon: PASS when horizon <= tau_L")

    # Secret 2: 无收敛数据时不再静默 PASS，应降级为 WARN（P2-4）
    a2 = Auditor(ccm_forward_rho=0.45, ccm_reverse_rho=0.15)
    r2 = a2.audit_ccm_direction()
    assert r2.status == "WARN", f"Expected WARN (convergence undetermined), got {r2.status}"
    print(f"  [OK] CCM direction: WARN when forward >> reverse but no convergence data")

    # Secret 2: Should warn for ambiguous
    a2b = Auditor(ccm_forward_rho=0.05, ccm_reverse_rho=0.03)
    r2b = a2b.audit_ccm_direction()
    assert r2b.status == "WARN", f"Expected WARN, got {r2b.status}"
    print(f"  [OK] CCM direction: WARN when both skills near zero")

    # Secret 2: Should WARN when rho high but NOT converging
    a2c = Auditor(ccm_forward_rho=0.45, ccm_reverse_rho=0.15,
                  ccm_forward_total_rise=0.01, ccm_forward_spearman_rho=0.3)
    r2c = a2c.audit_ccm_direction()
    assert r2c.status == "WARN", f"Expected WARN for non-converging, got {r2c.status}"
    print(f"  [OK] CCM direction: WARN when high rho but no convergence")

    # Secret 2: Should PASS when rho high AND converging
    a2d = Auditor(ccm_forward_rho=0.45, ccm_reverse_rho=0.15,
                  ccm_forward_total_rise=0.12, ccm_forward_spearman_rho=0.85)
    r2d = a2d.audit_ccm_direction()
    assert r2d.status == "PASS", f"Expected PASS for converging, got {r2d.status}"
    print(f"  [OK] CCM direction: PASS when high rho WITH convergence")

    # Tau audit: SKIP when tau not provided
    a_tau1 = Auditor(n=100, E=5)
    r_tau1 = a_tau1.audit_tau_selection()
    assert r_tau1.status == "SKIP", f"Expected SKIP, got {r_tau1.status}"
    print(f"  [OK] Tau audit: SKIP when tau not specified")

    # Tau audit: WARN when tau=1 (likely unoptimized default)
    a_tau2 = Auditor(n=100, E=5, tau=1)
    r_tau2 = a_tau2.audit_tau_selection()
    assert r_tau2.status == "WARN", f"Expected WARN, got {r_tau2.status}"
    print(f"  [OK] Tau audit: WARN when tau=1 (suspicious default)")

    # Tau audit: PASS when tau is reasonable
    a_tau3 = Auditor(n=100, E=4, tau=3)
    r_tau3 = a_tau3.audit_tau_selection()
    assert r_tau3.status == "PASS", f"Expected PASS, got {r_tau3.status}"
    print(f"  [OK] Tau audit: PASS when tau * (E-1) << N")

    # Tau audit: FAIL when embedding window too large
    a_tau4 = Auditor(n=20, E=6, tau=3)  # window = 3*5 = 15, 15/20 = 75%
    r_tau4 = a_tau4.audit_tau_selection()
    assert r_tau4.status == "FAIL", f"Expected FAIL, got {r_tau4.status}"
    print(f"  [OK] Tau audit: FAIL when embedding window > 50% of data")

    # Shared Hankel classifier
    status, ratio, p, q_rec = classify_hankel_ratio(100, 5)
    assert status == 'GOOD', f"Expected GOOD, got {status}"
    status2, _, _, _ = classify_hankel_ratio(100, 50)
    assert status2 == 'BROKEN', f"Expected BROKEN, got {status2}"
    print(f"  [OK] classify_hankel_ratio: shared function verified")

    # Secret 3: Should FAIL for p/q < 3
    a3 = Auditor(n=100, q=50)  # p = 51, ratio = 1.02
    r3 = a3.audit_hankel_aspect_ratio()
    assert r3.status == "FAIL", f"Expected FAIL, got {r3.status}"
    print(f"  [OK] Hankel ratio: FAIL when p/q < 3")

    # Secret 3: Should PASS for p/q >= 10
    a3b = Auditor(n=100, q=5)  # p = 96, ratio = 19.2
    r3b = a3b.audit_hankel_aspect_ratio()
    assert r3b.status == "PASS", f"Expected PASS, got {r3b.status}"
    print(f"  [OK] Hankel ratio: PASS when p/q >= 10")

    # Secret 4: Should recommend Multiview for short data
    a4 = Auditor(n=40, q=3, columns=['kills', 'damage', 'deaths'])
    r4 = a4.audit_multiview()
    assert "Multiview" in r4.recommendation or r4.status == "PASS"
    print(f"  [OK] Multiview: Recommends when N<50 with 3+ variables")

    # Secret 5: Should FAIL for high residual
    a5 = Auditor(svd_residual=0.5, svd_baseline=0.1)
    r5 = a5.audit_svd_residual()
    assert r5.status == "FAIL", f"Expected FAIL, got {r5.status}"
    print(f"  [OK] SVD residual: FAIL when ratio > 2.5x")

    # Secret 5: Should PASS for low residual
    a5b = Auditor(svd_residual=0.12, svd_baseline=0.1)
    r5b = a5b.audit_svd_residual()
    assert r5b.status == "PASS", f"Expected PASS, got {r5b.status}"
    print(f"  [OK] SVD residual: PASS when ratio < 1.5x")

    # Secret 6: Should PASS for agreement
    a6 = Auditor(edm_nonlinear=True, havok_kurtosis=4.0)
    r6 = a6.audit_cross_validation()
    assert r6.status == "PASS", f"Expected PASS, got {r6.status}"
    print(f"  [OK] Cross-validation: PASS when both agree")

    # Secret 6: Should WARN for disagreement
    a6b = Auditor(edm_nonlinear=True, havok_kurtosis=-1.0)
    r6b = a6b.audit_cross_validation()
    assert r6b.status == "WARN", f"Expected WARN, got {r6b.status}"
    print(f"  [OK] Cross-validation: WARN when EDM/HAVOK disagree")

    # Secret 8: Should PASS for a genuinely stationary series
    _rng = np.random.RandomState(0)
    stationary_series = _rng.randn(200)  # white noise: stationary by construction
    a8 = Auditor(data=stationary_series)
    r8 = a8.audit_stationarity()
    assert r8.status == "PASS", f"Expected PASS for white noise, got {r8.status}: {r8.details}"
    print(f"  [OK] Stationarity: PASS for white noise")

    # Secret 8: Should WARN (trend/difference-stationary) for a random walk with drift
    drift_series = np.cumsum(_rng.randn(200) + 0.3)  # unit-root + drift
    a8b = Auditor(data=drift_series)
    r8b = a8b.audit_stationarity()
    assert r8b.status == "WARN", f"Expected WARN for drifting random walk, got {r8b.status}"
    print(f"  [OK] Stationarity: WARN for random walk with drift")

    # Secret 8: Should WARN (not silently PASS) when N too small to assess
    a8c = Auditor(data=_rng.randn(10))
    r8c = a8c.audit_stationarity()
    assert r8c.status == "WARN", f"Expected WARN for N<min_n, got {r8c.status}"
    assert r8c.details.get("assessable") is False
    print(f"  [OK] Stationarity: WARN (not PASS) when N too small to assess")

    # Secret 8: Should SKIP gracefully with no data
    a8d = Auditor(n=100)
    r8d = a8d.audit_stationarity()
    assert r8d.status == "SKIP", f"Expected SKIP with no data, got {r8d.status}"
    print(f"  [OK] Stationarity: SKIP gracefully when no data provided")

    # Secret 9: Should PASS for a generic (continuous, well-spread) observation
    generic_series = _rng.uniform(0, 100, size=200)
    a9 = Auditor(data=generic_series)
    r9 = a9.audit_observation_genericity()
    assert r9.status == "PASS", f"Expected PASS for continuous data, got {r9.status}"
    print(f"  [OK] Observation genericity: PASS for continuous, well-spread data")

    # Secret 9: Should WARN for a binary/low-cardinality target
    binary_series = _rng.choice([0, 1], size=200)
    a9b = Auditor(data=binary_series)
    r9b = a9b.audit_observation_genericity()
    assert r9b.status == "WARN", f"Expected WARN for binary data, got {r9b.status}"
    assert r9b.details["non_injective"] is True
    print(f"  [OK] Observation genericity: WARN for binary target (non-injective)")

    # Secret 9: Should WARN for boundary-saturated data (sensor ceiling)
    saturated = np.clip(_rng.randn(200) * 3, -2, 2)  # heavy clipping at +/-2
    a9c = Auditor(data=saturated)
    r9c = a9c.audit_observation_genericity()
    assert r9c.status == "WARN", f"Expected WARN for saturated data, got {r9c.status}"
    assert r9c.details["boundary_saturated"] is True
    print(f"  [OK] Observation genericity: WARN for boundary-saturated (clipped) data")

    # Secret 9: is_binary flag alone (no data) should still trigger non-injective WARN
    # — this is the backward-compatible path: existing callers that only ever set
    # is_binary=True (without also passing raw data) must keep working.
    a9d = Auditor(data=generic_series, is_binary=True)
    r9d = a9d.audit_observation_genericity()
    assert r9d.details["non_injective"] is True
    print(f"  [OK] Observation genericity: is_binary flag alone still flags non-injective")

    # Non-finite (Inf) handling regression check — found via a full-
    # codebase edge-case census (empty/NaN/Inf/constant inputs across S8-
    # S14). Before this fix, S9 and S10 filtered only NaN, not +/-Inf:
    # an Inf value was silently counted as a legitimate "unique value" in
    # S9 (inflating n_unique, corrupting the boundary-saturation min/max)
    # and propagated into S10's Lomb-Scargle power computation as NaN,
    # which then silently evaluated `is_high_seasonality = nan > 0.30` as
    # False (NaN comparisons are always False in Python) — reporting
    # "assessable: True, no seasonality" for a result that was actually
    # just NaN, not a real "no" answer. Also, the pre-execution firewall's
    # general Data Quality Check never looked at `self.data` at all (only
    # at `self.n`), so nothing caught Inf/NaN contamination BEFORE
    # `SovereignHAVOK.fit()`'s own guard raised on the same data, well
    # after "audit PASSED" had already been shown. See docs/CHANGELOG.md.
    print("\n[Non-finite (Inf) handling regression check]")
    inf_data = np.concatenate([_rng.randn(48), [np.inf, -np.inf]])

    a_inf = Auditor(data=inf_data)
    r_dq_inf = a_inf.audit_data_quality()
    assert r_dq_inf.status == "FAIL", (
        f"General Data Quality Check must FAIL on Inf-contaminated data "
        f"(this is the pre-execution gate's job — catch it before "
        f"SovereignHAVOK.fit() has to), got {r_dq_inf.status}")
    print(f"  [OK] General Data Quality Check correctly FAILs on Inf-contaminated data")

    r8_inf = a_inf.audit_stationarity()
    assert r8_inf.details.get("n") == 48, (
        f"Secret 8 must filter out the 2 Inf points before assessing "
        f"stationarity, got n={r8_inf.details.get('n')}")
    print(f"  [OK] Secret 8 correctly filters Inf (not just NaN) before ADF/KPSS")

    r9_inf = a_inf.audit_observation_genericity()
    assert r9_inf.details["n_nonfinite_excluded"] == 2
    assert r9_inf.details["n_total"] == 48
    assert r9_inf.status == "PASS", (
        f"Secret 9 on otherwise-generic white noise contaminated with 2 "
        f"Inf points should PASS (the Inf issue belongs to the general "
        f"Data Quality Check, not to genericity) — the Inf exclusion is "
        f"noted informationally but must not itself flip this check to "
        f"WARN, got {r9_inf.status}")
    print(f"  [OK] Secret 9 correctly excludes Inf from its unique-value count "
          f"without double-reporting the general data-quality issue as its own WARN")

    r10_inf = dominant_periodicity(inf_data)
    assert r10_inf["assessable"] is True
    assert not np.isnan(r10_inf["power_fraction"]), (
        f"Secret 10 must not silently produce a NaN power_fraction when "
        f"Inf is filtered correctly — got {r10_inf['power_fraction']}")
    print(f"  [OK] Secret 10 correctly filters Inf, producing a real "
          f"(non-NaN) periodogram instead of a silently-garbage one")

    # Secret 10: two variables sharing a strong common periodic driver
    # should trigger a seasonality-confound WARN when CCM reports them
    # as convergent.
    _t = np.arange(120, dtype=float)
    shared_period = 12.0
    common_clock = np.sin(2 * np.pi * _t / shared_period)
    x_seasonal = common_clock + 0.1 * _rng.randn(120)
    y_seasonal = common_clock + 0.1 * _rng.randn(120)  # independent noise, same clock
    r10 = audit_seasonality_confound(
        {"x": x_seasonal, "y": y_seasonal}, [("x", "y", True)])
    assert r10.status == "WARN", f"Expected WARN for shared periodic driver, got {r10.status}"
    print(f"  [OK] Seasonality confound: WARN when CCM pair shares a strong common period")

    # Secret 10: aperiodic (noise) variables should PASS
    x_noise = _rng.randn(120)
    y_noise = _rng.randn(120)
    r10b = audit_seasonality_confound(
        {"x": x_noise, "y": y_noise}, [("x", "y", True)])
    assert r10b.status == "PASS", f"Expected PASS for non-periodic data, got {r10b.status}"
    print(f"  [OK] Seasonality confound: PASS when neither variable is strongly periodic")

    # Secret 10: non-convergent pairs should not be checked at all
    r10c = audit_seasonality_confound(
        {"x": x_seasonal, "y": y_seasonal}, [("x", "y", False)])
    assert r10c.status == "SKIP", f"Expected SKIP for no-convergent-pairs, got {r10c.status}"
    print(f"  [OK] Seasonality confound: SKIP when no CCM pair is marked convergent")

    # Full audit integration test
    print(f"\n  [Integration] Full audit on game-like config:")
    report = audit_pipeline(
        n=32, E=6, target_col='result',
        columns=['kills', 'damage', 'deaths', 'result'],
        pred_horizon=10, edm_nonlinear=True,
        havok_kurtosis=-0.12, is_binary=True,
    )
    report.print_report()

    print(f"\n  All auditor self-tests passed.")
    print("=" * 70)
