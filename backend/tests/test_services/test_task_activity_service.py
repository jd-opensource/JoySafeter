from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import NotFoundError
from app.models.task_activity import ActivityAuthorType, ActivityType
from app.services.task_activity_service import TaskActivityService


def _build_service() -> TaskActivityService:
    service = TaskActivityService(AsyncMock())
    service.repo = SimpleNamespace(
        get=AsyncMock(),
        list_by_task=AsyncMock(),
    )
    service.task_repo = SimpleNamespace(
        get_by_id_and_workspace=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_create_activity_missing_task_has_canonical_code() -> None:
    service = _build_service()
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    service.task_repo.get_by_id_and_workspace.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.create_activity(
            task_id=task_id,
            workspace_id=workspace_id,
            author_type=ActivityAuthorType.MEMBER,
            author_id="user-1",
            content="hello",
            activity_type=ActivityType.COMMENT,
        )

    assert exc_info.value.code == "TASK_NOT_FOUND"
    assert exc_info.value.data == {"task_id": str(task_id)}


@pytest.mark.asyncio
async def test_list_activities_missing_task_has_canonical_code() -> None:
    service = _build_service()
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    service.task_repo.get_by_id_and_workspace.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.list_activities(task_id=task_id, workspace_id=workspace_id)

    assert exc_info.value.code == "TASK_NOT_FOUND"
    assert exc_info.value.data == {"task_id": str(task_id)}
