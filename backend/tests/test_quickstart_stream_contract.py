from __future__ import annotations

import json

import pytest

from app.joysafeter_api.api.v1.quickstart import _stream_quickstart_events

pytestmark = pytest.mark.no_db


async def _events(*events: dict):
    for event in events:
        yield event


def _payloads(chunks: list[str]) -> list[dict]:
    return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]


@pytest.mark.asyncio
async def test_quickstart_rejects_malformed_tool_arguments_without_completing_step() -> None:
    chunks = [
        chunk
        async for chunk in _stream_quickstart_events(
            _events(
                {
                    "type": "tool_call_complete",
                    "id": "call-a",
                    "name": "generate_agent_config",
                    "args_json": '{}{"name":"Broken"}',
                },
                {"type": "done"},
            ),
            current_step=2,
            requires_tool=True,
        )
    ]

    payloads = _payloads(chunks)
    assert [payload["type"] for payload in payloads] == ["error"]
    assert payloads[0]["code"] == "UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_quickstart_requires_completed_tool_output_for_configuration_steps() -> None:
    chunks = [
        chunk
        async for chunk in _stream_quickstart_events(
            _events({"type": "text_delta", "text": "Working..."}, {"type": "done"}),
            current_step=2,
            requires_tool=True,
        )
    ]

    payloads = _payloads(chunks)
    assert [payload["type"] for payload in payloads] == ["text_delta", "error"]
    assert payloads[-1]["code"] == "UPSTREAM_INVALID_RESPONSE"
