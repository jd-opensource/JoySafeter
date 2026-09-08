from __future__ import annotations

import json

import pytest

from app.joysafeter_application.quickstart import QuickstartDesignService

pytestmark = pytest.mark.no_db


async def _events(*events: dict):
    for event in events:
        yield event


DESIGN_SERVICE = QuickstartDesignService()


@pytest.mark.asyncio
async def test_quickstart_rejects_malformed_tool_arguments_without_completing_step() -> None:
    payloads = [
        payload
        async for payload in DESIGN_SERVICE.stream_events(
            _events(
                {
                    "type": "tool_call_complete",
                    "id": "call-a",
                    "name": "generate_agent_config",
                    "args_json": '{}{"name":"Broken"}',
                },
                {"type": "done"},
            )
        )
    ]
    assert [payload["type"] for payload in payloads] == ["error"]
    assert payloads[0]["code"] == "UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_quickstart_requires_completed_tool_output_for_configuration_steps() -> None:
    payloads = [
        payload
        async for payload in DESIGN_SERVICE.stream_events(
            _events({"type": "text_delta", "text": "Working..."}, {"type": "done"})
        )
    ]
    assert [payload["type"] for payload in payloads] == ["text_delta", "error"]
    assert payloads[-1]["code"] == "UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_quickstart_design_events_use_phase_and_artifact_not_step_numbers() -> None:
    payloads = [
        payload
        async for payload in DESIGN_SERVICE.stream_events(
            _events(
                {
                    "type": "tool_call_complete",
                    "id": "call-a",
                    "name": "generate_agent_config",
                    "args_json": '{"name":"Reviewer","system":"Review carefully"}',
                },
                {"type": "done"},
            )
        )
    ]
    assert [payload["type"] for payload in payloads] == [
        "config_update",
        "phase_complete",
        "done",
    ]
    assert payloads[0]["phase"] == "design"
    assert payloads[0]["artifact"] == "agent_blueprint"
    assert "step" not in payloads[0]
    assert "step" not in payloads[1]
    assert "curl" not in payloads[1]
    assert "resource_id" not in payloads[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {"name": "Reviewer", "system": "x" * 5001},
        {"name": "Reviewer", "system": "Review carefully", "env": {"TOKEN": "secret"}},
        {
            "name": "Reviewer",
            "system": "Review carefully",
            "mcp_servers": [{"type": "url", "name": "docs", "url": "https://docs.example.com/mcp"}],
        },
        {
            "name": "Reviewer",
            "system": "Review carefully",
            "mcp_servers": {"docs": {"url": "https://docs.example.com/mcp"}},
        },
    ],
)
async def test_quickstart_rejects_complete_tool_output_outside_agent_context_contract(config) -> None:
    payloads = [
        payload
        async for payload in DESIGN_SERVICE.stream_events(
            _events(
                {
                    "type": "tool_call_complete",
                    "id": "call-a",
                    "name": "generate_agent_config",
                    "args_json": json.dumps(config),
                },
                {"type": "done"},
            )
        )
    ]

    assert [payload["type"] for payload in payloads] == ["error"]
    assert payloads[0]["code"] == "UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {
            "name": "Reviewer",
            "system": "Review carefully",
            "mcp_servers": [
                {
                    "type": "sse",
                    "name": "events",
                    "url": "https://events.example.com/sse",
                    "auth_requirement": "required",
                }
            ],
        },
        {
            "name": "Reviewer",
            "system": "Review carefully",
            "mcp_servers": [
                {
                    "type": "streamable_http",
                    "name": "duplicate",
                    "url": "https://one.example.com/mcp",
                    "auth_requirement": "required",
                },
                {
                    "type": "streamable_http",
                    "name": "duplicate",
                    "url": "https://two.example.com/mcp",
                    "auth_requirement": "required",
                },
            ],
        },
        {
            "name": "Reviewer",
            "system": "Review carefully",
            "tools": [{"type": "mcp_toolset", "mcp_server_name": "missing"}],
            "mcp_servers": [],
        },
    ],
)
async def test_quickstart_rejects_agent_configurations_that_agent_create_would_reject(config) -> None:
    payloads = [
        payload
        async for payload in DESIGN_SERVICE.stream_events(
            _events(
                {
                    "type": "tool_call_complete",
                    "id": "call-a",
                    "name": "generate_agent_config",
                    "args_json": json.dumps(config),
                },
                {"type": "done"},
            )
        )
    ]

    assert [payload["type"] for payload in payloads] == ["error"]
    assert payloads[0]["code"] == "UPSTREAM_INVALID_RESPONSE"
