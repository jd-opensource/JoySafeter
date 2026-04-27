"""Unit tests for draft execution dispatch."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.engine.orchestrator import ExecutionOrchestrator


@pytest.mark.asyncio
async def test_dispatch_draft_uses_requested_version_without_active_release() -> None:
    db = AsyncMock()
    orchestrator = ExecutionOrchestrator(db)
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    input_payload = {"source": "test-lab"}

    version = MagicMock()
    version.id = version_id
    version.agent_id = agent_id
    version.definition_kind = "graph"
    version.definition_payload = {"nodes": [{"id": "n1"}], "edges": []}

    agent = MagicMock()
    agent.id = agent_id
    agent.workspace_id = workspace_id
    agent.active_release_id = None

    run = MagicMock()
    orchestrator._get_version = AsyncMock(return_value=version)  # type: ignore[method-assign]
    orchestrator._get_agent = AsyncMock(return_value=agent)  # type: ignore[method-assign]
    orchestrator._create_and_fire_draft = AsyncMock(return_value=run)  # type: ignore[attr-defined]

    result = await orchestrator.dispatch_draft(
        agent_id=agent_id,
        version_id=version_id,
        prompt="hello draft",
        user_id="user-123",
        workspace_id=workspace_id,
        input_payload=input_payload,
    )

    assert result is run
    orchestrator._create_and_fire_draft.assert_awaited_once_with(  # type: ignore[attr-defined]
        agent=agent,
        version=version,
        workspace_id=workspace_id,
        prompt="hello draft",
        trigger_source="draft_test",
        user_id="user-123",
        input_payload=input_payload,
    )


def test_cli_provider_draft_runs_use_sandbox_engine_and_provider_runtime() -> None:
    orchestrator = ExecutionOrchestrator(AsyncMock())
    version = MagicMock()
    version.definition_kind = "openclaw"

    assert orchestrator._resolve_draft_engine_kind(version) == "sandbox"
    assert orchestrator._build_draft_runtime_binding(version) == {"runtime_type": "openclaw"}


@pytest.mark.parametrize(
    ("definition_kind", "engine_kind", "runtime_binding"),
    [
        ("graph", "graph", {}),
        ("code", "code", {}),
        ("claude_code", "sandbox", {"runtime_type": "claude_code"}),
        ("codex", "sandbox", {"runtime_type": "codex"}),
        ("openclaw", "sandbox", {"runtime_type": "openclaw"}),
    ],
)
def test_draft_engine_resolution_matches_definition_kind(
    definition_kind: str,
    engine_kind: str,
    runtime_binding: dict,
) -> None:
    orchestrator = ExecutionOrchestrator(AsyncMock())
    version = MagicMock()
    version.definition_kind = definition_kind

    assert orchestrator._resolve_draft_engine_kind(version) == engine_kind
    assert orchestrator._build_draft_runtime_binding(version) == runtime_binding
