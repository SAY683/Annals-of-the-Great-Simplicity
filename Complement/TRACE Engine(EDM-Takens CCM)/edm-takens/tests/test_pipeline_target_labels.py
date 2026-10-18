"""Regression tests for pipeline spike target labels."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline import _spike_target_label


def test_spike_label_uses_selected_target_not_result_column():
    row = pd.Series({"ate": -0.22, "adj_density": 0.5})
    assert _spike_target_label(row, "ate", is_binary=False) == "ate=-0.22"


def test_spike_label_keeps_binary_game_semantics():
    assert _spike_target_label(pd.Series({"result": 1}), "result", is_binary=True) == "W"
    assert _spike_target_label(pd.Series({"result": 0}), "result", is_binary=True) == "L"


def test_spike_label_handles_missing_and_nan_target():
    assert _spike_target_label(pd.Series({"ate": np.nan}), "ate") == "ate=?"
    assert _spike_target_label(pd.Series({"other": 1.0}), "ate") == "ate=?"