"""Service-level tests: an Environment references service credentials
by stable id (was name-based ``credential_ref``/``environment_credential_ids``).

Real-DB tests via conftest's ``db_session``: the CredentialService kind check is
enforced against Postgres. The full app is intentionally un-loadable mid-cutover,
so everything here runs at the service/route-helper level (no TestClient).
"""

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select

from app.joysafeter_api.api.v1.environments import create_environment, update_environment
from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.environments import (
    EnvironmentCredentialService,
)
from app.joysafeter_application.environments import (
    credential_service as environment_credential_service_module,
)
from app.joysafeter_application.environments.credential_service import (
    _changed_credential_binding_usages,
)
from app.joysafeter_domain.credentials import (
    CredentialImpact,
    CredentialUsage,
    DependencyDisposition,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    EnvironmentCredentialReference,
    UpdateEnvironmentRequest,
    extract_environment_credential_references,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialId,
    OrganizationId,
    ProjectId,
    SandboxId,
    SessionId,
    UserId,
)

TEST_USER_ID = UserId.new()
TEST_ORG_ID = OrganizationId.new()


async def _make_project(db_session) -> ProjectId:
    org = Organization(id=OrganizationId.new(), name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name=f"proj-{uuid.uuid4()}",
        slug=f"proj-{uuid.uuid4()}",
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> ProjectId:
    return await _make_project(db_session)


async def _make_service_credential(
    db_session,
    project_id: ProjectId,
    data: dict[str, str] | None = None,
) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="service",
            name=f"s-{uuid.uuid4()}",
            data=data if data is not None else {"ACCESS_TOKEN": "t"},
        ),
        project_id=project_id,
    )
    return cred.id


async def _make_model_credential(db_session, project_id: ProjectId) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "sk-secret"},
        ),
        project_id=project_id,
    )
    return cred.id


def _auth_ctx(project_id: ProjectId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=TEST_ORG_ID,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _egress_config(credential_ref: CredentialId) -> EnvironmentConfig:
    return EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api/",
                "credential_ref": str(credential_ref),
                "inject": {"type": "bearer", "credential_field": "ACCESS_TOKEN"},
            }
        ]
    )


@pytest.mark.asyncio
async def test_create_environment_with_valid_service_credential_persists(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    config = _egress_config(cred_id)
    await EnvironmentCredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).validate_references(
        config, project_id
    )

    svc = EnvironmentService(db_session)
    env = await svc.create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        project_id=project_id,
    )

    stored = env.config["egress_services"][0]["credential_ref"]
    assert stored == str(cred_id)
    assert "service_credential_id" not in env.config["egress_services"][0]


@pytest.mark.asyncio
async def test_validate_rejects_nonexistent_credential(db_session, project_id):
    config = _egress_config(CredentialId.new())
    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(config, project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_validate_rejects_non_service_credential_kind(db_session, project_id):
    model_cred_id = await _make_model_credential(db_session, project_id)
    config = _egress_config(model_cred_id)
    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(config, project_id)
    assert exc.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_validate_rejects_credential_from_other_project(db_session, project_id):
    other_project = await _make_project(db_session)
    other_cred_id = await _make_service_credential(db_session, other_project)
    config = _egress_config(other_cred_id)
    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(config, project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_validate_rejects_archived_credential_with_state_invalid(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    credential = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).get(
        credential_id, project_id=project_id
    )
    credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(_egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_STATE_INVALID"
    assert exc.value.data == {
        "credential_id": str(credential_id),
        "source": "egress_services",
        "index": 0,
        "path": "egress_services[0]",
    }


@pytest.mark.asyncio
async def test_validate_rejects_deleted_credential_with_not_found(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).soft_delete(
        credential_id,
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(_egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_http_egress_requires_exact_inject_field(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})

    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(_egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_environment_injection_requires_posix_material_names(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"NOT-POSIX": "value"})

    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(
            EnvironmentConfig(environment_credential_ids=[str(credential_id)]),
            project_id,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_validate_credential_references_direct_source(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    config = EnvironmentConfig(environment_credential_ids=[str(cred_id)])
    await EnvironmentCredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).validate_references(
        config, project_id
    )


def test_extract_environment_credential_references_from_both_sources():
    direct_id = CredentialId.new()
    egress_id = CredentialId.new()
    config = EnvironmentConfig(
        environment_credential_ids=[str(direct_id)],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api/",
                "credential_ref": str(egress_id),
            }
        ],
    )

    assert extract_environment_credential_references(config) == [
        EnvironmentCredentialReference(
            direct_id,
            "environment_credential_ids",
            0,
            "environment_credential_ids[0]",
        ),
        EnvironmentCredentialReference(egress_id, "egress_services", 0, "egress_services[0]"),
    ]


def test_extract_environment_references_preserves_each_occurrence_and_path():
    credential_id = CredentialId.new()
    config = EnvironmentConfig(
        environment_credential_ids=[credential_id],
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "ONE"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "TWO"},
            },
        ],
    )

    assert extract_environment_credential_references(config) == [
        EnvironmentCredentialReference(
            credential_id,
            "environment_credential_ids",
            0,
            "environment_credential_ids[0]",
        ),
        EnvironmentCredentialReference(credential_id, "egress_services", 0, "egress_services[0]"),
        EnvironmentCredentialReference(credential_id, "egress_services", 1, "egress_services[1]"),
    ]


