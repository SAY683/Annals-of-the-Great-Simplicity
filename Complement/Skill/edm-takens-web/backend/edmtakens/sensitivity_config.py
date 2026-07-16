"""
Sensitivity Analysis + Config Artifact
=======================================
Implements two methodological safeguards from research-rigor.md:

1. Sensitivity Scan: Run metric at E+/-1, theta-nearby.
   If conclusion vanishes at adjacent parameters, distrust.

2. Config Artifact: Save full analysis configuration as timestamped JSON.
   All params + package versions recorded for reproducibility.
"""

import json, os, sys, time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable


# ============================================================
# Sensitivity Scan
# ============================================================

def sensitivity_scan(data, base_E: int, metric_fn: Callable,
                     e_radius: int = 1, base_theta: float = None,
                     theta_radius: float = 2.0,
                     abs_range_threshold: float = 0.05) -> dict:
    """
    Run a sensitivity scan around a chosen embedding dimension (research-
    rigor.md's "does the conclusion survive parameter perturbation?" check).

    Evaluates `metric_fn(data, E, theta)` at E = base_E-e_radius .. base_E+
    e_radius (theta held at `base_theta`) and reports whether the metric's
    value is stable across that neighborhood. A conclusion that flips or
    swings wildly for E+/-1 is parameter-fragile and should be reported as
    such rather than presented as robust.

    Parameters
    ----------
    data : array-like
        Passed straight through to `metric_fn` as its first argument.
    base_E : int
        The embedding dimension actually used for the headline result;
        the scan checks base_E-e_radius .. base_E+e_radius.
    metric_fn : Callable[[data, E, theta], float]
        Any scalar metric (e.g. Simplex rho, HAVOK kurtosis) — this
        function is metric-agnostic by design.
    e_radius : int
        How far to scan on each side of base_E (default 1: E-1, E, E+1).
    base_theta : float, optional
        Theta value passed to `metric_fn` unchanged (this scan varies E
        only; theta_radius is currently unused/reserved for a future
        combined E-theta scan).
    abs_range_threshold : float
        See "Why both a relative AND absolute check" below. Default 0.05
        matches the `total_rise` threshold used for CCM convergence
        (ccm_causality.py) for the same underlying reason.

    Why both a relative AND absolute check (Round 10 fix)
    -------------------------------------------------------
    Stability was originally judged purely by coefficient of variation,
    `cv = std(neighbor_values) / |mean(neighbor_values)|`. CV is scale-
    invariant, which is usually the point — but scale-invariance backfires
    exactly when the mean is near zero: a metric hovering at noise level
    (e.g. rho = 0.01, -0.02, 0.015 — no real signal at any E) produces
    `cv ≈ 9` and gets classified "UNSTABLE — conclusion is parameter-
    fragile", while a metric swinging between 0.40 and 0.90 (a large,
    scientifically real change) produces `cv ≈ 0.31` and gets the milder
    "MARGINAL" label — the exact inverse of what a reader should be
    warned about. This is the same class of scale-dependence problem the
    project already fixed once for CCM convergence (switching from
    absolute slope to `total_rise`, Reviewer improvement #2) — see
    docs/CHANGELOG.md (Round 10) for the concrete repro. The fix here is
    the same idea in reverse: when the absolute spread of neighbor values
    is itself below `abs_range_threshold`, there is no meaningful signal
    to be "fragile" about, regardless of what CV says, so it's reported
    as stable (with an explicit note distinguishing "stable because
    genuinely robust" from "stable because there's nothing there").

    Returns
    -------
    dict with: base_E, base_value, neighbor values, neighbor_mean,
    neighbor_std, neighbor_range (new), cv, stability, is_stable,
    near_zero_signal (new, bool), recommendation.
    """
    import numpy as np

    E_min = max(2, base_E - e_radius)
    E_max = base_E + e_radius

    results = {}
    base_val = metric_fn(data, base_E, base_theta)
    results['base_E'] = base_E
    results['base_value'] = base_val

    neighbor_vals = []
    for E in range(E_min, E_max + 1):
        val = metric_fn(data, E, base_theta)
        neighbor_vals.append(val)
        results[f'E={E}'] = val

    results['neighbor_values'] = neighbor_vals
    results['neighbor_mean'] = float(np.mean(neighbor_vals))
    results['neighbor_std'] = float(np.std(neighbor_vals))
    neighbor_range = float(max(neighbor_vals) - min(neighbor_vals))
    results['neighbor_range'] = neighbor_range

    # Stability: coefficient of variation across neighbors
    cv = abs(results['neighbor_std'] / (abs(results['neighbor_mean']) + 1e-12))
    results['cv'] = float(cv)

    near_zero_signal = neighbor_range < abs_range_threshold
    results['near_zero_signal'] = near_zero_signal

    if near_zero_signal:
        # Absolute spread is negligible regardless of what CV says (see
        # docstring) — there's no real signal for the conclusion to be
        # fragile about.
        results['stability'] = (
            f'STABLE (no signal — all neighbor values within '
            f'{abs_range_threshold} of each other near zero)')
        results['is_stable'] = True
    elif cv < 0.1:
        results['stability'] = 'HIGHLY STABLE'
        results['is_stable'] = True
    elif cv < 0.3:
        results['stability'] = 'MODERATELY STABLE'
        results['is_stable'] = True
    elif cv < 0.5:
        results['stability'] = 'MARGINAL — report uncertainty'
        results['is_stable'] = False
    else:
        results['stability'] = 'UNSTABLE — conclusion is parameter-fragile'
        results['is_stable'] = False

    if near_zero_signal:
        results['recommendation'] = (
            "No meaningful signal at any nearby E (values cluster near "
            "zero) — there isn't a conclusion here to be fragile, there "
            "just isn't a conclusion.")
    else:
        results['recommendation'] = (
            "Conclusion is robust to embedding dimension variation."
            if results['is_stable'] else
            "WARNING: Conclusion changes significantly with embedding dimension. "
            "Report this sensitivity. The finding may be parameter-fragile."
        )

    return results


