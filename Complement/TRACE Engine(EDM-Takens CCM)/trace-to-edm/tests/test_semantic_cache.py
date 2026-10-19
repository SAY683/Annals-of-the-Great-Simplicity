"""Content-addressed semantic embedding cache contract."""

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import layer3_sacred


def test_embedding_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_EMBEDDING_CACHE_DIR", str(tmp_path))
    text = "新能源汽车价格战与市场结构变化"
    key = layer3_sacred._embedding_cache_key(text)
    vector = np.linspace(0.1, 1.0, 1536, dtype=np.float64)
    vector /= np.linalg.norm(vector)
    layer3_sacred._store_embedding_cache(key, vector)

    loaded = layer3_sacred._load_embedding_cache(key, 1536)
    assert loaded is not None
    assert loaded.shape == (1536,)
    assert np.isclose(np.linalg.norm(loaded), 1.0)
    assert np.allclose(loaded, vector)

    assert layer3_sacred._load_embedding_cache(key, 2048) is None
    assert layer3_sacred._embedding_cache_key(text + "（增补）") != key


def test_embedding_cache_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_EMBEDDING_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TRACE_EMBEDDING_CACHE_DISABLE", "1")
    text = "disabled cache"
    key = layer3_sacred._embedding_cache_key(text)
    vector = np.ones(1536, dtype=np.float64) / np.sqrt(1536)
    layer3_sacred._store_embedding_cache(key, vector)
    assert layer3_sacred._load_embedding_cache(key, 1536) is None
    assert not list(tmp_path.glob("*.npy"))