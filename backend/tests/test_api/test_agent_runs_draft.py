"""Contract tests for draft AgentRun endpoints."""

from __future__ import annotations

import uuid
import importlib.util
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


def _load_agent_runs_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/agent_runs.py"
    spec = importlib.util.spec_from_file_location("agent_runs_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


router = _load_agent_runs_router()


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


@patch("agent_runs_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("agent_runs_under_test.DispatchService")
def test_create_draft_run_dispatches_agent_version_without_release(
    mock_orchestrator_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_check_workspace_access.return_value = True

    run = MagicMock()
    run.id = run_id
    run.release_id = None
    run.agent_version_id = version_id
    run.workspace_id = workspace_id
    run.thread_id = None
    run.task_id = None
    run.trigger_source = "draft_test"
    run.goal = "hello draft"
    run.input_payload = None
    run.status = "running"
    run.current_execution_id = execution_id
    run.result_summary = None
    run.started_at = now
    run.ended_at = None
    run.created_by = "user-123"
    run.created_at = now
    mock_orchestrator_cls.return_value.dispatch_draft = AsyncMock(return_value=run)

    response = client.post(
        "/v1/runs/draft",
        json={
            "agent_id": str(agent_id),
            "version_id": str(version_id),
            "workspace_id": str(workspace_id),
            "goal": "hello draft",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["release_id"] is None
    assert body["data"]["agent_version_id"] == str(version_id)
    assert body["data"]["current_execution_id"] == str(execution_id)
    assert body["data"]["trigger_source"] == "draft_test"
    mock_orchestrator_cls.return_value.dispatch_draft.assert_awaited_once_with(
        agent_id=agent_id,
        version_id=version_id,
        prompt="hello draft",
        user_id="user-123",
        workspace_id=workspace_id,
        input_payload=None,
    )


@patch("agent_runs_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("agent_runs_under_test.DispatchService")
def test_create_release_run_authorizes_against_release_workspace(
    mock_orchestrator_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    release_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_check_workspace_access.return_value = True
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = workspace_id
    mock_db = AsyncMock()
    mock_db.execute.return_value = exec_result

    async def override_db():
        yield mock_db

    client.app.dependency_overrides[get_db] = override_db

    run = MagicMock()
    run.id = run_id
    run.release_id = release_id
    run.agent_version_id = None
    run.workspace_id = workspace_id
    run.thread_id = None
    run.task_id = None
    run.trigger_source = "api"
    run.goal = "hello release"
    run.input_payload = None
    run.status = "running"
    run.current_execution_id = execution_id
    run.result_summary = None
    run.started_at = now
    run.ended_at = None
    run.created_by = "user-123"
    run.created_at = now
    mock_orchestrator_cls.return_value.dispatch_direct = AsyncMock(return_value=run)

    response = client.post(
        "/v1/runs",
        json={
            "release_id": str(release_id),
            "trigger_source": "api",
            "goal": "hello release",
        },
    )

    assert response.status_code == 200
    mock_check_workspace_access.assert_awaited_once()
    assert mock_check_workspace_access.await_args.args[1] == workspace_id
    mock_orchestrator_cls.return_value.dispatch_direct.assert_awaited_once()


@patch("agent_runs_under_test.check_workspace_access", new_callable=AsyncMock)
@patch("agent_runs_under_test.DispatchService")
@patch("agent_runs_under_test.AgentRunService")
def test_cancel_run_authorizes_against_run_workspace_without_workspace_query(
    mock_service_cls,
    mock_orchestrator_cls,
    mock_check_workspace_access,
    client: TestClient,
) -> None:
    run_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    existing_run = MagicMock()
    existing_run.workspace_id = workspace_id
    mock_service_cls.return_value.get_run = AsyncMock(return_value=existing_run)
    mock_check_workspace_access.return_value = True

    cancelled_run = MagicMock()
    cancelled_run.id = run_id
    cancelled_run.release_id = None
    cancelled_run.agent_version_id = uuid.uuid4()
    cancelled_run.workspace_id = workspace_id
    cancelled_run.thread_id = None
    cancelled_run.task_id = None
    cancelled_run.trigger_source = "draft_test"
    cancelled_run.goal = "hello draft"
    cancelled_run.input_payload = None
    cancelled_run.status = "cancelled"
    cancelled_run.current_execution_id = uuid.uuid4()
    cancelled_run.result_summary = None
    cancelled_run.started_at = now
    cancelled_run.ended_at = now
    cancelled_run.created_by = "user-123"
    cancelled_run.created_at = now
    mock_orchestrator_cls.return_value.cancel_run = AsyncMock(return_value=cancelled_run)

    response = client.post(f"/v1/runs/{run_id}/cancel")

    assert response.status_code == 200
    mock_service_cls.return_value.get_run.assert_awaited_once_with(run_id)
    mock_check_workspace_access.assert_awaited_once()
    assert mock_check_workspace_access.await_args.args[1] == workspace_id
    mock_orchestrator_cls.return_value.cancel_run.assert_awaited_once_with(run_id)
