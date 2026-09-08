from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.joysafeter_shared.common.stream_errors import async_error_payload


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _anthropic_messages_url(base_url: str) -> str:
    if urlparse(base_url).path.rstrip("/").endswith("/v1"):
        return _join(base_url, "/messages")
    return _join(base_url, "/v1/messages")


def _tool_definition(tool: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    function = tool.get("function") if tool.get("type") == "function" else None
    source = function if isinstance(function, dict) else tool
    return (
        str(source.get("name") or ""),
        str(source.get("description") or ""),
        source.get("parameters") or source.get("input_schema") or {"type": "object"},
    )


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "description": description, "input_schema": schema}
        for tool in tools
        for name, description, schema in [_tool_definition(tool)]
    ]


def _chat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        }
        for tool in tools
        for name, description, schema in [_tool_definition(tool)]
    ]


def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "name": name, "description": description, "parameters": schema}
        for tool in tools
        for name, description, schema in [_tool_definition(tool)]
    ]


def _messages_to_transcript(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"{message['role']}: {message['content']}" for message in messages)


async def _read_error_body(response: httpx.Response) -> str:
    try:
        chunks: list[str] = []
        async for piece in response.aiter_text():
            chunks.append(piece)
            if sum(len(chunk) for chunk in chunks) > 1024:
                break
        body = "".join(chunks).strip()
        if not body:
            return ""
        try:
            payload = json.loads(body)
            message = (payload.get("error") or {}).get("message") if isinstance(payload, dict) else None
            if message:
                return str(message)[:400]
        except json.JSONDecodeError:
            pass
        return body[:400]
    except Exception:
        return ""


def _status_error_code(status: int) -> str:
    if status == 400:
        return "UPSTREAM_INVALID_REQUEST"
    if status == 401:
        return "UPSTREAM_AUTH_FAILED"
    if status == 403:
        return "UPSTREAM_ACCESS_DENIED"
    if status == 429:
        return "UPSTREAM_RATE_LIMITED"
    if status >= 500:
        return "UPSTREAM_UNAVAILABLE"
    return "UPSTREAM_ERROR"


def _status_error_event(status: int, detail: str = "") -> dict[str, Any]:
    return async_error_payload(
        code=_status_error_code(status),
        message=detail or f"upstream returned {status}",
        source="upstream",
        retryable=status == 429 or status >= 500,
        status=status,
    )


def _transport_error_event(exc: httpx.HTTPError) -> dict[str, Any]:
    payload = async_error_payload(
        code="UPSTREAM_CONNECTION_FAILED",
        message=f"transport error: {exc!s}",
        source="upstream",
        retryable=True,
    )
    payload["status"] = None
    return payload


async def _sse_payloads(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    def decode_line(line: str) -> dict[str, Any] | None:
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            return None
        data = line[5:].lstrip()
        if not data or data == "[DONE]":
            return None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if payload := decode_line(line):
                yield payload
    if payload := decode_line(buffer):
        yield payload


async def _stream_anthropic(
    *,
    base_url: str,
    api_key: str,
    bearer_token: bool,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    force_tool_name: str | None,
    max_tokens: int,
    timeout: float,
) -> AsyncGenerator[dict[str, Any], None]:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    if tools:
        body["tools"] = _anthropic_tools(tools)
    if force_tool_name:
        body["tool_choice"] = {"type": "tool", "name": force_tool_name}
    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    headers["authorization" if bearer_token else "x-api-key"] = f"Bearer {api_key}" if bearer_token else api_key
    tool_calls: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", _anthropic_messages_url(base_url), headers=headers, json=body) as response:
                if response.status_code != 200:
                    yield _status_error_event(response.status_code, await _read_error_body(response))
                    return
                async for event in _sse_payloads(response):
                    event_type = event.get("type")
                    index = str(event.get("index", "0"))
                    if event_type == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            tool_input = block.get("input")
                            tool_calls[index] = {
                                "id": str(block.get("id") or index),
                                "name": str(block.get("name") or ""),
                                "args": (
                                    json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
                                    if isinstance(tool_input, dict)
                                    else ""
                                ),
                                "saw_delta": False,
                            }
                    elif event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield {"type": "text_delta", "text": str(delta["text"])}
                        elif delta.get("type") == "input_json_delta":
                            piece = str(delta.get("partial_json") or "")
                            state = tool_calls.setdefault(
                                index,
                                {"id": index, "name": "", "args": "", "saw_delta": False},
                            )
                            if not state["saw_delta"]:
                                state["args"] = ""
                                state["saw_delta"] = True
                            state["args"] += piece
                            yield {
                                "type": "tool_call_delta",
                                "id": state["id"],
                                "name": state["name"] or None,
                                "args": piece,
                            }
                    elif event_type == "content_block_stop" and index in tool_calls:
                        state = tool_calls.pop(index)
                        yield {
                            "type": "tool_call_complete",
                            "id": state["id"],
                            "name": state["name"],
                            "args_json": state["args"],
                        }
                    elif event_type == "error":
                        error = event.get("error") or {}
                        yield async_error_payload(
                            code="UPSTREAM_STREAM_ERROR",
                            message=str(error.get("message") or "Unknown upstream stream error"),
                            source="upstream",
                            retryable=False,
                        )
                        return
    except httpx.HTTPError as exc:
        yield _transport_error_event(exc)
        return
    yield {"type": "done"}


async def _stream_chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    force_tool_name: str | None,
    max_tokens: int,
    temperature: float | None,
    timeout: float,
) -> AsyncGenerator[dict[str, Any], None]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "stream": True,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = _chat_tools(tools)
    if temperature is not None:
        body["temperature"] = temperature
    if force_tool_name:
        body["tool_choice"] = {"type": "function", "function": {"name": force_tool_name}}
    tool_calls: dict[str, dict[str, str]] = {}
    completed: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                _join(base_url, "/chat/completions"),
                headers={
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _status_error_event(response.status_code, await _read_error_body(response))
                    return
                async for event in _sse_payloads(response):
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "text_delta", "text": str(delta["content"])}
                    for call in delta.get("tool_calls") or []:
                        key = str(call.get("index", call.get("id", "0")))
                        state = tool_calls.setdefault(key, {"id": str(call.get("id") or key), "name": "", "args": ""})
                        function = call.get("function") or {}
                        if function.get("name"):
                            state["name"] = str(function["name"])
                        piece = str(function.get("arguments") or "")
                        if piece:
                            state["args"] += piece
                            yield {
                                "type": "tool_call_delta",
                                "id": state["id"],
                                "name": state["name"] or None,
                                "args": piece,
                            }
                    if choice.get("finish_reason") in {"tool_calls", "stop"}:
                        for key, state in tool_calls.items():
                            if key in completed or not state["name"]:
                                continue
                            completed.add(key)
                            yield {
                                "type": "tool_call_complete",
                                "id": state["id"],
                                "name": state["name"],
                                "args_json": state["args"],
                            }
    except httpx.HTTPError as exc:
        yield _transport_error_event(exc)
        return
    yield {"type": "done"}


