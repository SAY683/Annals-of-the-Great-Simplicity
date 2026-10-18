"""Tests for the provider-capability compatibility layer."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graphrag_compat.capabilities import detect_profile
from graphrag_compat.json_utils import extract_json_object, parse_json_object
from graphrag_compat.runtime import CapabilityAwareCompletion


class Payload:
    @classmethod
    def model_validate(cls, value):
        return SimpleNamespace(ok=value["ok"])


def test_deepseek_profile_disables_json_response_format(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_JSON_MODE", raising=False)
    profile = detect_profile(SimpleNamespace(model="deepseek-v4-flash", model_provider="openai", model_extra={}))
    assert profile.supports_json_response_format is False


def test_explicit_json_mode_override(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_JSON_MODE", "on")
    profile = detect_profile(SimpleNamespace(model="deepseek-v4-flash", model_provider="openai", model_extra={}))
    assert profile.supports_json_response_format is True
    monkeypatch.setenv("GRAPHRAG_JSON_MODE", "off")
    profile = detect_profile(SimpleNamespace(model="gpt-4o", model_provider="openai", model_extra={}))
    assert profile.supports_json_response_format is False


def test_json_fence_and_trailing_comma_are_repaired():
    raw = '```json\n{"answer": "ok", "items": [1, 2,],}\n```'
    assert parse_json_object(raw) == {"answer": "ok", "items": [1, 2]}
    assert extract_json_object(raw).startswith("{")


def test_capability_wrapper_strips_unsupported_json_mode():
    class Inner:
        def __init__(self):
            self.kwargs = None

        def completion(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(content='{"ok": true}', formatted_response=None)

    inner = Inner()
    profile = SimpleNamespace(supports_json_response_format=False)
    wrapped = CapabilityAwareCompletion(inner, profile)
    response = wrapped.completion(messages=[], response_format_json_object=True)
    assert inner.kwargs == {"messages": []}
    assert response.content == '{"ok": true}'


def test_thread_pool_is_wrapped_and_formats_responses():
    class Inner:
        def __init__(self):
            self.seen = None

        def completion(self, **kwargs):
            self.seen = kwargs
            return SimpleNamespace(content='```json\n{"ok": true,}\n```', formatted_response=None)

        @contextmanager
        def completion_thread_pool(self, *, response_handler, concurrency, queue_limit=0):
            def submit(request_id, **request):
                response_handler(request_id, self.completion(**request))
            yield submit

    inner = Inner()
    wrapped = CapabilityAwareCompletion(inner, SimpleNamespace(supports_json_response_format=False))
    results = []

    with wrapped.completion_thread_pool(
        response_handler=lambda request_id, response: results.append((request_id, response)),
        concurrency=2,
    ) as submit:
        submit(request_id="a", messages=[], response_format=Payload)

    assert "response_format" not in inner.seen
    assert results[0][1].formatted_response.ok is True


def test_batch_retries_provider_json_mode_rejection():
    class Unsupported(Exception):
        status_code = 400

    class Inner:
        def __init__(self):
            self.calls = []

        def completion(self, **kwargs):
            self.calls.append(kwargs)
            if "response_format" in kwargs:
                raise Unsupported("unsupported response_format parameter")
            return SimpleNamespace(content='{"ok": true}', formatted_response=None)

        @contextmanager
        def completion_thread_pool(self, *, response_handler, concurrency, queue_limit=0):
            def submit(request_id, **request):
                try:
                    response = self.completion(**request)
                except Exception as error:
                    response = error
                response_handler(request_id, response)
            yield submit

    inner = Inner()
    wrapped = CapabilityAwareCompletion(inner, SimpleNamespace(supports_json_response_format=True))
    results = wrapped.completion_batch(
        [{"messages": [], "response_format": Payload}],
        concurrency=1,
    )

    assert len(inner.calls) == 2
    assert "response_format" in inner.calls[0]
    assert "response_format" not in inner.calls[1]
    assert results[0].formatted_response.ok is True