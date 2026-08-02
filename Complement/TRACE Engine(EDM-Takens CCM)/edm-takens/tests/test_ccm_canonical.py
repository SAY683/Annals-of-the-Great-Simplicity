"""
Canonical CCM delegation tests.

Verifies that the two downstream wrappers (final_interpretation.ccm_with_convergence
and enhanced_cross_validate.verify_ccm_direction) delegate to the canonical
ccm_causality_test implementation rather than reimplementing verdict logic.
"""
import os
import sys
import inspect

import numpy as np
import pandas as pd

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

from ccm_causality import ccm_causality_test
from final_interpretation import ccm_with_convergence
from enhanced_cross_validate import verify_ccm_direction


def _coupled_logistic(n=400):
    np.random.seed(0)
    x = np.zeros(n); y = np.zeros(n)
    x[0], y[0] = 0.4, 0.2
    rx, ry, coupling = 3.8, 3.5, 0.1
    for t in range(1, n):
        x[t] = x[t-1] * (rx - rx * x[t-1] - coupling * y[t-1])
        y[t] = y[t-1] * (ry - ry * y[t-1] - coupling * x[t-1])
        x[t] = np.clip(x[t], 1e-6, 1 - 1e-6)
        y[t] = np.clip(y[t], 1e-6, 1 - 1e-6)
    return pd.DataFrame({'x': x[100:], 'y': y[100:]})


def test_downstream_wrappers_delegate_to_canonical():
    """Source-inspection check: only one convergence-verdict logic exists."""
    src_final = inspect.getsource(ccm_with_convergence)
    src_cross = inspect.getsource(verify_ccm_direction)
    assert 'ccm_causality_test(' in src_final, (
        "final_interpretation.ccm_with_convergence() no longer delegates "
        "to ccm_causality_test() — verdict logic may have been re-duplicated.")
    assert 'ccm_causality_test(' in src_cross, (
        "enhanced_cross_validate.verify_ccm_direction() no longer delegates "
        "to ccm_causality_test() — verdict logic may have been re-duplicated.")


def test_wrapper_smoke_consistency():
    """Both wrappers agree in direction/verdict on a strongly-coupled fixture."""
    df = _coupled_logistic()
    r_final = ccm_with_convergence(df, 'x', 'y', 3)
    r_cross = verify_ccm_direction(df, 'x', 'y', 3)
    assert r_final['forward']['final_rho'] > 0.5
    assert r_cross['forward_skill'] > 0.5
    assert r_final['forward']['is_converging'] is True
    assert r_cross['forward_converging'] is True
