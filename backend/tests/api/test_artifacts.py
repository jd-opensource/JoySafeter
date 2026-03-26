from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.artifacts import router
from app.core.database import get_db
from app.models.auth import AuthUser as User


async def mock_get_current_user():
    user = MagicMock(spec=User)
    user.id = "user-123"
    return user


async def mock_get_db():
    yield AsyncMock()


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(router)

    from app.common.dependencies import get_current_user

    test_app.dependency_overrides[get_current_user] = mock_get_current_user
    test_app.dependency_overrides[get_db] = mock_get_db

    with TestClient(test_app) as c:
        yield c


@patch("app.services.sandbox_manager._sandbox_pool")
@patch("app.services.sandbox_manager.SandboxManagerService")
def test_live_read_file_returns_raw_content_for_ui(mock_service_cls, mock_pool, client: TestClient) -> None:
    record = MagicMock()
    record.id = "sandbox-1"

    mock_service = mock_service_cls.return_value
    mock_service.get_user_sandbox_record = AsyncMock(return_value=record)

    adapter = MagicMock()
    adapter.is_started.return_value = True
    adapter.read.return_value = "     1\talpha\n     2\tbeta"
    adapter.raw_read.return_value = "alpha\nbeta"

    mock_pool.get = AsyncMock(return_value=adapter)
    mock_pool.release = AsyncMock(return_value=None)

    response = client.get("/v1/artifacts/thread-1/live/skills/demo/SKILL.md")

    assert response.status_code == 200
    assert response.text == "alpha\nbeta"
    adapter.raw_read.assert_called_once_with("skills/demo/SKILL.md")
    adapter.read.assert_not_called()
    mock_pool.release.assert_awaited_once_with("sandbox-1")
