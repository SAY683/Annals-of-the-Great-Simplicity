"""TRACE content cache and environment parsing contract."""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bridge


def test_trace_cache_roundtrip_and_failure_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_TRACE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(bridge, "_TRACE_CACHE_DISABLED", False)
    key = bridge._trace_cache_key("同一个文本", "light")
    assert bridge._trace_cache_key("另一个文本", "light") != key
    assert bridge._trace_cache_key("同一个文本", "deep") != key

    source = tmp_path / "source.json"
    source.write_text(json.dumps({"success": True, "ate": 0.1}), encoding="utf-8")
    bridge._store_trace_cache(key, source)
    output = tmp_path / "output"
    assert bridge._load_trace_cache(key, output) is True
    assert json.loads((output / "result.json").read_text(encoding="utf-8"))["ate"] == 0.1

    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"success": False, "error": "boom"}), encoding="utf-8")
    failed_key = bridge._trace_cache_key("失败文本", "light")
    bridge._store_trace_cache(failed_key, failed)
    assert bridge._load_trace_cache(failed_key, tmp_path / "failed-out") is False


def test_env_int_is_bounded_and_safe(monkeypatch):
    monkeypatch.setenv("TRACE_PREFETCH_WORKERS", "999")
    assert bridge._env_int("TRACE_PREFETCH_WORKERS", 2, 0, 8) == 8
    monkeypatch.setenv("TRACE_PREFETCH_WORKERS", "not-a-number")
    assert bridge._env_int("TRACE_PREFETCH_WORKERS", 2, 0, 8) == 2