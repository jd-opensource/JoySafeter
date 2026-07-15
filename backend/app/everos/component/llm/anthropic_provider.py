"""Anthropic Messages API provider for EverOS LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import httpx

from .protocol import ChatMessage, ChatResponse, LLMError, Usage


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
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens

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

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _messages_url(self._base_url),
                    headers={
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        "x-api-key": self._api_key,
                    },
                    json=request,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(exc.response.text) from exc
        except httpx.HTTPError as exc:
            raise LLMError(str(exc)) from exc

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
