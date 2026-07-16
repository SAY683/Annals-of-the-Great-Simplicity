"""
EDM-Takens Unified Pipeline Runner
====================================
Single entry point for the full EDM + HAVOK analysis pipeline with
auto-correction of numerically suboptimal configurations.

Design principle (see DESIGN.md):
  Layer 1: Environment validation
  Layer 2: Configuration audit + auto-correction (firewall)
  Layer 3: Algorithmic cross-validation

Usage:
  python run_pipeline.py                          # interactive mode
  python run_pipeline.py --data data/game_log.csv --target result
  python run_pipeline.py --auto-fix               # auto-correct config issues
  python run_pipeline.py --report-only            # skip computation, show env report
"""

import os, sys, warnings
# debt-22: 环境变量（MPLBACKEND/MPLCONFIGDIR/OMP_NUM_THREADS/MKL_NUM_THREADS）
# 已移至入口点 run_pipeline.py / run_backend.py，库模块不应在导入时
# 设置进程级环境变量。

import numpy as np
import pandas as pd
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from _paths import data_path

warnings.filterwarnings('ignore')

# ── Path setup ────────────────────────────────────────────
# All modules are siblings in src/. _paths.py resolves data/.
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


# ============================================================
# Layer 1: Environment Sniffer
# ============================================================

def sniff_environment() -> Dict:
    """
    Comprehensive environment report including pip-freeze style version
    listing and platform compatibility checks.

    Returns dict with: python, platform, packages, compatibility, files
    """
    import platform
    import importlib.util

    report = {
        'python_version': sys.version,
        'platform': platform.platform(),
        'os': os.name,
        'packages': {},
        'compatibility': {'warnings': [], 'issues': []},
        'files': {},
    }

    # Package versions
    for pkg in ['numpy', 'scipy', 'pandas', 'matplotlib', 'pyEDM']:
        try:
            mod = importlib.import_module(pkg)
            report['packages'][pkg] = getattr(mod, '__version__', 'unknown')
        except ImportError:
            report['packages'][pkg] = 'NOT INSTALLED'
            report['compatibility']['issues'].append(f'{pkg} not installed')

    # pyEDM internal version + fallback status
    try:
        import pyEDM
        report['packages']['pyEDM_full'] = pyEDM.__version__
        report['edm_backend'] = 'pyEDM'
    except Exception:
        report['packages']['pyEDM_full'] = 'NOT INSTALLED (using numpy fallback)'
        report['edm_backend'] = 'numpy_fallback'
        report['compatibility']['warnings'].append(
            'pyEDM not installed. Using pure numpy/scipy EDM fallback. '
            'All core algorithms functional. Install pyEDM for C++ performance.')

    # Platform quirks
    if os.name == 'nt':  # Windows
        report['compatibility']['warnings'].append(
            'Windows detected: multiprocessing uses spawn. '
            'pyEDM.Multiview may fail. Use numProcess=1.')
    if sys.version_info >= (3, 13):
        report['compatibility']['warnings'].append(
            'Python 3.13+: scipy multiprocess import may MemoryError. '
            'Set OMP_NUM_THREADS=1.')

    # File integrity
    for label, path in [
        ('core_havok', os.path.join(_SRC_DIR, 'sovereign_havok.py')),
        ('auditor', os.path.join(_SRC_DIR, 'edm_auditor.py')),
        ('cross_validate', os.path.join(_SRC_DIR, 'enhanced_cross_validate.py')),
        ('verify', os.path.join(_SRC_DIR, 'verify_algorithms.py')),
        ('interpret', os.path.join(_SRC_DIR, 'final_interpretation.py')),
        ('game_data', data_path('game_log.csv')),
    ]:
        report['files'][label] = os.path.exists(path)

    report['files_all_ok'] = all(report['files'].values())
    required_packages = {'numpy', 'scipy', 'pandas', 'matplotlib'}
    report['required_ready'] = (
        all(report['packages'][p] != 'NOT INSTALLED' for p in required_packages)
        and report['files_all_ok']
    )
    report['optional_ready'] = report['packages']['pyEDM'] != 'NOT INSTALLED'
    report['ready'] = report['required_ready']  # core functionality available

    return report


