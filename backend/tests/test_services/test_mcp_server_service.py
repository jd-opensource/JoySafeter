from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.services.mcp_server_service import McpServerService


def _build_service() -> McpServerService:
    service = McpServerService(AsyncMock())
    service.repo = SimpleNamespace(
        get_by_name=AsyncMock(),
        get=AsyncMock(),
    )
    service.commit = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_create_duplicate_name_has_canonical_code() -> None:
    service = _build_service()
    service.repo.get_by_name.return_value = SimpleNamespace(id=uuid.uuid4())
    data = SimpleNamespace(
        name="demo",
        description=None,
        transport="stdio",
        url=None,
        headers=None,
        timeout=None,
        retries=None,
        enabled=True,
    )

    with pytest.raises(InvalidRequestError) as exc_info:
        await service.create("user-1", data)

    assert exc_info.value.code == "MCP_SERVER_NAME_ALREADY_EXISTS"
    assert exc_info.value.data == {"name": "demo"}


@pytest.mark.asyncio
async def test_get_with_permission_missing_server_has_canonical_code() -> None:
    service = _build_service()
    server_id = uuid.uuid4()
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_with_permission(server_id, "user-1")

    assert exc_info.value.code == "MCP_SERVER_NOT_FOUND"
    assert exc_info.value.data == {"server_id": str(server_id)}
