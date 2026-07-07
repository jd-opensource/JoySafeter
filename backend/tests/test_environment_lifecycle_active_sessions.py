import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.environments import (
    archive_environment,
    create_environment,
    delete_environment,
    update_environment,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    UpdateEnvironmentRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


@pytest.mark.asyncio
async def test_create_environment_rejects_missing_secret_ref_with_structured_error(db_session):
    missing_ref = f"missing-secret-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(
        name=f"secret-ref-env-{uuid.uuid4()}", config=EnvironmentConfig(secret_refs=[missing_ref])
    )

    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ENVIRONMENT_SECRET_NOT_FOUND",
        "message": f"Secret not found: {missing_ref}",
        "data": {"secret_ref": missing_ref},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }

    row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.name == req.name))
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_archive_environment_rejects_non_archived_session_reference(db_session):
    env = JoySafeterEnvironment(name=f"env-ref-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    env_id = env.id

    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=env.name)
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
        "message": "Environment is referenced by one or more active sessions.",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_archive_environment_rejects_active_task_agent_reference_without_session(db_session):
    env = JoySafeterEnvironment(name=f"agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"env-agent-{uuid.uuid4()}", environment_ref=f"env_{env.id}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before archiving."
        ),
        "data": {"environment_id": str(env_id), "task_id": str(task.id), "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_environment_rejects_active_task_agent_reference_without_session(db_session):
    env = JoySafeterEnvironment(name=f"delete-agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"delete-env-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(AppError) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before deleting."
        ),
        "data": {"environment_id": str(env_id), "task_id": str(task.id), "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None


@pytest.mark.asyncio
async def test_delete_environment_rejects_agent_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"static-agent-env-ref-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"static-env-agent-{uuid.uuid4()}", environment_ref=f"env_{env.id}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    with pytest.raises(AppError) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_AGENT_REFERENCE",
        "message": f"Environment is referenced by agent '{agent.name}'.",
        "data": {"environment_id": str(env_id), "agent_name": agent.name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None


@pytest.mark.asyncio
async def test_update_environment_config_rejects_active_task_agent_reference(db_session):
    env = JoySafeterEnvironment(name=f"update-config-env-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    agent = JoySafeterAgent(name=f"update-config-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    task = JoySafeterTask(
        agent_id=agent.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.RUNNING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    req = UpdateEnvironmentRequest(config=EnvironmentConfig(env_vars={"NEW_ENV": "value"}))
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ACTIVE_TASK",
        "message": (
            f"Environment is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before updating config."
        ),
        "data": {"environment_id": str(env_id), "task_id": str(task.id), "source": "agent environment_ref"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert (env_row.config or {}).get("env_vars") != {"NEW_ENV": "value"}


@pytest.mark.asyncio
async def test_update_environment_name_rejects_agent_reference_without_active_task(db_session):
    env = JoySafeterEnvironment(name=f"update-name-env-{uuid.uuid4()}", description="")
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id
    original_name = env.name

    agent = JoySafeterAgent(name=f"update-name-agent-{uuid.uuid4()}", environment_ref=env.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = UpdateEnvironmentRequest(name=f"renamed-env-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_AGENT_REFERENCE",
        "message": f"Environment is referenced by agent '{agent.name}'.",
        "data": {"environment_id": str(env_id), "agent_name": agent.name},
        "source": "api",
        "retryable": False,
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name


@pytest.mark.asyncio
async def test_update_environment_rejects_archived_environment_with_structured_error(db_session):
    env = JoySafeterEnvironment(name=f"archived-update-env-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id
    original_name = env.name

    req = UpdateEnvironmentRequest(name=f"renamed-env-{uuid.uuid4()}")
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": "Cannot update an archived environment",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name


@pytest.mark.asyncio
async def test_archive_environment_rejects_already_archived_environment_with_structured_error(db_session):
    env = JoySafeterEnvironment(name=f"already-archived-env-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    with pytest.raises(AppError) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": "Environment is already archived",
        "data": {"environment_id": str(env_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_create_environment_image_build_failure_returns_structured_error_and_rolls_back(
    db_session,
    monkeypatch,
):
    async def fail_build(env):
        raise RuntimeError("apt failed")

    monkeypatch.setattr("app.joysafeter_api.api.v1.environments._validate_and_build_image", fail_build)

    env_name = f"build-fail-env-{uuid.uuid4()}"
    req = CreateEnvironmentRequest(name=env_name, config=EnvironmentConfig(env_vars={"A": "B"}))
    with pytest.raises(AppError) as exc_info:
        await create_environment(req, db_session, _auth_ctx())

    detail = await handled_app_error_payload(exc_info.value, status_code=500)
    assert detail["code"] == "ENVIRONMENT_IMAGE_BUILD_FAILED"
    assert detail["message"] == "Image build failed: apt failed"
    assert detail["data"]["operation"] == "create"
    assert detail["source"] == "runtime"
    assert detail["retryable"] is True
    assert detail["user_action"] == "retry"

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.name == env_name))
    ).scalar_one()
    assert str(env_row.id) == detail["data"]["environment_id"]
    assert env_row.deleted_at is not None


@pytest.mark.asyncio
async def test_update_environment_image_build_failure_returns_structured_error_without_deleting(
    db_session,
    monkeypatch,
):
    async def fail_build(env):
        raise RuntimeError("pip failed")

    monkeypatch.setattr("app.joysafeter_api.api.v1.environments._validate_and_build_image", fail_build)

    env = JoySafeterEnvironment(name=f"update-build-fail-env-{uuid.uuid4()}", description="", config={})
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    env_id = env.id

    req = UpdateEnvironmentRequest(config=EnvironmentConfig(env_vars={"A": "B"}))
    with pytest.raises(AppError) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=500) == {
        "code": "ENVIRONMENT_IMAGE_BUILD_FAILED",
        "message": "Image build failed: pip failed",
        "data": {"environment_id": str(env_id), "operation": "update"},
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.deleted_at is None
