"""Tolerant JSON extraction shared by all GraphRAG fallback paths."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> str:
    """Strip markdown fences/stray prose and repair common model JSON slips."""
    if not text:
        return text
    value = str(text).strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start:end + 1]
    value = re.sub(r",\s*([}\]])", r"\1", value)
    return value


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object with a json-repair fallback."""
    cleaned = extract_json_object(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    try:
        import json_repair
        parsed = json_repair.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    raise ValueError("model response did not contain a parseable JSON object")