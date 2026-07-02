"""OpenAI-compatible streaming chat helper.

A minimal async generator that wraps ``POST /chat/completions`` (or any
OpenAI-shaped gateway) and yields structured events suitable for the skill
authoring workspace. Quickstart keeps its own copy (``quickstart.py``) — that
one is wired to a 5-step wizard with curl generation and is intentionally
left alone to avoid regressions.

Event shapes yielded by :func:`stream_openai_chat`::

    {"type": "text_delta", "text": <str>}
        Streaming assistant content fragment.

    {"type": "tool_call_delta", "id": <str>, "name": <str|None>, "args": <str>}
        Partial JSON of a tool call. ``args`` is appended over time; callers
        accumulate until ``tool_call_complete``.

    {"type": "tool_call_complete", "id": <str>, "name": <str>, "args_json": <str>}
        Final tool call (finish_reason == "tool_calls" or "stop"). ``args_json``
        is the concatenated argument string, *unparsed* — the caller decides
        whether to ``json.loads`` it (so a partial-JSON consumer is free to
        treat ``tool_call_delta`` events as the source of truth).

    {"type": "done"}
        Stream finished normally. Emitted once.

    {"type": "error", "message": <str>, "status": <int|None>}
        Upstream/transport error. Caller should stop consuming.

Credentials (api_key, base_url, model) are passed in — this module does NOT
read settings or env. The endpoint layer fetches them from the user-supplied
secret via ``SecretService`` and forwards them down. That mirrors how
``quickstart.py`` handles credentials and keeps the helper multi-tenant safe.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

import httpx


async def stream_openai_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a chat completion against an OpenAI-compatible endpoint.

    See module docstring for the event protocol. Failure modes:

    * Non-200 upstream: yields a single ``error`` event then returns.
    * Network/timeout: yields a single ``error`` event then returns.
    * Malformed SSE line: skipped silently (matches OpenAI's own behavior
      where keepalive ``: ...`` lines and the terminal ``data: [DONE]``
      are not real chunks).

    ``temperature``/``max_tokens`` are omitted from the request when set to
    ``None`` so callers can match models that reject non-default values
    (e.g. ``gpt-5.5`` rejects any temperature other than 1).
    """
    url = _join(base_url, "/chat/completions")
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools

    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }

    # Per-tool-call accumulator. Keyed by the upstream-reported index/id
    # because OpenAI streams multiple tool calls interleaved.
    tool_calls: dict[str, dict[str, str]] = {}
    completed_keys: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    detail = await _read_error_body(response)
                    yield {
                        "type": "error",
                        "status": response.status_code,
                        "message": detail or f"upstream returned {response.status_code}",
                    }
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":") or not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            continue
                        try:
                            evt = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        choices = evt.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}

                        content = delta.get("content")
                        if content:
                            yield {"type": "text_delta", "text": content}

                        for call in delta.get("tool_calls") or []:
                            key = str(call.get("index", call.get("id", "0")))
                            state = tool_calls.setdefault(key, {"id": call.get("id") or key, "name": "", "args": ""})
                            fn = call.get("function") or {}
                            name = fn.get("name")
                            if name:
                                state["name"] = name
                            args_piece = fn.get("arguments")
                            if args_piece:
                                state["args"] += args_piece
                                yield {
                                    "type": "tool_call_delta",
                                    "id": state["id"],
                                    "name": state["name"] or None,
                                    "args": args_piece,
                                }

                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("tool_calls", "stop"):
                            # Emit a single ``complete`` per tool call we
                            # haven't already finalized. With ``stop`` and no
                            # tool calls this loop is a no-op.
                            for key, state in tool_calls.items():
                                if key in completed_keys:
                                    continue
                                if not state["name"]:
                                    # finish_reason='stop' without any tool
                                    # call data — nothing to complete.
                                    continue
                                completed_keys.add(key)
                                yield {
                                    "type": "tool_call_complete",
                                    "id": state["id"],
                                    "name": state["name"],
                                    "args_json": state["args"],
                                }

    except httpx.HTTPError as exc:
        yield {"type": "error", "status": None, "message": f"transport error: {exc!s}"}
        return

    yield {"type": "done"}


async def _read_error_body(response: httpx.Response) -> str:
    """Best-effort: extract a human-friendly error message from the upstream
    body without breaking the streaming context. Truncates at 400 chars."""
    try:
        chunks: list[str] = []
        async for piece in response.aiter_text():
            chunks.append(piece)
            if sum(len(c) for c in chunks) > 1024:
                break
        body = "".join(chunks).strip()
        if not body:
            return ""
        # OpenAI error responses are JSON-shaped: {"error": {"message": "..."}}.
        try:
            obj = json.loads(body)
            msg = (obj.get("error") or {}).get("message") if isinstance(obj, dict) else None
            if msg:
                return str(msg)[:400]
        except json.JSONDecodeError:
            pass
        return body[:400]
    except Exception:  # noqa: BLE001 — fallback is intentional
        return ""


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
