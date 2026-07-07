import uuid

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.agents import get_agent
from app.joysafeter_api.api.v1.environments import get_environment
from app.joysafeter_api.api.v1.memory_stores import get_memory, get_memory_store
from app.joysafeter_api.api.v1.sandboxes import get_sandbox
from app.joysafeter_api.api.v1.secrets import get_secret
from app.joysafeter_api.api.v1.tasks import create_task, get_task
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterCreateTaskRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


@pytest.mark.asyncio
async def test_get_agent_missing_agent_returns_structured_error(db_session):
    agent_id = uuid.uuid4()

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
    agent_id = uuid.uuid4()
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
    secret_id = uuid.uuid4()

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
    environment_id = uuid.uuid4()

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
    sandbox_id = uuid.uuid4()

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
async def test_get_task_missing_task_returns_structured_error(db_session):
    task_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await get_task(task_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "TASK_NOT_FOUND",
        "message": "Task not found",
        "data": {"task_id": str(task_id)},
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
