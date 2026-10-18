#!/usr/bin/env python3
"""GraphRAG CLI entrypoint with provider-capability compatibility installed first."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graphrag_compat import install  # noqa: E402

install()

from graphrag.cli.main import app  # noqa: E402

if __name__ == "__main__":
    app(prog_name="graphrag")