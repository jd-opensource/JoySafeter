from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.app_errors import AccessDeniedError, InvalidRequestError
from app.services.custom_tool_service import CustomToolService


def _build_service() -> CustomToolService:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    service = CustomToolService(db)
    service.repo = SimpleNamespace(
        count_by_user=AsyncMock(),
        get_by=AsyncMock(),
        get=AsyncMock(),
        delete_by_id=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_create_tool_quota_exceeded_has_canonical_code() -> None:
    service = _build_service()
    service.repo.count_by_user.return_value = 100

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.create_tool(
            owner_id="user-1",
            name="demo",
            code="print(1)",
            schema={},
        )

    assert exc_info.value.code == "CUSTOM_TOOL_QUOTA_EXCEEDED"
    assert exc_info.value.data == {"limit": 100}


@pytest.mark.asyncio
async def test_create_tool_duplicate_name_has_canonical_code() -> None:
    service = _build_service()
    service.repo.count_by_user.return_value = 0
    service.repo.get_by.return_value = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.create_tool(
            owner_id="user-1",
            name="demo",
            code="print(1)",
            schema={},
        )

    assert exc_info.value.code == "CUSTOM_TOOL_NAME_ALREADY_EXISTS"
    assert exc_info.value.data == {"name": "demo"}


@pytest.mark.asyncio
async def test_update_tool_wrong_owner_has_canonical_code() -> None:
    service = _build_service()
    tool_id = uuid.uuid4()
    service.repo.get.return_value = SimpleNamespace(id=tool_id, owner_id="user-1", name="demo")

    with pytest.raises(AccessDeniedError) as exc_info:
        await service.update_tool(tool_id, "user-2", name="new-name")

    assert exc_info.value.code == "CUSTOM_TOOL_UPDATE_FORBIDDEN"
    assert exc_info.value.data == {"tool_id": str(tool_id)}
