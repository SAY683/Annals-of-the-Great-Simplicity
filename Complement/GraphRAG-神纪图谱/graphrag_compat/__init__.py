"""Runtime compatibility layer for GraphRAG provider capabilities."""

from .capabilities import CapabilityProfile, detect_profile
from .runtime import install

__all__ = ["CapabilityProfile", "detect_profile", "install"]