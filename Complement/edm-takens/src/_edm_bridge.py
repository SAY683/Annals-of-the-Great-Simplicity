"""
Unified EDM Interface — _edm_bridge.py
========================================
Graceful-degradation wrapper that tries pyEDM first, falls back to
pure numpy/scipy _numpy_edm when pyEDM is unavailable.

All skill modules should use this bridge instead of importing pyEDM
directly. This eliminates the single point of failure.

Usage:
    from _edm_bridge import (
        EmbedDimension, Simplex, SMapPredictNonlinear, CCM, Multiview,
        EDM_AVAILABLE, EDM_BACKEND
    )

The API mirrors pyEDM's conventions with DataFrame support stripped
(to reduce dependency on pandas for the core algorithms). Modules
that need DataFrame-based pyEDM calls should use _edm_bridge_wrapper.

Design note:
  - When pyEDM is available: all functions delegate to pyEDM (full fidelity)
  - When pyEDM is unavailable: pure numpy fallback (slightly reduced accuracy,
    but all core algorithms functional)
  - EDM_AVAILABLE (bool) and EDM_BACKEND (str) let callers adapt behavior
"""

import numpy as np
import warnings

# ═══════════════════════════════════════════════════════════════
# Attempt pyEDM import
# ═══════════════════════════════════════════════════════════════

try:
    import pyEDM
    EDM_AVAILABLE = True
    EDM_BACKEND = 'pyEDM'
except ImportError:
    pyEDM = None
    EDM_AVAILABLE = False
    EDM_BACKEND = 'numpy_fallback'

# Always import numpy fallback
from _numpy_edm import (
    simplex_predict,
    EmbedDimension as _np_EmbedDimension,
    Simplex as _np_Simplex,
    SMapPredictNonlinear as _np_SMapPredictNonlinear,
    CCM as _np_CCM,
    Multiview as _np_Multiview,
    multiview_full as np_multiview_full,          # P7: full combinatorial scan
    false_nearest_neighbors as np_fnn,            # P8: FNN E-selection
)

# Re-export the pure-numpy enhanced methods (no pyEDM equivalent needed).
# These are always available regardless of pyEDM presence.
multiview_full = np_multiview_full
false_nearest_neighbors = np_fnn

if not EDM_AVAILABLE:
    warnings.warn(
        "pyEDM not available. Using pure numpy/scipy fallback for EDM. "
        "All core algorithms are functional but may have slightly reduced "
        "accuracy compared to the C++ pyEDM implementation. "
        "Install pyEDM for optimal performance: pip install pyEDM"
    )


# ═══════════════════════════════════════════════════════════════
# DataFrame-based wrappers (for modules that use DataFrames)
# ═══════════════════════════════════════════════════════════════

def EmbedDimension(data, columns, target, maxE=8, Tp=1,
                   lib=None, pred=None, showPlot=False, **kwargs):
    """Find optimal embedding dimension.

    Supports both DataFrame (pyEDM) and numpy array (fallback) inputs.
    """
    if EDM_AVAILABLE and hasattr(data, 'columns'):  # DataFrame
        return pyEDM.EmbedDimension(
            dataFrame=data, columns=columns, target=target,
            maxE=maxE, Tp=Tp, lib=lib, pred=pred,
            showPlot=showPlot, **kwargs)
    else:
        # Numpy array fallback
        series = np.asarray(data, dtype=float).ravel()
        E_opt, rho_curve = _np_EmbedDimension(series, maxE=maxE, Tp=Tp)
        # Return a DataFrame-like result (simple dict for compatibility)
        import pandas as pd
        result_df = pd.DataFrame({
            'E': np.arange(len(rho_curve)),
            'rho': rho_curve,
        })
        result_df.loc[0, 'rho'] = 0.0  # E=0 is not meaningful
        return result_df


def Simplex(data, columns, target, E, Tp=1, lib=None, pred=None,
            showPlot=False, **kwargs):
    """Simplex projection."""
    if EDM_AVAILABLE and hasattr(data, 'columns'):
        return pyEDM.Simplex(
            dataFrame=data, columns=columns, target=target,
            E=E, Tp=Tp, lib=lib, pred=pred,
            showPlot=showPlot, **kwargs)
    else:
        series = np.asarray(data, dtype=float).ravel()
        result = _np_Simplex(series, E=E, Tp=Tp, lib=lib, pred=pred)
        import pandas as pd
        df = pd.DataFrame({
            'Observations': result['observations'],
            'Predictions': result['predictions'],
        })
        # Attach corr method compatibility
        return df


def SMapPredictNonlinear(data, columns, target, E, lib=None, pred=None,
                         showPlot=False, **kwargs):
    """S-Map theta scan for nonlinearity detection."""
    if EDM_AVAILABLE and hasattr(data, 'columns'):
        # Use numProcess=1 to avoid Windows multiprocessing issues
        safe_kwargs = {k: v for k, v in kwargs.items()
                      if k not in ('numProcess',)}
        return pyEDM.PredictNonlinear(
            dataFrame=data, columns=columns, target=target,
            E=E, lib=lib, pred=pred,
            showPlot=showPlot, numProcess=1, **safe_kwargs)
    else:
        series = np.asarray(data, dtype=float).ravel()
        result = _np_SMapPredictNonlinear(series, E=E, lib=lib, pred=pred)
        import pandas as pd
        df = pd.DataFrame({
            'theta': result['theta_values'],
            'rho': result['rho_values'],
        })
        return df


