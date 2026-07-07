"""
EDM Pipeline Auditor — The Firewall Layer
==========================================
Pre-execution validation for ALL EDM + HAVOK pipeline steps.
Called before any computation to prevent invalid configurations
from propagating and producing garbage results.

Each forbidden rule (Secrets 1-7) is enforced by a dedicated
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
from typing import Optional, List, Dict, Any, Tuple
import warnings


@dataclass
class AuditFinding:
    """Single audit check result."""
    check_name: str
    secret_ref: str         # e.g., "Secret 1: Lyapunov Horizon"
    status: str             # "PASS", "WARN", "FAIL", "SKIP"
    message: str
    recommendation: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    """Complete audit report with all findings."""
    findings: List[AuditFinding] = field(default_factory=list)
    verdict: str = "PASS"        # PASS, WARN, FAIL
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0

    def add(self, finding: AuditFinding):
        self.findings.append(finding)
        self.total_checks += 1
        if finding.status == "PASS":
            self.passed += 1
        elif finding.status == "WARN":
            self.warnings += 1
        elif finding.status == "FAIL":
            self.failures += 1

    def finalize(self):
        if self.failures > 0:
            self.verdict = "FAIL"
        elif self.warnings > 0:
            self.verdict = "WARN"
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
              f"{self.failures} failures")
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
                 ccm_reverse_rho: float = None,
                 ccm_reverse_total_rise: float = None,
                 ccm_reverse_spearman_rho: float = None,
                 svd_residual: float = None,
                 svd_baseline: float = None,
                 edm_nonlinear: bool = None,
                 havok_kurtosis: float = None):
        """
        Parameters can be passed individually or derived from existing analysis.

        CCM convergence parameters (Secret 2/7 upgrade):
          ccm_forward_total_rise: total rise in rho across library sizes
          ccm_forward_spearman_rho: Spearman rank correlation (monotonicity)
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
        self.ccm_reverse_rho = ccm_reverse_rho
        self.ccm_reverse_total_rise = ccm_reverse_total_rise
        self.ccm_reverse_spearman_rho = ccm_reverse_spearman_rho
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
                details={"tau_L": tau_L, "pred_horizon": self.pred_horizon}
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

        # Convergence checks (only if convergence metrics provided)
        fwd_converges = True  # default: no convergence data → assume OK
        rev_converges = True
        if self.ccm_forward_total_rise is not None and self.ccm_forward_spearman_rho is not None:
            fwd_converges = (self.ccm_forward_total_rise > 0.05
                           and self.ccm_forward_spearman_rho > 0.7)
        if self.ccm_reverse_total_rise is not None and self.ccm_reverse_spearman_rho is not None:
            rev_converges = (self.ccm_reverse_total_rise > 0.05
                           and self.ccm_reverse_spearman_rho > 0.7)

        if fwd < 0.15 and rev < 0.15:
            return AuditFinding(
                "CCM Direction Check", "Secret 2: CCM Victim Mirror",
                "WARN",
                f"No detectable causal link (fwd={fwd:.3f}, rev={rev:.3f})",
                "Both cross-map skills are near zero. No causation detectable.",
                details={"forward": fwd, "reverse": rev}
            )
        elif fwd > 0.3 and delta > 0.1:
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
                details={"p": p, "q": self.q, "ratio": ratio, "q_recommended": q_recommended}
            )
        else:  # BROKEN
            return AuditFinding(
                "Hankel Aspect Ratio Check", "Secret 3: Hankel Golden Ratio",
                "FAIL",
                f"p/q = {ratio:.1f} < 3. SVD is NUMERICALLY BROKEN!",
                f"STOP. Reduce q to <= {q_recommended} immediately. "
                f"Results with this configuration are garbage.",
                details={"p": p, "q": self.q, "ratio": ratio, "q_recommended": q_recommended}
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
        ratio = self.svd_residual / (baseline + 1e-12)

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
                        "ratio": ratio}
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

    # ── Additional: Data Quality Checks ─────────────────────

    def audit_data_quality(self) -> AuditFinding:
        """Basic data quality validation."""
        if self.n is None:
            return AuditFinding("Data Quality Check", "General",
                              "SKIP", "No data length provided")

        issues = []
        if self.n < 20:
            issues.append(f"N={self.n} is critically small")
        if self.is_binary and self.target_col:
            issues.append(f"Binary target '{self.target_col}' — prefer "
                         "continuous covariates for EDM")

        if not issues:
            return AuditFinding("Data Quality Check", "General",
                              "PASS", f"N={self.n}, data format OK")
        else:
            return AuditFinding("Data Quality Check", "General",
                              "WARN", "; ".join(issues),
                              "See edge_cases_reference.md for mitigations")

    def audit_embedding_dimension(self) -> AuditFinding:
        """Validate embedding dimension against sample size."""
        if self.E is None or self.n is None:
            return AuditFinding("Embedding Dimension Check", "General",
                              "SKIP", "Missing E or n")

        max_safe_E = max(2, self.n // 5)
        if self.E <= max_safe_E:
            return AuditFinding("Embedding Dimension Check", "General",
                              "PASS",
                              f"E={self.E} <= max_safe={max_safe_E} (N/5). "
                              f"Attractor can be populated.",
                              details={"E": self.E, "max_safe_E": max_safe_E})
        else:
            return AuditFinding("Embedding Dimension Check", "General",
                              "WARN",
                              f"E={self.E} > max_safe={max_safe_E} (N/5). "
                              f"Attractor may be sparse.",
                              f"Reduce E to <= {max_safe_E} or accept sparse coverage.",
                              details={"E": self.E, "max_safe_E": max_safe_E})

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
            # If any issue mentions window fraction > 0.5 → FAIL
            # Otherwise → WARN
            status = "FAIL" if any("0.5" in i for i in issues) else "WARN"
            return AuditFinding(
                "Tau Selection Check", "Time Delay Validation",
                status, "; ".join(issues),
                "Compute tau via AMI (edm_tau_optimization.optimal_tau) "
                "and ensure tau * (E-1) << N."
            )

    # ── Full Audit ─────────────────────────────────────────

    def run_full_audit(self) -> AuditReport:
        """Run all applicable audit checks and produce a report."""
        report = AuditReport()

        # Always run data quality and embedding check
        report.add(self.audit_data_quality())
        report.add(self.audit_embedding_dimension())
        report.add(self.audit_tau_selection())

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
                   ccm_reverse_total_rise=None, ccm_reverse_spearman_rho=None,
                   svd_residual=None, svd_baseline=None,
                   edm_nonlinear=None, havok_kurtosis=None,
                   target_col=None, columns=None, is_binary=False):
    """
    One-shot audit of an EDM+HAVOK pipeline configuration.

    Returns AuditReport. Call report.print_report() for readable output.

    CCM convergence parameters (added for Secret 2/7 upgrade):
      ccm_forward_total_rise, ccm_forward_spearman_rho,
      ccm_reverse_total_rise, ccm_reverse_spearman_rho
      — required for convergence-based CCM validation.
    """
    auditor = Auditor(
        data=data, df=df, n=n, q=q or E, E=E or q, tau=tau,
        pred_horizon=pred_horizon, lyap_lambda=lyap_lambda,
        havok_r=havok_r, ccm_forward_rho=ccm_forward,
        ccm_forward_total_rise=ccm_forward_total_rise,
        ccm_forward_spearman_rho=ccm_forward_spearman_rho,
        ccm_reverse_rho=ccm_reverse,
        ccm_reverse_total_rise=ccm_reverse_total_rise,
        ccm_reverse_spearman_rho=ccm_reverse_spearman_rho,
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

    # Secret 2: Should detect convergent direction
    a2 = Auditor(ccm_forward_rho=0.45, ccm_reverse_rho=0.15)
    r2 = a2.audit_ccm_direction()
    assert r2.status == "PASS", f"Expected PASS, got {r2.status}"
    print(f"  [OK] CCM direction: PASS when forward >> reverse")

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
