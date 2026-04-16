"""Tests for coordinator tools (spawn_agent, get_agent_result, LangChain wrappers)."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from app.core.agent.coordinator_tools import spawn_agent, get_agent_result
from app.core.agent.cli_backends.base import CLIResult
from app.models.execution import Execution, ExecutionSource, MissionExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution(**overrides) -> Execution:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id="user-1",
        source=ExecutionSource.COORDINATOR,
        runtime_type="claude_code",
        status=MissionExecutionStatus.QUEUED,
        last_seq=0,
        result_summary=None,
        error_message=None,
    )
    defaults.update(overrides)
    e = MagicMock(spec=Execution)
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


# ---------------------------------------------------------------------------
# spawn_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_agent_wait_completed():
    """spawn_agent with wait=True returns completed result."""
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(id=exec_id)
    cli_result = CLIResult(status="completed", output="task done", session_id="sess-1")

    mock_svc = AsyncMock()
    mock_svc.create_execution = AsyncMock(return_value=fake_execution)

    mock_runner = AsyncMock()
    mock_runner.run = AsyncMock(return_value=cli_result)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionRunner", return_value=mock_runner),
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        # async context manager mock
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await spawn_agent(
            agent_name="coder",
            prompt="write hello world",
            workspace_id=str(uuid.uuid4()),
            user_id="user-1",
            parent_execution_id=str(uuid.uuid4()),
            runtime_type="claude_code",
            wait=True,
        )

    assert result["execution_id"] == str(exec_id)
    assert result["status"] == "completed"
    assert result["output"] == "task done"
    assert result["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_spawn_agent_wait_failure():
    """spawn_agent with wait=True handles runner exceptions."""
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(id=exec_id)

    mock_svc = AsyncMock()
    mock_svc.create_execution = AsyncMock(return_value=fake_execution)

    mock_runner = AsyncMock()
    mock_runner.run = AsyncMock(side_effect=RuntimeError("container crashed"))

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionRunner", return_value=mock_runner),
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await spawn_agent(
            agent_name="coder",
            prompt="do stuff",
            workspace_id=str(uuid.uuid4()),
            user_id="user-1",
            parent_execution_id=str(uuid.uuid4()),
            wait=True,
        )

    assert result["status"] == "failed"
    assert "container crashed" in result["output"]


@pytest.mark.asyncio
async def test_spawn_agent_no_wait():
    """spawn_agent with wait=False returns dispatched immediately."""
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(id=exec_id)

    mock_svc = AsyncMock()
    mock_svc.create_execution = AsyncMock(return_value=fake_execution)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
        patch("app.core.agent.coordinator_tools._fire_and_forget") as mock_fire,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await spawn_agent(
            agent_name="scanner",
            prompt="scan the repo",
            workspace_id=str(uuid.uuid4()),
            user_id="user-1",
            parent_execution_id=str(uuid.uuid4()),
            wait=False,
        )

    assert result["status"] == "dispatched"
    assert result["execution_id"] == str(exec_id)
    mock_fire.assert_called_once()


# ---------------------------------------------------------------------------
# get_agent_result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_agent_result_completed():
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(
        id=exec_id,
        status=MissionExecutionStatus.COMPLETED,
        result_summary={"output": "all good"},
    )

    mock_svc = AsyncMock()
    mock_svc.get_execution = AsyncMock(return_value=fake_execution)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_result(str(exec_id), user_id="user-1")

    assert result["status"] == "completed"
    assert result["output"] == "all good"


@pytest.mark.asyncio
async def test_get_agent_result_not_found():
    mock_svc = AsyncMock()
    mock_svc.get_execution = AsyncMock(return_value=None)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_result(str(uuid.uuid4()), user_id="user-1")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_get_agent_result_failed():
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(
        id=exec_id,
        status=MissionExecutionStatus.FAILED,
        error_message="OOM killed",
    )

    mock_svc = AsyncMock()
    mock_svc.get_execution = AsyncMock(return_value=fake_execution)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_result(str(exec_id), user_id="user-1")

    assert result["status"] == "failed"
    assert "OOM killed" in result["output"]


@pytest.mark.asyncio
async def test_get_agent_result_running():
    exec_id = uuid.uuid4()
    fake_execution = _make_execution(
        id=exec_id,
        status=MissionExecutionStatus.RUNNING,
    )

    mock_svc = AsyncMock()
    mock_svc.get_execution = AsyncMock(return_value=fake_execution)

    with (
        patch("app.core.agent.coordinator_tools.async_session_factory") as mock_factory,
        patch("app.core.agent.coordinator_tools.ExecutionService", return_value=mock_svc),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_agent_result(str(exec_id), user_id="user-1")

    assert result["status"] == "running"
    assert "still" in result["output"]


# ---------------------------------------------------------------------------
# make_coordinator_tools (LangChain wrappers)
# ---------------------------------------------------------------------------

def test_make_coordinator_tools_returns_two_tools():
    """make_coordinator_tools returns a list of 2 LangChain tools."""
    from app.core.agent.coordinator_langgraph_tools import make_coordinator_tools

    tools = make_coordinator_tools(
        workspace_id=str(uuid.uuid4()),
        user_id="user-1",
        parent_execution_id=str(uuid.uuid4()),
    )
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "spawn_cli_agent" in names
    assert "check_agent_result" in names


def test_coordinator_tools_have_descriptions():
    """Each tool has a non-empty description for the LLM."""
    from app.core.agent.coordinator_langgraph_tools import make_coordinator_tools

    tools = make_coordinator_tools(
        workspace_id=str(uuid.uuid4()),
        user_id="user-1",
        parent_execution_id=str(uuid.uuid4()),
    )
    for t in tools:
        assert t.description, f"Tool {t.name} has no description"


def test_coordinator_tools_are_async():
    """Both tools should be coroutine-based."""
    from app.core.agent.coordinator_langgraph_tools import make_coordinator_tools

    tools = make_coordinator_tools(
        workspace_id=str(uuid.uuid4()),
        user_id="user-1",
        parent_execution_id=str(uuid.uuid4()),
    )
    for t in tools:
        # LangChain async tools have a coroutine attribute or are StructuredTool with coroutine
        assert hasattr(t, "coroutine") or t.is_async, f"Tool {t.name} is not async"
