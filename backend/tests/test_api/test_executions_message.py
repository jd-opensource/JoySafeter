"""Tests for POST /v1/executions/{id}/message endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.executions import router
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


@patch("app.api.v1.executions.ExecutionOrchestrator")
def test_inject_message_calls_send_message(mock_orchestrator_cls, client: TestClient) -> None:
    """POST /{id}/message should call orchestrator.send_message with execution_id and message."""
    execution_id = uuid.uuid4()
    mock_orchestrator = mock_orchestrator_cls.return_value
    mock_orchestrator.send_message = AsyncMock(return_value=None)

    response = client.post(
        f"/v1/executions/{execution_id}/message",
        json={"message": "hello world"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "sent"
    mock_orchestrator.send_message.assert_awaited_once_with(execution_id, "hello world")


@patch("app.api.v1.executions.ExecutionOrchestrator")
def test_inject_message_empty_body_returns_422(mock_orchestrator_cls, client: TestClient) -> None:
    """POST /{id}/message with missing message field should return 422 Unprocessable Entity."""
    execution_id = uuid.uuid4()

    response = client.post(
        f"/v1/executions/{execution_id}/message",
        json={},
    )

    assert response.status_code == 422
    mock_orchestrator_cls.return_value.send_message.assert_not_called()
