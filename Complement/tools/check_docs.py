#!/usr/bin/env python3
"""Check relative Markdown links inside the Complement source tree.

Usage:
  python tools/check_docs.py
  python tools/check_docs.py --root .

The check intentionally ignores external URLs, anchors, code blocks and generated
dependency directories. Exit code 1 means at least one relative target is missing.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

SKIP_DIRS = {'.git', '.venv', '__pycache__', 'node_modules', 'release'}
LINK = re.compile(r'(?<!!)\[[^\]]*\]\((<[^>]+>|[^)]+)\)')


def markdown_files(root: Path):
    for path in root.rglob('*.md'):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def visible_lines(text: str):
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    checked = 0
    broken = []
    for path in markdown_files(root):
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            text = path.read_text(encoding='utf-8', errors='replace')
        for line in visible_lines(text):
            for match in LINK.finditer(line):
                raw = match.group(1).strip()
                if raw.startswith('<') and raw.endswith('>'):
                    raw = raw[1:-1]
                target = urllib.parse.unquote(raw.split('#', 1)[0].split('?', 1)[0].strip())
                if not target or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                    continue
                checked += 1
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    broken.append((path, raw, resolved))
    print(f'[docs] checked {checked} relative links in {root}')
    for path, raw, resolved in broken:
        print(f'[docs] BROKEN {path.relative_to(root)} -> {raw} ({resolved})', file=sys.stderr)
    if broken:
        print(f'[docs] {len(broken)} broken link(s)', file=sys.stderr)
        return 1
    print('[docs] all relative links resolve')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())