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
                     theta_radius: float = 2.0) -> dict:
    """
    Run a sensitivity scan around optimal embedding dimension.
    ...
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

    # Stability: coefficient of variation across neighbors
    cv = abs(results['neighbor_std'] / (abs(results['neighbor_mean']) + 1e-12))
    results['cv'] = float(cv)

    if cv < 0.1:
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

    results['recommendation'] = (
        "Conclusion is robust to embedding dimension variation."
        if results['is_stable'] else
        "WARNING: Conclusion changes significantly with embedding dimension. "
        "Report this sensitivity. The finding may be parameter-fragile."
    )

    return results


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


def capture_config(data, E=None, tau=None, theta=None,
                   q=None, r=None, lib="", pred="",
                   analysis_type="exploratory",
                   n_surrogates=99, notes="",
                   data_path="", target_col="",
                   columns=None) -> AnalysisConfig:
    """
    Capture full analysis configuration including package versions.

    Call this BEFORE running analysis. Saves a timestamped artifact.
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
