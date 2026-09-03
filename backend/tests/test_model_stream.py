from __future__ import annotations

import json

import httpx
import pytest

from app.joysafeter_shared.llm import model_stream

pytestmark = pytest.mark.no_db


def _sse(*events: dict) -> str:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "response_body", "expected_path", "expected_tool_shape"),
    [
        (
            "anthropic_messages",
            _sse(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "call-a", "name": "update_draft"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"name":"A"}'},
                },
                {"type": "content_block_stop", "index": 0},
            ),
            "/v1/messages",
            {"name": "update_draft", "input_schema": {"type": "object"}},
        ),
        (
            "chat_completions",
            _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-c",
                                        "function": {
                                            "name": "update_draft",
                                            "arguments": '{"name":"C"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            "/v1/chat/completions",
            {
                "type": "function",
                "function": {
                    "name": "update_draft",
                    "description": "Update",
                    "parameters": {"type": "object"},
                },
            },
        ),
        (
            "openai_responses",
            _sse(
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {"type": "function_call", "id": "call-r", "name": "update_draft"},
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "call-r",
                    "arguments": '{"name":"R"}',
                },
            ),
            "/v1/responses",
            {
                "type": "function",
                "name": "update_draft",
                "description": "Update",
                "parameters": {"type": "object"},
            },
        ),
    ],
)
async def test_model_stream_normalizes_supported_protocols(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    response_body: str,
    expected_path: str,
    expected_tool_shape: dict,
) -> None:
    requests: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=response_body)

    monkeypatch.setattr(
        model_stream.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    events = [
        event
        async for event in model_stream.stream_model(
            protocol=protocol,
            base_url="https://models.example.test/v1",
            api_key="secret",
            bearer_token=protocol == "anthropic_messages",
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "update_draft",
                        "description": "Update",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            force_tool_name="update_draft",
        )
    ]

    assert requests[0].url.path == expected_path
    request_body = json.loads(requests[0].content)
    assert request_body["tools"][0] | expected_tool_shape == request_body["tools"][0]
    assert events[-1] == {"type": "done"}
    assert next(event for event in events if event["type"] == "tool_call_complete")["args_json"].startswith('{"name"')


@pytest.mark.asyncio
async def test_anthropic_accepts_inline_tool_input_and_terminal_sse_without_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient
    response_body = (
        "data:"
        + json.dumps(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "call-a",
                    "name": "update_draft",
                    "input": {"name": "Inline"},
                },
            },
        )
        + "\n\ndata:"
        + json.dumps({"type": "content_block_stop", "index": 0})
    )

    monkeypatch.setattr(
        model_stream.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=response_body)),
            **kwargs,
        ),
    )

    events = [
        event
        async for event in model_stream.stream_model(
            protocol="anthropic_messages",
            base_url="https://models.example.test/v1",
            api_key="secret",
            bearer_token=True,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"name": "update_draft", "input_schema": {"type": "object"}}],
            force_tool_name="update_draft",
        )
    ]

    assert events == [
        {
            "type": "tool_call_complete",
            "id": "call-a",
            "name": "update_draft",
            "args_json": '{"name":"Inline"}',
        },
        {"type": "done"},
    ]


@pytest.mark.asyncio
async def test_anthropic_streamed_tool_input_replaces_empty_inline_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient
    response_body = _sse(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "call-a",
                "name": "update_draft",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"name":"Streamed"}'},
        },
        {"type": "content_block_stop", "index": 0},
    )

    monkeypatch.setattr(
        model_stream.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=response_body)),
            **kwargs,
        ),
    )

    events = [
        event
        async for event in model_stream.stream_model(
            protocol="anthropic_messages",
            base_url="https://models.example.test/v1",
            api_key="secret",
            bearer_token=True,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"name": "update_draft", "input_schema": {"type": "object"}}],
            force_tool_name="update_draft",
        )
    ]

    assert next(event for event in events if event["type"] == "tool_call_complete")["args_json"] == (
        '{"name":"Streamed"}'
    )


@pytest.mark.asyncio
async def test_model_stream_rejects_successful_stream_without_normalized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient

    monkeypatch.setattr(
        model_stream.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=_sse({"type": "message_stop"}))),
            **kwargs,
        ),
    )

    events = [
        event
        async for event in model_stream.stream_model(
            protocol="anthropic_messages",
            base_url="https://models.example.test",
            api_key="secret",
            bearer_token=True,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
        )
    ]

    assert len(events) == 1
    assert (
        events[0]
        | {
            "type": "error",
            "code": "UPSTREAM_EMPTY_RESPONSE",
            "message": "Upstream completed without text or tool output.",
            "source": "upstream",
            "retryable": True,
        }
        == events[0]
    )


@pytest.mark.asyncio
async def test_model_stream_preserves_upstream_invalid_request_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient

    monkeypatch.setattr(
        model_stream.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={"error": {"message": "该key不允许访问该模型"}},
                )
            ),
            **kwargs,
        ),
    )

    events = [
        event
        async for event in model_stream.stream_model(
            protocol="anthropic_messages",
            base_url="https://models.example.test/v1",
            api_key="secret",
            bearer_token=True,
            model="test-model",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
        )
    ]

    assert len(events) == 1
    assert (
        events[0]
        | {
            "type": "error",
            "code": "UPSTREAM_INVALID_REQUEST",
            "message": "该key不允许访问该模型",
            "source": "upstream",
            "retryable": False,
            "status": 400,
        }
        == events[0]
    )
