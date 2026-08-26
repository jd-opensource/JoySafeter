import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.joysafeter_api.api.v1 import triggers as trigger_api
from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.triggers import TriggerApplicationService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, CredentialId, OrganizationId, ProjectId, TriggerId, UserId

USER_ID = UserId.from_public("user_00000000-0000-0000-0000-000000000001")
ORG_ID = OrganizationId.from_public("org_00000000-0000-0000-0000-000000000001")
PROJECT_ID = ProjectId.from_public("proj_00000000-0000-0000-0000-000000000001")


async def _make_service_credential(db_session, project_id: ProjectId) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="service",
            name=f"s-{uuid.uuid4()}",
            data={"WEBHOOK_SECRET": "hook-secret-value"},
        ),
        project_id=project_id,
    )
    return cred.id


def _ctx(project_id: ProjectId = PROJECT_ID, org_id: OrganizationId = ORG_ID) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=USER_ID,
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
        project_role="admin",
    )


def _app(db, ctx: JoySafeterAuthContext) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(trigger_api.router, prefix="/api/v1/triggers")
    app.dependency_overrides[trigger_api.get_db] = lambda: db
    app.dependency_overrides[trigger_api.require_joysafeter_write] = lambda: ctx
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class _NoDb:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid trigger payload should be rejected before DB access")


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_create_invalid_trigger_type_returns_semantic_error_without_db_access():
    app = _app(_NoDb(), _ctx())
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "bad-type",
                "type": "event",
                "agent_id": f"agent_{uuid.uuid4()}",
                "prompt_template": "run",
            },
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_TYPE_UNSUPPORTED"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"]["type"] == "event"


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_create_invalid_webhook_auth_method_returns_semantic_error_without_db_access():
    app = _app(_NoDb(), _ctx())
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "bad-auth",
                "type": "webhook",
                "agent_id": f"agent_{uuid.uuid4()}",
                "prompt_template": "run",
                "webhook_auth_credential_id": str(CredentialId.new()),
                "webhook_auth_field": "WEBHOOK_SECRET",
                "auth_methods": ["magic-link"],
            },
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_AUTH_METHODS_INVALID"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"] == {"type": "webhook"}


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_update_invalid_webhook_auth_method_returns_semantic_error_without_db_access():
    app = _app(_NoDb(), _ctx())
    async with _client(app) as client:
        resp = await client.patch(
            f"/api/v1/triggers/{TriggerId.new()}",
            json={"auth_methods": ["magic-link"]},
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_AUTH_METHODS_INVALID"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"] == {"type": "webhook"}


@pytest.mark.no_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_methods",
    (
        123,
        "hmac",
        {"hmac": True},
        [["hmac"]],
        [123],
    ),
    ids=("non-iterable", "string", "mapping", "unhashable-item", "non-string-item"),
)
async def test_direct_create_rejects_malformed_auth_methods_before_db_access(auth_methods):
    service = TriggerApplicationService(_NoDb(), credential_audit_actor=CredentialAuditActor.system("test"))

    with pytest.raises(RequestValidationAppError) as exc:
        await service.create(
            name=f"bad-auth-{uuid.uuid4()}",
            type="webhook",
            agent_id=AgentId.new(),
            prompt_template="run",
            webhook_auth_credential_id=CredentialId.new(),
            webhook_auth_field="WEBHOOK_SECRET",
            auth_methods=auth_methods,
            project_id=PROJECT_ID,
        )

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


