from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.models.task import TaskStatus
from app.services.task_service import TaskService


def _build_service() -> TaskService:
    service = TaskService(AsyncMock())
    service.repo = SimpleNamespace(
        get_by_id_and_workspace=AsyncMock(),
        get_for_update=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_update_task_invalid_status_has_canonical_code() -> None:
    service = _build_service()
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    service.repo.get_by_id_and_workspace.return_value = SimpleNamespace(status=TaskStatus.BACKLOG)

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.update_task(task_id, workspace_id, status="nope")

    assert exc_info.value.code == "TASK_STATUS_INVALID"
    assert exc_info.value.data == {"status": "nope"}


@pytest.mark.asyncio
async def test_update_task_invalid_transition_has_canonical_code() -> None:
    service = _build_service()
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    service.repo.get_by_id_and_workspace.return_value = SimpleNamespace(status=TaskStatus.BACKLOG)

    with patch("app.services.task_service.transition_task", new_callable=AsyncMock) as mock_transition:
        from app.core.state_machines.engine import InvalidTransition

        mock_transition.side_effect = InvalidTransition("task", TaskStatus.BACKLOG, TaskStatus.DONE)
        with pytest.raises(InvalidRequestError) as exc_info:
            await service.update_task(task_id, workspace_id, status=TaskStatus.DONE.value)

    assert exc_info.value.code == "TASK_STATUS_TRANSITION_INVALID"
    assert exc_info.value.data == {"from_status": "backlog", "to_status": "done"}


@pytest.mark.asyncio
async def test_assign_to_agent_missing_task_has_canonical_code() -> None:
    service = _build_service()
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    service.repo.get_for_update.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.assign_to_agent(task_id=task_id, workspace_id=workspace_id, agent_id=agent_id)

    assert exc_info.value.code == "TASK_NOT_FOUND"
    assert exc_info.value.data == {"task_id": str(task_id)}