async def _stream_responses(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    force_tool_name: str | None,
    max_tokens: int,
    timeout: float,
) -> AsyncGenerator[dict[str, Any], None]:
    body: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": _messages_to_transcript(messages),
        "stream": True,
        "max_output_tokens": max_tokens,
    }
    if tools:
        body["tools"] = _responses_tools(tools)
    if force_tool_name:
        body["tool_choice"] = {"type": "function", "name": force_tool_name}
    tool_calls: dict[str, dict[str, str]] = {}
    completed: set[str] = set()

    def tool_key(event: dict[str, Any], item: dict[str, Any] | None = None) -> str:
        source = item or event
        return str(
            source.get("id") or source.get("call_id") or event.get("item_id") or event.get("output_index") or "0"
        )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                _join(base_url, "/responses"),
                headers={
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _status_error_event(response.status_code, await _read_error_body(response))
                    return
                async for event in _sse_payloads(response):
                    event_type = event.get("type")
                    if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                        if event.get("delta"):
                            yield {"type": "text_delta", "text": str(event["delta"])}
                    elif event_type in {"response.output_item.added", "response.output_item.done"}:
                        item = event.get("item") or {}
                        if item.get("type") == "function_call":
                            key = tool_key(event, item)
                            state = tool_calls.setdefault(key, {"id": key, "name": "", "args": ""})
                            if item.get("name"):
                                state["name"] = str(item["name"])
                            if item.get("arguments"):
                                state["args"] = str(item["arguments"])
                            if event_type == "response.output_item.done" and key not in completed:
                                completed.add(key)
                                yield {
                                    "type": "tool_call_complete",
                                    "id": state["id"],
                                    "name": state["name"],
                                    "args_json": state["args"],
                                }
                    elif event_type == "response.function_call_arguments.delta":
                        key = tool_key(event)
                        state = tool_calls.setdefault(key, {"id": key, "name": "", "args": ""})
                        piece = str(event.get("delta") or "")
                        state["args"] += piece
                        yield {
                            "type": "tool_call_delta",
                            "id": state["id"],
                            "name": state["name"] or None,
                            "args": piece,
                        }
                    elif event_type == "response.function_call_arguments.done":
                        key = tool_key(event)
                        state = tool_calls.setdefault(key, {"id": key, "name": "", "args": ""})
                        if event.get("name"):
                            state["name"] = str(event["name"])
                        if event.get("arguments"):
                            state["args"] = str(event["arguments"])
                        if key not in completed:
                            completed.add(key)
                            yield {
                                "type": "tool_call_complete",
                                "id": state["id"],
                                "name": state["name"],
                                "args_json": state["args"],
                            }
                    elif event_type in {"error", "response.failed"}:
                        error = event.get("error") or (event.get("response") or {}).get("error") or {}
                        yield async_error_payload(
                            code="UPSTREAM_STREAM_ERROR",
                            message=str(error.get("message") or "Unknown upstream stream error"),
                            source="upstream",
                            retryable=False,
                        )
                        return
    except httpx.HTTPError as exc:
        yield _transport_error_event(exc)
        return
    yield {"type": "done"}


async def stream_model(
    *,
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    force_tool_name: str | None = None,
    bearer_token: bool = False,
    max_tokens: int = 4096,
    temperature: float | None = None,
    timeout: float = 120.0,
) -> AsyncGenerator[dict[str, Any], None]:
    common = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "system": system,
        "messages": messages,
        "tools": tools or [],
        "force_tool_name": force_tool_name,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if protocol == "anthropic_messages":
        stream = _stream_anthropic(**common, bearer_token=bearer_token)
    elif protocol == "openai_responses":
        stream = _stream_responses(**common)
    elif protocol == "chat_completions":
        stream = _stream_chat_completions(**common, temperature=temperature)
    else:
        raise ValueError(f"Unsupported model protocol: {protocol}")
    saw_output = False
    async for event in stream:
        event_type = event.get("type")
        if event_type in {"text_delta", "tool_call_complete"}:
            saw_output = True
        if event_type == "done" and not saw_output:
            yield async_error_payload(
                code="UPSTREAM_EMPTY_RESPONSE",
                message="Upstream completed without text or tool output.",
                source="upstream",
                retryable=True,
            )
            return
        yield event


__all__ = ["stream_model"]
