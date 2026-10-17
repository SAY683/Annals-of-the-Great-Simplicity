"""CSV contract regression tests for trace-to-edm."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csv_builder import COLUMN_COUNT, TrajectoryCSV  # noqa: E402


def test_column_count_contract():
    assert COLUMN_COUNT == 89


def test_all_columns_are_grouped_without_other(tmp_path):
    manager = TrajectoryCSV(csv_path=tmp_path / "trajectory.csv")
    groups = manager.get_columns_by_layer()

    assert len(groups["meta"]) == 7
    assert len(groups["layer1"]) == 30
    assert len(groups["layer2"]) == 4
    assert len(groups["layer3"]) == 48
    assert groups["other"] == []
    assert sum(len(v) for v in groups.values()) == COLUMN_COUNT


def test_provenance_column_is_meta(tmp_path):
    manager = TrajectoryCSV(csv_path=tmp_path / "trajectory.csv")
    groups = manager.get_columns_by_layer()

    assert "trace_data_source" in groups["meta"]