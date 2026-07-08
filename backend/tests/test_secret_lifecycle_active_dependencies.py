import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.secrets import create_secret, delete_secret, list_secrets, update_secret
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


class _DisabledCipher:
    is_enabled = False

    def encrypt(self, value: str) -> str:
        return value

    def decrypt_or_passthrough(self, value: str) -> str:
        return value


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
async def test_list_secrets_returns_uuid_cursor_compatible_with_after_id(db_session):
    await _secret(db_session)
    await _secret(db_session)

    page = await list_secrets(limit=1, after_id=None, db=db_session, auth_ctx=_auth_ctx())

    assert page["has_more"] is True
    assert page["last_id"] is not None
    uuid.UUID(page["last_id"])


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

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_ENVIRONMENT_REFERENCE",
        "message": f"Secret is referenced by environment '{env.name}'. Use ?force=true to force delete.",
        "data": {"secret_id": str(secret.id), "secret_name": secret.name, "environment_name": env.name},
        "source": "api",
        "retryable": False,
    }
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_delete_secret_rejects_agent_reference_without_force(db_session):
    secret = await _secret(db_session)
    agent = JoySafeterAgent(name=f"static-secret-agent-{uuid.uuid4()}", secret_ref=secret.name)
    db_session.add(agent)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_AGENT_REFERENCE",
        "message": f"Secret is referenced by agent '{agent.name}'. Use ?force=true to force delete.",
        "data": {"secret_id": str(secret.id), "secret_name": secret.name, "agent_name": agent.name},
        "source": "api",
        "retryable": False,
    }
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

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_ACTIVE_TASK_DEPENDENCY",
        "message": (
            f"Secret is required by active task '{task.id}' via agent secret_ref. "
            "Stop or wait for the task before deleting."
        ),
        "data": {
            "secret_id": str(secret.id),
            "secret_name": secret.name,
            "task_id": str(task.id),
            "source": "agent secret_ref",
            "operation": "deleting",
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
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

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_ACTIVE_TASK_DEPENDENCY",
        "message": (
            f"Secret is required by active task '{task.id}' via session environment_ref. "
            "Stop or wait for the task before deleting."
        ),
        "data": {
            "secret_id": str(secret.id),
            "secret_name": secret.name,
            "task_id": str(task.id),
            "source": "session environment_ref",
            "operation": "deleting",
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
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

    with pytest.raises(AppError) as exc_info:
        await delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_ACTIVE_TASK_DEPENDENCY",
        "message": (
            f"Secret is required by active task '{task.id}' via agent environment_ref. "
            "Stop or wait for the task before deleting."
        ),
        "data": {
            "secret_id": str(secret.id),
            "secret_name": secret.name,
            "task_id": str(task.id),
            "source": "agent environment_ref",
            "operation": "deleting",
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
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
    with pytest.raises(AppError) as exc_info:
        await update_secret(req, None, secret.id, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SECRET_ACTIVE_TASK_DEPENDENCY",
        "message": (
            f"Secret is required by active task '{task.id}' via agent secret_ref. "
            "Stop or wait for the task before updating."
        ),
        "data": {
            "secret_id": str(secret.id),
            "secret_name": secret.name,
            "task_id": str(task.id),
            "source": "agent secret_ref",
            "operation": "updating",
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    row = await _assert_secret_intact(db_session, secret.id)
    assert row.data == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_create_secret_reports_missing_vault_configuration(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_secret_service._cipher",
        _DisabledCipher(),
    )

    req = CreateSecretRequest(name=f"new-secret-{uuid.uuid4()}", data={"TOKEN": "new-value"})
    with pytest.raises(AppError) as exc_info:
        await create_secret(req, None, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SECRET_VAULT_CONFIGURATION_REQUIRED",
        "message": "Managed secrets require JOYSAFETER_VAULT_ENCRYPTION_KEY to be configured.",
        "data": {"operation": "create"},
        "source": "runtime",
        "retryable": True,
        "user_action": "configure",
    }


@pytest.mark.asyncio
async def test_update_secret_reports_missing_vault_configuration_without_mutating(db_session, monkeypatch):
    secret = await _secret(db_session)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_secret_service._cipher",
        _DisabledCipher(),
    )

    req = UpdateSecretRequest(data={"TOKEN": "new-value"})
    with pytest.raises(AppError) as exc_info:
        await update_secret(req, None, secret.id, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=503) == {
        "code": "SECRET_VAULT_CONFIGURATION_REQUIRED",
        "message": "Managed secrets require JOYSAFETER_VAULT_ENCRYPTION_KEY to be configured.",
        "data": {"operation": "update"},
        "source": "runtime",
        "retryable": True,
        "user_action": "configure",
    }

    row = await _assert_secret_intact(db_session, secret.id)
    assert row.data == {"TOKEN": "value"}
