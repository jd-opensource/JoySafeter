import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from credential_test_helpers import encrypted_secret_data
from error_contract_helpers import handled_app_error_payload
from fastapi import FastAPI
from sqlalchemy import select
from starlette.requests import Request

from app.joysafeter_api.api.v1 import secrets as secrets_api
from app.joysafeter_api.api.v1.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    list_secrets,
    set_default_secret,
    update_secret,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, UpdateSecretRequest
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import SecretId
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


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 34567),
            "path": "/api/v1/secrets",
            "headers": [],
            "query_string": b"",
        }
    )


def _app(db, auth_ctx: JoySafeterAuthContext) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(secrets_api.router, prefix="/api/v1/secrets")
    app.dependency_overrides[secrets_api.get_db] = lambda: db
    app.dependency_overrides[secrets_api.get_joysafeter_auth_context] = lambda: auth_ctx
    app.dependency_overrides[secrets_api.require_joysafeter_write] = lambda: auth_ctx
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class _DisabledCipher:
    def encrypt(self, value: str) -> str:
        raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY is required for credential encryption")

    def decrypt_stored(self, value: str) -> str:
        raise ValueError("JOYSAFETER_VAULT_ENCRYPTION_KEY is required for credential encryption")


async def _secret(db_session, *, name: str | None = None) -> JoySafeterSecret:
    secret = JoySafeterSecret(
        name=name or f"secret-{uuid.uuid4()}",
        kind="generic",
        provider=None,
        protocol=None,
        data=encrypted_secret_data({"TOKEN": "value"}),
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
        kind="generic",
        provider=None,
        protocol=None,
        data=encrypted_secret_data({"TOKEN": "value"}),
        project_id=project_id,
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)
    return secret


async def _project_llm_secret(db_session, *, project_id: str, name: str | None = None) -> JoySafeterSecret:
    await _ensure_project(db_session, project_id)
    secret = JoySafeterSecret(
        name=name or f"llm-secret-{uuid.uuid4()}",
        kind="llm",
        provider="openai",
        protocol="openai_responses",
        data=encrypted_secret_data({"OPENAI_API_KEY": "value"}),
        project_id=project_id,
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)
    return secret


async def _assert_secret_intact(db_session, secret_id: SecretId) -> JoySafeterSecret:
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == secret_id))).scalar_one()
    assert row.deleted_at is None
    return row


async def _add_secret_reference(
    db_session,
    secret: JoySafeterSecret,
    category: str,
) -> str:
    if category == "agent":
        resource = JoySafeterAgent(name=f"rename-agent-{uuid.uuid4()}", secret_ref=secret.name)
        db_session.add(resource)
    elif category == "environment_direct":
        resource = JoySafeterEnvironment(
            name=f"rename-direct-environment-{uuid.uuid4()}",
            description="",
            config={"secret_refs": [secret.name]},
        )
        db_session.add(resource)
    elif category == "environment_egress":
        resource = JoySafeterEnvironment(
            name=f"rename-egress-environment-{uuid.uuid4()}",
            description="",
            config={
                "egress_services": [
                    {
                        "name": "crm",
                        "base_url": "https://crm.example.com",
                        "credential_ref": secret.name,
                        "inject": {"type": "bearer", "secret_key": "TOKEN"},
                    }
                ]
            },
        )
        db_session.add(resource)
    elif category == "trigger":
        agent = JoySafeterAgent(name=f"rename-trigger-agent-{uuid.uuid4()}")
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        resource = JoySafeterTrigger(
            name=f"rename-trigger-{uuid.uuid4()}",
            type="webhook",
            agent_id=agent.id,
            prompt_template="run",
            secret_ref=secret.name,
            secret_key="TOKEN",
            config={"auth_methods": ["hmac"]},
            filter={},
            last_payload={},
        )
        db_session.add(resource)
    else:
        raise AssertionError(f"unsupported test dependency category: {category}")
    await db_session.commit()
    return resource.name


