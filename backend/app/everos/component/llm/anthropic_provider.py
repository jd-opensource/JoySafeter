"""Anthropic Messages API provider for EverOS LLM calls."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from app.everos.core.observability.logging import get_logger

from .protocol import ChatMessage, ChatResponse, LLMError, Usage

logger = get_logger(__name__)

# Transient upstream failures worth retrying (gateway flaps: "no channels
# available", 429 throttling, 502/504 proxy hiccups). 4xx (except 429) are
# caller/config errors and are not retried.
_LLM_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_LLM_MAX_ATTEMPTS = 4
_LLM_BACKOFF_BASE_SECONDS = 0.8


class AnthropicProvider:
    """Thin async wrapper over Anthropic's Messages API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self._timeout = float(timeout)
        self._temperature = temperature
        self._max_tokens = max_tokens
        # Serialize in-flight requests on this client. The upstream gateway
        # (ai-api.jdcloud.com) has been observed to cross concurrent responses
        # — e.g. an episode-extraction request receiving a parallel
        # foresight-extraction request's body — which then fails schema
        # validation downstream. Extraction is background / best-effort, so
        # trading intra-client concurrency for correctness is the right call.
        # Per client instance (per-project singleton); distinct projects still
        # run in parallel.
        self._request_lock = asyncio.Lock()

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> ChatResponse:
        """Send a Messages API request and return the parsed response."""
        if response_format is not None:
            extra = {**extra, "response_format": dict(response_format)}
        system, anthropic_messages = _normalise_messages(messages)
        request: dict[str, Any] = {
            "model": model or self._model,
            "messages": anthropic_messages,
            "temperature": (
                temperature if temperature is not None else self._temperature
            ),
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
        }
        if system:
            request["system"] = system
        request.update(extra)

        # Cache-bust: the upstream gateway (ai-api.jdcloud.com) keys a response
        # cache on request content, and has been observed to return a *different*
        # extraction call's cached body for a request over the same conversation
        # — e.g. an episode-extraction request receiving the foresight response
        # for that conversation, which then fails episode schema validation.
        # A unique per-request nonce forces a cache miss so every call gets its
        # own response. (Validated: appending a nonce fixes the cross-talk while
        # a serialization lock alone does not.)
        _append_request_nonce(request)

        url = _messages_url(self._base_url)
        started = monotonic()
        log_scope = {
            "provider": "anthropic",
            "model": str(request["model"]),
            "base_url_host": _base_url_host(self._base_url),
            "timeout_seconds": self._timeout,
        }

        # The upstream gateway flaps with transient 5xx / 429 (e.g. "no channels
        # available for model ...") and connection resets. Extraction issues
        # several sequential LLM calls, so a single transient failure otherwise
        # aborts the whole episode. Retry transient failures with backoff; the
        # lock is released between attempts (backoff sleep sits outside it).
        response: httpx.Response | None = None
        for attempt in range(_LLM_MAX_ATTEMPTS):
            try:
                async with self._request_lock:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.post(
                            url,
                            headers={
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json",
                                "x-api-key": self._api_key,
                            },
                            json=request,
                        )
                        response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status in _LLM_RETRYABLE_STATUS and attempt + 1 < _LLM_MAX_ATTEMPTS
                logger.warning(
                    "llm_request_failed",
                    **log_scope,
                    elapsed_ms=_elapsed_ms(started),
                    status_code=status,
                    error_type=type(exc).__name__,
                    attempt=attempt + 1,
                    will_retry=retryable,
                )
                if retryable:
                    await asyncio.sleep(_LLM_BACKOFF_BASE_SECONDS * (2**attempt))
                    continue
                raise LLMError(exc.response.text) from exc
            except httpx.HTTPError as exc:
                retryable = attempt + 1 < _LLM_MAX_ATTEMPTS
                logger.warning(
                    "llm_request_failed",
                    **log_scope,
                    elapsed_ms=_elapsed_ms(started),
                    error_type=type(exc).__name__,
                    attempt=attempt + 1,
                    will_retry=retryable,
                )
                if retryable:
                    await asyncio.sleep(_LLM_BACKOFF_BASE_SECONDS * (2**attempt))
                    continue
                raise LLMError(str(exc)) from exc

        logger.info(
            "llm_request_completed",
            **log_scope,
            elapsed_ms=_elapsed_ms(started),
            status_code=response.status_code,
        )
        body = response.json()
        usage = body.get("usage") or {}
        return ChatResponse(
            content=_content_text(body.get("content") or []),
            model=str(body.get("model") or request["model"]),
            usage=Usage(
                prompt_tokens=int(usage.get("input_tokens") or 0),
                completion_tokens=int(usage.get("output_tokens") or 0),
            ),
            finish_reason=_normalise_stop_reason(body.get("stop_reason")),
            raw=None,
        )


def _messages_url(base_url: str) -> str:
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def _append_request_nonce(request: dict[str, Any]) -> None:
    """Append a unique nonce to the request so a content-keyed upstream cache
    cannot serve another call's cached response for the same conversation.

    Mutates ``request`` in place. The nonce rides as an HTML comment appended
    to the last message's text — invisible to the model's task, but enough to
    change whatever content hash the gateway keys its cache on. If the last
    message shape is unrecognised, a ``metadata`` marker is used as a fallback.
    """
    marker = f"\n\n<!-- request-nonce: {uuid.uuid4().hex} -->"
    messages = request.get("messages")
    if isinstance(messages, list) and messages:
        last = messages[-1]
        if isinstance(last, dict):
            content = last.get("content")
            if isinstance(content, str):
                last["content"] = content + marker
                return
            if isinstance(content, list):
                last["content"] = [*content, {"type": "text", "text": marker}]
                return
    # Fallback: Anthropic ignores unknown top-level keys, but the gateway still
    # hashes the body, so a nonce field also busts the cache.
    request["metadata"] = {**request.get("metadata", {}), "everos_nonce": uuid.uuid4().hex}


def _base_url_host(base_url: str) -> str:
    return urlsplit(base_url).netloc or base_url


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _normalise_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    normalised: list[dict[str, str]] = []
    for message in messages:
        data = message.model_dump()
        role = str(data.get("role") or "user")
        content = str(data.get("content") or "")
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        normalised.append({"role": role, "content": content})
    if not normalised:
        normalised.append({"role": "user", "content": ""})
    return "\n\n".join(system_parts) or None, normalised


def _content_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _normalise_stop_reason(
    value: str | None,
) -> Literal["stop", "length", "content_filter"] | None:
    if value in ("end_turn", "stop_sequence"):
        return "stop"
    if value == "max_tokens":
        return "length"
    if value == "refusal":
        return "content_filter"
    return None
