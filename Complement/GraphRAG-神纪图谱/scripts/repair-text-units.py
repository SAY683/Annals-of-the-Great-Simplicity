#!/usr/bin/env python3
"""Repair U+FFFD in GraphRAG text units and optionally rebuild vectors.

Usage:
  python scripts/repair-text-units.py --dry-run
  python scripts/repair-text-units.py
  python scripts/repair-text-units.py --rebuild-vectors
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "project" / "output"
LANCEDB = OUT / "lancedb"
EMBED_URL = "http://127.0.0.1:8081/v1/embeddings"
MODEL = "bge-m3"
FFFD = "\ufffd"


def sha512_text(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def repair_one(text: str, document: str) -> tuple[str, int, int]:
    if FFFD not in text:
        return text, 0, 0
    chunks = re.split(r"(\ufffd+)", text)
    parts = []
    replaced = 0
    for chunk in chunks:
        if chunk.startswith(FFFD):
            parts.append("." * len(chunk))
            replaced += len(chunk)
        else:
            parts.append(re.escape(chunk))
    pattern = "".join(parts)
    matches = list(re.finditer(pattern, document, flags=re.S))
    if not matches:
        return text, 0, 0
    if len(matches) == 1:
        best = matches[0]
    else:
        best = max(matches, key=lambda m: difflib.SequenceMatcher(None, text, m.group(0)).ratio())
    return best.group(0), replaced, len(matches)


def remap_list(value, mapping):
    if value is None:
        return value
    try:
        return [mapping.get(str(x), str(x)) for x in value]
    except TypeError:
        return value


def embed_texts(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    out = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        payload = json.dumps({"model": MODEL, "input": batch}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            EMBED_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data") or []
        if len(items) != len(batch):
            raise RuntimeError(f"embedding response size mismatch: {len(items)} != {len(batch)}")
        out.extend([item["embedding"] for item in items])
    return out


def rebuild_vectors(text_units: pd.DataFrame) -> None:
    import lancedb

    db = lancedb.connect(str(LANCEDB))
    old = db.open_table("text_unit_text").to_pandas()
    old_by_id = {str(r["id"]): r for _, r in old.iterrows()}

    texts = [str(x) for x in text_units["text"].tolist()]
    print(f"[vectors] re-embedding all {len(texts)} text units ...")
    vectors = embed_texts(texts)

    rows = []
    for (_, row), vector in zip(text_units.iterrows(), vectors):
        new_id = str(row["id"])
        base = old_by_id.get(new_id)
        meta = {}
        if base is not None:
            for key, value in base.items():
                if key not in ("id", "vector"):
                    meta[key] = value
        else:
            now = datetime.now(timezone.utc).isoformat()
            meta["create_date"] = now
            meta["update_date"] = now
        meta["id"] = new_id
        meta["vector"] = vector
        rows.append(meta)

    df = pd.DataFrame(rows)
    db.create_table("text_unit_text", data=df, mode="overwrite")
    new_table = db.open_table("text_unit_text")
    try:
        new_table.create_index(metric="cosine", vector_column_name="vector")
    except Exception as e:
        print(f"[vectors] warning: index creation skipped: {e}")
    print(f"[vectors] rebuilt text_unit_text with {len(df)} rows")

def main() -> int:
    global EMBED_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rebuild-vectors", action="store_true")
    ap.add_argument("--embedding-url", default=EMBED_URL)
    args = ap.parse_args()

    documents = pd.read_parquet(OUT / "documents.parquet")
    document = str(documents.iloc[0]["text"])
    text_units = pd.read_parquet(OUT / "text_units.parquet")
    old_ids = [str(x) for x in text_units["id"].tolist()]
    mapping = {}
    repaired_rows = []
    total_replaced = 0

    for i, row in text_units.iterrows():
        old_text = str(row["text"])
        new_text, replaced, match_count = repair_one(old_text, document)
        if FFFD in new_text:
            print(f"[repair] WARN unit {i} still contains U+FFFD (matches={match_count})")
        if new_text != old_text:
            old_id = old_ids[i]
            new_id = sha512_text(new_text)
            mapping[old_id] = new_id
            total_replaced += replaced
            print(f"[repair] unit {i}: {replaced} char(s), id {old_id[:12]} -> {new_id[:12]}")
        repaired_rows.append(new_text)

    text_units["text"] = repaired_rows
    text_units["id"] = [sha512_text(x) for x in repaired_rows]

    if args.dry_run:
        print(f"[repair] dry-run: {total_replaced} characters would be repaired; parquet not written")
        return 0

    for filename in ("entities.parquet", "relationships.parquet", "documents.parquet", "communities.parquet"):
        path = OUT / filename
        df = pd.read_parquet(path)
        if "text_unit_ids" in df.columns:
            df["text_unit_ids"] = df["text_unit_ids"].map(lambda v: remap_list(v, mapping))
            df.to_parquet(path, index=False)

    text_units.to_parquet(OUT / "text_units.parquet", index=False)
    version_path = OUT / "data_version.json"
    try:
        previous = json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        previous = {}
    version = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entities": int(len(pd.read_parquet(OUT / "entities.parquet"))),
        "relationships": int(len(pd.read_parquet(OUT / "relationships.parquet"))),
        "communities": int(len(pd.read_parquet(OUT / "communities.parquet"))),
        "text_units": int(len(text_units)),
        "repaired_chars": int(previous.get("repaired_chars", 0)) + int(total_replaced),
        "remapped_ids": int(previous.get("remapped_ids", 0)) + len(mapping),
        "text_unit_hash": hashlib.sha256("\n".join(text_units["id"].astype(str)).encode("utf-8")).hexdigest(),
    }
    version_path.write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[repair] wrote text_units.parquet and data_version.json ({len(mapping)} id remaps)")

    if args.rebuild_vectors:
        rebuild_vectors(text_units)
    else:
        print("[vectors] skipped; pass --rebuild-vectors after starting the 8081 embedding service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())