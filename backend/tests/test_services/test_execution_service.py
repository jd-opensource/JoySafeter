from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import NotFoundError
from app.services.execution_service import ExecutionService


@pytest.mark.asyncio
async def test_get_execution_without_user_id_raises_canonical_not_found() -> None:
    service = ExecutionService(AsyncMock())
    execution_id = uuid.uuid4()
    service.get_execution_internal = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_execution(execution_id, user_id=None)

    assert exc_info.value.code == "EXECUTION_NOT_FOUND"
    assert exc_info.value.data == {"execution_id": str(execution_id)}
