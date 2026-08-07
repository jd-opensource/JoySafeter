import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.agents import get_agent
from app.joysafeter_api.api.v1.environments import get_environment
from app.joysafeter_api.api.v1.memory_stores import get_memory, get_memory_store
from app.joysafeter_api.api.v1.sandboxes import get_sandbox
from app.joysafeter_api.api.v1.sandboxes import stop_sandbox as stop_sandbox_route
from app.joysafeter_api.api.v1.secrets import get_secret
from app.joysafeter_api.api.v1.sessions import get_session as get_session_route
from app.joysafeter_api.api.v1.sessions import list_events as list_session_events_route
from app.joysafeter_api.api.v1.tasks import create_task, get_task
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, EnvironmentId, SandboxId, SecretId, TaskId


def _auth_ctx(project_id: str | None = None) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _create_project(db_session, name: str) -> Project:
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name=f"{name} Org",
        slug=f"{name.lower()}-org-{uuid.uuid4()}",
    )
    project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4()}",
    )
    db_session.add_all([org, project])
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _create_project_session(db_session, name: str) -> tuple[Project, JoySafeterSession]:
    project = await _create_project(db_session, name)
    agent = JoySafeterAgent(name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, project_id=project.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return project, session


@pytest.mark.asyncio
async def test_get_agent_missing_agent_returns_structured_error(db_session):
    agent_id = AgentId.new()

    with pytest.raises(AppError) as exc_info:
        await get_agent(agent_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "AGENT_NOT_FOUND",
        "message": "Agent not found",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_task_missing_agent_returns_structured_error(db_session):
    agent_id = AgentId.new()
    req = JoySafeterCreateTaskRequest(agent_id=agent_id, prompt="run scan")

    with pytest.raises(AppError) as exc_info:
        await create_task(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "TASK_AGENT_NOT_FOUND",
        "message": "Agent not found",
        "data": {"agent_id": str(agent_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_memory_store_missing_store_returns_structured_error(db_session):
    store_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_memory_store(store_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "MEMORY_STORE_NOT_FOUND",
        "message": "Memory store not found",
        "data": {"memory_store_id": str(store_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_secret_missing_secret_returns_structured_error(db_session):
    secret_id = SecretId.new()

    with pytest.raises(AppError) as exc_info:
        await get_secret(secret_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SECRET_NOT_FOUND",
        "message": "Secret not found",
        "data": {"secret_id": str(secret_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_environment_missing_environment_returns_structured_error(db_session):
    environment_id = EnvironmentId.new()

    with pytest.raises(AppError) as exc_info:
        await get_environment(environment_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "ENVIRONMENT_NOT_FOUND",
        "message": "Environment not found",
        "data": {"environment_id": str(environment_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_sandbox_missing_sandbox_returns_structured_error(db_session):
    sandbox_id = SandboxId.new()

    with pytest.raises(AppError) as exc_info:
        await get_sandbox(sandbox_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SANDBOX_NOT_FOUND",
        "message": "Sandbox not found",
        "data": {"sandbox_id": str(sandbox_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_session_service_keeps_project_boundary_for_core_read_write_paths(db_session):
    project, session = await _create_project_session(db_session, "SessionBoundaryProject")
    other_project = await _create_project(db_session, "SessionBoundaryOtherProject")
    project_id = project.id
    session_id = session.id
    svc = SessionService(db_session)
    await svc.send_event(session_id, "agent.message", {"content": [{"type": "text", "text": "visible"}]})

    assert await svc.get_session(session_id, project_id=other_project.id) is None
    events, has_more = await svc.list_events(session_id, project_id=other_project.id)
    assert events == []
    assert has_more is False
    assert await svc.update_session_status(session_id, "running", project_id=other_project.id) is False
    assert await svc.archive_session(session_id, project_id=other_project.id) is False
    assert await svc.delete_session(session_id, project_id=other_project.id) is False

    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == session_id))).scalar_one()
    assert row.project_id == project_id
    assert row.status == "idle"
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_get_session_cross_project_returns_structured_not_found(db_session):
    _, session = await _create_project_session(db_session, "SessionRouteProject")
    other_project = await _create_project(db_session, "SessionRouteOtherProject")

    with pytest.raises(AppError) as exc_info:
        await get_session_route(session.id, db_session, _auth_ctx(other_project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_NOT_FOUND",
        "message": "Session not found",
        "data": {"session_id": str(session.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_list_session_events_cross_project_returns_structured_not_found(db_session):
    _, session = await _create_project_session(db_session, "SessionEventsRouteProject")
    other_project = await _create_project(db_session, "SessionEventsRouteOtherProject")

    with pytest.raises(AppError) as exc_info:
        await list_session_events_route(session.id, 50, None, db_session, _auth_ctx(other_project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_NOT_FOUND",
        "message": "Session not found",
        "data": {"session_id": str(session.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_sandbox_cross_project_returns_structured_not_found(db_session):
    project = await _create_project(db_session, "SandboxVisibleProject")
    other_project = await _create_project(db_session, "SandboxOtherProject")
    sandbox = await SandboxService(db_session).create_sandbox(
        image="joysafeter/test:latest",
        status="idle",
        project_id=project.id,
    )

    with pytest.raises(AppError) as exc_info:
        await get_sandbox(sandbox.id, db_session, _auth_ctx(other_project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SANDBOX_NOT_FOUND",
        "message": "Sandbox not found",
        "data": {"sandbox_id": str(sandbox.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_sandbox_service_stop_keeps_project_boundary_and_does_not_mutate_cross_project_row(db_session):
    project = await _create_project(db_session, "SandboxStopProject")
    other_project = await _create_project(db_session, "SandboxStopOtherProject")
    sandbox = await SandboxService(db_session).create_sandbox(
        image="joysafeter/test:latest",
        status="idle",
        project_id=project.id,
    )
    sandbox_id = sandbox.id

    stopped = await SandboxService(db_session).stop_sandbox(sandbox_id, project_id=other_project.id)

    assert stopped is False
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))).scalar_one()
    assert row.status == "idle"


@pytest.mark.asyncio
async def test_stop_sandbox_cross_project_returns_structured_not_found(db_session):
    project = await _create_project(db_session, "SandboxRouteStopProject")
    other_project = await _create_project(db_session, "SandboxRouteStopOtherProject")
    sandbox = await SandboxService(db_session).create_sandbox(
        image="joysafeter/test:latest",
        status="idle",
        project_id=project.id,
    )
    sandbox_id = sandbox.id

    with pytest.raises(AppError) as exc_info:
        await stop_sandbox_route(sandbox_id, db_session, _auth_ctx(other_project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SANDBOX_NOT_FOUND",
        "message": "Sandbox not found",
        "data": {"sandbox_id": str(sandbox_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))).scalar_one()
    assert row.status == "idle"


@pytest.mark.asyncio
async def test_get_task_missing_task_returns_structured_error(db_session):
    task_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_task(TaskId(task_id), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "TASK_NOT_FOUND",
        "message": "Task not found",
        "data": {"task_id": f"task_{task_id}"},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_memory_missing_memory_returns_structured_error(db_session):
    store = JoySafeterMemoryStore(name=f"store-{uuid.uuid4()}", description="")
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)
    memory_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_memory(store.id, memory_id, None, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "MEMORY_NOT_FOUND",
        "message": "Memory not found",
        "data": {"memory_store_id": str(store.id), "memory_id": str(memory_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