@pytest.mark.no_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_methods",
    (
        123,
        "hmac",
        {"hmac": True},
        [["hmac"]],
        [123],
    ),
    ids=("non-iterable", "string", "mapping", "unhashable-item", "non-string-item"),
)
async def test_direct_update_rejects_malformed_auth_methods_before_db_access(auth_methods):
    service = TriggerApplicationService(_NoDb(), credential_audit_actor=CredentialAuditActor.system("test"))

    with pytest.raises(RequestValidationAppError) as exc:
        await service.update(TriggerId.new(), PROJECT_ID, auth_methods=auth_methods)

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_create_missing_webhook_auth_methods_returns_semantic_error_without_db_access():
    app = _app(_NoDb(), _ctx())
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "missing-auth",
                "type": "webhook",
                "agent_id": f"agent_{uuid.uuid4()}",
                "prompt_template": "run",
                "webhook_auth_credential_id": str(CredentialId.new()),
                "webhook_auth_field": "WEBHOOK_SECRET",
            },
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_AUTH_METHODS_REQUIRED"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"] == {"type": "webhook"}


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_create_blank_webhook_secret_key_returns_semantic_error_without_db_access():
    app = _app(_NoDb(), _ctx())
    async with _client(app) as client:
        resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "blank-secret-key",
                "type": "webhook",
                "agent_id": f"agent_{uuid.uuid4()}",
                "prompt_template": "run",
                "webhook_auth_credential_id": str(CredentialId.new()),
                "webhook_auth_field": "   ",
            },
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_SECRET_KEY_REQUIRED"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"] == {"type": "webhook"}


@pytest.mark.asyncio
async def test_update_invalid_session_mode_returns_semantic_error(db_session):
    org = Organization(
        id=OrganizationId.new(), name=f"Trigger HTTP Org {uuid.uuid4()}", slug=f"trigger-http-org-{uuid.uuid4()}"
    )
    db_session.add(org)
    await db_session.flush()

    project = Project(
        id=ProjectId.new(), org_id=org.id, name="Trigger HTTP Project", slug=f"trigger-http-project-{uuid.uuid4()}"
    )
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(id=AgentId.new(), name=f"trigger-http-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()

    cred_id = await _make_service_credential(db_session, project.id)

    trigger = JoySafeterTrigger(
        id=TriggerId.new(),
        name=f"trigger-http-{uuid.uuid4()}",
        type="webhook",
        agent_id=agent.id,
        prompt_template="run",
        enabled=True,
        session_mode="fresh",
        filter={},
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        last_payload={},
        project_id=project.id,
        user_id=USER_ID,
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()

    app = _app(db_session, _ctx(project_id=project.id, org_id=org.id))
    async with _client(app) as client:
        resp = await client.patch(f"/api/v1/triggers/{trigger.id}", json={"session_mode": "loop"})

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_SESSION_MODE_INVALID"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"]["session_mode"] == "loop"


@pytest.mark.asyncio
async def test_update_blank_webhook_secret_key_returns_semantic_error_without_persisting(db_session):
    org = Organization(
        id=OrganizationId.new(),
        name=f"Trigger HTTP Secret Org {uuid.uuid4()}",
        slug=f"trigger-http-secret-org-{uuid.uuid4()}",
    )
    db_session.add(org)
    await db_session.flush()

    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Trigger HTTP Secret Project",
        slug=f"trigger-http-secret-project-{uuid.uuid4()}",
    )
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(id=AgentId.new(), name=f"trigger-http-secret-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()

    cred_id = await _make_service_credential(db_session, project.id)

    trigger = JoySafeterTrigger(
        id=TriggerId.new(),
        name=f"trigger-http-secret-{uuid.uuid4()}",
        type="webhook",
        agent_id=agent.id,
        prompt_template="run",
        enabled=True,
        session_mode="fresh",
        filter={},
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        last_payload={},
        project_id=project.id,
        user_id=USER_ID,
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()

    app = _app(db_session, _ctx(project_id=project.id, org_id=org.id))
    async with _client(app) as client:
        resp = await client.patch(f"/api/v1/triggers/{trigger.id}", json={"webhook_auth_field": "   "})

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_SECRET_KEY_REQUIRED"
    assert resp.json()["user_action"] == "fix_input"
    assert resp.json()["data"] == {"type": "webhook"}
    await db_session.refresh(trigger)
    assert trigger.webhook_auth_field == "WEBHOOK_SECRET"
