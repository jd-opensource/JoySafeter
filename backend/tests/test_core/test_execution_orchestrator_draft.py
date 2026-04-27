"""Unit tests for draft execution dispatch."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.app_errors import InvalidRequestError
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.models.agent_run import AgentRun
from app.models.execution import Execution


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


@pytest.mark.asyncio
async def test_dispatch_copilot_draft_uses_requested_version_without_active_release() -> None:
    db = AsyncMock()
    orchestrator = ExecutionOrchestrator(db)
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    graph_context = {"graph": {"nodes": []}}
    conversation_history = [{"role": "user", "content": "hello"}]

    version = MagicMock()
    version.id = version_id
    version.agent_id = agent_id

    agent = MagicMock()
    agent.id = agent_id
    agent.workspace_id = workspace_id
    agent.active_release_id = None

    run = MagicMock()
    copilot_payload = {
        "graph_context": graph_context,
        "conversation_history": conversation_history,
        "mode": "deepagents",
        "provider_name": "openai",
        "model_name": "gpt-5",
        "user_id": "user-123",
        "graph_id": str(agent_id),
    }

    orchestrator._get_version = AsyncMock(return_value=version)  # type: ignore[method-assign]
    orchestrator._get_agent = AsyncMock(return_value=agent)  # type: ignore[method-assign]
    orchestrator._create_and_fire_draft = AsyncMock(return_value=run)  # type: ignore[attr-defined]

    result = await orchestrator.dispatch_copilot_draft(
        agent_id=agent_id,
        version_id=version_id,
        workspace_id=workspace_id,
        prompt="hello copilot draft",
        user_id="user-123",
        graph_context=graph_context,
        conversation_history=conversation_history,
        mode="deepagents",
        provider_name="openai",
        model_name="gpt-5",
    )

    assert result is run
    orchestrator._create_and_fire_draft.assert_awaited_once_with(  # type: ignore[attr-defined]
        agent=agent,
        version=version,
        workspace_id=workspace_id,
        prompt="hello copilot draft",
        trigger_source="draft_copilot",
        user_id="user-123",
        input_payload=copilot_payload,
        engine_kind_override="copilot",
        definition_kind_override="copilot",
        definition_payload_override=copilot_payload,
        executor_kind_override="copilot",
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


@pytest.mark.asyncio
async def test_create_and_fire_draft_copilot_overrides_keep_draft_ownership() -> None:
    db = MagicMock()
    added_objects: list[object] = []

    def add_side_effect(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        added_objects.append(obj)

    db.add.side_effect = add_side_effect
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    orchestrator = ExecutionOrchestrator(db)
    orchestrator.publish_run_status_change = AsyncMock()  # type: ignore[method-assign]
    orchestrator._fire_engine = AsyncMock()  # type: ignore[method-assign]

    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent = MagicMock()
    agent.id = agent_id
    version = MagicMock()
    version.id = version_id
    version.definition_kind = "graph"
    version.definition_payload = {"nodes": [{"id": "v1"}], "edges": []}

    copilot_payload = {
        "graph_context": {"graph": {"nodes": []}},
        "conversation_history": [{"role": "user", "content": "hello"}],
        "mode": "deepagents",
        "provider_name": "openai",
        "model_name": "gpt-5",
        "user_id": "user-123",
        "graph_id": str(agent_id),
    }

    run = await orchestrator._create_and_fire_draft(
        agent=agent,
        version=version,
        workspace_id=workspace_id,
        prompt="hello copilot draft",
        trigger_source="draft_copilot",
        user_id="user-123",
        input_payload=copilot_payload,
        engine_kind_override="copilot",
        definition_kind_override="copilot",
        definition_payload_override=copilot_payload,
        executor_kind_override="copilot",
    )

    assert run.release_id is None
    assert run.agent_version_id == version_id

    persisted_run = next(obj for obj in added_objects if isinstance(obj, AgentRun))
    persisted_execution = next(obj for obj in added_objects if isinstance(obj, Execution))

    assert persisted_run.release_id is None
    assert persisted_run.agent_version_id == version_id
    assert persisted_execution.executor_kind == "copilot"

    orchestrator._fire_engine.assert_awaited_once_with(  # type: ignore[attr-defined]
        execution=persisted_execution,
        release_runtime_binding={},
        runtime_kind="graph",
        version=version,
        agent=agent,
        workspace_id=workspace_id,
        prompt="hello copilot draft",
        engine_kind_override="copilot",
        definition_kind_override="copilot",
        definition_payload_override=copilot_payload,
    )


@pytest.mark.asyncio
async def test_create_and_fire_draft_rejects_partial_override_sets() -> None:
    orchestrator = ExecutionOrchestrator(AsyncMock())
    agent = MagicMock()
    version = MagicMock()
    version.id = uuid.uuid4()
    version.definition_kind = "graph"

    with pytest.raises(InvalidRequestError, match="all absent or all present"):
        await orchestrator._create_and_fire_draft(
            agent=agent,
            version=version,
            workspace_id=uuid.uuid4(),
            prompt="hello",
            trigger_source="draft_copilot",
            user_id="user-123",
            engine_kind_override="copilot",
        )
