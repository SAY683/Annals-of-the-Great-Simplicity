"""
EDM-Takens Skill — Automated Test Runner
==========================================
One-command full verification. Runs all layers in order.

Usage:
  python run_tests.py              # from skill root
  python run_tests.py --quick      # skip slow tests (Lorenz, logistic)
  python run_tests.py --verbose    # show full output

Exit code 0 = all tests passed. Non-zero = failures found.
"""

import sys, os, time, traceback

# Ensure src/ is importable
_SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SRC)

def _version_tuple(v):
    """Convert version string to comparable tuple."""
    return tuple(int(x) for x in v.split('.')[:3])

# ── Test runner infrastructure ──────────────────────────────

PASS, FAIL, SKIP = 0, 0, 0
VERBOSE = False
QUICK = False
START_TIME = time.time()


def test(name):
    """Decorator-like context manager for test sections."""
    class _TestCtx:
        def __enter__(self):
            self.name = name
            if not QUICK or 'slow' not in name.lower():
                print(f"\n{'─'*60}\n  {name}\n{'─'*60}")
            return self
        def __exit__(self, *args):
            pass
    return _TestCtx()


def check(condition, msg, fatal=False):
    """Assert-like check that tracks pass/fail without stopping."""
    global PASS, FAIL
    if condition:
        PASS += 1
        if VERBOSE: print(f"    [OK] {msg}")
    else:
        FAIL += 1
        print(f"    [XX] {msg}")
        if fatal:
            raise AssertionError(msg)