# ============================================================
# Secret 12: Prediction Decay Profile Analysis
# ============================================================

def decay_profile_scan(data, E: int, max_tp: int = None,
                       lyap_lambda: float = None,
                       column_name: str = 'x',
                       lib: str = None, pred: str = None) -> dict:
    """
    Secret 12: a single Tp=1 prediction skill is not, by itself, a
    dynamical diagnosis. Scanning rho across Tp in [1, min(20, N/3)] and
    classifying the *shape* of its decay recovers information a single
    rho throws away — and, combined with a Lyapunov exponent estimate
    (Secret 1), gives a consistency check: if tau_L implies predictability
    should survive to Tp=50 but rho has already collapsed to zero by
    Tp=5, either lambda_max is underestimated or the system has a
    characteristic timescale unrelated to chaotic divergence.

    | Decay shape | Diagnosis |
    |---|---|
    | Exponential (rho(Tp) fit R^2 > 0.85) | Consistent with chaotic dynamics; fitted lambda should roughly match Secret 1's Lyapunov estimate |
    | Sharp cutoff at some Tp | A characteristic timescale exists; the system crosses between dynamical regimes there |
    | Flat (rho(Tp=5)/rho(Tp=1) > 0.8) | Linear/stochastic process dominates; little nonlinear structure |
    | Oscillatory (residual AC(1) > 0.5) | Quasi-periodic dynamics + noise |

    All thresholds `[E]` — the decay-profile concept itself traces to
    Farmer & Sidorowich (1987), Casdagli (1989), and Sugihara & May
    (1990), but none of them specify these exact cutoffs; they are this
    project's engineering operationalization. See
    docs/thresholds_and_heuristics.md and
    references/forbidden_rules_reference.md (Secret 12).

    Parameters
    ----------
    data : array-like
        The series to scan (single variable).
    E : int
        Embedding dimension (shared q/E convention).
    max_tp : int, optional
        Defaults to min(20, N//3) per the spec.
    lyap_lambda : float, optional
        If provided (e.g. from Secret 1's Lyapunov estimate), the fitted
        exponential decay rate is compared against it for consistency.
    column_name, lib, pred : passed through to the EDM bridge's Simplex().

    Returns
    -------
    dict with: assessable, tps, rhos, exp_r2, lambda_fit, sharp_cutoff,
    cutoff_tp, oscillatory, residual_ac1, flat, rho5_over_rho1, shape
    (the primary classification), and (if lyap_lambda given)
    lambda_lyap_ratio + lyapunov_consistency.
    """
    import numpy as np
    import pandas as pd
    from scipy.stats import pearsonr
    from _edm_bridge import Simplex as _bridge_Simplex

    series = np.asarray(data, dtype=float).ravel()
    n = len(series)

    if max_tp is None:
        max_tp = min(20, n // 3)
    max_tp = max(1, max_tp)

    if n < 30 or max_tp < 3:
        return {
            "assessable": False,
            "note": f"N={n} or max_tp={max_tp} insufficient "
                    f"(need N>=30 and max_tp>=3 to classify a decay shape).",
        }

    df = pd.DataFrame({column_name: series})
    if lib is None:
        lib = f'1 {n}'
    if pred is None:
        pred = f'1 {n}'

    tps = list(range(1, max_tp + 1))
    rhos = []
    for tp in tps:
        try:
            result = _bridge_Simplex(
                data=df, columns=column_name, target=column_name,
                E=E, Tp=tp, lib=lib, pred=pred, showPlot=False)
            obs = np.asarray(result['Observations'].values, dtype=float)
            predc = np.asarray(result['Predictions'].values, dtype=float)
            mask = ~np.isnan(obs) & ~np.isnan(predc)
            rho = float(pearsonr(obs[mask], predc[mask])[0]) if mask.sum() > 2 else np.nan
        except Exception:
            rho = np.nan
        rhos.append(rho)

    rhos = np.array(rhos)
    valid = ~np.isnan(rhos)
    if valid.sum() < 3:
        return {"assessable": False,
                "note": "Too few valid Tp predictions to classify a decay shape "
                        "(EDM engine failed at most horizons)."}

    tps_arr = np.array(tps)[valid]
    rhos_valid = rhos[valid]
    # Negative rho means "worse than the sample mean", not "extra decay" —
    # clip to 0 for shape analysis (the log-fit below requires positivity
    # anyway).
    rhos_clipped = np.clip(rhos_valid, 0, None)

    out = {"assessable": True, "tps": tps_arr.tolist(), "rhos": rhos_valid.tolist()}

    # 1. Exponential fit: rho(Tp) ~ A * exp(-lambda * Tp)
    eps = 1e-3
    pos_mask = rhos_clipped > eps
    exp_r2 = None
    lambda_fit = None
    log_rho = fitted = None
    if pos_mask.sum() >= 3:
        log_rho = np.log(rhos_clipped[pos_mask])
        tp_pos = tps_arr[pos_mask]
        slope, intercept = np.polyfit(tp_pos, log_rho, 1)
        lambda_fit = float(-slope)
        fitted = slope * tp_pos + intercept
        ss_res = float(np.sum((log_rho - fitted) ** 2))
        ss_tot = float(np.sum((log_rho - np.mean(log_rho)) ** 2))
        exp_r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
    out["exp_r2"] = exp_r2
    out["lambda_fit"] = lambda_fit

    # 2. Sharp cutoff: second-difference spike (|d2 rho| > 2 sigma_d2)
    sharp_cutoff = False
    cutoff_tp = None
    if len(rhos_valid) >= 5:
        d2 = np.diff(rhos_valid, 2)
        sigma_d2 = float(np.std(d2))
        if sigma_d2 > 1e-12:
            spike_idx = np.where(np.abs(d2) > 2 * sigma_d2)[0]
            if len(spike_idx) > 0:
                sharp_cutoff = True
                cutoff_tp = int(tps_arr[spike_idx[0] + 1])
    out["sharp_cutoff"] = sharp_cutoff
    out["cutoff_tp"] = cutoff_tp

    # 3. Oscillatory: lag-1 autocorrelation of the exponential-fit residual
    oscillatory = False
    if exp_r2 is not None and log_rho is not None and len(log_rho) >= 4:
        residuals = log_rho - fitted
        ac1 = float(np.corrcoef(residuals[:-1], residuals[1:])[0, 1])
        out["residual_ac1"] = ac1
        oscillatory = ac1 > 0.5
    out["oscillatory"] = oscillatory

    # 4. Flat: rho(Tp=5) / rho(Tp=1) > 0.8
    flat = False
    tps_list = tps_arr.tolist()
    if 1 in tps_list and 5 in tps_list:
        rho1 = rhos_valid[tps_list.index(1)]
        rho5 = rhos_valid[tps_list.index(5)]
        if rho1 > eps:
            ratio5 = float(rho5 / rho1)
            out["rho5_over_rho1"] = ratio5
            flat = ratio5 > 0.8
    out["flat"] = flat

    # Primary shape classification (priority: flat > exponential > sharp
    # cutoff > oscillatory > ambiguous — flat is checked first because an
    # exponential fit can spuriously achieve high R^2 on a nearly-flat
    # curve with tiny slope; a flat curve is a more specific and more
    # actionable diagnosis than "technically exponential").
    if flat:
        shape = "flat/power-law (linear dynamics dominant)"
    elif exp_r2 is not None and exp_r2 > 0.85 and not sharp_cutoff:
        shape = "exponential decay (consistent with chaotic dynamics)"
    elif sharp_cutoff:
        shape = f"sharp cutoff near Tp={cutoff_tp} (characteristic timescale)"
    elif oscillatory:
        shape = "oscillatory decay (quasi-periodic dynamics + noise)"
    else:
        shape = "ambiguous — does not cleanly match a known decay pattern"
    out["shape"] = shape

    # 5. Consistency with an independent Lyapunov estimate (Secret 1)
    if lyap_lambda is not None and lambda_fit is not None and lyap_lambda > 1e-12:
        ratio = lambda_fit / lyap_lambda
        out["lambda_lyap_ratio"] = float(ratio)
        if 0.5 <= ratio <= 3.0:
            out["lyapunov_consistency"] = "consistent"
        elif ratio < 0.3 or ratio > 3.0:
            out["lyapunov_consistency"] = "INCONSISTENT — flag for manual review"
        else:
            out["lyapunov_consistency"] = "borderline"

    return out


# ============================================================
# Config Artifact
# ============================================================

@dataclass
class AnalysisConfig:
    """Complete analysis configuration for reproducibility."""
    # Data
    data_path: str = ""
    n_samples: int = 0
    n_variables: int = 0
    target_col: str = ""
    columns: List[str] = field(default_factory=list)

    # EDM params
    E: Optional[int] = None
    tau: Optional[int] = None
    theta: Optional[float] = None
    lib: str = ""
    pred: str = ""

    # HAVOK params
    q: Optional[int] = None      # embedding dimension
    r: Optional[int] = None      # truncation rank
    energy_threshold: float = 0.99
    dt: float = 1.0
    window_length: int = 11
    poly_order: int = 2
    basis: str = "V"

    # Surrogate test
    n_surrogates: int = 99
    surrogate_method: str = "IAAFT"

    # Environment
    python_version: str = ""
    numpy_version: str = ""
    scipy_version: str = ""
    pandas_version: str = ""
    pyedm_version: str = ""

    # Meta
    timestamp: str = ""
    analysis_type: str = "exploratory"   # exploratory or confirmatory
    random_seed: int = 42
    notes: str = ""

    # Audit provenance (P6: record firewall verdict for full traceability)
    audit_verdict: str = ""              # PASS / WARN / FAIL / ""
    audit_findings_summary: str = ""     # compact "PASS:x WARN:y FAIL:z"


def capture_config(data, E=None, tau=None, theta=None,
                   q=None, r=None, lib="", pred="",
                   analysis_type="exploratory",
                   n_surrogates=99, notes="",
                   data_path="", target_col="",
                   columns=None,
                   audit_verdict="", audit_findings_summary="") -> AnalysisConfig:
    """
    Capture full analysis configuration including package versions.

    Call this BEFORE running analysis. Saves a timestamped artifact.
    The optional audit_* fields (P6) record the firewall verdict so the
    artifact captures not only what parameters were used but whether the
    configuration passed the pre-/post-execution audit.
    """
    import numpy, scipy, pandas

    config = AnalysisConfig(
        data_path=data_path,
        n_samples=len(data) if data is not None else 0,
        n_variables=len(columns) if columns else 1,
        target_col=target_col,
        columns=columns or [],
        E=E, tau=tau, theta=theta,
        lib=lib, pred=pred,
        q=q or E, r=r,
        timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'),
        analysis_type=analysis_type,
        random_seed=int(time.time()) % 10000,
        notes=notes,
        n_surrogates=n_surrogates,
        audit_verdict=audit_verdict,
        audit_findings_summary=audit_findings_summary,
        python_version=sys.version.split()[0],
        numpy_version=numpy.__version__,
        scipy_version=scipy.__version__,
        pandas_version=pandas.__version__,
    )

    try:
        import pyEDM
        config.pyedm_version = pyEDM.__version__
    except ImportError:
        config.pyedm_version = "not installed"

    return config


def save_config(config: AnalysisConfig, output_path: str) -> str:
    """Save analysis config as JSON artifact."""
    d = asdict(config)
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return output_path


def load_config(path: str) -> AnalysisConfig:
    """Load a saved analysis config."""
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return AnalysisConfig(**{k: v for k, v in d.items() if k in AnalysisConfig.__dataclass_fields__})


# ============================================================
# Self-test
# ============================================================

if __name__ == '__main__':
    import numpy as np

    print("=" * 60)
    print("  Sensitivity + Config Module — Self-Test")
    print("=" * 60)

    # Sensitivity scan
    print("\n[1] Sensitivity scan")
    np.random.seed(42)
    data = np.sin(np.linspace(0, 10*np.pi, 200)) + 0.1*np.random.randn(200)

    def simple_metric(d, E, theta):
        """Toy metric: embedding dimension affects prediction."""
        n = len(d)
        if n <= E + 1:
            return 0.0
        preds = d[E:]
        obs = d[:-E] if len(d[:-E]) == len(preds) else d[:len(preds)]
        return float(np.corrcoef(obs[:len(preds)], preds)[0, 1])

    scan = sensitivity_scan(data, base_E=3, metric_fn=simple_metric)
    print(f"  Base (E=3): {scan['base_value']:.4f}")
    print(f"  Neighbor CV: {scan['cv']:.3f}")
    print(f"  Stability: {scan['stability']}")
    assert 'stability' in scan

    # Near-zero CV blowup regression check (Round 10): a metric hovering
    # at noise level around zero must NOT be reported as "UNSTABLE" just
    # because dividing by a near-zero mean inflates CV — see docstring.
    print("\n[1b] Near-zero signal (CV blowup guard)")
    def near_zero_metric(d, E, theta):
        return {2: 0.01, 3: -0.02, 4: 0.015}.get(E, 0.0)
    scan_nz = sensitivity_scan(data, base_E=3, metric_fn=near_zero_metric)
    print(f"  neighbor_values={scan_nz['neighbor_values']}, cv={scan_nz['cv']:.2f}, "
          f"stability={scan_nz['stability']}")
    assert scan_nz['near_zero_signal'] is True
    assert scan_nz['is_stable'] is True, (
        "near-zero-mean noise must not be reported as UNSTABLE just "
        "because CV blows up dividing by a tiny mean")
    print("  [OK] Near-zero-mean noise correctly reported as no-signal, not UNSTABLE")

    # Secret 12: Prediction Decay Profile Analysis
    print("\n[1c] Decay profile scan (Secret 12)")

    # Chaotic series with a genuinely FAST decorrelation time, so the
    # Tp<=5 "flat" check and the exponential-fit classification both get
    # meaningfully exercised. The fully chaotic logistic map (r=4.0,
    # Lyapunov exponent ln(2)≈0.693/step) is used rather than Lorenz here:
    # Lorenz integrated at any fixed dt has a fixed Lyapunov TIME
    # (~1.1 time units) that has to be matched to the Tp step size by
    # subsampling, and even reasonably-tuned subsampling still leaves
    # rho(Tp=5)/rho(Tp=1) > 0.8 (correctly "flat" by the spec's own Tp=5
    # criterion, since 5 steps is still a modest fraction of one Lyapunov
    # time) — that's a fact about Lorenz's timescale relative to a fixed
    # Tp=5 checkpoint, not a bug in the classifier. The logistic map's
    # much larger per-step Lyapunov exponent decorrelates within just a
    # few iterations regardless of subsampling, giving a clean, decisive
    # "not flat, exponential decay" case to verify against. See
    # docs/CHANGELOG.md. x0=0.2 (not 0.5) avoids the r=4.0 critical-point
    # degeneracy fixed in Round 9 (verify_algorithms.py's logistic test
    # had the same pitfall).
    def _logistic_series(r=4.0, n=500, x0=0.2):
        x = np.zeros(n); x[0] = x0
        for i in range(1, n):
            x[i] = r * x[i-1] * (1 - x[i-1])
        return x[200:]
    lorenz_x = _logistic_series()
    decay_chaotic = decay_profile_scan(lorenz_x, E=3, max_tp=15)
    assert decay_chaotic["assessable"] is True
    print(f"  Chaotic (logistic r=4.0): shape={decay_chaotic['shape']}")
    print(f"    exp_r2={decay_chaotic['exp_r2']}, flat={decay_chaotic['flat']}, "
          f"rho5/rho1={decay_chaotic.get('rho5_over_rho1')}")
    assert decay_chaotic["flat"] is False, (
        "a fast-decorrelating chaotic map should not be classified flat")
    assert decay_chaotic["exp_r2"] is not None and decay_chaotic["exp_r2"] > 0.85, (
        "fast chaotic decay should fit an exponential well")
    assert "exponential" in decay_chaotic["shape"]

    # Near-linear / strongly autocorrelated series: rho should stay high
    # across Tp (flat profile — "linear dynamics dominant"). phi=0.995
    # (not something more modest like 0.97) and a fixed seed verified to
    # give a comfortable margin above the 0.8 threshold — Simplex is a
    # k-NN heuristic, not the theoretically optimal AR(1) linear
    # predictor, so its empirical k-step decay is noisier than the raw
    # phi^k autocorrelation and a phi too close to the threshold makes
    # this assertion flaky across RNG seeds even though the qualitative
    # classification (flat vs not) is correct almost always.
    np.random.seed(1)
    ar_series = np.zeros(300)
    for i in range(1, 300):
        ar_series[i] = 0.995 * ar_series[i-1] + 0.02 * np.random.randn()
    decay_flat = decay_profile_scan(ar_series, E=3, max_tp=15)
    assert decay_flat["assessable"] is True
    print(f"  Near-linear AR(0.995): shape={decay_flat['shape']}")
    print(f"    rho5_over_rho1={decay_flat.get('rho5_over_rho1')}")
    assert decay_flat["flat"] is True, (
        "a strongly autocorrelated near-linear series should show a flat decay profile")

    # Lyapunov consistency check wiring (using an arbitrary but plausible
    # lambda; just verifying the ratio/consistency fields populate).
    if decay_chaotic["lambda_fit"] is not None:
        decay_with_lyap = decay_profile_scan(
            lorenz_x, E=3, max_tp=15, lyap_lambda=decay_chaotic["lambda_fit"])
        assert decay_with_lyap.get("lyapunov_consistency") == "consistent", (
            "comparing lambda_fit against itself must be reported as consistent")
        print(f"  [OK] Lyapunov consistency check: self-comparison reports 'consistent'")

    # Too-short data must gracefully report unassessable, not crash
    decay_short = decay_profile_scan(np.random.randn(15), E=3)
    assert decay_short["assessable"] is False
    print(f"  [OK] Decay profile: gracefully unassessable for N=15 (too short)")

    print("  [OK] Decay profile scan distinguishes chaotic (non-flat) vs linear (flat) dynamics")

    # Config capture + save
    print("\n[2] Config artifact")
    cfg = capture_config(data, E=3, tau=1, theta=0.0, q=3,
                         analysis_type="exploratory",
                         notes="Self-test run", target_col="result",
                         columns=["result", "kills"])
    path = save_config(cfg, "results/_test_config.json")
    print(f"  Saved: {path}")
    assert os.path.exists(path)

    # Load back
    cfg2 = load_config(path)
    assert cfg2.E == 3
    assert cfg2.analysis_type == "exploratory"
    print(f"  Loaded: E={cfg2.E}, type={cfg2.analysis_type}, "
          f"numpy={cfg2.numpy_version}")

    # Cleanup
    os.remove(path)
    print(f"  Cleaned: {path}")

    print("\n" + "=" * 60)
    print("  Sensitivity + Config: VERIFIED")
    print("=" * 60)
