import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.joysafeter_api.api.v1.environments import archive_environment, delete_environment, update_environment
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_environment import EnvironmentConfig, UpdateEnvironmentRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


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

    with pytest.raises(HTTPException) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Environment is referenced by one or more active sessions."

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

    with pytest.raises(HTTPException) as exc_info:
        await archive_environment(env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Environment is required by active task '{task.id}' via agent environment_ref. "
        "Stop or wait for the task before archiving."
    )

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

    with pytest.raises(HTTPException) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Environment is required by active task '{task.id}' via agent environment_ref. "
        "Stop or wait for the task before deleting."
    )

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

    with pytest.raises(HTTPException) as exc_info:
        await delete_environment(env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == f"Environment is referenced by agent '{agent.name}'."

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
    with pytest.raises(HTTPException) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Environment is required by active task '{task.id}' via agent environment_ref. "
        "Stop or wait for the task before updating config."
    )

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
    with pytest.raises(HTTPException) as exc_info:
        await update_environment(req, env_id, db_session, _auth_ctx())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == f"Environment is referenced by agent '{agent.name}'."

    db_session.expire_all()
    env_row = (
        await db_session.execute(select(JoySafeterEnvironment).where(JoySafeterEnvironment.id == env_id))
    ).scalar_one()
    assert env_row.name == original_name
