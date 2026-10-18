#!/usr/bin/env python3
"""Cross-machine Python capability doctor for the Complement toolchain.

Usage:
  python tools/check_env.py
  python tools/check_env.py --json
  python tools/check_env.py --required numpy,pandas,jieba,dowhy,causallearn

Candidate order is portable-first: explicit component variables, .venv,
COMPLEMENT_PYTHON_CANDIDATES, Windows py launcher, then PATH. No machine-specific
drive is assumed. Exit code 0 means at least one candidate has every required module.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import importlib.util, json, sys
mods = ["numpy","pandas","scipy","sklearn","jieba","dowhy","causallearn",
        "pyEDM","fastapi","uvicorn","torch","transformers","graphrag","lancedb","mcp"]
print(json.dumps({
    "python": sys.executable,
    "version": sys.version.split()[0],
    "modules": {m: bool(importlib.util.find_spec(m)) for m in mods},
}, ensure_ascii=False))
'''

DEFAULT_REQUIRED = ["numpy", "pandas", "scipy", "sklearn", "jieba", "dowhy", "causallearn"]
USEFUL = ["pyEDM", "fastapi", "uvicorn", "torch", "transformers", "graphrag", "lancedb", "mcp"]


def _probe(exe: str) -> dict | None:
    try:
        p = subprocess.run([exe, "-c", PROBE], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        if p.returncode != 0:
            return None
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def _candidates() -> list[str]:
    out: list[str] = []
    for key in ("TRACE_PYTHON_CMD", "EDM_PYTHON_CMD", "GRAPHRAG_PYTHON"):
        value = os.environ.get(key)
        if value:
            out.append(value)
    out.append(str(ROOT / ".venv" / "Scripts" / "python.exe"))
    out.append(str(ROOT / ".venv" / "bin" / "python"))
    for value in os.environ.get("COMPLEMENT_PYTHON_CANDIDATES", "").split(os.pathsep):
        if value.strip():
            out.append(value.strip())
    py = shutil.which("py")
    if py:
        for ver in ("-3.13", "-3.12", "-3.11", "-3.10"):
            try:
                p = subprocess.run([py, ver, "-c", "import sys; print(sys.executable)"],
                                   capture_output=True, text=True, timeout=10)
                if p.returncode == 0 and p.stdout.strip():
                    out.append(p.stdout.strip())
            except Exception:
                pass
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            out.append(found)
    out.append(sys.executable)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--required", default=",".join(DEFAULT_REQUIRED))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    required = [x.strip() for x in args.required.split(",") if x.strip()]

    seen: set[str] = set()
    rows = []
    for cand in _candidates():
        if not cand or cand in seen:
            continue
        seen.add(cand)
        exe = cand
        if not Path(exe).exists():
            found = shutil.which(cand)
            if not found:
                continue
            exe = found
        probe = _probe(exe)
        if not probe:
            continue
        missing = [m for m in required if not probe["modules"].get(m)]
        rows.append({
            "path": probe["python"],
            "version": probe["version"],
            "ok": not missing,
            "missing": missing,
            "useful": {m: probe["modules"].get(m, False) for m in USEFUL},
        })

    rows.sort(key=lambda r: (not r["ok"], len(r["missing"]), r["path"]))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("Complement Python Doctor")
        print("=" * 78)
        for r in rows:
            mark = "OK  " if r["ok"] else "MISS"
            print(f"[{mark}] {r['path']}  ({r['version']})")
            if r["missing"]:
                print(f"        missing: {', '.join(r['missing'])}")
            print("        useful: " + ", ".join(
                f"{k}={'Y' if v else 'N'}" for k, v in r["useful"].items()))
        if not rows:
            print("No Python candidates found.")
        print("=" * 78)
        print(f"required: {', '.join(required)}")

    return 0 if any(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())