@pytest.mark.asyncio
async def test_validate_same_credential_as_direct_and_egress_occurrences(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"ACCESS_TOKEN": "t"})
    config = EnvironmentConfig(
        environment_credential_ids=[credential_id],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "ACCESS_TOKEN"},
            }
        ],
    )

    await EnvironmentCredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).validate_references(
        config, project_id
    )


@pytest.mark.asyncio
async def test_validate_repeated_egress_credential_checks_each_field(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"VALID": "t"})
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "VALID"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "MISSING"},
            },
        ]
    )

    with pytest.raises(AppError) as exc:
        await EnvironmentCredentialService(
            db_session, audit_actor=CredentialAuditActor.system("test")
        ).validate_references(config, project_id)

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"
    assert exc.value.data == {
        "credential_id": str(credential_id),
        "source": "egress_services",
        "index": 1,
        "path": "egress_services[1]",
    }


@pytest.mark.asyncio
async def test_environment_create_route_accepts_same_credential_direct_and_egress(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"ACCESS_TOKEN": "t"})
    config = EnvironmentConfig(
        environment_credential_ids=[credential_id],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "ACCESS_TOKEN"},
            }
        ],
    )

    response = await create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")
    audit = await db_session.scalar(
        select(SecurityAuditLog).where(
            SecurityAuditLog.event_type == "environment.credentials.updated",
            SecurityAuditLog.details["target_id"].astext == str(response.id),
        )
    )
    assert audit is not None
    assert audit.user_id == TEST_USER_ID
    assert audit.details["principal_type"] == "user"
    assert audit.details["principal_id"] == str(TEST_USER_ID)
    assert audit.details["runtime_restart_required"] is False


