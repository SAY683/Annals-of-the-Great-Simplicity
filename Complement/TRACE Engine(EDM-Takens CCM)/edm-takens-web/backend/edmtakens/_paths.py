"""
Skill path resolution. Import this to get skill-root-relative paths.

Web variant: supports EDMTAKENS_DATA_DIR environment variable so the
FastAPI backend can redirect data lookups to the uploaded-file folder.
"""
import os

_SKILL_SRC = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(_SKILL_SRC)
SKILL_DATA = os.environ.get(
    'EDMTAKENS_DATA_DIR',
    os.path.join(SKILL_ROOT, '..', '..', 'edm-takens', 'examples', 'game_analysis', 'data')
)


def data_path(filename: str) -> str:
    """Get absolute path to a data file. Defaults to SKILL_DATA."""
    return os.path.join(SKILL_DATA, filename)