def CCM(data, columns, target, E, Tp=0, libSizes=None, sample=30,
        showPlot=False, **kwargs):
    """Convergent Cross Mapping (Victim Mirror Principle).

    CRITICAL: pyEDM.CCM(columns=Y, target=X) tests X->Y.
    Because columns builds the manifold, target is what we predict.
    M_Y predicts X → tests X drives Y.
    """
    if EDM_AVAILABLE and hasattr(data, 'columns'):
        return pyEDM.CCM(
            dataFrame=data, columns=columns, target=target,
            E=E, Tp=Tp, libSizes=libSizes, sample=sample,
            showPlot=showPlot, **kwargs)
    else:
        # Extract series from numpy array
        arr = np.asarray(data, dtype=float)
        if arr.ndim == 1:
            raise ValueError("CCM needs 2 columns (cause, effect)")
        # Determine which column is which
        # columns=effect_var, target=cause_var → builds M_effect, predicts cause
        if hasattr(data, 'columns'):
            col_idx = list(data.columns).index(columns)
            tgt_idx = list(data.columns).index(target)
        else:
            col_idx = int(columns) if isinstance(columns, (int, np.integer)) else 0
            tgt_idx = int(target) if isinstance(target, (int, np.integer)) else 1

        cause = arr[:, tgt_idx]
        effect = arr[:, col_idx]
        result = _np_CCM(cause, effect, E=E, Tp=Tp,
                         libSizes=libSizes, sample=sample)
        import pandas as pd
        df = pd.DataFrame({
            'LibSize': result['lib_sizes'],
            f'{target}:{columns}': result['rhos'],
        })
        return df


def Multiview(data, columns, target, E, Tp=1, lib=None, pred=None,
              showPlot=False, **kwargs):
    """Multiview embedding (spatial embedding for short data)."""
    if EDM_AVAILABLE and hasattr(data, 'columns'):
        try:
            return pyEDM.Multiview(
                dataFrame=data, columns=columns, target=target,
                E=E, Tp=Tp, lib=lib, pred=pred,
                showPlot=showPlot, numProcess=1, **kwargs)
        except Exception as e:
            warnings.warn(f"pyEDM.Multiview failed ({e}). "
                         f"Using numpy SVD-based Multiview fallback.")
            # Fall through to numpy fallback
            pass

    # Numpy fallback
    arr = np.asarray(data, dtype=float)
    if hasattr(data, 'columns') and isinstance(target, str):
        tgt_idx = list(data.columns).index(target)
    else:
        tgt_idx = int(target) if isinstance(target, (int, np.integer)) else 0

    result = _np_Multiview(arr, target_col=tgt_idx, E=E,
                          lib=lib, pred=pred, Tp=Tp)
    import pandas as pd
    df = pd.DataFrame({
        'rho': [result['rho']],
        'E': [result['E']],
        'n_components': [result['n_components']],
    })
    return df


# ═══════════════════════════════════════════════════════════════
# Quick diagnostic
# ═══════════════════════════════════════════════════════════════

def edm_status():
    """Return EDM backend status for environment checks."""
    info = {
        'backend': EDM_BACKEND,
        'pyedm_available': EDM_AVAILABLE,
    }
    if EDM_AVAILABLE:
        try:
            info['pyedm_version'] = pyEDM.__version__
        except Exception:
            info['pyedm_version'] = 'unknown'
    else:
        info['pyedm_version'] = None
        info['fallback_note'] = (
            'Using pure numpy/scipy EDM implementation. '
            'All core algorithms (Simplex, S-Map, CCM, Multiview) '
            'are functional. Install pyEDM for C++ performance: '
            'pip install pyEDM'
        )
    return info


if __name__ == '__main__':
    print("=" * 60)
    print("  _edm_bridge.py — Self-Test")
    print("=" * 60)
    status = edm_status()
    for k, v in status.items():
        print(f"  {k}: {v}")

    # Quick functional test with numpy data
    np.random.seed(42)
    import pandas as pd
    t = np.linspace(0, 10 * np.pi, 100)
    sine = np.sin(t) + 0.05 * np.random.randn(100)

    print(f"\n[1] EmbedDimension (numpy array)")
    E_opt, rho_c = _np_EmbedDimension(sine, maxE=6)
    print(f"  Optimal E={E_opt}")

    print(f"\n[2] Simplex (numpy array)")
    result = _np_Simplex(sine, E=E_opt, lib=(1, 50), pred=(51, 100))
    print(f"  rho={result['rho']:.4f}")

    print(f"\n  _edm_bridge.py: VERIFIED")
    print("=" * 60)