@pytest.mark.asyncio
async def test_environment_update_route_rejects_second_invalid_egress_occurrence(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"VALID": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    original_config = dict(environment.config)
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "VALID"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "MISSING"},
            },
        ]
    )

    with pytest.raises(AppError) as exc:
        await update_environment(
            UpdateEnvironmentRequest(config=config),
            environment.id,
            db_session,
            _auth_ctx(project_id),
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"
    await db_session.refresh(environment)
    assert environment.config == original_config


@pytest.mark.asyncio
async def test_environment_update_orders_mutation_audit_pending_single_commit_nudge(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add(sandbox)
    await db_session.commit()
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    events: list[str] = []
    committed: list[None] = []
    impacts = []
    original_update = EnvironmentService.update_environment
    original_append = application.uow.audit.append
    original_mark = application.uow.impacts.mark_pending

    async def recorded_update(self, *args, **kwargs):
        events.append("mutation")
        return await original_update(self, *args, **kwargs)

    async def recorded_append(entry):
        events.append("audit")
        assert entry.target_type == "environment"
        await original_append(entry)

    async def recorded_mark(impact):
        events.append("pending")
        impacts.append(impact)
        return await original_mark(impact)

    async def recorded_nudge():
        events.append("nudge")

    monkeypatch.setattr(EnvironmentService, "update_environment", recorded_update)

    def compose_with_request_actor(*args, **kwargs):
        application.uow.audit._actor = kwargs["audit_actor"]
        return application

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        compose_with_request_actor,
    )
    monkeypatch.setattr(application.uow.audit, "append", recorded_append)
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)
    sqlalchemy_event.listen(
        db_session.sync_session,
        "after_commit",
        lambda session: (events.append("commit"), committed.append(None)),
    )

    config = EnvironmentConfig(environment_credential_ids=[credential_id])
    response = await update_environment(
        UpdateEnvironmentRequest(config=config),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")
    assert events == ["mutation", "audit", "pending", "commit", "nudge"]
    assert len(committed) == 1
    assert [impact.usage for impact in impacts] == [CredentialUsage.ENVIRONMENT_INJECTION]
    assert impacts[0].dispositions == frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION})
    await db_session.refresh(sandbox)
    assert sandbox.networking_status == "ready"
    audit = (
        await db_session.execute(
            select(SecurityAuditLog).where(SecurityAuditLog.event_type == "environment.credentials.updated")
        )
    ).scalar_one()
    assert audit.user_id == TEST_USER_ID
    assert audit.ip_address == "unknown"
    assert audit.details["principal_type"] == "user"
    assert audit.details["principal_id"] == str(TEST_USER_ID)
    assert audit.details["target_type"] == "environment"
    assert audit.details["runtime_restart_required"] is True


@pytest.mark.asyncio
async def test_environment_direct_binding_update_marks_only_its_live_session_sandbox_restart_required(
    db_session,
    project_id,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "value"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    unrelated_environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"unrelated-env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    matching_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        environment_id=environment.id,
        runtime_config_generation=4,
    )
    matching_session_without_sandbox = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        environment_id=environment.id,
        runtime_config_generation=9,
    )
    unrelated_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        environment_id=unrelated_environment.id,
        runtime_config_generation=6,
    )
    db_session.add_all([matching_session, matching_session_without_sandbox, unrelated_session])
    await db_session.flush()
    matching_sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=matching_session.id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
    )
    unrelated_sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=unrelated_session.id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
    )
    db_session.add_all([matching_sandbox, unrelated_sandbox])
    await db_session.commit()

    await update_environment(
        UpdateEnvironmentRequest(config=EnvironmentConfig(environment_credential_ids=[credential_id])),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    await db_session.refresh(matching_sandbox)
    await db_session.refresh(unrelated_sandbox)
    await db_session.refresh(matching_session)
    await db_session.refresh(matching_session_without_sandbox)
    await db_session.refresh(unrelated_session)
    assert matching_sandbox.runtime_config_status == "restart_required"
    assert matching_sandbox.runtime_config_last_reason == "environment.updated"
    assert matching_sandbox.runtime_config_required_at is not None
    assert matching_sandbox.networking_status == "ready"
    assert unrelated_sandbox.runtime_config_status == "ready"
    assert matching_session.runtime_config_generation == 5
    assert matching_session.runtime_config_generation_reason == "environment.updated"
    assert matching_session.runtime_config_generation_updated_at is not None
    assert matching_session_without_sandbox.runtime_config_generation == 10
    assert matching_session_without_sandbox.runtime_config_generation_reason == "environment.updated"
    assert matching_session_without_sandbox.runtime_config_generation_updated_at is not None
    assert unrelated_session.runtime_config_generation == 6


@pytest.mark.asyncio
async def test_direct_injection_credential_rotation_requires_reactivation_without_network_refresh(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "old"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"env-{uuid.uuid4()}",
            config=EnvironmentConfig(environment_credential_ids=[credential_id]),
        ),
        project_id=project_id,
    )
    other_environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"other-env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=environment.id,
        runtime_config_generation=2,
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {"config": {}},
        },
    )
    snapshot_only_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        environment_id=None,
        runtime_config_generation=7,
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {"config": {"environment_credential_ids": [str(credential_id)]}},
        },
    )
    other_environment_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        environment_id=other_environment.id,
        runtime_config_generation=11,
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {"config": {"environment_credential_ids": [str(credential_id)]}},
        },
    )
    db_session.add_all([session, snapshot_only_session, other_environment_session])
    await db_session.flush()
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session.id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add(sandbox)
    await db_session.commit()
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    impacts = []
    network_refreshes = []
    original_mark = application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    application.uow.impacts.mark_pending = capture_impact
    monkeypatch.setattr(
        "app.joysafeter_infrastructure.credentials.network_policy_adapter.nudge_sandbox_network_policy_refreshes",
        lambda *args, **kwargs: network_refreshes.append((args, kwargs)),
    )

    await application.resource_service.update(
        credential_id,
        UpdateCredentialRequest(data={"TOKEN": "new"}),
        project_id=project_id,
    )

    assert [impact.usage for impact in impacts] == [CredentialUsage.ENVIRONMENT_INJECTION]
    assert impacts[0].dispositions == frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION})
    assert impacts[0].affected_sandbox_ids == frozenset({sandbox.id})
    assert impacts[0].affected_session_ids == frozenset({session.id, snapshot_only_session.id})
    await db_session.refresh(sandbox)
    await db_session.refresh(session)
    await db_session.refresh(snapshot_only_session)
    await db_session.refresh(other_environment_session)
    assert sandbox.runtime_config_status == "restart_required"
    assert sandbox.runtime_config_last_reason == "credential_updated"
    assert sandbox.runtime_config_required_at is not None
    assert sandbox.networking_status == "ready"
    assert session.runtime_config_generation == 3
    assert session.runtime_config_generation_reason == "credential_updated"
    assert session.runtime_config_generation_updated_at is not None
    assert snapshot_only_session.runtime_config_generation == 8
    assert snapshot_only_session.runtime_config_generation_reason == "credential_updated"
    assert other_environment_session.runtime_config_generation == 11
    assert network_refreshes == []