@pytest.mark.asyncio
async def test_list_secrets_returns_canonical_secret_cursor(db_session):
    await _secret(db_session)
    await _secret(db_session)

    page = await list_secrets(limit=1, after_id=None, db=db_session, auth_ctx=_auth_ctx())

    assert page["has_more"] is True
    assert page["last_id"] is not None
    assert str(SecretId.from_public(page["last_id"])) == page["last_id"]


@pytest.mark.asyncio
async def test_create_secret_rejects_blank_field_name_without_persisting(db_session):
    project_id = f"project-{uuid.uuid4()}"
    await _ensure_project(db_session, project_id)
    secret_name = f"invalid-secret-{uuid.uuid4()}"
    app = _app(db_session, _project_auth_ctx(project_id))

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/secrets",
            json={
                "kind": "generic",
                "name": secret_name,
                "data": {"   ": "must-not-persist"},
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "REQUEST_VALIDATION_ERROR"
    assert payload["user_action"] == "fix_input"
    assert payload["data"]["errors"] == [
        {
            "field": "body.data",
            "message": "Value error, Secret field names must not be blank",
            "type": "value_error",
        }
    ]
    persisted = (
        await db_session.execute(
            select(JoySafeterSecret).where(
                JoySafeterSecret.project_id == project_id,
                JoySafeterSecret.name == secret_name,
            )
        )
    ).scalar_one_or_none()
    assert persisted is None


@pytest.mark.asyncio
async def test_create_secret_rejects_blank_resource_name_before_side_effects(
    db_session,
    monkeypatch,
):
    project_id = f"project-{uuid.uuid4()}"
    await _ensure_project(db_session, project_id)
    audit = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(secrets_api, "audit_joysafeter_event", audit)
    monkeypatch.setattr(secrets_api, "refresh_live_limited_sandbox_network_policies", refresh)
    app = _app(db_session, _project_auth_ctx(project_id))

    async with _client(app) as client:
        response = await client.post(
            "/api/v1/secrets",
            json={"kind": "generic", "name": "   ", "data": {"TOKEN": "must-not-persist"}},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
    assert response.json()["data"]["errors"] == [
        {
            "field": "body.name",
            "message": "Value error, Secret name must not be blank",
            "type": "value_error",
        }
    ]
    persisted = (
        (await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.project_id == project_id)))
        .scalars()
        .all()
    )
    assert persisted == []
    audit.assert_not_awaited()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_secret_rejects_blank_field_name_without_mutating(db_session):
    project_id = f"project-{uuid.uuid4()}"
    secret = await _project_secret(db_session, project_id=project_id)
    secret_id = secret.id
    app = _app(db_session, _project_auth_ctx(project_id))

    async with _client(app) as client:
        response = await client.put(
            f"/api/v1/secrets/{secret_id}",
            json={"data": {"": "must-not-persist"}},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "REQUEST_VALIDATION_ERROR"
    assert payload["user_action"] == "fix_input"
    assert payload["data"]["errors"] == [
        {
            "field": "body.data",
            "message": "Value error, Secret field names must not be blank",
            "type": "value_error",
        }
    ]
    db_session.expire_all()
    persisted = (
        await db_session.execute(select(JoySafeterSecret).where(JoySafeterSecret.id == secret_id))
    ).scalar_one()
    assert SecretService(db_session).get_secret_data(persisted) == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_update_secret_rejects_blank_resource_name_before_side_effects(
    db_session,
    monkeypatch,
):
    project_id = f"project-{uuid.uuid4()}"
    secret = await _project_secret(db_session, project_id=project_id, name="stable-name")
    secret_id = secret.id
    audit = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(secrets_api, "audit_joysafeter_event", audit)
    monkeypatch.setattr(secrets_api, "refresh_live_limited_sandbox_network_policies", refresh)
    app = _app(db_session, _project_auth_ctx(project_id))

    async with _client(app) as client:
        response = await client.put(
            f"/api/v1/secrets/{secret_id}",
            json={"name": "\t", "data": {"TOKEN": "must-not-persist"}},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
    assert response.json()["data"]["errors"] == [
        {
            "field": "body.name",
            "message": "Value error, Secret name must not be blank",
            "type": "value_error",
        }
    ]
    persisted = await _assert_secret_intact(db_session, secret_id)
    assert persisted.name == "stable-name"
    assert SecretService(db_session).get_secret_data(persisted) == {"TOKEN": "value"}
    audit.assert_not_awaited()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_secret_create_and_update_persist_trimmed_resource_names(db_session, monkeypatch):
    project_id = f"project-{uuid.uuid4()}"
    await _ensure_project(db_session, project_id)
    monkeypatch.setattr(secrets_api, "audit_joysafeter_event", AsyncMock())
    monkeypatch.setattr(
        secrets_api,
        "refresh_live_limited_sandbox_network_policies",
        AsyncMock(return_value=0),
    )
    app = _app(db_session, _project_auth_ctx(project_id))

    async with _client(app) as client:
        create_response = await client.post(
            "/api/v1/secrets",
            json={
                "kind": "generic",
                "name": "  canonical-service  ",
                "data": {"TOKEN": "value"},
            },
        )
        assert create_response.status_code == 201
        assert create_response.json()["name"] == "canonical-service"
        secret_id = SecretId.from_public(create_response.json()["id"])

        update_response = await client.put(
            f"/api/v1/secrets/{secret_id}",
            json={"name": "  renamed-service  ", "data": {"TOKEN": "next-value"}},
        )

    assert update_response.status_code == 200
    assert update_response.json()["name"] == "renamed-service"
    persisted = await db_session.get(JoySafeterSecret, secret_id)
    assert persisted is not None
    assert persisted.name == "renamed-service"
    assert SecretService(db_session).get_secret_data(persisted) == {"TOKEN": "next-value"}


@pytest.mark.asyncio
async def test_historical_noncanonical_secret_names_remain_listable_and_renamable(db_session):
    project_id = f"project-{uuid.uuid4()}"
    historical = await _project_secret(
        db_session,
        project_id=project_id,
        name="  historical-service  ",
    )
    auth_ctx = _project_auth_ctx(project_id)

    page = await list_secrets(
        limit=10,
        after_id=None,
        kind=None,
        name=None,
        provider=None,
        protocol=None,
        compatible_engine=None,
        db=db_session,
        auth_ctx=auth_ctx,
    )
    updated = await SecretService(db_session).update_secret(
        historical.id,
        UpdateSecretRequest(name=" cleaned-service ", data={"TOKEN": "value"}),
        project_id=project_id,
    )

    assert [item["name"] for item in page["data"]] == ["  historical-service  "]
    assert updated is not None
    assert updated.name == "cleaned-service"


@pytest.mark.asyncio
async def test_secret_reference_inventory_classifies_all_rename_blockers(db_session):
    secret = await _secret(db_session)
    resource_names = {
        category: await _add_secret_reference(db_session, secret, category)
        for category in ("agent", "environment_direct", "environment_egress", "trigger")
    }

    dependencies = await SecretService(db_session).secret_reference_dependencies(secret.name)

    assert [(dependency.category, dependency.resource_name) for dependency in dependencies] == [
        ("agent", resource_names["agent"]),
        ("environment_direct", resource_names["environment_direct"]),
        ("environment_egress", resource_names["environment_egress"]),
        ("trigger", resource_names["trigger"]),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category",
    ["agent", "environment_direct", "environment_egress", "trigger"],
)
async def test_update_secret_blocks_referenced_rename_without_mutation_or_side_effects(
    db_session,
    monkeypatch,
    category,
):
    secret = await _secret(db_session)
    await _add_secret_reference(db_session, secret, category)
    audit = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(secrets_api, "audit_joysafeter_event", audit)
    monkeypatch.setattr(secrets_api, "refresh_live_limited_sandbox_network_policies", refresh)
    app = _app(db_session, _auth_ctx())

    async with _client(app) as client:
        response = await client.put(
            f"/api/v1/secrets/{secret.id}",
            json={"name": "renamed-secret", "data": {"TOKEN": "must-not-persist"}},
        )

    assert response.status_code == 409
    assert response.json() == {
        "code": "SECRET_RENAME_REFERENCED",
        "message": "Secret name cannot be changed while the current name is referenced",
        "data": {
            "secret_id": str(secret.id),
            "secret_name": secret.name,
            "dependency_categories": [category],
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    persisted = await _assert_secret_intact(db_session, secret.id)
    assert persisted.name == secret.name
    assert SecretService(db_session).get_secret_data(persisted) == {"TOKEN": "value"}
    assert "must-not-persist" not in response.text
    audit.assert_not_awaited()
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_secret_responses_omit_historical_blank_field_names_without_plaintext(db_session):
    project_id = f"project-{uuid.uuid4()}"
    await _ensure_project(db_session, project_id)
    secret = JoySafeterSecret(
        name=f"historical-secret-{uuid.uuid4()}",
        kind="generic",
        provider=None,
        protocol=None,
        data=encrypted_secret_data(
            {
                "": "empty-name-plaintext",
                "   ": "whitespace-name-plaintext",
                " TOKEN ": "surrounded-name-plaintext",
                "TOKEN": "normal-name-plaintext",
            }
        ),
        project_id=project_id,
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)
    auth_ctx = _project_auth_ctx(project_id)

    page = await list_secrets(
        limit=10,
        after_id=None,
        kind=None,
        name=secret.name,
        provider=None,
        protocol=None,
        compatible_engine=None,
        db=db_session,
        auth_ctx=auth_ctx,
    )
    detail = await get_secret(secret.id, db_session, auth_ctx)

    assert page["data"][0]["keys"] == [" TOKEN ", "TOKEN"]
    assert set(detail.secret_data) == {" TOKEN ", "TOKEN"}
    assert all(value.startswith("********") for value in detail.secret_data.values())
    assert not {
        "empty-name-plaintext",
        "whitespace-name-plaintext",
        "surrounded-name-plaintext",
        "normal-name-plaintext",
    }.intersection(detail.secret_data.values())


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
async def test_delete_secret_rejects_egress_environment_reference_without_force(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"egress-secret-env-{uuid.uuid4()}",
        description="",
        config={
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": secret.name,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ]
        },
    )
    db_session.add(env)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await secrets_api.delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    payload = await handled_app_error_payload(exc_info.value, status_code=409)
    assert payload["code"] == "SECRET_ENVIRONMENT_REFERENCE"
    assert payload["data"]["environment_name"] == env.name
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
async def test_delete_secret_rejects_trigger_reference_without_force_but_allows_force(db_session):
    secret = await _secret(db_session)
    agent = JoySafeterAgent(name=f"trigger-secret-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    trigger = JoySafeterTrigger(
        name=f"secret-trigger-{uuid.uuid4()}",
        type="webhook",
        agent_id=agent.id,
        prompt_template="run",
        secret_ref=secret.name,
        secret_key="TOKEN",
        config={"auth_methods": ["hmac"]},
        filter={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await secrets_api.delete_secret(None, secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    payload = await handled_app_error_payload(exc_info.value, status_code=409)
    assert payload["code"] == "SECRET_TRIGGER_REFERENCE"
    assert payload["data"]["trigger_name"] == trigger.name
    await _assert_secret_intact(db_session, secret.id)

    await secrets_api.delete_secret(_request(), secret.id, True, db_session, _auth_ctx())
    deleted = await SecretService(db_session).get_secret(secret.id)
    assert deleted is None


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
async def test_force_delete_secret_rejects_active_task_agent_egress_environment_ref(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"agent-egress-env-secret-{uuid.uuid4()}",
        description="",
        config={
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": secret.name,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ]
        },
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    agent = JoySafeterAgent(name=f"agent-egress-env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
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
        await secrets_api.delete_secret(None, secret.id, True, db_session, _auth_ctx())  # type: ignore[arg-type]

    payload = await handled_app_error_payload(exc_info.value, status_code=409)
    assert payload["code"] == "SECRET_ACTIVE_TASK_DEPENDENCY"
    assert payload["data"]["task_id"] == str(task.id)
    assert payload["data"]["source"] == "agent environment_ref"
    assert payload["data"]["operation"] == "deleting"
    await _assert_secret_intact(db_session, secret.id)


@pytest.mark.asyncio
async def test_force_delete_secret_does_not_refresh_for_active_egress_dependency(db_session, monkeypatch):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"refresh-agent-egress-env-secret-{uuid.uuid4()}",
        description="",
        config={
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": secret.name,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ]
        },
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    agent = JoySafeterAgent(name=f"refresh-agent-egress-env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
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
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.joysafeter_api.api.v1.secrets.refresh_live_limited_sandbox_network_policies",
        refresh,
    )

    with pytest.raises(AppError) as exc_info:
        await secrets_api.delete_secret(_request(), secret.id, True, db_session, _auth_ctx())

    payload = await handled_app_error_payload(exc_info.value, status_code=409)
    assert payload["code"] == "SECRET_ACTIVE_TASK_DEPENDENCY"
    assert payload["data"]["task_id"] == str(task.id)
    assert payload["data"]["source"] == "agent environment_ref"
    assert payload["data"]["operation"] == "deleting"
    await _assert_secret_intact(db_session, secret.id)
    assert refresh.await_count == 0


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
    agent = JoySafeterAgent(name=f"agent-env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
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
async def test_update_secret_allows_data_only_change_with_active_agent_dependency(db_session):
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

    await update_secret(
        UpdateSecretRequest(data={"TOKEN": "new-value"}),
        _request(),
        secret.id,
        db_session,
        _auth_ctx(),
    )
    row = await _assert_secret_intact(db_session, secret.id)
    assert row.name == secret.name
    assert SecretService(db_session).get_secret_data(row) == {"TOKEN": "new-value"}


@pytest.mark.asyncio
async def test_update_secret_allows_data_only_change_with_active_egress_dependency(db_session):
    secret = await _secret(db_session)
    env = JoySafeterEnvironment(
        name=f"update-agent-egress-env-secret-{uuid.uuid4()}",
        description="",
        config={
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": secret.name,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ]
        },
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    agent = JoySafeterAgent(name=f"update-agent-egress-env-agent-{uuid.uuid4()}", environment_ref=str(env.id))
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

    await secrets_api.update_secret(
        UpdateSecretRequest(data={"TOKEN": "new-value"}),
        _request(),
        secret.id,
        db_session,
        _auth_ctx(),
    )
    row = await _assert_secret_intact(db_session, secret.id)
    assert row.name == secret.name
    assert SecretService(db_session).get_secret_data(row) == {"TOKEN": "new-value"}


@pytest.mark.asyncio
async def test_update_secret_treats_padded_same_name_as_data_only_with_active_dependency(db_session):
    secret = await _secret(db_session, name="canonical-secret")
    agent = JoySafeterAgent(name=f"same-name-agent-{uuid.uuid4()}", secret_ref=secret.name)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    db_session.add(
        JoySafeterTask(
            agent_id=agent.id,
            prompt="scan target",
            status=JoySafeterTaskStatus.PENDING.value,
        )
    )
    await db_session.commit()

    await update_secret(
        UpdateSecretRequest(name="  canonical-secret  ", data={"TOKEN": "new-value"}),
        _request(),
        secret.id,
        db_session,
        _auth_ctx(),
    )

    row = await _assert_secret_intact(db_session, secret.id)
    assert row.name == "canonical-secret"
    assert SecretService(db_session).get_secret_data(row) == {"TOKEN": "new-value"}


@pytest.mark.asyncio
async def test_update_secret_refreshes_live_limited_sandbox_network_policies(db_session, monkeypatch):
    secret = await _secret(db_session)
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.joysafeter_api.api.v1.secrets.refresh_live_limited_sandbox_network_policies",
        refresh,
    )

    await secrets_api.update_secret(
        UpdateSecretRequest(data={"TOKEN": "new-value"}),
        _request(),
        secret.id,
        db_session,
        _auth_ctx(),
    )  # type: ignore[arg-type]

    refresh.assert_awaited_once_with(
        db_session,
        project_id=None,
        reason="secret.updated",
        source_type="secret",
        source_id=str(secret.id),
    )


@pytest.mark.asyncio
async def test_delete_secret_refreshes_live_limited_sandbox_network_policies(db_session, monkeypatch):
    secret = await _secret(db_session)
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.joysafeter_api.api.v1.secrets.refresh_live_limited_sandbox_network_policies",
        refresh,
    )

    await secrets_api.delete_secret(_request(), secret.id, False, db_session, _auth_ctx())

    refresh.assert_awaited_once_with(
        db_session,
        project_id=None,
        reason="secret.deleted",
        source_type="secret",
        source_id=str(secret.id),
    )


@pytest.mark.asyncio
async def test_force_delete_secret_refreshes_only_after_successful_validation(db_session, monkeypatch):
    secret = await _secret(db_session)
    referenced_secret = await _secret(db_session)
    agent = JoySafeterAgent(name=f"refresh-secret-agent-{uuid.uuid4()}", secret_ref=referenced_secret.name)
    db_session.add(agent)
    await db_session.commit()
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "app.joysafeter_api.api.v1.secrets.refresh_live_limited_sandbox_network_policies",
        refresh,
    )

    await secrets_api.delete_secret(_request(), secret.id, True, db_session, _auth_ctx())

    refresh.assert_awaited_once_with(
        db_session,
        project_id=None,
        reason="secret.deleted",
        source_type="secret",
        source_id=str(secret.id),
    )

    with pytest.raises(AppError):
        await secrets_api.delete_secret(None, referenced_secret.id, False, db_session, _auth_ctx())  # type: ignore[arg-type]

    assert refresh.await_count == 1


@pytest.mark.asyncio
async def test_create_secret_reports_missing_vault_configuration(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_secret_service._cipher",
        _DisabledCipher(),
    )

    req = CreateSecretRequest(kind="generic", name=f"new-secret-{uuid.uuid4()}", data={"TOKEN": "new-value"})
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
    original_data = dict(secret.data)
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
    assert row.data == original_data


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
    assert SecretService(db_session).get_secret_data(row) == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_delete_secret_rejects_cross_project_at_service_boundary(db_session):
    secret = await _project_secret(db_session, project_id="project-b")

    deleted = await SecretService(db_session).delete_secret(secret.id, project_id="project-a")
    hard_deleted = await SecretService(db_session).hard_delete_secret(secret.id, project_id="project-a")

    assert deleted is False
    assert hard_deleted is False
    row = await _assert_secret_intact(db_session, secret.id)
    assert SecretService(db_session).get_secret_data(row) == {"TOKEN": "value"}


@pytest.mark.asyncio
async def test_set_default_secret_rejects_cross_project_at_service_boundary(db_session):
    target = await _project_llm_secret(db_session, project_id="project-b")
    default = await _project_llm_secret(db_session, project_id="project-a")
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
    project_a_default = await _project_llm_secret(db_session, project_id="project-a")
    project_a_next = await _project_llm_secret(db_session, project_id="project-a")
    project_b_default = await _project_llm_secret(db_session, project_id="project-b")
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
        CreateSecretRequest(kind="generic", name="old-secret", data={}),
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
