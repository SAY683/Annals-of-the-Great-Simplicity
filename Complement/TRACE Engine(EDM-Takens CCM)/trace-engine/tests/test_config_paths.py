"""Regression tests for case-sensitive portable model paths."""

from pathlib import Path

import _config


def test_get_trace_models_dir_prefers_models_capitalization(tmp_path, monkeypatch):
    root = tmp_path / "trace"
    models = root / "Models"
    models.mkdir(parents=True)
    monkeypatch.setenv("TRACE_ROOT", str(root))

    assert _config.get_trace_models_dir() == models


def test_get_trace_models_dir_accepts_legacy_lowercase(tmp_path, monkeypatch):
    root = tmp_path / "trace"
    models = root / "models"
    models.mkdir(parents=True)
    monkeypatch.setenv("TRACE_ROOT", str(root))

    assert _config.get_trace_models_dir() == models


def test_nested_engine_layout_detects_capital_models(tmp_path):
    product = tmp_path / "product"
    model = product / "trace-engine" / "Models" / "shehui-llama"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"x")

    assert _config._is_nested_engine_trace_root(product)