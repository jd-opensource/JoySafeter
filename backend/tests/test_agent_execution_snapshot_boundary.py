from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.joysafeter_domain.credentials.references import build_agent_execution_snapshot

pytestmark = pytest.mark.no_db


def test_agent_execution_snapshot_keeps_tools_without_provider_permission_mode() -> None:
    agent = SimpleNamespace(
        id="agent-test",
        version=3,
        name="snapshot-agent",
        engine_kind="codex",
        model={"id": "gpt-test"},
        system_prompt="system",
        description=None,
        metadata_={},
        env={},
        mcp_servers=[],
        skills=[],
        agents=[],
        commands=[],
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"permission_policy": {"type": "always_ask"}},
                "configs": [],
            }
        ],
        multiagent=None,
        environment_id=None,
        model_credential_id=None,
    )

    snapshot = build_agent_execution_snapshot(agent)

    assert snapshot["tools"] == agent.tools
    assert "permission_mode" not in snapshot
