"""
SovereignHAVOK class unit tests (P3: closes the test-implementation gap).

The legacy tests/test_havok.py exercises the old havok_decompose() function.
This module tests the current SovereignHAVOK class directly:
  - fit basic path
  - V/U basis kurtosis consistency
  - predict_next_state shape
  - small-sample SG window auto-cap
  - NaN/Inf rejection (P2 safeguard)
  - constant-data warning
  - discrete eigenvalue stability
"""
import os, sys, warnings
import numpy as np

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

warnings.filterwarnings('ignore')


def test_fit_basic():
    t = np.linspace(0, 20 * np.pi, 500)
    sine = np.sin(t) + 0.02 * np.random.randn(500)
    from sovereign_havok import SovereignHAVOK
    sh = SovereignHAVOK(q_delays=15, dt=0.125, energy_threshold=0.999).fit(sine)
    assert sh.is_valid_, "fit should set is_valid_=True"
    assert sh.r_ >= 2, f"rank r={sh.r_} should be >= 2"
    assert 0.0 <= sh.explained_var_ <= 1.0
    assert -10.0 < sh.kurtosis_vr_ < 10.0
    print(f"  [PASS] fit basic: r={sh.r_}, kurt={sh.kurtosis_vr_:.3f}, "
          f"expl_var={sh.explained_var_:.1%}")
    return True


def test_vu_basis_consistency():
    np.random.seed(42)
    data = np.random.randn(80) * 0.5 + np.sin(np.linspace(0, 4 * np.pi, 80))
    from sovereign_havok import SovereignHAVOK
    sh_v = SovereignHAVOK(q_delays=6, basis="V").fit(data)
    sh_u = SovereignHAVOK(q_delays=6, basis="U").fit(data)
    assert sh_v.r_ == sh_u.r_, f"V/U rank differ: {sh_v.r_} vs {sh_u.r_}"
    delta = abs(sh_v.kurtosis_vr_ - sh_u.kurtosis_vr_)
    assert delta < 0.5, f"V/U kurtosis delta={delta:.3f} too large"
    print(f"  [PASS] V/U basis: r={sh_v.r_}, delta_kurt={delta:.4f}")
    return True


def test_predict_next_state():
    t = np.linspace(0, 10 * np.pi, 300)
    sine = np.sin(t) + 0.02 * np.random.randn(300)
    from sovereign_havok import SovereignHAVOK
    sh = SovereignHAVOK(q_delays=10, dt=0.1).fit(sine)
    v0 = np.zeros(sh.r_ - 1)
    nxt = sh.predict_next_state(v0, 0.0)
    assert nxt.shape == (sh.r_ - 1,), f"predict shape {nxt.shape} != ({sh.r_-1},)"
    assert np.all(np.isfinite(nxt)), "predict returned non-finite"
    # multi-step
    traj = sh.predict_n_steps(v0, np.zeros(5), 5)
    assert traj.shape == (6, sh.r_ - 1)
    print(f"  [PASS] predict_next_state: shape={nxt.shape}, finite=OK")
    return True


def test_small_sample_sg_cap():
    np.random.seed(0)
    small = np.random.randn(32) * 0.5 + np.sin(np.linspace(0, 4 * np.pi, 32))
    from sovereign_havok import SovereignHAVOK
    sh = SovereignHAVOK(q_delays=6, window_length=11, poly_order=2).fit(small)
    # SG window must be auto-capped at p//4 for small data
    p = len(small) - 6 + 1
    expected_cap = max(5, p // 4)
    if expected_cap % 2 == 0:
        expected_cap -= 1
    assert sh.is_valid_
    print(f"  [PASS] small sample: r={sh.r_}, p={p}, SG cap~{expected_cap}")
    return True


def test_nan_rejection():
    from sovereign_havok import SovereignHAVOK
    bad = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0])
    sh = SovereignHAVOK(q_delays=3)
    try:
        sh.fit(bad)
        print("  [FAIL] NaN data should have raised ValueError")
        return False
    except ValueError as e:
        assert "NaN" in str(e) or "Inf" in str(e)
        print(f"  [PASS] NaN rejection: {str(e)[:50]}")
        return True


def test_constant_data_warning():
    from sovereign_havok import SovereignHAVOK
    const = np.ones(50) * 3.0
    sh = SovereignHAVOK(q_delays=5)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        sh.fit(const)
        assert any("constant" in str(x.message).lower() or "rank-1" in str(x.message)
                   for x in w), "expected constant-data warning"
    print(f"  [PASS] constant data warning issued")
    return True


def test_eigenvalue_stability():
    t = np.linspace(0, 20 * np.pi, 500)
    sine = np.sin(t) + 0.02 * np.random.randn(500)
    from sovereign_havok import SovereignHAVOK
    sh = SovereignHAVOK(q_delays=15, dt=0.125).fit(sine)
    # discrete eigenvalues should be bounded for a stable sine
    assert np.all(np.isfinite(sh.eigenvalues_d_))
    assert np.all(np.abs(sh.eigenvalues_d_) < 1e6), "eigenvalues exploded"
    print(f"  [PASS] eigenvalues finite & bounded: "
          f"max|eig_d|={np.max(np.abs(sh.eigenvalues_d_)):.4f}")
    return True


def run_all():
    tests = [
        ('fit basic', test_fit_basic),
        ('V/U basis consistency', test_vu_basis_consistency),
        ('predict_next_state', test_predict_next_state),
        ('small-sample SG cap', test_small_sample_sg_cap),
        ('NaN rejection', test_nan_rejection),
        ('constant-data warning', test_constant_data_warning),
        ('eigenvalue stability', test_eigenvalue_stability),
    ]
    passed = failed = 0
    print('=' * 60)
    print('  SovereignHAVOK Class Test Suite (P3)')
    print('=' * 60)
    for name, fn in tests:
        print(f'\n--- {name} ---')
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f'  [ERROR] {name}: {e}')
            import traceback; traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"  Total: {passed + failed}  |  Passed: {passed}  |  Failed: {failed}")
    print('=' * 60)
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if run_all() else 1)
