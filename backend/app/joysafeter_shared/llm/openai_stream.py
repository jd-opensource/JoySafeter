from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from app.joysafeter_shared.llm.model_stream import (
    _status_error_event,
    _transport_error_event,
    stream_model,
)


async def stream_openai_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> AsyncGenerator[dict[str, Any], None]:
    system = "\n\n".join(str(message["content"]) for message in messages if message.get("role") == "system")
    conversation = [message for message in messages if message.get("role") != "system"]
    async for event in stream_model(
        protocol="chat_completions",
        base_url=base_url,
        api_key=api_key,
        model=model,
        system=system,
        messages=conversation,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    ):
        yield event


__all__ = ["_status_error_event", "_transport_error_event", "stream_openai_chat"]
