#!/usr/bin/env python3
"""Verify the GraphRAG runtime, data version and data quality.

The default mode blocks only on installation/data-integrity problems. The LLM
proxy and embedding service are reported as advisory warnings because they are
started only when a query is run. Use ``--require-services`` when you want a
strict runtime gate (for example before an E2E query test).

Usage:
  python scripts/verify-env.py
  python scripts/verify-env.py --no-services
  python scripts/verify-env.py --data-only --no-services
  python scripts/verify-env.py --require-services
  python scripts/verify-env.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import socket
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "project" / "output"
REQUIRED = {
    "graphrag": "3.1.1",
    "lancedb": "0.34.0",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "numpy": "2.4.6",
    "networkx": "3.6.1",
    "mcp": "2.0.0",
    "openai": "2.53.0",
    "tiktoken": "0.13.0",
    "python-dotenv": "1.2.2",
    "json-repair": "0.61.7",
}
REQUIRED_OUTPUTS = (
    "entities.parquet",
    "relationships.parquet",
    "communities.parquet",
    "text_units.parquet",
    "documents.parquet",
)
COUNT_KEYS = {
    "entities": "entities.parquet",
    "relationships": "relationships.parquet",
    "communities": "communities.parquet",
    "text_units": "text_units.parquet",
}


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def text_unit_hash(text_units: pd.DataFrame) -> str:
    ids = [str(x) for x in text_units["id"].tolist()]
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def add_check(checks: list[dict], name: str, ok: bool, *, actual=None,
              expected=None, blocking: bool = True, hint: str | None = None) -> None:
    row = {
        "check": name,
        "ok": bool(ok),
        "blocking": bool(blocking),
        "actual": actual,
        "expected": expected,
    }
    if hint:
        row["hint"] = hint
    checks.append(row)


def alias_check(checks: list[dict]) -> None:
    path = ROOT / "mcp" / "entity_aliases.json"
    add_check(checks, "entity_aliases.json", path.exists(), actual=str(path), expected="exists")
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = data.get("groups", [])
        valid = isinstance(groups, list) and all(
            isinstance(g, dict)
            and isinstance(g.get("canonical"), str)
            and bool(g["canonical"].strip())
            and isinstance(g.get("aliases"), list)
            and all(isinstance(a, str) and a.strip() for a in g["aliases"])
            for g in groups
        )
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        if valid:
            for group in groups:
                canonical = group["canonical"]
                for alias in group["aliases"]:
                    key = alias.casefold()
                    owner = seen.get(key)
                    if owner is not None and owner != canonical:
                        duplicates.append(f"{alias} ({owner} / {canonical})")
                    else:
                        seen[key] = canonical
        add_check(
            checks,
            "entity_aliases schema",
            valid and not duplicates,
            actual={"groups": len(groups), "duplicates": duplicates} if valid else "invalid",
            expected="valid groups, no cross-group duplicate aliases",
        )
    except Exception as e:
        add_check(checks, "entity_aliases schema", False, actual=str(e), expected="valid JSON")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-services", action="store_true",
                    help="make 8081/15721 availability blocking")
    ap.add_argument("--no-services", action="store_true",
                    help="do not probe query-time services")
    ap.add_argument("--data-only", action="store_true",
                    help="skip package checks and validate data/version consistency only")
    args = ap.parse_args()
    if args.require_services and args.no_services:
        ap.error("--require-services and --no-services are mutually exclusive")

    checks: list[dict] = []
    if not args.data_only:
        for pkg, expected in REQUIRED.items():
            try:
                actual = metadata.version(pkg)
                add_check(checks, f"package:{pkg}", actual == expected, actual=actual, expected=expected)
            except Exception:
                add_check(checks, f"package:{pkg}", False, actual=None, expected=expected)

    add_check(checks, "output dir", OUT.is_dir(), actual=str(OUT), expected="exists")
    for filename in REQUIRED_OUTPUTS:
        path = OUT / filename
        add_check(checks, f"output:{filename}", path.is_file(), actual=str(path), expected="exists")

    version_path = OUT / "data_version.json"
    version: dict = {}
    if version_path.exists():
        try:
            version = json.loads(version_path.read_text(encoding="utf-8"))
        except Exception:
            version = {}
    add_check(
        checks,
        "data_version.json",
        bool(version),
        actual=version.get("generated_at"),
        expected="generated",
        hint="run scripts/repair-text-units.py or regenerate the index",
    )

    tables: dict[str, pd.DataFrame] = {}
    for key, filename in COUNT_KEYS.items():
        path = OUT / filename
        try:
            tables[key] = pd.read_parquet(path)
        except Exception as e:
            add_check(checks, f"read:{filename}", False, actual=str(e), expected="readable parquet")

    actual_counts = {key: len(table) for key, table in tables.items()}
    expected_counts = {key: version.get(key) for key in actual_counts}
    add_check(
        checks,
        "data_version counts",
        bool(version) and actual_counts == expected_counts,
        actual=actual_counts,
        expected=expected_counts,
        hint="re-run scripts/repair-text-units.py after replacing parquet files",
    )

    text_units = tables.get("text_units")
    if text_units is not None and "text" in text_units.columns:
        ufffd = int(text_units["text"].fillna("").astype(str).str.count("\ufffd").sum())
        add_check(checks, "text_units U+FFFD", ufffd == 0, actual=ufffd, expected=0)
    else:
        add_check(checks, "text_units U+FFFD", False, actual="text column unavailable", expected=0)

    if text_units is not None and "id" in text_units.columns:
        actual_hash = text_unit_hash(text_units)
        add_check(
            checks,
            "data_version text_unit_hash",
            bool(version.get("text_unit_hash")) and actual_hash == version.get("text_unit_hash"),
            actual=actual_hash[:16],
            expected=str(version.get("text_unit_hash", ""))[:16],
            hint="parquet IDs and data_version.json are out of sync",
        )
    else:
        add_check(checks, "data_version text_unit_hash", False,
                  actual="id column unavailable", expected="sha256 over text-unit ids")

    if not args.data_only and text_units is not None and "id" in text_units.columns:
        try:
            import lancedb

            db = lancedb.connect(str(OUT / "lancedb"))
            vectors = db.open_table("text_unit_text").to_pandas()
            parquet_ids = {str(x) for x in text_units["id"].tolist()}
            vector_ids = {str(x) for x in vectors["id"].tolist()} if "id" in vectors.columns else set()
            vector_dims = sorted({len(v) for v in vectors["vector"].tolist()}) if "vector" in vectors.columns else []
            add_check(
                checks,
                "LanceDB vector/parquet sync",
                len(vectors) == len(text_units) and parquet_ids == vector_ids and len(vector_dims) == 1,
                actual={"rows": len(vectors), "id_set_matches": parquet_ids == vector_ids, "dims": vector_dims},
                expected={"rows": len(text_units), "id_set_matches": True, "dims": "one consistent dimension"},
                hint="re-run scripts/repair-text-units.py --rebuild-vectors",
            )
        except Exception as e:
            add_check(checks, "LanceDB vector/parquet sync", False, actual=str(e), expected="readable vector table")

    alias_check(checks)

    if not args.no_services:
        blocking = bool(args.require_services)
        for port, label in ((8081, "embedding"), (15721, "LLM proxy")):
            up = port_open(port)
            add_check(
                checks,
                f"port:{port} {label}",
                up,
                actual="listening" if up else "closed",
                expected="listening",
                blocking=blocking,
                hint="required only while running GraphRAG queries; use --require-services for a strict gate",
            )

    overall_ok = all(c["ok"] or not c["blocking"] for c in checks)
    warnings = [c for c in checks if not c["ok"] and not c["blocking"]]

    if args.json:
        print(json.dumps({
            "ok": overall_ok,
            "warnings": len(warnings),
            "checks": checks,
            "data_version": version,
        }, ensure_ascii=False, indent=2))
    else:
        print("GraphRAG Runtime Check")
        print("=" * 72)
        for c in checks:
            mark = "PASS" if c["ok"] else ("WARN" if not c["blocking"] else "FAIL")
            print(f"[{mark}] {c['check']}: actual={c['actual']} expected={c['expected']}")
            if not c["ok"] and c.get("hint"):
                print(f"       hint: {c['hint']}")
        print("=" * 72)
        print(f"data_version: {version.get('generated_at')} | "
              f"text_unit_hash: {str(version.get('text_unit_hash', ''))[:16]}")
        if warnings:
            print(f"{len(warnings)} advisory service warning(s); core data checks are separate.")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())