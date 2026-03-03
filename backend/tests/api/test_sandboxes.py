"""
Tests for Admin Sandbox API
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_sandboxes import router
from app.core.database import get_db
from app.models.auth import AuthUser as User

# Create a minimal app for testing
app = FastAPI()
app.include_router(router)


# Mock dependencies
async def mock_get_current_admin_user():
    user = MagicMock(spec=User)
    user.id = "admin-user"
    user.is_super_user = True
    return user


async def mock_get_db():
    yield AsyncMock()


@pytest.fixture
def client():
    # Create a fresh app for each test to avoid pollution
    test_app = FastAPI()
    test_app.include_router(router)

    # Import the exact dependency function object to override
    from app.api.v1.admin_sandboxes import get_current_admin_user

    # helper to override
    test_app.dependency_overrides[get_current_admin_user] = mock_get_current_admin_user
    test_app.dependency_overrides[get_db] = mock_get_db

    with TestClient(test_app) as c:
        yield c


@patch("app.api.v1.admin_sandboxes.SandboxManagerService")
def test_list_sandboxes(mock_service_cls, client):
    # Setup
    mock_db = AsyncMock()
    # update override for this specific test
    client.app.dependency_overrides[get_db] = lambda: mock_db

    from datetime import datetime

    # Mock DB execution
    sandbox_item = MagicMock()
    sandbox_item.id = "sandbox-1"
    sandbox_item.user_id = "user-1"
    sandbox_item.status = "running"
    sandbox_item.image = "img"
    sandbox_item.created_at = datetime(2023, 1, 1)
    sandbox_item.updated_at = datetime(2023, 1, 1)
    sandbox_item.idle_timeout = 300
    sandbox_item.runtime = "runc"
    sandbox_item.container_id = "cid"
    sandbox_item.last_active_at = None
    sandbox_item.error_message = None
    sandbox_item.cpu_limit = 1.0
    sandbox_item.memory_limit = 512

    sandbox_item.user.name = "Test User"
    sandbox_item.user.email = "test@example.com"

    # scalars().all() returns list
    # scalar_one() returns int
    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1

    mock_list_result = MagicMock()
    mock_list_result.scalars.return_value.all.return_value = [sandbox_item]

    mock_db.execute.side_effect = [mock_count_result, mock_list_result]

    # Run
    response = client.get("/admin/sandboxes")

    # Verify
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1


@patch("app.api.v1.admin_sandboxes.SandboxManagerService")
def test_stop_sandbox(mock_service_cls, client):
    # Setup
    mock_service = mock_service_cls.return_value
    mock_service.stop_sandbox = AsyncMock(return_value=True)

    # Run
    response = client.post("/admin/sandboxes/sb-1/stop")

    # Verify
    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_service.stop_sandbox.assert_called_once_with("sb-1")


@patch("app.api.v1.admin_sandboxes.SandboxManagerService")
def test_stop_sandbox_not_found(mock_service_cls, client):
    # Setup
    mock_service = mock_service_cls.return_value
    mock_service.stop_sandbox = AsyncMock(return_value=False)

    # Run
    response = client.post("/admin/sandboxes/sb-unknown/stop")

    # Verify
    assert response.status_code == 404


@patch("app.api.v1.admin_sandboxes.SandboxManagerService")
def test_delete_sandbox(mock_service_cls, client):
    # Setup
    mock_service = mock_service_cls.return_value
    mock_service.delete_sandbox = AsyncMock(return_value=True)

    # Run
    response = client.delete("/admin/sandboxes/sb-1")

    # Verify
    assert response.status_code == 200
    mock_service.delete_sandbox.assert_called_once_with("sb-1")
