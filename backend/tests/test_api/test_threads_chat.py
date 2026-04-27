"""Contract tests for thread chat entrypoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.threads import router
from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


async def mock_get_current_user():
    user = MagicMock(spec=User)
    user.id = "user-123"
    user.is_superuser = False
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


@patch("app.api.v1.threads.check_workspace_access", new_callable=AsyncMock)
@patch("app.core.events.execution_event_bus.publish", new_callable=AsyncMock)
@patch("app.api.v1.threads.DispatchService")
def test_chat_publishes_user_message_event_without_direct_thread_write(
    mock_orchestrator_cls,
    mock_publish,
    mock_check_access,
    client: TestClient,
) -> None:
    thread_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    mock_check_access.return_value = True

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    run = MagicMock()
    run.id = run_id
    run.current_execution_id = execution_id
    mock_orchestrator_cls.return_value.dispatch_chat = AsyncMock(return_value=run)

    response = client.post(
        f"/v1/threads/{thread_id}/chat?workspace_id={workspace_id}",
        json={"message": "hello from chat"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {
        "run_id": str(run_id),
        "execution_id": str(execution_id),
    }
    mock_orchestrator_cls.return_value.dispatch_chat.assert_awaited_once_with(
        thread_id=thread_id,
        message="hello from chat",
        user_id="user-123",
    )
    mock_publish.assert_awaited_once()
    published_envelope = mock_publish.await_args.args[0]
    assert published_envelope.event_type == "user_message"
    assert published_envelope.thread_id == thread_id
    assert published_envelope.execution_id == execution_id
    assert published_envelope.payload == {"text": "hello from chat"}


@patch("app.api.v1.threads.check_workspace_access", new_callable=AsyncMock)
@patch("app.api.v1.threads.DispatchService")
def test_chat_rejects_thread_with_running_run(
    mock_orchestrator_cls,
    mock_check_access,
    client: TestClient,
) -> None:
    thread_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    mock_check_access.return_value = True

    active_run = MagicMock()
    active_run.status = "running"

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = active_run
    mock_db = AsyncMock()
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    response = client.post(
        f"/v1/threads/{thread_id}/chat?workspace_id={workspace_id}",
        json={"message": "second message"},
    )

    assert response.status_code == 400
    assert "active run" in response.json()["message"]
    mock_orchestrator_cls.return_value.dispatch_chat.assert_not_called()
