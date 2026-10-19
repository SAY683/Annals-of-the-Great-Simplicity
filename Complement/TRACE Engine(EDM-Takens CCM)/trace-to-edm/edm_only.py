#!/usr/bin/env python3
"""Lightweight EDM-only trigger.

This avoids importing the full bridge (pandas/Qwen layers) when the Web route
only needs to submit an EDM job. The full bridge remains the CLI compatibility
path for `bridge.py --edm-only`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from edm_trigger import EDMTrigger


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="ate")
    ap.add_argument("--q", type=int, default=3)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--time-start", default=None)
    ap.add_argument("--time-end", default=None)
    ap.add_argument("--predict-window", type=int, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    trigger = EDMTrigger()
    result = trigger.run_analysis(
        target_col=args.target,
        q=args.q,
        wait=not args.no_wait,
        time_start=args.time_start,
        time_end=args.time_end,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())