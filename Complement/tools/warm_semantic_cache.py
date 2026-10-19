#!/usr/bin/env python3
r"""Precompute Qwen semantic embeddings for a local plain-text corpus.

This tool is intentionally offline: it reads .txt files, calls the same
`encode_text` implementation used by trace-to-edm, and stores content-addressed
.vectors in TRACE_EMBEDDING_CACHE_DIR (or the active project's cache).

Example:
  $env:TRACE_EMBEDDING_CACHE_DIR = "$env:TEMP\semantic-news"
  python tools\warm_semantic_cache.py --corpus-dir news\normalized
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", required=True, type=Path)
    ap.add_argument("--pattern", default="*.txt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[2]
    trace_to_edm = repo / "Complement" / "TRACE Engine(EDM-Takens CCM)" / "trace-to-edm"
    if not trace_to_edm.is_dir():
        raise SystemExit(f"trace-to-edm not found: {trace_to_edm}")
    sys.path.insert(0, str(trace_to_edm))

    from layer3_sacred import encode_text  # noqa: E402

    corpus_dir = args.corpus_dir.resolve()
    files = sorted(corpus_dir.glob(args.pattern))
    if args.limit > 0:
        files = files[:args.limit]
    if not files:
        raise SystemExit(f"no files matching {args.pattern!r} under {corpus_dir}")

    failures = []
    started = time.time()
    for index, path in enumerate(files, 1):
        item_started = time.time()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            vector = encode_text(text)
            status = f"dim={vector.shape[0]}"
        except Exception as exc:
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            status = "FAILED"
        if not args.quiet:
            elapsed = time.time() - item_started
            print(f"[semantic] {index}/{len(files)} {path.name} {status} {elapsed:.1f}s", flush=True)

    elapsed = time.time() - started
    print(f"[semantic] completed {len(files) - len(failures)}/{len(files)} in {elapsed:.1f}s")
    for name, error in failures:
        print(f"[semantic] FAILED {name}: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())