from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import NotFoundError, ResourceConflictError
from app.services.agent_service import AgentService


def _build_service() -> AgentService:
    service = AgentService(AsyncMock())
    service.agent_repo = SimpleNamespace(get=AsyncMock())
    return service


@pytest.mark.asyncio
async def test_get_agent_missing_agent_has_canonical_code() -> None:
    service = _build_service()
    agent_id = uuid.uuid4()
    service.agent_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_agent(agent_id)

    assert exc_info.value.code == "AGENT_NOT_FOUND"
    assert exc_info.value.data == {"agent_id": str(agent_id)}


@pytest.mark.asyncio
async def test_delete_agent_with_task_reference_has_canonical_code() -> None:
    db = AsyncMock()
    service = AgentService(db)
    agent_id = uuid.uuid4()
    service.agent_repo = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id)))

    result = AsyncMock()
    result.scalar.return_value = True
    db.execute.return_value = result

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.delete_agent(agent_id)

    assert exc_info.value.code == "AGENT_DELETE_TASK_REFERENCE_CONFLICT"
    assert exc_info.value.data == {"agent_id": str(agent_id)}