def print_env_report(report: Dict):
    """Pretty-print environment report."""
    print("\n" + "=" * 60)
    print("  LAYER 1: ENVIRONMENT REPORT")
    print("=" * 60)
    print(f"  Python:  {report['python_version'].split()[0]}")
    print(f"  Platform: {report['platform']}")
    print(f"\n  Packages:")
    for pkg, ver in report['packages'].items():
        status = "[OK]" if ver != 'NOT INSTALLED' else "[XX]"
        print(f"    {status} {pkg}: {ver}")
    if report['compatibility']['warnings']:
        print(f"\n  Compatibility warnings:")
        for w in report['compatibility']['warnings']:
            print(f"    [!] {w}")
    if report['compatibility']['issues']:
        print(f"\n  Compatibility issues:")
        for i in report['compatibility']['issues']:
            print(f"    [XX] {i}")
    print(f"\n  Files: {'ALL OK' if report['files_all_ok'] else 'MISSING:'}")
    if not report['files_all_ok']:
        for label, ok in report['files'].items():
            if not ok:
                print(f"    [XX] {label}")
    overall = 'READY' if report['required_ready'] else 'NOT READY'
    if report['required_ready'] and not report.get('optional_ready', False):
        overall += ' (optional pyEDM missing — numpy fallback active)'
    print(f"\n  Overall: {overall}")
    print("=" * 60)


# ============================================================
# Layer 2: Auto-Correction
# ============================================================

@dataclass
class AutoCorrection:
    """An auto-correction applied to the pipeline configuration."""
    parameter: str
    original_value: Any
    corrected_value: Any
    reason: str
    severity: str  # 'INFO', 'WARN', 'CRITICAL'


