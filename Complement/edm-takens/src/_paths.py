"""
Skill path resolution. Import this to get skill-root-relative paths.
"""
import os

_SKILL_SRC = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(_SKILL_SRC)
SKILL_DATA = os.path.join(SKILL_ROOT, 'data')


def data_path(filename: str) -> str:
    """Get absolute path to a data file in the skill's data/ directory."""
    return os.path.join(SKILL_DATA, filename)
