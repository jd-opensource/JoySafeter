"""Contract tests for executions API endpoints."""

from __future__ import annotations

import uuid
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


def _load_executions_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/executions.py"
    spec = importlib.util.spec_from_file_location("executions_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


router = _load_executions_router()


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
    register_exception_handlers(test_app)

    from app.common.dependencies import get_current_user

    test_app.dependency_overrides[get_current_user] = mock_get_current_user
    test_app.dependency_overrides[get_db] = mock_get_db

    with TestClient(test_app) as c:
        yield c


@patch("executions_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("executions_under_test.DispatchService")
def test_inject_message_calls_send_message(
    mock_orchestrator_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    """POST /{id}/message should call orchestrator.send_message with execution_id and message."""
    execution_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    mock_orchestrator = mock_orchestrator_cls.return_value
    mock_orchestrator.send_message = AsyncMock(return_value=None)
    mock_check_workspace_access.return_value = True

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = workspace_id
    mock_db = AsyncMock()
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    response = client.post(
        f"/v1/executions/{execution_id}/message",
        json={"message": "hello world"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "sent"
    mock_check_workspace_access.assert_awaited_once()
    assert mock_check_workspace_access.await_args.args[1] == workspace_id
    mock_orchestrator.send_message.assert_awaited_once_with(execution_id, "hello world")


@patch("executions_under_test.DispatchService")
def test_inject_message_empty_body_returns_422(mock_orchestrator_cls, client: TestClient) -> None:
    """POST /{id}/message with missing message field should return 422 Unprocessable Entity."""
    execution_id = uuid.uuid4()

    response = client.post(
        f"/v1/executions/{execution_id}/message",
        json={},
    )

    assert response.status_code == 422
    mock_orchestrator_cls.return_value.send_message.assert_not_called()


@patch("executions_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("executions_under_test.DispatchService")
def test_inject_message_unsupported_returns_canonical_error(
    mock_dispatch_service_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    execution_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    mock_dispatch = mock_dispatch_service_cls.return_value
    mock_dispatch.send_message = AsyncMock(
        side_effect=NotImplementedError("Message injection is not supported for code executions")
    )
    mock_check_workspace_access.return_value = True

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = workspace_id
    mock_db = AsyncMock()
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    response = client.post(
        f"/v1/executions/{execution_id}/message",
        json={"message": "hello world"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": {
            "code": "EXECUTION_MESSAGE_UNSUPPORTED",
            "message": "Message injection is not supported for code executions",
            "data": None,
        },
    }


@patch("executions_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("executions_under_test.ExecutionService")
def test_list_execution_events_returns_page_contract(
    mock_service_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    execution_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    mock_service = mock_service_cls.return_value
    mock_check_workspace_access.return_value = True

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = workspace_id
    mock_db = AsyncMock()
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    event_1 = MagicMock()
    event_1.id = uuid.uuid4()
    event_1.execution_id = execution_id
    event_1.sequence_no = 2
    event_1.event_type = "assistant_text"
    event_1.payload = {"content": "hello"}
    event_1.created_at = "2026-04-24T12:00:00Z"

    event_2 = MagicMock()
    event_2.id = uuid.uuid4()
    event_2.execution_id = execution_id
    event_2.sequence_no = 3
    event_2.event_type = "tool_use_start"
    event_2.payload = {"tool": {"name": "Bash"}}
    event_2.created_at = "2026-04-24T12:00:01Z"

    mock_service.list_events_after = AsyncMock(return_value=[event_1, event_2])

    response = client.get(
        f"/v1/executions/{execution_id}/events?after_seq=1"
    )

    assert response.status_code == 200
    mock_check_workspace_access.assert_awaited_once()
    assert mock_check_workspace_access.await_args.args[1] == workspace_id
    body = response.json()
    assert body["data"] == {
        "execution_id": str(execution_id),
        "events": [
            {
                "id": str(event_1.id),
                "execution_id": str(execution_id),
                "seq": 2,
                "event_type": "assistant_text",
                "payload": {"content": "hello"},
                "created_at": "2026-04-24T12:00:00Z",
            },
            {
                "id": str(event_2.id),
                "execution_id": str(execution_id),
                "seq": 3,
                "event_type": "tool_use_start",
                "payload": {"tool": {"name": "Bash"}},
                "created_at": "2026-04-24T12:00:01Z",
            },
        ],
        "next_after_seq": 3,
    }
    mock_service.list_events_after.assert_awaited_once_with(
        execution_id,
        "user-123",
        after_seq=1,
        limit=500,
    )
