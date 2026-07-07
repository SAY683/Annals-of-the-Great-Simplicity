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

import os, tempfile, sys, warnings
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = os.path.join(tempfile.gettempdir(), 'edm_takens_mpl')
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

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
        ('core_havok', 'sovereign_havok.py'),
        ('auditor', 'edm_auditor.py'),
        ('cross_validate', 'enhanced_cross_validate.py'),
        ('verify', 'verify_algorithms.py'),
        ('interpret', 'final_interpretation.py'),
        ('game_data', os.path.join('..', 'data', 'game_log.csv')),
    ]:
        full = os.path.join(_SRC_DIR, path)
        report['files'][label] = os.path.exists(full)

    report['files_all_ok'] = all(report['files'].values())
    report['ready'] = (
        all(v != 'NOT INSTALLED' for v in report['packages'].values())
        and report['files_all_ok']
    )

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
    print(f"\n  Overall: {'READY' if report['ready'] else 'NOT READY'}")
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

    def auto_correct(self, n: int, n_columns: int):
        """Apply auto-correction rules (see DESIGN.md for philosophy)."""
        self.corrections = []

        # Rule 1: Hankel aspect ratio
        if self.q is not None:
            p = n - self.q + 1
            ratio = p / self.q
            if ratio < 10:
                q_safe = max(2, (n + 1) // 11)
                if self.auto_fix and q_safe != self.q:
                    self.corrections.append(AutoCorrection(
                        'q (embedding dim)', self.q, q_safe,
                        f'Hankel p/q={ratio:.1f} < 10. SVD degraded.',
                        'WARN'))
                    self.q = q_safe
                elif not self.auto_fix:
                    self.corrections.append(AutoCorrection(
                        'q', self.q, q_safe,
                        f'Hankel p/q={ratio:.1f} < 10. '
                        f'Recommend q={q_safe}. Use --auto-fix.',
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
        return env

    # ── Load data ──
    data_file = config.data_path or data_path('game_log.csv')
    df = pd.read_csv(data_file)
    n = len(df)
    n_columns = len(config.columns)
    print(f"\n  Data: {config.data_path} ({n} records, {n_columns} columns)")
    print(f"  Target: {config.target_col}")

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
    from edm_auditor import audit_pipeline
    audit = audit_pipeline(
        n=n, E=config.q, tau=config.tau,
        target_col=config.target_col,
        columns=config.columns, is_binary=config.is_binary,
    )
    audit.print_report()

    if audit.verdict == 'FAIL' and not config.auto_fix:
        print("\n  AUDIT FAILED. Use --auto-fix to correct, or fix manually.")
        return {'env': env, 'config': config, 'audit': audit}

    # ── Layer 3: Run analysis ──
    print(f"\n{'─' * 60}")
    print("  LAYER 3: Running analysis pipeline")
    print(f"{'─' * 60}")

    # HAVOK
    from sovereign_havok import SovereignHAVOK
    data = df[config.target_col].values.astype(float)

    wl = config.window_length
    if wl % 2 == 0: wl -= 1

    sh = SovereignHAVOK(
        q_delays=config.q, dt=config.dt,
        energy_threshold=config.energy_threshold,
        window_length=wl, poly_order=2, basis="V")
    sh.fit(data)

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

    # Stability — use discrete-time eigenvalues (|λ_d| vs 1)
    max_ev = np.max(np.abs(sh.eigenvalues_d_))
    if max_ev > 1.05:
        stab = "DIVERGENT (unstable modes exist)"
    elif max_ev > 0.9:
        stab = "Near-critical / stable"
    else:
        stab = f"Highly dissipative (half-life ~{np.log(2)/(1-max_ev+1e-12):.1f} games)"
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
                print(f"    Game {gi+1:2d}: v_r={fs:+.3f} ({direction}), "
                      f"K/D={int(row['kills'])}/{int(row['deaths'])}, {res}")

    # Quick CCM check
    try:
        from _edm_bridge import CCM, EDM_AVAILABLE
        print(f"\n  [CCM Quick Check (Victim Mirror)]")
        for cause in ['kills', 'damage', 'deaths']:
            if EDM_AVAILABLE:
                ccm = CCM(
                    data=df, E=config.q, Tp=0,
                    columns='result', target=cause,
                    libSizes=f'5 {n-2} 5', sample=min(30, n),
                    showPlot=False)
                col = [c for c in ccm.columns if c != 'LibSize'][0]
                rho = float(ccm.iloc[-1][col])
            else:
                # Numpy fallback CCM
                cause_arr = df[cause].values.astype(float)
                effect_arr = df['result'].values.astype(float)
                ccm_result = CCM(data=np.column_stack([cause_arr, effect_arr]),
                                columns='result', target=cause,
                                E=config.q, libSizes=f'5 {n-2} 5', sample=min(30, n))
                ccm_col = [c for c in ccm.columns if c != 'LibSize'][0]
                rho = float(ccm[ccm_col].iloc[-1])
            direction = f"{cause} -> result" if rho > 0.2 else "weak/no signal"
            print(f"    M_result -> {cause}: rho={rho:+.3f} ({direction})")
    except Exception as e:
        print(f"    CCM unavailable: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Pipeline complete.")
    print(f"  Full report: python src/final_interpretation.py")
    print(f"  Scored verification: python src/verify_algorithms.py")

    # ── Layer 4: Config artifact (auto-saved for reproducibility) ──
    os.makedirs('results', exist_ok=True)
    try:
        from sensitivity_config import capture_config, save_config
        cfg = capture_config(
            data=df[config.target_col].values,
            E=config.q, tau=config.tau,
            q=config.q,
            analysis_type="exploratory",
            target_col=config.target_col,
            columns=config.columns,
            data_path=config.data_path,
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
    }


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='EDM-Takens Unified Pipeline')
    parser.add_argument('--data', default=data_path('game_log.csv'),
                       help='Path to CSV data file')
    parser.add_argument('--target', default='result',
                       help='Target column name')
    parser.add_argument('--auto-fix', action='store_true',
                       help='Auto-correct suboptimal configurations')
    parser.add_argument('--report-only', action='store_true',
                       help='Only show environment report, skip computation')
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

    run_pipeline(config, auto_fix=args.auto_fix,
                report_only=args.report_only)
