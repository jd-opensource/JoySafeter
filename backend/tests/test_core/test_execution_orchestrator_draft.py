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
        version=version,
        workspace_id=workspace_id,
        prompt="hello draft",
        trigger_source="draft_test",
        user_id="user-123",
        input_payload=input_payload,
    )
