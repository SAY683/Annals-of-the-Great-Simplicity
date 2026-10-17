#!/usr/bin/env python3
"""Verify the web layer consumes the single canonical edm-takens source."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "edm-takens" / "src"
PYPROJECT = ROOT / "edm-takens" / "pyproject.toml"
DUPLICATE_COPY = ROOT / "edm-takens-web" / "backend" / "edmtakens"
REQUIRED = [
    "_numpy_edm", "sovereign_havok", "pipeline", "edm_auditor",
    "enhanced_cross_validate", "environment_check", "final_interpretation",
    "ccm_causality", "_edm_bridge", "_paths", "verify_algorithms",
    "edm_adaptive_pipeline", "edm_tau_optimization", "sensitivity_config",
    "router", "surrogate_test", "multiview_svd_monitor", "_usability",
    "data_quality", "analysis_profiles",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    failures = []

    if not SRC.is_dir():
        failures.append(f"canonical source missing: {SRC}")
    if not PYPROJECT.is_file():
        failures.append(f"editable package metadata missing: {PYPROJECT}")
    if DUPLICATE_COPY.exists():
        failures.append(f"duplicate algorithm copy still exists: {DUPLICATE_COPY}")

    missing = [name for name in REQUIRED if not (SRC / f"{name}.py").is_file()]
    if missing:
        failures.append("missing source modules: " + ", ".join(missing))

    if SRC.is_dir() and str(SRC) not in sys.path:
        sys.path.append(str(SRC))
    if importlib.util.find_spec("pipeline") is None:
        failures.append("pipeline module is not importable from canonical source")

    if failures:
        print("SOURCE-LAYOUT CHECK FAILED")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 1

    if args.quiet:
        print(f"source-only layout OK: {len(REQUIRED)} modules in edm-takens/src")
    else:
        print("EDM-TAKENS source layout check")
        print("=" * 64)
        print(f"canonical source: {SRC}")
        print("web duplicate copy: absent")
        print(f"required modules: {len(REQUIRED)}/{len(REQUIRED)} present")
        print("pipeline import: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