@pytest.mark.asyncio
async def test_mixed_environment_update_advances_generation_once_and_keeps_project_wide_egress_refresh(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "old"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=environment.id,
        runtime_config_generation=13,
    )
    db_session.add(session)
    await db_session.flush()
    attached = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session.id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    unrelated = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add_all([attached, unrelated])
    await db_session.commit()
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    impacts = []
    original_mark = application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        lambda *args, **kwargs: application,
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)

    await update_environment(
        UpdateEnvironmentRequest(
            config=EnvironmentConfig(
                environment_credential_ids=[credential_id],
                egress_services=[
                    {
                        "name": "api",
                        "base_url": "https://api.example.com",
                        "credential_ref": credential_id,
                        "inject": {"type": "bearer", "credential_field": "TOKEN"},
                    }
                ],
            )
        ),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    await db_session.refresh(session)
    await db_session.refresh(attached)
    await db_session.refresh(unrelated)
    assert len(impacts) == 1
    assert impacts[0].usage is CredentialUsage.ENVIRONMENT_INJECTION
    assert impacts[0].dispositions == frozenset(
        {
            DependencyDisposition.REVALIDATE_ON_ACTIVATION,
            DependencyDisposition.REFRESH_RUNTIME_POLICY,
        }
    )
    assert impacts[0].affected_session_ids == frozenset({session.id})
    assert impacts[0].affected_sandbox_ids == frozenset({attached.id, unrelated.id})
    assert session.runtime_config_generation == 14
    assert session.runtime_config_generation_reason == "environment.updated"
    assert attached.runtime_config_status == "restart_required"
    assert attached.networking_status == "pending"
    assert unrelated.networking_status == "pending"


@pytest.mark.asyncio
async def test_session_without_environment_binding_uses_snapshot_for_direct_credential_rotation(
    db_session,
    project_id,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "old"})
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=None,
        runtime_config_generation=21,
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {"config": {"environment_credential_ids": [str(credential_id)]}},
        },
    )
    db_session.add(session)
    await db_session.flush()
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        chat_session_id=session.id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
    )
    db_session.add(sandbox)
    await db_session.commit()

    await compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
    ).resource_service.update(
        credential_id,
        UpdateCredentialRequest(data={"TOKEN": "new"}),
        project_id=project_id,
    )

    await db_session.refresh(session)
    await db_session.refresh(sandbox)
    assert session.runtime_config_generation == 22
    assert session.runtime_config_generation_reason == "credential_updated"
    assert sandbox.runtime_config_status == "restart_required"


