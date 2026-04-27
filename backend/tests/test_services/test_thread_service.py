from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import NotFoundError
from app.services.thread_service import ThreadService


def _build_service() -> ThreadService:
    db = AsyncMock()
    service = ThreadService(db)
    service.thread_repo = SimpleNamespace(
        get=AsyncMock(),
        update=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_get_thread_missing_thread_has_canonical_code() -> None:
    service = _build_service()
    thread_id = uuid.uuid4()
    service.thread_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_thread(thread_id)

    assert exc_info.value.code == "THREAD_NOT_FOUND"
    assert exc_info.value.data == {"thread_id": str(thread_id)}


@pytest.mark.asyncio
async def test_archive_thread_missing_thread_has_canonical_code() -> None:
    service = _build_service()
    thread_id = uuid.uuid4()
    service.thread_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.archive_thread(thread_id)

    assert exc_info.value.code == "THREAD_NOT_FOUND"
    assert exc_info.value.data == {"thread_id": str(thread_id)}