def section(title):
    global PASS, FAIL
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def result():
    elapsed = time.time() - START_TIME
    total = PASS + FAIL
    print(f"\n{'='*60}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    print(f"  Time: {elapsed:.1f}s")
    if FAIL == 0:
        print(f"  VERDICT: ALL TESTS PASSED")
    else:
        print(f"  VERDICT: {FAIL} FAILURE(S)")
    print(f"{'='*60}")
    return FAIL == 0


# ── Layer 0: Environment ──────────────────────────────────

def test_environment():
    with test("Layer 0: Environment Validation"):
        from environment_check import validate_environment
        env = validate_environment(_SKILL_ROOT)
        check(env.ready, f"Environment ready ({len(env.file_checks)} files verified)")
        for fc in env.file_checks:
            check(fc['exists'], f"File: {fc['label']}")
        check(env.checks[0].installed, f"Python {env.python_version}")

        import numpy;  check(_version_tuple(numpy.__version__) >= (1,22), f"numpy {numpy.__version__}")
        import scipy;  check(_version_tuple(scipy.__version__) >= (1,8), f"scipy {scipy.__version__}")
        import pandas; check(_version_tuple(pandas.__version__) >= (1,4), f"pandas {pandas.__version__}")

        try:
            import pyEDM
            check(True, f"pyEDM {pyEDM.__version__}")
        except ImportError:
            check(True, "pyEDM not installed (optional, numpy fallback active)")


# ── Layer 1: Core Engine ──────────────────────────────────

def test_core_engine():
    with test("Layer 1: SovereignHAVOK Core Engine"):
        import numpy as np
        from sovereign_havok import SovereignHAVOK

        # Sine test
        t = np.linspace(0, 20*np.pi, 500)
        sine = np.sin(t) + 0.02*np.random.randn(500)
        sh = SovereignHAVOK(q_delays=15, dt=0.125).fit(sine)
        check(sh.is_valid_, "Sine: fit successful")
        check(sh.r_ >= 2, f"Sine: rank r={sh.r_} >= 2")
        check(abs(sh.kurtosis_vr_) < 1.5, f"Sine: near-Gaussian kurtosis={sh.kurtosis_vr_:.3f}")

        # Small sample test
        small = np.random.randn(32) * 0.5 + np.sin(np.linspace(0, 4*np.pi, 32))
        sh_s = SovereignHAVOK(q_delays=6, window_length=5, poly_order=2).fit(small)
        check(sh_s.is_valid_, "Small sample (n=32): fit successful")
        check(sh_s.r_ >= 2, f"Small sample: rank r={sh_s.r_} >= 2")

        # V-basis vs U-basis consistency
        sh_v = SovereignHAVOK(q_delays=6, basis="V").fit(small)
        sh_u = SovereignHAVOK(q_delays=6, basis="U").fit(small)
        delta = abs(sh_v.kurtosis_vr_ - sh_u.kurtosis_vr_)
        check(delta < 0.3, f"V-U basis agreement: delta-kurt={delta:.4f}")

        # Predict method
        v0 = np.zeros(sh.r_ - 1)
        next_v = sh.predict_next_state(v0, 0.0)
        check(len(next_v) == sh.r_ - 1, f"Predict: output shape ({len(next_v)},) correct")

        # Eigenvalue sanity
        ev_max = np.max(np.abs(sh.eigenvalues_))
        check(ev_max < 1e6, f"Eigenvalues bounded: max|eig|={ev_max:.4f}")

    if not QUICK:
        with test("Layer 1b: Lorenz Chaotic System (slow)"):
            def lorenz(x, y, z, s=10, r=28, b=8/3):
                return s*(y-x), x*(r-z)-y, x*y-b*z
            dt_l, n_l = 0.01, 5000
            x = np.zeros(n_l); x[0], y, z = 1.0, 1.0, 1.0
            for i in range(1, n_l):
                dx, dy, dz = lorenz(x[i-1], y, z)
                x[i] = x[i-1] + dx*dt_l; y += dy*dt_l; z += dz*dt_l
            lx = x[1000:]
            sh_l = SovereignHAVOK(q_delays=25, dt=0.01).fit(lx)
            check(sh_l.is_valid_, "Lorenz: fit successful")
            check(sh_l.kurtosis_vr_ > 1.0, f"Lorenz: heavy-tailed kurtosis={sh_l.kurtosis_vr_:.3f}")
            check(sh_l.explained_var_ > 0.95, f"Lorenz: high expl_var={sh_l.explained_var_:.1%}")


# ── Layer 2: Auditor Firewall ─────────────────────────────

def test_auditor():
    with test("Layer 2: Auditor Firewall — Blocking invalid configs"):
        from edm_auditor import audit_pipeline, Auditor

        # Should FAIL: Hankel ratio p/q < 3
        r_bad = audit_pipeline(n=32, E=15, target_col='result', is_binary=True)
        check(r_bad.verdict in ('FAIL', 'WARN'), f"Hankel E=15: verdict={r_bad.verdict} (expected FAIL/WARN)")
        check(r_bad.failures >= 1 or r_bad.warnings >= 1, "Blocked or warned on p/q < 3")

        # Should PASS: safe config
        r_ok = audit_pipeline(n=32, E=3)
        check(r_ok.verdict in ('PASS', 'WARN'), f"Safe E=3: verdict={r_ok.verdict}")

        # Should WARN: binary target
        r_bin = audit_pipeline(n=32, E=3, target_col='result', is_binary=True)
        check(r_bin.warnings >= 1, f"Binary target: warned ({r_bin.warnings} warnings)")

        # Should recommend Multiview for N<100
        r_mv = audit_pipeline(n=40, E=3, columns=['a','b','c'])
        check(any('Multiview' in str(f.message) for f in r_mv.findings
                  if f.status == 'PASS'),
              "Multiview recommended for N<100 with 3+ columns")

        # Individual auditor methods
        a = Auditor(n=100, q=50)
        r_hk = a.audit_hankel_aspect_ratio()
        check(r_hk.status == 'FAIL', f"Hankel p/q=1.02 → {r_hk.status}")

        a2 = Auditor(n=100, q=5)
        r_hk2 = a2.audit_hankel_aspect_ratio()
        check(r_hk2.status == 'PASS', f"Hankel p/q=19.2 → {r_hk2.status}")

        # CCM direction（P2-4：无收敛数据时降级为 WARN）
        a3 = Auditor(ccm_forward_rho=0.45, ccm_reverse_rho=0.15)
        r_ccm = a3.audit_ccm_direction()
        check(r_ccm.status == 'WARN', f"CCM direction (no convergence data): {r_ccm.status}")

        # SVD residual
        a4 = Auditor(svd_residual=0.5, svd_baseline=0.1)
        r_svd = a4.audit_svd_residual()
        check(r_svd.status == 'FAIL', f"SVD residual 5x: {r_svd.status}")

        # EDM-HAVOK cross-validation
        a5 = Auditor(edm_nonlinear=True, havok_kurtosis=4.0)
        r_cv = a5.audit_cross_validation()
        check(r_cv.status == 'PASS', f"Cross-val agree: {r_cv.status}")

        a6 = Auditor(edm_nonlinear=True, havok_kurtosis=-1.0)
        r_cv2 = a6.audit_cross_validation()
        check(r_cv2.status == 'WARN', f"Cross-val disagree: {r_cv2.status}")


# ── Layer 3: Cross-Validation ─────────────────────────────

def test_cross_validation():
    with test("Layer 3: Cross-Validation + Verification Suite"):
        from enhanced_cross_validate import check_hankel_aspect_ratio
        from verify_algorithms import InternalConsistencyTests
        import pandas as pd

        # Hankel ratio checker
        hk = check_hankel_aspect_ratio(32, 6)
        check(hk['status'] == 'CRITICAL', f"damage E=6: {hk['status']} (ratio={hk['aspect_ratio']:.1f})")

        hk2 = check_hankel_aspect_ratio(32, 3)
        check(hk2['status'] == 'GOOD', f"result E=3: {hk2['status']} (ratio={hk2['aspect_ratio']:.1f})")

        hk3 = check_hankel_aspect_ratio(100, 5)
        check(hk3['aspect_ratio'] >= 10, f"Large N: ratio={hk3['aspect_ratio']:.1f} >= 10")

        # Internal consistency (Level 4 from verify_algorithms)
        from _paths import data_path
        df = pd.read_csv(data_path('game_log.csv'))
        ic = InternalConsistencyTests(df)
        ic.run_all()
        check(ic.score >= 16, f"Internal consistency: {ic.score}/{ic.max_score} (target >= 16)")

        # Auto-correction in pipeline
        from pipeline import PipelineConfig
        cfg = PipelineConfig(q=10, window_length=11, auto_fix=True)
        cfg.auto_correct(n=32, n_columns=4)
        check(len(cfg.corrections) >= 2, f"Auto-corrections applied: {len(cfg.corrections)}")
        check(cfg.q < 10, f"q reduced from 10 to {cfg.q}")
        check(cfg.window_length < 11, f"SG window capped from 11 to {cfg.window_length}")


# ── Layer 4: Secrets 4+5 ──────────────────────────────────

def test_canonical_ccm():
    with test("Layer 3b: Canonical CCM Delegation"):
        import inspect
        from final_interpretation import ccm_with_convergence
        from enhanced_cross_validate import verify_ccm_direction

        src_final = inspect.getsource(ccm_with_convergence)
        src_cross = inspect.getsource(verify_ccm_direction)
        check('ccm_causality_test(' in src_final,
              "final_interpretation.ccm_with_convergence delegates to canonical test")
        check('ccm_causality_test(' in src_cross,
              "enhanced_cross_validate.verify_ccm_direction delegates to canonical test")


def test_secrets_4_5():
    with test("Layer 4: Secret 4 (Multiview) + Secret 5 (SVD Residual)"):
        from multiview_svd_monitor import SVDResidualMonitor
        import numpy as np

        # Secret 5: SVD Residual Monitor
        np.random.seed(42)
        data1 = np.sin(np.linspace(0, 10*np.pi, 200)) + 0.1*np.random.randn(200)
        data2 = np.sin(np.linspace(0, 10*np.pi, 200)) * 2.0 + 0.5*np.random.randn(200)
        data_shift = np.concatenate([data1, data2])

        mon = SVDResidualMonitor(baseline_window=50, detection_threshold=2.0)
        baseline = mon.fit_baseline(data_shift[:60], q=5, r=3)
        check(baseline > 0, f"Baseline residual: {baseline:.4f}")

        for s in range(0, len(data_shift) - 60 + 1, 5):
            mon.update(data_shift[s:s+60], q=5, r=3)

        check(mon.alarm_triggered, "Attractor deformation detected (alarm triggered)")

        # Adaptive forgetting
        truncated = mon.trigger_adaptive_forgetting(data_shift, q=5)
        check(len(truncated) == len(data_shift) // 2,
              f"Adaptive forgetting: {len(data_shift)} -> {len(truncated)}")

        # Fresh monitor on stable data
        mon2 = SVDResidualMonitor(baseline_window=50, detection_threshold=2.0)
        stable_data = np.sin(np.linspace(0, 20*np.pi, 300)) + 0.05*np.random.randn(300)
        mon2.fit_baseline(stable_data[:60], q=5, r=3)
        for s in range(0, len(stable_data) - 60 + 1, 5):
            mon2.update(stable_data[s:s+60], q=5, r=3)
        check(not mon2.alarm_triggered, "Stable data: NO false alarm")


# ── Layer 5: Game Data Integration ────────────────────────

def test_game_data():
    with test("Layer 5: Game Data End-to-End Integration"):
        from final_interpretation import ccm_with_convergence, estimate_lyapunov_robust
        import pandas as pd

        from _paths import data_path
        df = pd.read_csv(data_path('game_log.csv'))
        check(len(df) == 32, f"Game data: {len(df)} games loaded")
        check(df['result'].mean() > 0, f"Win rate: {df['result'].mean():.0%}")

        # CCM with convergence check
        ccm = ccm_with_convergence(df, 'kills', 'result', E=3)
        check('verdict' in ccm, "CCM: verdict present")
        check(ccm['forward']['final_rho'] is not None, "CCM forward: rho computed")
        check(ccm['reverse']['final_rho'] is not None, "CCM reverse: rho computed")

        # Lyapunov with R^2 check
        lyap = estimate_lyapunov_robust(df['kills'].values, E=3)
        check('lambda_max' in lyap, "Lyapunov: estimation executed")
        check('fit_r2' in lyap, f"Lyapunov: R^2 quality check present (fit_r2={lyap.get('fit_r2', 'N/A'):.3f})")

        # Full HAVOK on game data
        from sovereign_havok import SovereignHAVOK
        import numpy as np
        for var in ['result', 'kills', 'damage', 'deaths']:
            data = df[var].values.astype(float)
            E = {'result': 3, 'kills': 2, 'damage': 6, 'deaths': 3}[var]
            wl = min(7, max(5, (len(data) - E) // 4))
            if wl % 2 == 0: wl -= 1
            sh = SovereignHAVOK(q_delays=E, window_length=wl, poly_order=2).fit(data)
            check(sh.is_valid_, f"HAVOK {var}: fit OK (r={sh.r_}, kurt={sh.kurtosis_vr_:.3f})")
            check(sh.r_ >= 1, f"HAVOK {var}: rank r={sh.r_} >= 1")
            check(abs(sh.kurtosis_vr_) < 10, f"HAVOK {var}: kurtosis bounded")


# ── Layer 6: End-to-End Interpretation (slow) ────────────

def test_e2e_interpretation():
    # Name contains 'slow' so --quick skips it. This guards against the
    # class of regression that let the interpret_game_data NameError survive
    # (P4): the main interpretation entry must actually run to completion.
    if QUICK:
        return  # truly skip slow e2e test in quick mode
    with test("Layer 6: End-to-End Interpretation (slow)"):
        import os as _os
        from final_interpretation import interpret_game_data
        _os.makedirs('results', exist_ok=True)
        try:
            interpret_game_data()
            check(True, "interpret_game_data completed without error")
            check(_os.path.exists('results/game_interpretation.png'),
                  "visualization PNG produced")
        except Exception as e:
            check(False, f"interpret_game_data failed: {type(e).__name__}: {e}")


# ── Layer 7: Module Self-Tests (subprocess) ──────────────
#
# Every module below carries its own `if __name__ == '__main__':`
# self-test block. Before this layer existed, run_tests.py never
# actually invoked any of them — it only re-implemented its own,
# separate checks in Layers 1-6. That gap let real, reproducible bugs
# survive silently: edm_auditor.py's tau-selection status logic had a
# self-test that asserted FAIL and got WARN; surrogate_test.py's Lorenz
# significance self-test could never mathematically reach p<0.05 at
# n_surrogates=19; verify_algorithms.py's logistic-map self-test hit a
# degenerate float64 orbit and returned NaN. All three modules reported
# "self-tests passed" was never even checked by `python run_tests.py`,
# so nothing here would have caught them. This layer closes that gap by
# actually running each module as a subprocess and checking its exit
# code, so a self-test failure anywhere in the skill surfaces the same
# way a Layer 1-6 check would. See docs/CHANGELOG.md.

def test_module_self_tests():
    import subprocess
    with test("Layer 7: Module Self-Tests (subprocess)"):
        fast_modules = [
            'sovereign_havok.py', 'edm_auditor.py', 'ccm_causality.py',
            'surrogate_test.py', '_edm_bridge.py', 'edm_tau_optimization.py',
            'edm_adaptive_pipeline.py', 'multiview_svd_monitor.py',
            'router.py', 'sensitivity_config.py', 'environment_check.py',
        ]
        slow_modules = [
            'verify_algorithms.py',   # runs full ground-truth suite (Lorenz etc.)
            'enhanced_cross_validate.py',  # runs full cross-validation report
        ]
        modules = fast_modules if QUICK else fast_modules + slow_modules
        for mod in modules:
            path = os.path.join(_SRC, mod)
            if not os.path.exists(path):
                check(False, f"{mod}: file missing")
                continue
            # ccm_causality.py runs multiple CCM sweeps in legacy mode on
            # Windows, which is slower than the pyEDM parallel path.
            mod_timeout = 600 if mod == 'ccm_causality.py' else 300
            try:
                proc = subprocess.run(
                    [sys.executable, path], cwd=_SRC,
                    capture_output=True, text=True, timeout=mod_timeout)
                ok = proc.returncode == 0
                check(ok, f"{mod}: self-test exit code {proc.returncode}")
                if not ok and VERBOSE:
                    print(proc.stdout[-2000:])
                    print(proc.stderr[-2000:])
            except subprocess.TimeoutExpired:
                check(False, f"{mod}: self-test timed out (>300s)")


# ── Main ──────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='EDM-Takens Skill Test Runner')
    parser.add_argument('--quick', action='store_true',
                       help='Skip slow tests (Lorenz, logistic)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show all check results')
    args = parser.parse_args()

    QUICK = args.quick
    VERBOSE = args.verbose

    print("=" * 60)
    print("  EDM-TAKENS SKILL — AUTOMATED TEST SUITE")
    print(f"  Quick mode: {QUICK}  |  Verbose: {VERBOSE}")
    print("=" * 60)

    section("RUNNING ALL LAYERS")

    test_environment()
    test_core_engine()
    test_auditor()
    test_cross_validation()
    test_canonical_ccm()
    test_secrets_4_5()
    test_game_data()
    test_e2e_interpretation()
    test_module_self_tests()

    ok = result()
    sys.exit(0 if ok else 1)