@pytest.mark.asyncio
async def test_duplicate_direct_impacts_advance_each_session_generation_once(
    db_session,
    project_id,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "old"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"env-{uuid.uuid4()}",
            config=EnvironmentConfig(environment_credential_ids=[credential_id]),
        ),
        project_id=project_id,
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=environment.id,
        runtime_config_generation=30,
    )
    db_session.add(session)
    await db_session.commit()
    impact = CredentialImpact(
        usage=CredentialUsage.ENVIRONMENT_INJECTION,
        source="credential",
        source_id=str(credential_id),
        reason="duplicate_direct",
        project_id=project_id,
        affected_sandbox_ids=frozenset(),
        affected_session_ids=frozenset(),
        dispositions=frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
    )
    adapter = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    ).uow.impacts

    adapter.begin_mutation()
    await adapter.mark_pending(impact)
    await adapter.mark_pending(impact)
    await db_session.commit()

    await db_session.refresh(session)
    assert session.runtime_config_generation == 31


@pytest.mark.asyncio
async def test_environment_create_with_credentials_has_no_runtime_impact(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "value"})
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add(sandbox)
    await db_session.commit()
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    impacts = []

    async def capture_impact(impact):
        impacts.append(impact)
        return impact

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        lambda *args, **kwargs: application,
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)

    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"env-{uuid.uuid4()}",
            config=EnvironmentConfig(
                environment_credential_ids=[credential_id],
                egress_services=[
                    {
                        "name": "api",
                        "base_url": "https://api.example.com",
                        "credential_ref": credential_id,
                        "inject": {"type": "bearer", "credential_field": "TOKEN"},
                    }
                ],
            ),
        ),
        project_id=project_id,
        commit=False,
    )
    await EnvironmentCredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).commit_update(
        environment,
        project_id=project_id,
        old_config=None,
        new_config=environment.config,
    )

    await db_session.refresh(sandbox)
    assert impacts == []
    assert sandbox.networking_status == "ready"

    assert await EnvironmentService(db_session).archive_environment(
        environment.id,
        project_id=project_id,
    )
    await db_session.refresh(sandbox)
    assert impacts == []
    assert sandbox.networking_status == "ready"

    assert await EnvironmentService(db_session).delete_environment(
        environment.id,
        project_id=project_id,
    )
    await db_session.refresh(sandbox)
    assert impacts == []
    assert sandbox.networking_status == "ready"


@pytest.mark.asyncio
async def test_direct_credential_rotation_excludes_http_terminated_destroyed_and_other_project_sandboxes(
    db_session,
    project_id,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "old"})
    await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"env-{uuid.uuid4()}",
            config=EnvironmentConfig(environment_credential_ids=[credential_id]),
        ),
        project_id=project_id,
    )
    other_project_id = await _make_project(db_session)
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    other_agent = JoySafeterAgent(
        id=AgentId.new(),
        project_id=other_project_id,
        name=f"agent-{uuid.uuid4()}",
    )
    db_session.add_all([agent, other_agent])
    await db_session.flush()
    direct_snapshot = {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "environment": {"config": {"environment_credential_ids": [str(credential_id)]}},
    }
    http_snapshot = {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "environment": {
            "config": {
                "egress_services": [
                    {
                        "name": "api",
                        "base_url": "https://api.example.com",
                        "credential_ref": str(credential_id),
                        "inject": {"type": "bearer", "credential_field": "TOKEN"},
                    }
                ]
            }
        },
    }
    http_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        agent_snapshot=http_snapshot,
    )
    terminated_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="terminated",
        agent_snapshot=direct_snapshot,
    )
    destroyed_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="idle",
        agent_snapshot=direct_snapshot,
    )
    other_project_session = JoySafeterSession(
        id=SessionId.new(),
        project_id=other_project_id,
        agent_id=other_agent.id,
        status="running",
        agent_snapshot=direct_snapshot,
    )
    db_session.add_all([http_session, terminated_session, destroyed_session, other_project_session])
    await db_session.flush()
    sandboxes = [
        JoySafeterSandbox(
            id=SandboxId.new(),
            project_id=project_id,
            chat_session_id=http_session.id,
            image="test-image:latest",
            status="running",
            networking_status="ready",
        ),
        JoySafeterSandbox(
            id=SandboxId.new(),
            project_id=project_id,
            chat_session_id=terminated_session.id,
            image="test-image:latest",
            status="running",
            networking_status="ready",
        ),
        JoySafeterSandbox(
            id=SandboxId.new(),
            project_id=project_id,
            chat_session_id=destroyed_session.id,
            image="test-image:latest",
            status="running",
            destroyed_at=datetime.now(timezone.utc),
            networking_status="ready",
        ),
        JoySafeterSandbox(
            id=SandboxId.new(),
            project_id=other_project_id,
            chat_session_id=other_project_session.id,
            image="test-image:latest",
            status="running",
            networking_status="ready",
        ),
    ]
    db_session.add_all(sandboxes)
    await db_session.commit()

    await compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
    ).resource_service.update(
        credential_id,
        UpdateCredentialRequest(data={"TOKEN": "new"}),
        project_id=project_id,
    )

    for sandbox in sandboxes:
        await db_session.refresh(sandbox)
        assert sandbox.runtime_config_status == "ready"
        assert sandbox.networking_status == "ready"


