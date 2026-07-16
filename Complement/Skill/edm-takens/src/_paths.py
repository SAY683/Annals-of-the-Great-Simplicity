"""
Skill path resolution. Import this to get skill-root-relative paths.

Supports EDMTAKENS_DATA_DIR environment variable so deployments can
redirect data lookups to a custom folder (e.g., uploaded files).
"""
import os

_SKILL_SRC = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(_SKILL_SRC)
SKILL_DATA = os.environ.get(
    'EDMTAKENS_DATA_DIR',
    os.path.join(SKILL_ROOT, 'examples', 'game_analysis', 'data')
)


def data_path(filename: str) -> str:
    """Get absolute path to a data file. Defaults to SKILL_DATA."""
    return os.path.join(SKILL_DATA, filename)
