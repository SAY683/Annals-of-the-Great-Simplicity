#!/usr/bin/env python3
"""Verify local model weights for the Complement portable suite.

The model directories are intentionally kept in two places:
  * Complement/TRACE Engine(EDM-Takens CCM)/Models/
  * Complement/TRACE Engine(EDM-Takens CCM)/trace-engine/Models/

Do not move or delete them. This script only checks presence, size and optional
SHA256, and prints the ModelScope download command when something is missing.

Usage:
  python tools/verify_models.py
  python tools/verify_models.py --sha256
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = ROOT / "TRACE Engine(EDM-Takens CCM)"

MODELSCOPE = {
    "shenji-llama": "modelscope download say101/TRACE-Engine-EDM-Takens-CCM-shenji-llama-470m",
    "shehui-llama": "modelscope download say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-27m",
    "shehui-llama-v4-archive": "modelscope download say101/TRACE-Engine-EDM-Takens-CCM-shehui-llama-470m",
    "Qwen2.5-1.5B-Instruct": "modelscope download qwen/Qwen2.5-1.5B-Instruct",
    "Qwen2.5-3B-Instruct": "modelscope download qwen/Qwen2.5-3B-Instruct",
}

# path, expected bytes, required, note
MANIFEST = [
    ("Models/Qwen2.5-1.5B-Instruct/model.safetensors", 3_087_467_144, True, "trace-to-edm L3 / portable marker"),
    ("Models/Qwen2.5-3B-Instruct/model-00001-of-00002.safetensors", 3_968_658_944, False, "optional 3B L3"),
    ("Models/Qwen2.5-3B-Instruct/model-00002-of-00002.safetensors", 2_203_268_048, False, "optional 3B L3"),
    ("Models/shehui-llama/model.safetensors", 101_369_216, True, "SUPER default"),
    ("Models/shenji-llama/model.safetensors", 1_875_583_416, True, "SUPER theology"),
    ("Models/shehui-llama-v4-archive/model.safetensors", 1_880_199_616, False, "archive"),
    ("trace-engine/Models/shehui-llama/model.safetensors", 101_369_216, True, "engine mirror"),
    ("trace-engine/Models/shenji-llama/model.safetensors", 1_875_583_416, True, "engine mirror"),
    ("trace-engine/Models/shehui-llama-v4-archive/model.safetensors", 1_880_199_616, False, "engine archive mirror"),
]


def resolve_case_insensitive(root: Path, relative: str) -> Path:
    """Resolve a manifest path even when a checkout uses models/ vs Models/."""
    current = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        exact = current / part
        if exact.exists():
            current = exact
            continue
        wanted = part.casefold()
        try:
            match = next(
                (child for child in current.iterdir() if child.name.casefold() == wanted),
                None,
            )
        except OSError:
            match = None
        if match is None:
            return current.joinpath(*parts[index:])
        current = match
    return current


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256", action="store_true", help="compute SHA256 (slow, reads all weights)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []
    missing_required = False
    for rel, expected, required, note in MANIFEST:
        path = resolve_case_insensitive(TRACE_ROOT, rel)
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        ok_size = exists and size == expected
        row = {
            "path": str(path.relative_to(ROOT)),
            "expected_bytes": expected,
            "actual_bytes": size,
            "exists": exists,
            "size_ok": ok_size,
            "required": required,
            "note": note,
        }
        if args.sha256 and exists:
            row["sha256"] = sha256(path)
        if required and not ok_size:
            missing_required = True
        rows.append(row)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("Complement Model Manifest")
        print("=" * 88)
        for row in rows:
            mark = "OK  " if row["size_ok"] else ("MISS" if not row["exists"] else "SIZE")
            flag = "required" if row["required"] else "optional"
            print(f"[{mark}] {row['path']}")
            print(f"       {flag}; expected={row['expected_bytes']:,}; actual={row['actual_bytes']:,}; {row['note']}")
            if not row["size_ok"]:
                parts = Path(row["path"]).parts
                name = next((part for part in reversed(parts) if part in MODELSCOPE), "")
                if name:
                    print(f"       fix: {MODELSCOPE[name]}")
        print("=" * 88)
        if missing_required:
            print("Required model files are missing or have unexpected sizes.")
            print("Download weights from ModelScope, then place .safetensors in the listed directories.")
            print("See Docs/10-models.md for details. Do not move/delete the two model directories.")
        else:
            print("All required model files are present with expected sizes.")
    return 1 if missing_required else 0


if __name__ == "__main__":
    raise SystemExit(main())