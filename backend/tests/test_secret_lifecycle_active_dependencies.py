import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    list_secrets,
    set_default_secret,
    update_secret,
)
from app.joysafeter_api.services import SecretService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


def _project_auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
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


async def _ensure_project(db_session, project_id: str) -> None:
    existing = await db_session.get(Project, project_id)
    if existing:
        return
    org = await db_session.get(Organization, "test-org")
    if not org:
        org = Organization(id="test-org", name="Test Org", slug="test-org")
        db_session.add(org)
    db_session.add(
        Project(
            id=project_id,
            org_id="test-org",
            name=project_id,
            slug=project_id,
            is_default=False,
        )
    )
    await db_session.commit()


async def _project_secret(db_session, *, project_id: str, name: str | None = None) -> JoySafeterSecret:
    await _ensure_project(db_session, project_id)
    secret = JoySafeterSecret(
        name=name or f"secret-{uuid.uuid4()}",
        provider="custom",
        protocol="custom",
        data={"TOKEN": "value"},
        project_id=project_id,
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


@pytest.mark.asyncio
async def test_update_secret_rejects_cross_project_at_service_boundary(db_session):
    secret = await _project_secret(db_session, project_id="project-b")

    updated = await SecretService(db_session).update_secret(
        secret.id,
        UpdateSecretRequest(data={"TOKEN": "new-value"}),
        project_id="project-a",
    )

    assert updated is None
    row = await _assert_secret_intact(db_session, secret.id)
    assert row.data == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_delete_secret_rejects_cross_project_at_service_boundary(db_session):
    secret = await _project_secret(db_session, project_id="project-b")

    deleted = await SecretService(db_session).delete_secret(secret.id, project_id="project-a")
    hard_deleted = await SecretService(db_session).hard_delete_secret(secret.id, project_id="project-a")

    assert deleted is False
    assert hard_deleted is False
    row = await _assert_secret_intact(db_session, secret.id)
    assert row.data == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_set_default_secret_rejects_cross_project_at_service_boundary(db_session):
    target = await _project_secret(db_session, project_id="project-b")
    default = await _project_secret(db_session, project_id="project-a")
    target_id = target.id
    default_id = default.id
    default.is_default = True
    await db_session.commit()

    updated = await SecretService(db_session).set_default_secret(target_id, project_id="project-a")

    assert updated is None
    db_session.expire_all()
    target_row = (
        await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == target_id))
    ).scalar_one()
    default_row = (
        await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == default_id))
    ).scalar_one()
    assert target_row.is_default is False
    assert default_row.is_default is True


@pytest.mark.asyncio
async def test_set_default_secret_clears_only_current_project_defaults(db_session):
    project_a_default = await _project_secret(db_session, project_id="project-a")
    project_a_next = await _project_secret(db_session, project_id="project-a")
    project_b_default = await _project_secret(db_session, project_id="project-b")
    project_a_default_id = project_a_default.id
    project_a_next_id = project_a_next.id
    project_b_default_id = project_b_default.id
    project_a_default.is_default = True
    project_b_default.is_default = True
    await db_session.commit()

    updated = await SecretService(db_session).set_default_secret(project_a_next_id, project_id="project-a")

    assert updated is not None
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(JoySafeterSecret.id, JoySafeterSecret.is_default).where(
                JoySafeterSecret.id.in_([project_a_default_id, project_a_next_id, project_b_default_id])
            )
        )
    ).all()
    defaults = {secret_id: is_default for secret_id, is_default in rows}
    assert defaults == {
        project_a_default_id: False,
        project_a_next_id: True,
        project_b_default_id: True,
    }


@pytest.mark.asyncio
async def test_create_secret_purges_only_same_project_soft_deleted_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_secret_service._cipher",
        _DisabledCipher(),
    )
    stale_other_project = await _project_secret(db_session, project_id="project-b", name="old-secret")
    stale_same_project = await _project_secret(db_session, project_id="project-a", name="old-secret")
    stale_other_project_id = stale_other_project.id
    stale_same_project_id = stale_same_project.id
    stale_other_project.deleted_at = utc_now()
    stale_same_project.deleted_at = utc_now()
    await db_session.commit()

    created = await SecretService(db_session).create_secret(
        CreateSecretRequest(name="old-secret", data={}),
        project_id="project-a",
    )

    assert created.project_id == "project-a"
    db_session.expire_all()
    other_project_row = (
        await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == stale_other_project_id))
    ).scalar_one()
    same_project_row = (
        await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == stale_same_project_id))
    ).scalar_one_or_none()
    assert other_project_row.deleted_at is not None
    assert same_project_row is None


@pytest.mark.asyncio
async def test_get_secret_route_rejects_cross_project_secret(db_session):
    secret = await _project_secret(db_session, project_id="project-b")

    with pytest.raises(AppError) as exc_info:
        await get_secret(secret.id, db_session, _project_auth_ctx("project-a"))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SECRET_NOT_FOUND",
        "message": "Secret not found",
        "data": {"secret_id": str(secret.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_set_default_secret_route_rejects_cross_project_secret(db_session):
    secret = await _project_secret(db_session, project_id="project-b")

    with pytest.raises(AppError) as exc_info:
        await set_default_secret(None, secret.id, db_session, _project_auth_ctx("project-a"))  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SECRET_NOT_FOUND",
        "message": "Secret not found",
        "data": {"secret_id": str(secret.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
