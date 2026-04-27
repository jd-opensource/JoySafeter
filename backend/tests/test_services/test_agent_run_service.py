"""AgentRunService tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.services.agent_run_service import AgentRunService


@pytest.mark.asyncio
async def test_list_runs_filters_agent_runs_by_workspace() -> None:
    service = AgentRunService(AsyncMock())
    service.run_repo.find_by_agent_and_trigger = AsyncMock(return_value=[])
    agent_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    await service.list_runs(workspace_id=workspace_id, agent_id=agent_id)

    service.run_repo.find_by_agent_and_trigger.assert_awaited_once_with(
        agent_id=agent_id,
        workspace_id=workspace_id,
        trigger_source=None,
        status=None,
    )


@pytest.mark.asyncio
async def test_list_runs_requires_workspace_for_agent_filter() -> None:
    service = AgentRunService(AsyncMock())

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.list_runs(agent_id=uuid.uuid4())
    assert exc_info.value.code == "AGENT_RUN_WORKSPACE_REQUIRED"
    assert exc_info.value.data == {"filter": "agent_id"}


@pytest.mark.asyncio
async def test_list_runs_filters_release_runs_by_workspace() -> None:
    service = AgentRunService(AsyncMock())
    service.run_repo.list_by_release = AsyncMock(return_value=[])
    release_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    await service.list_runs(workspace_id=workspace_id, release_id=release_id)

    service.run_repo.list_by_release.assert_awaited_once_with(release_id, workspace_id)


@pytest.mark.asyncio
async def test_list_runs_filters_task_runs_by_workspace() -> None:
    service = AgentRunService(AsyncMock())
    service.run_repo.list_by_task = AsyncMock(return_value=[])
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    await service.list_runs(workspace_id=workspace_id, task_id=task_id)

    service.run_repo.list_by_task.assert_awaited_once_with(task_id, workspace_id)


@pytest.mark.asyncio
async def test_list_runs_requires_any_filter() -> None:
    service = AgentRunService(AsyncMock())

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.list_runs()

    assert exc_info.value.code == "AGENT_RUN_FILTER_REQUIRED"


@pytest.mark.asyncio
async def test_get_run_missing_run_has_canonical_code() -> None:
    service = AgentRunService(AsyncMock())
    run_id = uuid.uuid4()
    service.run_repo.get = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_run(run_id)

    assert exc_info.value.code == "AGENT_RUN_NOT_FOUND"
    assert exc_info.value.data == {"run_id": str(run_id)}
