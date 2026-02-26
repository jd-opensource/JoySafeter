from __future__ import annotations

import json

from proxy.streaming import OpenAIToAnthropicStreamConverter


def _parse_sse_event(raw: str) -> tuple[str, dict]:
    lines = [line for line in raw.strip().splitlines() if line]
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    event_name = lines[0][7:]
    data = json.loads(lines[1][6:])
    return event_name, data


def test_streaming_converter_text_and_tool_call_sequence() -> None:
    converter = OpenAIToAnthropicStreamConverter(model_name="claude-sonnet-4-6")

    chunks = [
        {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "weather", "arguments": '{"city":"'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'Beijing"}'}}
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 9},
        },
    ]

    raw_events: list[str] = []
    for chunk in chunks:
        raw_events.extend(converter.consume_chunk(chunk))

    parsed = [_parse_sse_event(event) for event in raw_events]
    event_names = [event for event, _ in parsed]

    assert "message_start" in event_names
    assert "content_block_start" in event_names
    assert "content_block_delta" in event_names
    assert "content_block_stop" in event_names
    assert "message_delta" in event_names
    assert "message_stop" in event_names

    message_delta_payload = [payload for name, payload in parsed if name == "message_delta"][0]
    assert message_delta_payload["delta"]["stop_reason"] == "tool_use"
    assert message_delta_payload["usage"] == {"input_tokens": 20, "output_tokens": 9}

    tool_delta_payloads = [
        payload
        for name, payload in parsed
        if name == "content_block_delta" and payload["delta"]["type"] == "input_json_delta"
    ]
    assert len(tool_delta_payloads) == 2
    assert tool_delta_payloads[0]["delta"]["partial_json"] == '{"city":"'
    assert tool_delta_payloads[1]["delta"]["partial_json"] == 'Beijing"}'


def test_streaming_converter_done_line_finalizes_once() -> None:
    converter = OpenAIToAnthropicStreamConverter(model_name="claude-sonnet-4-6")

    events = converter.consume_sse_line('data: {"choices":[{"delta":{"content":"pong"},"finish_reason":null}]}')
    assert events

    done_events = converter.consume_sse_line("data: [DONE]")
    assert done_events

    second_done = converter.consume_sse_line("data: [DONE]")
    assert second_done == []
