import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.joysafeter_api.api.v1.secrets import delete_secret, update_secret
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_secret import UpdateSecretRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


async def _secret(db_session, *, name: str | None = None) -> JoySafeterSecret:
    secret = JoySafeterSecret(
        name=name or f"secret-{uuid.uuid4()}",
        provider="custom",
        protocol="custom",
        data={"TOKEN": "value"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)
    return secret


async def _assert_secret_intact(db_session, secret_id: uuid.UUID) -> JoySafeterSecret:
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == secret_id))).scalar_one()
    assert row.deleted_at is None
    return row


@pytest.mark.asyncio
async def test_delete_secret_rejects_environment_reference_without_force(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"env-secret-{uuid.uuid4()}",
        description="",
        config={"secret_refs": [secret.name]},
    )
    db_session.add(env)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail == f"Secret is referenced by environment '{env.name}'. Use ?force=true to force delete."
    )
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_force_delete_secret_rejects_active_task_agent_secret_ref(db_session):
    secret = await _secret(db_session)
    agent = JoySafeterAgent(name=f"secret-agent-{uuid.uuid4()}", secret_ref=secret.name)
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
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Secret is required by active task '{task.id}' via agent secret_ref. "
        "Stop or wait for the task before deleting."
    )
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_force_delete_secret_rejects_active_task_session_environment_ref(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"session-env-secret-{uuid.uuid4()}",
        description="",
        config={"secret_refs": [secret.name]},
    )
    agent = JoySafeterAgent(name=f"session-env-agent-{uuid.uuid4()}")
    db_session.add_all([env, agent])
    await db_session.commit()
    await db_session.refresh(env)
    await db_session.refresh(agent)
    session = JoySafeterSession(agent_id=agent.id, status="idle", environment_ref=env.name)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    task = JoySafeterTask(
        agent_id=agent.id,
        chat_session_id=session.id,
        prompt="scan target",
        status=JoySafeterTaskStatus.SCHEDULING.value,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    with pytest.raises(HTTPException) as exc_info:
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Secret is required by active task '{task.id}' via session environment_ref. "
        "Stop or wait for the task before deleting."
    )
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_force_delete_secret_rejects_active_task_agent_environment_ref(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"agent-env-secret-{uuid.uuid4()}",
        description="",
        config={"secret_refs": [secret.name]},
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    agent = JoySafeterAgent(name=f"agent-env-agent-{uuid.uuid4()}", environment_ref=f"env_{env.id}")
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

    with pytest.raises(HTTPException) as exc_info:
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Secret is required by active task '{task.id}' via agent environment_ref. "
        "Stop or wait for the task before deleting."
    )
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_update_secret_rejects_active_task_agent_secret_ref(db_session):
    secret = await _secret(db_session)
    agent = JoySafeterAgent(name=f"update-secret-agent-{uuid.uuid4()}", secret_ref=secret.name)
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

    req = UpdateSecretRequest(data={"TOKEN": "new-value"})
    with pytest.raises(HTTPException) as exc_info:
        await update_secret(req, None, secret.id, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        f"Secret is required by active task '{task.id}' via agent secret_ref. "
        "Stop or wait for the task before updating."
    )

    row = await _assert_secret_intact(db_session, secret.id)
    assert row.data == {"TOKEN": "value"}