@pytest.mark.asyncio
async def test_environment_update_unchanged_binding_config_has_no_pending_impact(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    config = EnvironmentConfig(environment_credential_ids=[credential_id])
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        project_id=project_id,
    )
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    marked = 0
    nudged = 0

    async def recorded_mark(impact):
        nonlocal marked
        marked += 1
        return impact

    async def recorded_nudge():
        nonlocal nudged
        nudged += 1

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        lambda *args, **kwargs: application,
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)

    response = await update_environment(
        UpdateEnvironmentRequest(config=config),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")
    assert marked == 0
    assert nudged == 0


def test_environment_binding_impact_usages_are_semantic_and_surface_specific() -> None:
    credential_id = CredentialId.new()
    direct = EnvironmentConfig(environment_credential_ids=[credential_id]).model_dump(mode="json")
    egress = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ]
    ).model_dump(mode="json")
    both = EnvironmentConfig.model_validate({**egress, "environment_credential_ids": [str(credential_id)]}).model_dump(
        mode="json"
    )

    assert _changed_credential_binding_usages(direct, direct) == ()
    assert _changed_credential_binding_usages(None, direct) == (CredentialUsage.ENVIRONMENT_INJECTION,)
    assert _changed_credential_binding_usages(None, egress) == (CredentialUsage.HTTP_EGRESS,)
    assert set(_changed_credential_binding_usages(None, both)) == {
        CredentialUsage.ENVIRONMENT_INJECTION,
        CredentialUsage.HTTP_EGRESS,
    }


def test_environment_config_accepts_typed_credential_ids_at_schema_boundary() -> None:
    credential_id = CredentialId.new()

    config = EnvironmentConfig(
        environment_credential_ids=[credential_id],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": credential_id,
            }
        ],
    )

    assert config.environment_credential_ids == [credential_id]
    assert config.egress_services[0].credential_ref == credential_id


