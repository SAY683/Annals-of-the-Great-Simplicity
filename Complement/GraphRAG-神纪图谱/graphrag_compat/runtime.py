"""In-memory GraphRAG capability compatibility layer.

This module never edits site-packages. It wraps graphrag_llm completion objects
at runtime so provider capability decisions apply to all GraphRAG call sites.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

from .capabilities import CapabilityProfile, detect_profile
from .json_utils import parse_json_object

_INSTALLED = False


def _is_response_format(value: Any) -> bool:
    return isinstance(value, type) and hasattr(value, "model_validate")


def _response_content(response: Any) -> str:
    content = getattr(response, "content", None)
    if content:
        return str(content)
    try:
        return str(response.choices[0].message.content or "")
    except Exception:
        return ""


def _with_formatted_response(response: Any, response_format: Any) -> Any:
    if response is None or response_format is None or not _is_response_format(response_format):
        return response
    if getattr(response, "formatted_response", None) is not None:
        return response
    try:
        parsed = response_format.model_validate(parse_json_object(_response_content(response)))
        if hasattr(response, "model_copy"):
            return response.model_copy(update={"formatted_response": parsed})
        try:
            response.formatted_response = parsed
        except Exception:
            pass
    except Exception:
        pass
    return response


def _prepare_kwargs(kwargs: dict[str, Any], profile: CapabilityProfile):
    response_format = kwargs.get("response_format")
    json_object = kwargs.get("response_format_json_object")
    outgoing = dict(kwargs)
    if not profile.supports_json_response_format:
        outgoing.pop("response_format", None)
        outgoing.pop("response_format_json_object", None)
    return outgoing, response_format, json_object or response_format


def _without_json_mode(kwargs: dict[str, Any]) -> dict[str, Any]:
    retry = dict(kwargs)
    retry.pop("response_format", None)
    retry.pop("response_format_json_object", None)
    return retry


def _is_retryable(error: Exception) -> bool:
    text = str(error).lower()
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    return status in (400, 404, 422) or any(token in text for token in (
        "response_format", "json mode", "json_object", "unsupported parameter",
    ))


class CapabilityAwareCompletion:
    """Delegate to an LLM completion while normalizing provider capabilities."""

    def __init__(self, inner: Any, profile: CapabilityProfile):
        self._inner = inner
        self._profile = profile

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _sync_call(self, method_name: str, kwargs: dict[str, Any]):
        outgoing, response_format, fallback_format = _prepare_kwargs(kwargs, self._profile)
        method = getattr(self._inner, method_name)
        try:
            response = method(**outgoing)
        except Exception as error:
            if self._profile.supports_json_response_format and (response_format or fallback_format) and _is_retryable(error):
                response = method(**_without_json_mode(kwargs))
            else:
                raise
        return _with_formatted_response(response, fallback_format)

    def completion(self, /, **kwargs: Any):
        return self._sync_call("completion", kwargs)

    async def completion_async(self, /, **kwargs: Any):
        outgoing, response_format, fallback_format = _prepare_kwargs(kwargs, self._profile)
        method = getattr(self._inner, "completion_async")
        try:
            response = await method(**outgoing)
        except Exception as error:
            if self._profile.supports_json_response_format and (response_format or fallback_format) and _is_retryable(error):
                response = await method(**_without_json_mode(kwargs))
            else:
                raise
        return _with_formatted_response(response, fallback_format)

    def completion_batch(
        self,
        completion_requests,
        *,
        concurrency: int,
        queue_limit: int = 0,
    ):
        """Batch through the compatibility thread pool, including retries/formatting."""
        responses: list[Any] = [None] * len(completion_requests)

        def handle_response(request_id: str, response: Any) -> None:
            responses[int(request_id)] = response

        with self.completion_thread_pool(
            response_handler=handle_response,
            concurrency=concurrency,
            queue_limit=queue_limit,
        ) as submit:
            for index, request in enumerate(completion_requests):
                submit(request_id=str(index), **dict(request))
        return responses

    @contextmanager
    def completion_thread_pool(self, **kwargs):
        """Mirror GraphRAG's thread-pool contract while wrapping every request."""
        response_handler: Callable[[str, Any], Any] = kwargs.pop("response_handler")
        pending: dict[str, dict[str, Any]] = {}
        formats: dict[str, Any] = {}

        def handle_response(request_id: str, response: Any):
            fallback_format = formats.pop(request_id, None)
            original = pending.pop(request_id, None)
            if (
                isinstance(response, Exception)
                and original is not None
                and fallback_format is not None
                and self._profile.supports_json_response_format
                and _is_retryable(response)
            ):
                try:
                    response = self._inner.completion(**_without_json_mode(original))
                except Exception as error:
                    response = error
            if not isinstance(response, Exception):
                response = _with_formatted_response(response, fallback_format)
            return response_handler(request_id, response)

        with self._inner.completion_thread_pool(
            response_handler=handle_response,
            **kwargs,
        ) as submit:
            def submit_compatible(request_id: str, **request: Any):
                outgoing, _response_format, fallback_format = _prepare_kwargs(
                    request,
                    self._profile,
                )
                pending[request_id] = dict(request)
                formats[request_id] = fallback_format
                return submit(request_id=request_id, **outgoing)

            yield submit_compatible


def install() -> None:
    """Install the compatibility wrapper once, before GraphRAG imports its modules."""
    global _INSTALLED
    if _INSTALLED:
        return
    import graphrag_llm.completion as completion_module

    original = completion_module.create_completion
    if getattr(original, "_graphrag_compat", False):
        _INSTALLED = True
        return

    def create_completion(model_config, *args, **kwargs):
        inner = original(model_config, *args, **kwargs)
        return CapabilityAwareCompletion(inner, detect_profile(model_config))

    create_completion._graphrag_compat = True
    completion_module.create_completion = create_completion

    try:
        from graphrag.index.operations.summarize_communities.community_reports_extractor import (
            CommunityReportResponse,
        )

        original_validate = CommunityReportResponse.model_validate_json.__func__

        @classmethod
        def tolerant_validate_json(cls, data, *args, **kwargs):
            from .json_utils import extract_json_object

            return original_validate(cls, extract_json_object(data), *args, **kwargs)

        CommunityReportResponse.model_validate_json = tolerant_validate_json
    except Exception:
        pass
    _INSTALLED = True