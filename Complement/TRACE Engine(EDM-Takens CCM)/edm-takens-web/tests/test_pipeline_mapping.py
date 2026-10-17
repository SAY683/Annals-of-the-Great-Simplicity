"""Regression tests for edm-takens-web column remapping.

The old positional zip(schema_aliases, other_vars) could swap an existing
`deaths` / `damage` pair when the CSV already used canonical game-log names.
"""
import sys
from pathlib import Path

import pandas as pd

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))
sys.path.insert(0, str(WEB_ROOT.parent / "edm-takens" / "src"))

from services.file_management import _prepare_pipeline_data  # noqa: E402


def _write_csv(path: Path, frame: pd.DataFrame) -> str:
    frame.to_csv(path, index=False)
    return str(path)


def test_canonical_game_log_columns_are_not_swapped(tmp_path):
    frame = pd.DataFrame({
        "game": [1, 2, 3, 4],
        "result": [1, 0, 1, 0],
        "kills": [2, 1, 4, 0],
        "deaths": [0, 3, 1, 2],
        "damage": [100, 80, 130, 40],
        "mvp": [1, 0, 1, 0],
    })
    csv_path = _write_csv(tmp_path / "game_log.csv", frame)
    path, target, variables, original_target, display_map = _prepare_pipeline_data(
        csv_path, "result", ["result", "kills", "deaths", "damage", "mvp"]
    )

    assert target == "result"
    assert original_target == "result"
    assert display_map == {}
    assert path == csv_path
    assert variables[:1] == ["result"]


def test_noncanonical_columns_map_to_unused_aliases(tmp_path):
    frame = pd.DataFrame({
        "outcome": [1, 0, 1, 0],
        "alpha": [2, 1, 4, 0],
        "beta": [0, 3, 1, 2],
        "gamma": [100, 80, 130, 40],
    })
    csv_path = _write_csv(tmp_path / "custom.csv", frame)
    path, target, variables, original_target, display_map = _prepare_pipeline_data(
        csv_path, "outcome", ["outcome", "alpha", "beta", "gamma"]
    )

    assert target == "result"
    assert original_target == "outcome"
    assert display_map == {
        "result": "outcome",
        "kills": "alpha",
        "damage": "beta",
        "deaths": "gamma",
    }
    assert variables == ["result", "kills", "damage", "deaths"]
    mapped = pd.read_csv(path)
    assert mapped["kills"].tolist() == frame["alpha"].tolist()
    assert mapped["damage"].tolist() == frame["beta"].tolist()
    assert mapped["deaths"].tolist() == frame["gamma"].tolist()
