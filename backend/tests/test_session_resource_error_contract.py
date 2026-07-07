import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.sessions import add_session_resource, create_session, delete_session_resource
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_session import (
    CreateSessionRequest,
    SessionFileResourceRequest,
    SessionRepoResourceRequest,
    SessionResourceRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


async def _create_agent(db_session) -> JoySafeterAgent:
    agent = JoySafeterAgent(name=f"resource-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _create_session(db_session) -> JoySafeterSession:
    agent = await _create_agent(db_session)
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _session_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(JoySafeterSession))).scalar_one()


@pytest.mark.asyncio
async def test_create_session_missing_memory_store_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    missing_store_id = uuid.uuid4()
    req = CreateSessionRequest(
        agent_id=agent.id,
        resources=[SessionResourceRequest(memory_store_id=missing_store_id)],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_MEMORY_STORE_NOT_FOUND",
        "message": f"Memory store not found: {missing_store_id}",
        "data": {"memory_store_id": str(missing_store_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_missing_file_resource_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    missing_file_id = f"file_{uuid.uuid4()}"
    req = CreateSessionRequest(
        agent_id=agent.id,
        file_resources=[SessionFileResourceRequest(file_id=missing_file_id)],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_invalid_repo_resource_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    req = CreateSessionRequest(
        agent_id=agent.id,
        repo_resources=[SessionRepoResourceRequest(url=" ")],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_REPO_URL_REQUIRED",
        "message": "repo resource url is required",
        "data": {"resource_type": "github_repository"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_add_session_resource_rejects_non_object_body_with_structured_error(db_session):
    session = await _create_session(db_session)

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, [], _auth_ctx(), db_session)  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_RESOURCE_BODY_INVALID",
        "message": "Request body must be an object",
        "data": {"expected": "object"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_add_session_resource_missing_file_returns_structured_error(db_session):
    session = await _create_session(db_session)
    missing_file_id = f"file_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, {"type": "file", "file_id": missing_file_id}, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"session_id": str(session.id), "file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_delete_session_resource_invalid_id_returns_structured_error(db_session):
    session = await _create_session(db_session)

    with pytest.raises(AppError) as exc_info:
        await delete_session_resource(session.id, "sesrsc_not-a-uuid", _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_RESOURCE_ID_INVALID",
        "message": "Invalid resource_id",
        "data": {"session_id": str(session.id), "resource_id": "sesrsc_not-a-uuid"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
