"""Provider capability detection for GraphRAG compatibility."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityProfile:
    supports_json_response_format: bool
    reason: str


def detect_profile(model_config: Any) -> CapabilityProfile:
    """Detect JSON response-mode support from env and model configuration."""
    override = os.environ.get("GRAPHRAG_JSON_MODE", "auto").strip().lower()
    if override == "off":
        return CapabilityProfile(False, "GRAPHRAG_JSON_MODE=off")
    if override == "on":
        return CapabilityProfile(True, "GRAPHRAG_JSON_MODE=on")

    model = str(getattr(model_config, "model", "") or "")
    provider = str(getattr(model_config, "model_provider", "") or "")
    extra = getattr(model_config, "model_extra", None) or {}
    api_base = str(extra.get("api_base", "") or getattr(model_config, "api_base", "") or "")
    probe = f"{provider} {model} {api_base}".lower()

    incompatible_tokens = ("deepseek", "ollama", "127.0.0.1:15721", "localhost:15721")
    if any(token in probe for token in incompatible_tokens):
        return CapabilityProfile(False, f"provider/model does not support JSON response mode: {probe}")
    return CapabilityProfile(True, "provider appears to support JSON response mode")