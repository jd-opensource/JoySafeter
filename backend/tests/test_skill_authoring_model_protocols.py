from __future__ import annotations

import pytest

from app.joysafeter_domain.services import joysafeter_skill_authoring

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "bearer_token"),
    [
        ("anthropic_messages", True),
        ("openai_responses", False),
        ("chat_completions", False),
    ],
)
async def test_skill_authoring_uses_shared_gateway_for_each_supported_protocol(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    bearer_token: bool,
) -> None:
    captured: dict[str, object] = {}

    async def fake_stream_model(**kwargs):
        captured.update(kwargs)
        yield {
            "type": "tool_call_complete",
            "id": "call-1",
            "name": "update_draft",
            "args_json": '{"name":"portable-skill"}',
        }
        yield {"type": "done"}

    monkeypatch.setattr(joysafeter_skill_authoring, "stream_model", fake_stream_model)

    events = [
        event
        async for event in joysafeter_skill_authoring.stream_authoring_chat(
            protocol=protocol,
            api_key="secret",
            bearer_token=bearer_token,
            base_url="https://models.example.test/v1",
            model="test-model",
            history=[{"role": "user", "content": "Create a portable skill"}],
        )
    ]

    assert captured["protocol"] == protocol
    assert captured["bearer_token"] is bearer_token
    assert captured["force_tool_name"] == "update_draft"
    assert events == [
        {"type": "draft_patch", "patch": {"name": "portable-skill"}},
        {"type": "done"},
    ]
