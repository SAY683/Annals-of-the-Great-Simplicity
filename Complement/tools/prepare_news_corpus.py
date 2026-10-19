#!/usr/bin/env python3
"""Normalize public WeChat HTML exports into plain text in parallel.

This tool performs local preprocessing only: no network, login, cookies, or
history discovery. Article bodies remain in the caller-selected output
directory and should normally be Git-ignored.

Example:
  python tools/prepare_news_corpus.py --html-dir news/html --out-dir news/normalized --workers 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bs4 import BeautifulSoup


def normalize_html(path: Path, out_dir: Path, metadata: dict) -> dict:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    def one(selector: str) -> str:
        node = soup.select_one(selector)
        return node.get_text(" ", strip=True) if node else ""
    content = soup.select_one("#js_content")
    text = content.get_text("\n", strip=True) if content else ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{path.stem}.txt"
    txt_path.write_text(text, encoding="utf-8")
    meta = metadata.get(path.stem, {})
    return {
        "id": path.stem,
        "title": meta.get("title") or one("#activity-name"),
        "account": meta.get("account") or one("#js_name"),
        "date": meta.get("date") or one("#publish_time"),
        "url": meta.get("url", ""),
        "chars": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "html_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "text_path": str(txt_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--manifest", type=Path, default=None,
                    help="optional manifest.json with id/title/account/date/url")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    html_dir = args.html_dir.resolve()
    out_dir = args.out_dir.resolve()
    files = sorted(html_dir.glob("*.html"))
    if not files:
        raise SystemExit(f"no .html files under {html_dir}")

    metadata = {}
    if args.manifest and args.manifest.exists():
        raw = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        if isinstance(raw, list):
            metadata = {str(item.get("id")): item for item in raw if isinstance(item, dict)}
        elif isinstance(raw, dict):
            metadata = raw

    workers = max(1, min(int(args.workers), len(files)))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(normalize_html, path, out_dir, metadata) for path in files]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["id"])
    index_path = out_dir / "corpus_index.json"
    index_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[news] normalized {len(results)} articles with {workers} workers")
    print(f"[news] chars={sum(r['chars'] for r in results)} min={min(r['chars'] for r in results)} max={max(r['chars'] for r in results)}")
    print(f"[news] index={index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())