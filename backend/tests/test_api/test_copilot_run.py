"""Contract tests for draft copilot run endpoint."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.exceptions import register_exception_handlers
from app.core.database import get_db
from app.models.auth import AuthUser as User


def _load_copilot_router():
    module_path = Path(__file__).resolve().parents[2] / "app/api/v1/copilot.py"
    spec = importlib.util.spec_from_file_location("copilot_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


router = _load_copilot_router()


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


@patch("copilot_under_test.DispatchService", create=True)
def test_copilot_run_dispatches_draft_contract(
    mock_dispatch_service_cls,
    client: TestClient,
) -> None:
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    run_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    run = MagicMock()
    run.id = run_id
    run.current_execution_id = execution_id
    mock_dispatch_service_cls.return_value.dispatch_copilot_draft = AsyncMock(return_value=run)

    response = client.post(
        "/v1/copilot/run",
        json={
            "agent_id": str(agent_id),
            "version_id": str(version_id),
            "workspace_id": str(workspace_id),
            "prompt": "plan the draft",
            "graph_context": {"node_id": "graph-1"},
            "conversation_history": [{"role": "user", "content": "hi"}],
            "mode": "deepagents",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "run_id": str(run_id),
        "execution_id": str(execution_id),
    }
    mock_dispatch_service_cls.return_value.dispatch_copilot_draft.assert_awaited_once_with(
        agent_id=agent_id,
        version_id=version_id,
        workspace_id=workspace_id,
        prompt="plan the draft",
        user_id="user-123",
        graph_context={"node_id": "graph-1"},
        conversation_history=[{"role": "user", "content": "hi"}],
        mode="deepagents",
        provider_name=None,
        model_name=None,
    )


@patch("copilot_under_test.DispatchService", create=True)
def test_copilot_run_requires_draft_identifiers(
    mock_dispatch_service_cls,
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/copilot/run",
        json={
            "agent_id": str(uuid.uuid4()),
            "prompt": "plan the draft",
            "graph_context": {"node_id": "graph-1"},
            "conversation_history": [{"role": "user", "content": "hi"}],
            "mode": "deepagents",
        },
    )

    assert response.status_code == 422
    mock_dispatch_service_cls.return_value.dispatch_copilot_draft.assert_not_called()