@dataclass
class PipelineConfig:
    """Pipeline configuration with auto-correction support."""
    data_path: str = None  # resolved at runtime
    target_col: str = 'result'
    columns: List[str] = field(default_factory=lambda:
                               ['result', 'kills', 'damage', 'deaths'])
    q: Optional[int] = None       # embedding dimension (auto-detect if None)
    tau: Optional[int] = None     # time delay (auto-compute if None)
    max_E: int = 8
    energy_threshold: float = 0.99
    dt: float = 1.0
    window_length: int = 11
    is_binary: bool = True
    auto_fix: bool = False        # enable auto-correction
    corrections: List[AutoCorrection] = field(default_factory=list)
    analysis_type: str = "exploratory"  # 'exploratory' | 'confirmatory' | 'preregistered'
                                          # — drives Secret 13's multiple-
                                          # comparison correction method
                                          # AND sensitivity_config's config
                                          # artifact (previously hardcoded
                                          # to "exploratory" in two separate
                                          # places; see docs/CHANGELOG.md).

    def auto_correct(self, n: int, n_columns: int):
        """Apply auto-correction rules (see DESIGN.md for philosophy)."""
        self.corrections = []

        # Rule 1: Hankel aspect ratio
        if self.q is not None:
            p = n - self.q + 1
            ratio = p / self.q
            if ratio < 10:
                # Largest q that can still give p/q >= 10 is floor((n+1)/11).
                # For very small n this may still leave ratio < 10 because
                # q cannot go below 2; in that case the correction is the
                # best-effort minimum and the user is told explicitly.
                q_safe = max(2, (n + 1) // 11)
                p_new = n - q_safe + 1
                ratio_new = p_new / q_safe if q_safe > 0 else ratio
                if ratio_new < 10:
                    unavoidable = (
                        f' With N={n}, p/q>={10:.0f} is impossible while '
                        f'maintaining q>=2 (best achievable p/q={ratio_new:.1f}). '
                        f'Collect more data or treat results as exploratory.'
                    )
                else:
                    unavoidable = ''
                if self.auto_fix and q_safe != self.q:
                    self.corrections.append(AutoCorrection(
                        'q (embedding dim)', self.q, q_safe,
                        f'Hankel p/q={ratio:.1f} < 10. SVD degraded. '
                        f'Auto-reduced to q={q_safe} '
                        f'(p/q={ratio_new:.1f}).{unavoidable}',
                        'WARN'))
                    self.q = q_safe
                elif not self.auto_fix:
                    self.corrections.append(AutoCorrection(
                        'q', self.q, q_safe,
                        f'Hankel p/q={ratio:.1f} < 10. '
                        f'Recommend q={q_safe} '
                        f'(p/q={ratio_new:.1f}).{unavoidable} '
                        f'Use --auto-fix.',
                        'WARN'))

        # Rule 2: SG window cap (enforced in sovereign_havok.py)
        if self.q is not None:
            p = n - self.q + 1
            wl_safe = max(5, p // 4)
            if wl_safe % 2 == 0: wl_safe -= 1
            if wl_safe < self.window_length:
                self.corrections.append(AutoCorrection(
                    'window_length', self.window_length, wl_safe,
                    f'SG window capped at p//4={wl_safe} for small data.',
                    'INFO'))
                self.window_length = wl_safe

        # Rule 3: Embedding dimension cap
        max_safe_E = max(2, n // 5)
        if self.q is not None and self.q > max_safe_E:
            if self.auto_fix:
                self.corrections.append(AutoCorrection(
                    'q (too large)', self.q, max_safe_E,
                    f'E > N/5={max_safe_E}. Attractor would be sparse.',
                    'WARN'))
                self.q = max_safe_E
            else:
                self.corrections.append(AutoCorrection(
                    'q', self.q, max_safe_E,
                    f'E > N/5={max_safe_E}. Results may be unreliable.',
                    'WARN'))

        # Rule 4: Missing tau -> auto-compute
        if self.tau is None and self.q is not None:
            try:
                from edm_tau_optimization import optimal_tau
                df = pd.read_csv(self.data_path)
                data = df[self.target_col].values.astype(float)
                tau_val, diag = optimal_tau(data)
                self.corrections.append(AutoCorrection(
                    'tau', None, tau_val,
                    f'Auto-computed via {diag["method"]}.',
                    'INFO'))
                self.tau = tau_val
            except Exception:
                self.tau = 1
                self.corrections.append(AutoCorrection(
                    'tau', None, 1,
                    'AMI computation failed. Using default tau=1.',
                    'WARN'))

        # Rule 5: Binary target advisory
        if self.is_binary and self.target_col:
            self.corrections.append(AutoCorrection(
                'is_binary', self.is_binary, 'advisory only',
                f'Binary target detected. EDM rho ceiling ~0.87. '
                f'Prefer continuous covariates for embedding.',
                'INFO'))


# ============================================================
# Layer 3: Orchestrated Pipeline
# ============================================================

def run_pipeline(config: PipelineConfig = None,
                 auto_fix: bool = False,
                 report_only: bool = False):
    """
    Run the complete EDM + HAVOK pipeline with auto-correction.

    Parameters
    ----------
    config : PipelineConfig, optional
    auto_fix : bool
        Enable auto-correction of suboptimal configurations.
    report_only : bool
        Only print environment report, skip computation.
    """
    if config is None:
        config = PipelineConfig(auto_fix=auto_fix)

    # ── Layer 1: Environment ──
    env = sniff_environment()
    print_env_report(env)

    if report_only:
        return env

    if not env['ready']:
        print("\n  ENVIRONMENT NOT READY. Fix issues above before proceeding.")
        return {**env, 'error': 'environment_not_ready'}

    # ── Load data ──
    data_file = config.data_path or data_path('game_log.csv')
    df = pd.read_csv(data_file)
    n = len(df)
    n_columns = len(config.columns)
    print(f"\n  Data: {config.data_path} ({n} records, {n_columns} columns)")
    print(f"  Target: {config.target_col}")

    # ── Early sanity gate: non-finite values ──
    # Runs BEFORE Layer 2's auto-E-detection (EmbedDimension below), which
    # performs real numerical computation (pyEDM's KDTree nearest-neighbor
    # search) that crashes hard — with a confusing low-level traceback
    # from deep inside pyEDM/scipy, not a clear message — on Inf/NaN input.
    # The full pre-execution audit (Secret 8/9, Hankel ratio, etc., below)
    # needs `config.q` as an input and can only run AFTER Layer 2
    # determines it when auto-detection is enabled — a genuine chicken-
    # and-egg ordering constraint — but a basic finiteness check doesn't
    # need E at all, so it belongs here, before ANY computation touches
    # the data. Found via a full-codebase edge-case census: Inf-
    # contaminated data crashed uncaught inside pyEDM's KDTree
    # construction, entirely bypassing the audit firewall whose whole
    # point is to catch exactly this before expensive/fragile computation
    # runs. See docs/CHANGELOG.md.
    _raw_target = df[config.target_col].values.astype(float)
    _n_nonfinite = int(np.sum(~np.isfinite(_raw_target)))
    if _n_nonfinite > 0:
        print(f"\n  [FATAL] Target column '{config.target_col}' contains "
              f"{_n_nonfinite} non-finite value(s) (NaN/Inf) out of {n}. "
              f"Clean or impute before running this pipeline: EDM/HAVOK "
              f"cannot produce meaningful results from non-finite input, "
              f"and proceeding would crash deep inside pyEDM's neighbor "
              f"search with a confusing low-level error instead of this "
              f"clear one.")
        return {'env': env, 'config': config, 'audit': None,
                'error': 'non_finite_target_data', 'n_nonfinite': _n_nonfinite}

    # Check covariate columns too: the gate above only guards target_col,
    # so Inf-contaminated covariates still crashed CCM's KDTree downstream
    # with the same confusing low-level scipy traceback this gate exists
    # to prevent. Non-numeric columns are skipped (CCM handles them on its
    # own); every numeric column in config.columns must be finite.
    _cov_nonfinite_cols: list = []
    for _col in config.columns:
        if _col == config.target_col or _col not in df.columns:
            continue
        try:
            _raw_cov = df[_col].values.astype(float)
        except (ValueError, TypeError):
            continue
        _n_cov_nf = int(np.sum(~np.isfinite(_raw_cov)))
        if _n_cov_nf > 0:
            _cov_nonfinite_cols.append(f"'{_col}' ({_n_cov_nf})")
    if _cov_nonfinite_cols:
        _col_detail = ", ".join(_cov_nonfinite_cols)
        print(f"\n  [FATAL] Non-finite value(s) (NaN/Inf) found in "
              f"covariate column(s): {_col_detail}. Clean or impute "
              f"before running this pipeline: CCM's nearest-neighbor "
              f"search crashes deep inside scipy on Inf input instead of "
              f"producing this clear error.")
        return {'env': env, 'config': config, 'audit': None,
                'error': 'non_finite_covariate_data',
                'columns': _cov_nonfinite_cols}

    # ── Layer 2: Auto-Correction ──
    # Auto-detect E if not specified
    if config.q is None:
        from _edm_bridge import EmbedDimension
        lib = f'1 {n - 7}'
        pred = f'{n - 6} {n}'
        rho_E = EmbedDimension(
            data=df, lib=lib, pred=pred, maxE=config.max_E, Tp=1,
            columns=config.target_col, target=config.target_col,
            showPlot=False, numProcess=1)
        config.q = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])
        print(f"  E auto-detected: {config.q}")

    config.auto_correct(n, n_columns)
    if config.corrections:
        print(f"\n  Auto-Corrections ({len(config.corrections)}):")
        for c in config.corrections:
            icon = {'INFO': '[*]', 'WARN': '[!]', 'CRITICAL': '[XX]'}[c.severity]
            print(f"    {icon} {c.parameter}: {c.original_value} -> {c.corrected_value}")
            print(f"       {c.reason}")

    # ── Auditor check ──
    # `data` is extracted here (moved up from Layer 3, Round 11) so
    # Secret 8 (Stationarity) and Secret 9 (Observation Genericity) — both
    # pre-execution gates in the same tier as Secret 3 (Hankel) per
    # references/forbidden_rules_reference.md's interaction diagram — can
    # actually run. Before this fix, `audit_pipeline()` was called without
    # `data=`, so any data-dependent gate silently SKIPped every time this
    # was invoked through the standard pipeline entry point, regardless of
    # whether the underlying data itself was fine or not.
    data = df[config.target_col].values.astype(float)
    from edm_auditor import audit_pipeline
    audit = audit_pipeline(
        data=data, n=n, E=config.q, tau=config.tau,
        target_col=config.target_col,
        columns=config.columns, is_binary=config.is_binary,
    )
    audit.print_report()

    # debt-20: audit verdict 分级处理。
    # 旧版: verdict=='FAIL' → 硬停止（无法继续）。
    # 新版: 配合 debt-18 的 5 档 verdict 系统：
    #   BLOCKED → 硬停止（CRITICAL severity，不可继续）
    #   FAIL    → SOFT_FAIL（MAJOR severity，可继续但标记结果为 audit_soft_fail）
    #   WARN / PASS_WITH_NOTES / INCONCLUSIVE / PASS → 正常继续
    _audit_soft_fail = False
    if audit.verdict == 'BLOCKED':
        print("\n  AUDIT BLOCKED (verdict=BLOCKED). This is a hard stop regardless of --auto-fix.")
        print("  CRITICAL-severity issues cannot be auto-corrected; fix the data/config manually.")
        return {'env': env, 'config': config, 'audit': audit,
                'error': 'audit_blocked'}
    elif audit.verdict == 'FAIL':
        print("\n  [WARN] AUDIT FAIL (verdict=FAIL, SOFT_FAIL). Proceeding with marked results.")
        print("  MAJOR-severity issues detected — interpret downstream results with caution.")
        _audit_soft_fail = True

    # ── Layer 3: Run analysis ──
    print(f"\n{'─' * 60}")
    print("  LAYER 3: Running analysis pipeline")
    print(f"{'─' * 60}")

    # HAVOK
    from sovereign_havok import SovereignHAVOK, classify_havok_stability

    wl = config.window_length
    if wl % 2 == 0: wl -= 1

    sh = SovereignHAVOK(
        q_delays=config.q, dt=config.dt,
        energy_threshold=config.energy_threshold,
        window_length=wl, poly_order=2, basis="V")
    sh.fit(data)

    # Pipeline-layer decision on HAVOK degeneracy: sovereign_havok.fit()
    # sets is_degenerate_=True for near-constant / zero-energy input where
    # SVD is rank-1 and kurtosis/eigenvalue diagnostics are meaningless.
    # Annotate loudly so downstream interpretation knows not to trust the
    # dynamics, rather than silently producing garbage numbers.
    if getattr(sh, 'is_degenerate_', False):
        print("\n  [WARN] HAVOK degenerate input detected (is_degenerate_=True): "
              "near-constant or zero-energy signal. SVD rank ~1; "
              "kurtosis/eigenvalue/stability diagnostics are NOT meaningful. "
              "Interpretation will be annotated as degenerate.")

    print(f"\n  [HAVOK Results]")
    print(f"    Rank r:              {sh.r_}")
    print(f"    Explained variance:  {sh.explained_var_:.1%}")
    print(f"    Regression R^2:      {sh.regression_r2_:.4f}")
    print(f"    Kurtosis (v_r):      {sh.kurtosis_vr_:.3f}")
    print(f"    Max |eigenvalue_d|:    {np.max(np.abs(sh.eigenvalues_d_)):.4f}")

    # Forcing type
    k = sh.kurtosis_vr_
    if k > 3.0:
        ftype = "HEAVY-TAILED: strong intermittent phase transitions"
    elif k > 1.5:
        ftype = "Moderate tails: intermittent components present"
    elif k > 0.5:
        ftype = "Light tails: weak non-Gaussian"
    elif k > -0.5:
        ftype = "Near-Gaussian: system in stable orbit"
    else:
        ftype = "Sub-Gaussian (platykurtic): bounded/constrained dynamics"
    print(f"    Forcing type:        {ftype}")

    # Stability — use discrete-time eigenvalues (|λ_d| vs 1).
    # Delegates to the shared classify_havok_stability() (sovereign_havok.py)
    # so this label can never drift out of sync with diagnose() or
    # enhanced_cross_validate.py's copy of the same 1.05/0.90 thresholds.
    max_ev = np.max(np.abs(sh.eigenvalues_d_))
    stab_tier = classify_havok_stability(max_ev)
    if stab_tier.startswith("Divergent"):
        stab = "DIVERGENT (unstable modes exist)"
    elif stab_tier.startswith("Highly dissipative"):
        stab = f"Highly dissipative (half-life ~{np.log(2)/(1-max_ev+1e-12):.1f} games)"
    else:
        stab = "Near-critical / stable"
    print(f"    Stability:           {stab}")

    # Forcing spikes
    forcing = sh.forcing_
    th = 1.5 * np.std(forcing)
    spike_idx = np.where(np.abs(forcing) > th)[0]
    if len(spike_idx) > 0:
        print(f"\n  Phase transition events ({len(spike_idx)} spikes):")
        for si in spike_idx[:8]:
            gi = si + sh.q
            if gi < len(df):
                row = df.iloc[gi]
                fs = forcing[si]
                direction = "UP" if fs > 0 else "DOWN"
                res = 'W' if row['result'] == 1 else 'L'
                kd = ""
                if 'kills' in df.columns and 'deaths' in df.columns:
                    kd = f", K/D={int(row['kills'])}/{int(row['deaths'])}"
                print(f"    Game {gi+1:2d}: v_r={fs:+.3f} ({direction}){kd}, {res}")

    # CCM check across candidate causes (Secret 2/7 convergence + Secret 13
    # multiple-comparison correction). K=3 candidate->target pairs tested
    # here is exactly the scenario Secret 13 exists for: reporting each
    # pair's raw p<0.05 independently would inflate the family-wise false
    # positive rate (~14% for K=3 at nominal alpha=0.05). Uses the
    # canonical ccm_batch_test() (ccm_causality.py) rather than a manual
    # per-cause loop with no correction — see ccm_causality.py's
    # docstring and docs/CHANGELOG.md (Round 11).
    ccm_rhos = {}
    ccm_details = {}
    ccm_batch = None
    try:
        from ccm_causality import ccm_batch_test
        print(f"\n  [CCM Batch Check (Victim Mirror + Secret 13 correction)]")
        candidate_pairs = [(cause, config.target_col)
                           for cause in ['kills', 'damage', 'deaths']
                           if cause in df.columns and cause != config.target_col]
        ccm_batch = ccm_batch_test(df, candidate_pairs, config.q,
                                   analysis_label=config.analysis_type)
        print(f"    Method: {ccm_batch['method']}")
        for pres in ccm_batch['pairs']:
            cause = pres['cause']
            fwd = pres['raw_result']['forward']
            ccm_rhos[cause] = fwd['final_rho']
            ccm_details[cause] = pres['raw_result']
            direction = f"{cause} -> {config.target_col}" if fwd['final_rho'] > 0.2 else "weak/no signal"
            conv = "converging" if fwd['is_converging'] else "NOT converging"
            sig = "significant (corrected)" if pres['significant_corrected'] else "not significant (corrected)"
            print(f"    M_{config.target_col} -> {cause}: rho={fwd['final_rho']:+.3f} "
                  f"({direction}, {conv}) — {sig}")
        if ccm_batch.get('warn'):
            print(f"    [!] {ccm_batch['note']}")
    except Exception as e:
        print(f"    CCM unavailable: {e}")

    # ── Post-computation audit feedback (Secrets 2 & 6) ──
    # The pre-execution audit cannot inspect HAVOK kurtosis or CCM results
    # because they do not exist yet. Feed them back now so the firewall can
    # actually enforce cross-validation (Secret 6) and CCM direction (Secret 2).
    #
    # IMPORTANT: this used to pass only the bare final-rho values
    # (ccm_forward=fwd_rho, ccm_reverse=rev_rho) into audit_pipeline(),
    # never populating ccm_forward_total_rise / ccm_forward_spearman_rho.
    # edm_auditor.audit_ccm_direction() treats missing convergence data
    # as "assume converged" by default, so this silently disabled the
    # exact convergence safeguard the auditor's own docstring says it
    # provides — a high-but-non-converging (spurious) rho could sail
    # through with a clean PASS. Now that ccm_details already carries
    # total_rise/spearman_rho/is_converging from the canonical test
    # above, we pass them through explicitly. See docs/CHANGELOG.md.
    # P1 修复：post_audit 必须显式初始化为 None，否则 ccm_rhos 为空或
    # except 触发时 post_audit 未定义，下游 return 字典会抛 NameError。
    post_audit = None
    try:
        from edm_auditor import audit_pipeline as _post_audit
        # Pick the strongest CCM pair for direction audit
        if ccm_rhos:
            best_cause = max(ccm_rhos, key=ccm_rhos.get)
            ccm_result = ccm_details[best_cause]
            fwd, rev = ccm_result['forward'], ccm_result['reverse']
            post_audit = _post_audit(
                n=n, E=config.q, tau=config.tau,
                target_col=config.target_col, columns=config.columns,
                is_binary=config.is_binary,
                havok_kurtosis=sh.kurtosis_vr_,
                ccm_forward=fwd['final_rho'], ccm_reverse=rev['final_rho'],
                ccm_forward_total_rise=fwd['total_rise'],
                ccm_forward_spearman_rho=fwd['spearman_rho'],
                ccm_forward_spearman_p=fwd['spearman_p'],
                ccm_reverse_total_rise=rev['total_rise'],
                ccm_reverse_spearman_rho=rev['spearman_rho'],
                ccm_reverse_spearman_p=rev['spearman_p'],
            )
            print(f"\n  [Post-Computation Audit Feedback]")
            print(f"    HAVOK kurtosis fed back: {sh.kurtosis_vr_:+.3f}")
            print(f"    CCM {best_cause}: fwd={fwd['final_rho']:+.3f} "
                  f"(converging={fwd['is_converging']}) "
                  f"rev={rev['final_rho']:+.3f} (converging={rev['is_converging']})")
            print(f"    Verdict: {ccm_result['verdict']}")
            print(f"    [Secret 11 disclaimer] {ccm_result.get('disclaimer', '')}")
            post_audit.print_report()
    except Exception as e:
        print(f"    Post-audit skipped: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Pipeline complete.")
    print(f"  Full report: python src/final_interpretation.py")
    print(f"  Scored verification: python src/verify_algorithms.py")

    # ── Layer 4: Config artifact (auto-saved for reproducibility) ──
    os.makedirs('results', exist_ok=True)
    try:
        from sensitivity_config import capture_config, save_config
        # P6: record audit verdict + findings summary for full provenance
        audit_summary = (f"PASS:{audit.passed} WARN:{audit.warnings} "
                         f"FAIL:{audit.failures}")
        cfg = capture_config(
            data=df[config.target_col].values,
            E=config.q, tau=config.tau,
            q=config.q,
            analysis_type=config.analysis_type,
            target_col=config.target_col,
            columns=config.columns,
            data_path=config.data_path,
            audit_verdict=audit.verdict,
            audit_findings_summary=audit_summary,
        )
        config_path = save_config(cfg,
            f"results/config_{int(__import__('time').time())}.json")
        print(f"  Config saved: {config_path}")
    except Exception as e:
        print(f"  Config save skipped: {e}")
    print(f"{'=' * 60}")

    return {
        'env': env,
        'config': config,
        'audit': audit,
        'havok': sh,
        # P1 修复：暴露 ccm_batch 和 post_audit 给前端 summary。
        # 此前 return 字典遗漏这两个字段，导致 _build_summary 中的
        # pipe_dict.get("ccm_batch") 永远返回 None，CCM 部分从未真正填充。
        'ccm_batch': ccm_batch,
        'post_audit': post_audit,
        # debt-20: SOFT_FAIL 标记——audit verdict 为 FAIL 时继续执行，
        # 但标记结果以便下游（summary/前端）知道审计未通过。
        'audit_soft_fail': _audit_soft_fail,
    }


# ============================================================
# P5: Unified full-analysis entry (chains all three stages)
# ============================================================

def run_full_analysis(config: 'PipelineConfig' = None,
                      auto_fix: bool = False,
                      skip_cross_validation: bool = False,
                      skip_interpretation: bool = False):
    """
    Run the complete analysis chain per the SKILL.md flow diagram:

      pipeline (env→audit→HAVOK→CCM→config)
        → enhanced_cross_validate (EDM-HAVOK cross-validation + 3 safeguards)
        → final_interpretation (dynamical interpretation + visualization)

    Each stage is independently robust; this wrapper just sequences them so a
    user gets the full SKILL.md flow in one call. Any stage failure is caught
    and reported without aborting later stages that don't depend on it.

    Returns dict with keys: pipeline_result, cross_validation, interpretation.
    """
    results = {'pipeline': None, 'cross_validation': None,
               'interpretation': None}

    # Stage 1: pipeline
    print("\n" + "#" * 60)
    print("#  STAGE 1/3: Pipeline (env + audit + HAVOK + CCM)")
    print("#" * 60)
    try:
        results['pipeline'] = run_pipeline(config, auto_fix=auto_fix)
    except Exception as e:
        print(f"  Pipeline stage failed: {type(e).__name__}: {e}")
        results['pipeline'] = {'error': str(e)}

    # Stage 2: cross-validation
    if not skip_cross_validation:
        print("\n" + "#" * 60)
        print("#  STAGE 2/3: Enhanced Cross-Validation (3 safeguards)")
        print("#" * 60)
        try:
            from enhanced_cross_validate import run_enhanced_validation
            csv = (config.data_path if config and config.data_path
                   else data_path('game_log.csv'))
            cv_variables = config.columns if config else None
            cv_target = config.target_col if config else 'result'
            results['cross_validation'] = run_enhanced_validation(
                csv_path=csv, variables=cv_variables, target_col=cv_target)
        except Exception as e:
            print(f"  Cross-validation stage failed: {type(e).__name__}: {e}")
            results['cross_validation'] = {'error': str(e)}

    # Stage 3: interpretation
    if not skip_interpretation:
        print("\n" + "#" * 60)
        print("#  STAGE 3/3: Dynamical Interpretation")
        print("#" * 60)
        try:
            from final_interpretation import interpret_game_data
            import pandas as pd
            csv = config.data_path if config else data_path('game_log.csv')
            df_interp = pd.read_csv(csv)
            variables = config.columns if config else None
            target_col = config.target_col if config else None
            causality_pairs = None
            if config and config.columns and config.target_col:
                causality_pairs = [(c, config.target_col)
                                   for c in config.columns
                                   if c != config.target_col and c in df_interp.columns]
            results['interpretation'] = interpret_game_data(
                df=df_interp,
                variables=variables,
                causality_pairs=causality_pairs,
                target_col=target_col,
                output_path='results/dynamics_interpretation.png',
                title='HAVOK DYNAMICAL INTERPRETATION',
                unit='samples')
        except Exception as e:
            print(f"  Interpretation stage failed: {type(e).__name__}: {e}")
            results['interpretation'] = {'error': str(e)}

    print("\n" + "=" * 60)
    print("  run_full_analysis complete.")
    print(f"  pipeline: {'OK' if results['pipeline'] and 'error' not in (results['pipeline'] or {}) else 'ISSUE'}")
    print(f"  cross-validation: {'OK' if results['cross_validation'] and 'error' not in (results['cross_validation'] or {}) else 'skipped/issue'}")
    print(f"  interpretation: {'OK' if results['interpretation'] and 'error' not in (results['interpretation'] or {}) else 'skipped/issue'}")
    print("=" * 60)
    return results


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='EDM-Takens Unified Pipeline / Full Analysis')
    parser.add_argument('--data', default=data_path('game_log.csv'),
                       help='Path to CSV data file')
    parser.add_argument('--target', default='result',
                       help='Target column name')
    parser.add_argument('--auto-fix', action='store_true',
                       help='Auto-correct suboptimal configurations')
    parser.add_argument('--report-only', action='store_true',
                       help='Only show environment report, skip computation')
    parser.add_argument('--full-analysis', action='store_true',
                       help='Run pipeline + cross-validation + interpretation chain')
    parser.add_argument('--q', type=int, default=None,
                       help='Embedding dimension (auto-detect if omitted)')
    parser.add_argument('--max-e', type=int, default=8,
                       help='Maximum embedding dimension to search')

    args = parser.parse_args()

    config = PipelineConfig(
        data_path=args.data,
        target_col=args.target,
        q=args.q,
        max_E=args.max_e,
        auto_fix=args.auto_fix,
    )

    if args.full_analysis:
        run_full_analysis(config, auto_fix=args.auto_fix)
    else:
        run_pipeline(config, auto_fix=args.auto_fix,
                    report_only=args.report_only)
