"""Streaming conversion from OpenAI SSE chunks to Anthropic SSE events."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from .converters import map_openai_finish_reason_to_anthropic


@dataclass
class _ToolCallState:
    index: int
    block_index: int
    tool_call_id: str
    name: str
    arguments_buffer: str = ""
    closed: bool = False


class OpenAIToAnthropicStreamConverter:
    """Convert OpenAI streaming chunks into Anthropic SSE event sequence."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.message_id = f"msg_{uuid.uuid4().hex}"

        self.started = False
        self.finished = False

        self.next_block_index = 0
        self.text_block_index: int | None = None
        self.text_block_closed = False

        self.tool_states: dict[int, _ToolCallState] = {}
        self.usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def consume_sse_line(self, line: str) -> list[str]:
        """Consume one upstream SSE line and return zero or more Anthropic SSE events."""
        if not line.startswith("data: "):
            return []

        data_payload = line[6:].strip()
        if not data_payload:
            return []

        if data_payload == "[DONE]":
            return self.finalize()

        try:
            parsed = json.loads(data_payload)
        except json.JSONDecodeError:
            return []

        if not isinstance(parsed, dict):
            return []

        return self.consume_chunk(parsed)

    def consume_chunk(self, chunk: dict[str, Any]) -> list[str]:
        """Consume one parsed OpenAI chunk and return Anthropic SSE events."""
        if self.finished:
            return []

        events: list[str] = []

        choice = self._first_choice(chunk)
        if choice is None:
            self._remember_usage(chunk)
            return events

        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = {}

        finish_reason = choice.get("finish_reason")

        self._remember_usage(chunk)

        has_meaningful_data = bool(delta) or finish_reason is not None
        if has_meaningful_data and not self.started:
            events.append(self._event("message_start", self._message_start_payload()))
            self.started = True

        content = delta.get("content")
        if isinstance(content, str) and content:
            if self.text_block_index is None:
                self.text_block_index = self.next_block_index
                self.next_block_index += 1
                events.append(
                    self._event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": self.text_block_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
            events.append(
                self._event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self.text_block_index,
                        "delta": {"type": "text_delta", "text": content},
                    },
                )
            )

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                events.extend(self._consume_tool_call_delta(tool_call))

        if finish_reason is not None:
            events.extend(self.finalize(finish_reason))

        return events

    def finalize(self, finish_reason: Any = "stop") -> list[str]:
        """Finalize stream and emit remaining Anthropic events once."""
        if self.finished:
            return []

        events: list[str] = []

        if not self.started:
            events.append(self._event("message_start", self._message_start_payload()))
            self.started = True

        if self.text_block_index is not None and not self.text_block_closed:
            events.append(
                self._event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": self.text_block_index},
                )
            )
            self.text_block_closed = True

        for state in sorted(self.tool_states.values(), key=lambda item: item.block_index):
            if state.closed:
                continue
            events.append(
                self._event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": state.block_index},
                )
            )
            state.closed = True

        events.append(
            self._event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": map_openai_finish_reason_to_anthropic(finish_reason),
                        "stop_sequence": None,
                    },
                    "usage": self.usage,
                },
            )
        )
        events.append(self._event("message_stop", {"type": "message_stop"}))

        self.finished = True
        return events

    def _consume_tool_call_delta(self, tool_call: dict[str, Any]) -> list[str]:
        events: list[str] = []

        index_raw = tool_call.get("index", 0)
        index = int(index_raw) if isinstance(index_raw, (int, float)) else 0

        function_obj = tool_call.get("function")
        if not isinstance(function_obj, dict):
            function_obj = {}

        state = self.tool_states.get(index)
        if state is None:
            tool_call_id = tool_call.get("id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                tool_call_id = f"call_{uuid.uuid4().hex[:10]}"

            name = function_obj.get("name")
            if not isinstance(name, str) or not name:
                name = f"tool_{index}"

            block_index = self.next_block_index
            self.next_block_index += 1
            state = _ToolCallState(
                index=index,
                block_index=block_index,
                tool_call_id=tool_call_id,
                name=name,
            )
            self.tool_states[index] = state

            events.append(
                self._event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_call_id,
                            "name": name,
                            "input": {},
                        },
                    },
                )
            )
        else:
            if not state.name.startswith("tool_"):
                pass
            else:
                maybe_name = function_obj.get("name")
                if isinstance(maybe_name, str) and maybe_name:
                    state.name = maybe_name

            maybe_id = tool_call.get("id")
            if isinstance(maybe_id, str) and maybe_id:
                state.tool_call_id = maybe_id

        arguments_delta = function_obj.get("arguments")
        if isinstance(arguments_delta, str) and arguments_delta:
            state.arguments_buffer += arguments_delta
            events.append(
                self._event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": state.block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": arguments_delta,
                        },
                    },
                )
            )

        return events

    def _message_start_payload(self) -> dict[str, Any]:
        return {
            "type": "message_start",
            "message": {
                "id": self.message_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": self.model_name,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }

    def _remember_usage(self, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usage")
        if not isinstance(usage, dict):
            return
        self.usage = {
            "input_tokens": int(usage.get("prompt_tokens") or self.usage["input_tokens"] or 0),
            "output_tokens": int(usage.get("completion_tokens") or self.usage["output_tokens"] or 0),
        }

    @staticmethod
    def _first_choice(chunk: dict[str, Any]) -> dict[str, Any] | None:
        choices = chunk.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            return choices[0]
        return None

    @staticmethod
    def _event(event_name: str, data: dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