def test_environment_config_rejects_legacy_aliases() -> None:
    credential_id = CredentialId.new()
    canonical = EnvironmentConfig.model_validate(
        {
            "environment_credential_ids": [str(credential_id)],
            "egress_services": [
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com",
                    "credential_ref": str(credential_id),
                    "inject": {"credential_field": "TOKEN"},
                }
            ],
        }
    )
    document = canonical.model_dump(mode="json")
    assert document["environment_credential_ids"] == [str(credential_id)]
    assert document["egress_services"][0]["inject"]["credential_field"] == "TOKEN"
    assert "secret_refs" not in document
    assert "secret_key" not in document["egress_services"][0]["inject"]

    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate({"secret_refs": [str(credential_id)]})
    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate(
            {
                "egress_services": [
                    {
                        "name": "crm",
                        "base_url": "https://crm.example.com",
                        "service_credential_id": str(credential_id),
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate(
            {
                "egress_services": [
                    {
                        "name": "crm",
                        "base_url": "https://crm.example.com",
                        "credential_ref": str(credential_id),
                        "inject": {"secret_key": "TOKEN"},
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_environment_persistence_uses_canonical_fields(db_session, project_id) -> None:
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(
            name=f"env-{uuid.uuid4()}",
            config=EnvironmentConfig.model_validate(
                {
                    "environment_credential_ids": [str(credential_id)],
                    "egress_services": [
                        {
                            "name": "crm",
                            "base_url": "https://crm.example.com",
                            "credential_ref": str(credential_id),
                            "inject": {"credential_field": "TOKEN"},
                        }
                    ],
                }
            ),
        ),
        project_id=project_id,
    )

    assert environment.config["environment_credential_ids"] == [str(credential_id)]
    assert environment.config["egress_services"][0]["credential_ref"] == str(credential_id)
    assert environment.config["egress_services"][0]["inject"]["credential_field"] == "TOKEN"
    assert "secret_refs" not in environment.config
    assert "service_credential_id" not in environment.config["egress_services"][0]
    assert "secret_key" not in environment.config["egress_services"][0]["inject"]


def test_environment_binding_impact_ignores_display_name_and_equivalent_url_spelling() -> None:
    credential_id = CredentialId.new()
    original = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ]
    ).model_dump(mode="json")
    renamed = EnvironmentConfig.model_validate(
        {
            **original,
            "egress_services": [{**original["egress_services"][0], "name": "customer-api"}],
        }
    ).model_dump(mode="json")
    equivalent_url = EnvironmentConfig.model_validate(
        {
            **original,
            "egress_services": [
                {
                    **original["egress_services"][0],
                    "base_url": "https://CRM.EXAMPLE.COM:443/api",
                }
            ],
        }
    ).model_dump(mode="json")

    assert _changed_credential_binding_usages(original, renamed) == ()
    assert _changed_credential_binding_usages(original, equivalent_url) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("new_name", "new_url"),
    (
        ("customer-api", "https://crm.example.com/api"),
        ("crm", "https://CRM.EXAMPLE.COM:443/api"),
    ),
    ids=("rename-only", "normalized-url-equivalent"),
)
async def test_environment_semantic_only_egress_changes_do_not_mark_or_nudge(
    db_session,
    project_id,
    monkeypatch,
    new_name,
    new_url,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    original = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api",
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ]
    )
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=original),
        project_id=project_id,
    )
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    marked = 0
    nudged = 0

    async def recorded_mark(impact):
        nonlocal marked
        marked += 1
        return impact

    async def recorded_nudge():
        nonlocal nudged
        nudged += 1

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        lambda *args, **kwargs: application,
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)

    updated = EnvironmentConfig(
        egress_services=[
            {
                "name": new_name,
                "base_url": new_url,
                "credential_ref": credential_id,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ]
    )
    response = await update_environment(
        UpdateEnvironmentRequest(config=updated),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == updated.model_dump(mode="json")
    assert marked == 0
    assert nudged == 0


@pytest.mark.asyncio
async def test_environment_update_nudge_failure_is_logged_and_nonfatal(
    db_session,
    project_id,
    monkeypatch,
    caplog,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )

    async def failing_nudge():
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(
        environment_credential_service_module,
        "compose_credential_application",
        lambda *args, **kwargs: application,
    )
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", failing_nudge)

    response = await update_environment(
        UpdateEnvironmentRequest(config=EnvironmentConfig(environment_credential_ids=[credential_id])),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.id == environment.id
    assert "environment credential impact nudge failed after commit" in caplog.text


def test_environment_binding_has_no_direct_credential_or_second_refresh_transaction() -> None:
    path = Path(__file__).resolve().parents[1] / "app/joysafeter_application/environments/credential_service.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert {"EnvironmentInjectionBinding", "HttpEgressBinding"} <= imported
    assert "CredentialService" not in imported
    assert not {"kind", "get_credential_data", "reveal_values"} & attributes

    service_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EnvironmentCredentialService"
    )
    validate_references = next(
        node
        for node in service_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "validate_references"
    )
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(validate_references):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls = [
        node
        for node in ast.walk(validate_references)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"EnvironmentInjectionBinding", "HttpEgressBinding", "EgressInjectPolicy"}
    ]
    assert calls
    for call in calls:
        parent = parents.get(call)
        while parent is not None and not isinstance(parent, ast.Try):
            parent = parents.get(parent)
        assert isinstance(parent, ast.Try), ast.unparse(call)
