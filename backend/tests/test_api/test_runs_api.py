from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.runs import router
from app.core.database import get_db
from app.models.agent_run import AgentRunStatus
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


def make_run(*, agent_name: str = "skill_creator", run_type: str = "generic_agent") -> MagicMock:
    now = datetime.now(UTC)
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = AgentRunStatus.RUNNING
    run.run_type = run_type
    run.agent_name = agent_name
    run.source = "run_center"
    run.thread_id = "thread-123"
    run.graph_id = uuid.uuid4()
    run.title = "Build a skill"
    run.started_at = now
    run.finished_at = None
    run.last_seq = 5
    run.error_code = None
    run.error_message = None
    run.last_heartbeat_at = now
    run.updated_at = now
    return run


@patch("app.api.v1.runs.RunService")
def test_list_runs_forwards_agent_filters_and_returns_agent_fields(mock_service_cls, client: TestClient) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.list_recent_runs = AsyncMock(return_value=[make_run()])

    response = client.get(
        "/v1/runs",
        params={
            "run_type": "generic_agent",
            "agent_name": "skill_creator",
            "status": "running",
            "search": "skill",
            "limit": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["agent_name"] == "skill_creator"
    assert body["data"]["items"][0]["agent_display_name"] == "Skill Creator"
    mock_service.list_recent_runs.assert_awaited_once_with(
        user_id="user-123",
        run_type="generic_agent",
        agent_name="skill_creator",
        status="running",
        search="skill",
        limit=25,
    )


@patch("app.api.v1.runs.RunService")
def test_list_agents_returns_registered_agent_definitions(mock_service_cls, client: TestClient) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.list_agents = AsyncMock(
        return_value=[
            MagicMock(agent_name="skill_creator", display_name="Skill Creator"),
        ]
    )

    response = client.get("/v1/runs/agents")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == [
        {"agent_name": "skill_creator", "display_name": "Skill Creator"},
    ]


@patch("app.api.v1.runs.RunService")
def test_create_run_uses_generic_agent_endpoint(mock_service_cls, client: TestClient) -> None:
    mock_service = mock_service_cls.return_value
    created_run = make_run()
    mock_service.create_run = AsyncMock(return_value=created_run)

    response = client.post(
        "/v1/runs",
        json={
            "agent_name": "skill_creator",
            "graph_id": str(created_run.graph_id),
            "message": "Build a reusable skill",
            "thread_id": "thread-123",
            "input": {"edit_skill_id": "skill-1"},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == str(created_run.id)
    mock_service.create_run.assert_awaited_once()


@patch("app.api.v1.runs.RunService")
def test_find_active_run_uses_generic_agent_name_filter(mock_service_cls, client: TestClient) -> None:
    active_run = make_run()
    mock_service = mock_service_cls.return_value
    mock_service.find_latest_active_run = AsyncMock(return_value=active_run)

    response = client.get(
        "/v1/runs/active",
        params={
            "agent_name": "skill_creator",
            "graph_id": str(active_run.graph_id),
            "thread_id": "thread-123",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == str(active_run.id)
    mock_service.find_latest_active_run.assert_awaited_once_with(
        user_id="user-123",
        agent_name="skill_creator",
        graph_id=active_run.graph_id,
        thread_id="thread-123",
    )
