"""AgentRunService tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.common.exceptions import BadRequestException
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

    with pytest.raises(BadRequestException):
        await service.list_runs(agent_id=uuid.uuid4())


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
