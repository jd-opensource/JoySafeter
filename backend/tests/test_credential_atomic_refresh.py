"""Atomicity tests for credential mutation + sandbox network-policy mark-pending.

Audit Blocker 5: a credential mutation and the sandbox ``pending`` mark must
commit together. If the mutation committed first and the refresh committed
separately, a crash between the two commits would leave the DB holding the new
credential while the sandbox is never flagged for re-push — Envoy keeps the OLD
credential (dangerous for revocation/rotation).

Real-DB tests (Postgres via conftest's ``db_session``): the primitive runs an
``UPDATE ... RETURNING`` over ``joysafeter_sandboxes`` filtered by the JSONB
fingerprint, so sqlite is not a substitute.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_api.api.v1.network_policy_refresh import (
    mark_live_sandboxes_pending,
    refresh_live_limited_sandbox_network_policies,
)
from app.joysafeter_application.credentials.application_service import CredentialGroupService, CredentialService
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.credentials import CredentialUsage, DependencyDisposition
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
    JoySafeterSessionCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
    UpdateCredentialGroupRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import (
    SqlAlchemyCredentialRepository,
)
from app.joysafeter_shared.ids import AgentId, EnvironmentId, OrganizationId, ProjectId, SandboxId, SessionId


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


def _limited_sandbox(project_id: ProjectId, status: str = "running") -> JoySafeterSandbox:
    """A live limited-networking sandbox (the refresh target shape)."""
    return JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status=status,
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )


@pytest_asyncio.fixture
async def project_id(db_session) -> ProjectId:
    return await _make_project(db_session)


@pytest_asyncio.fixture
async def other_project_id(db_session) -> ProjectId:
    return await _make_project(db_session)


@asynccontextmanager
async def _fresh_session(postgres_url: str):
    """A brand-new session/connection to prove data is durably COMMITTED (not just
    cached in the writing session). This is the true atomicity check: if the
    mutation and the pending mark did not commit together, a fresh read would not
    see both."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _sandbox_status(db_session, sandbox_id) -> str:
    row = await db_session.execute(
        select(JoySafeterSandbox.networking_status).where(JoySafeterSandbox.id == sandbox_id)
    )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_update_marks_sandbox_pending_atomically(db_session, postgres_url, project_id):
    """A credential update flips the live limited sandbox to ``pending`` and both
    the credential change and the sandbox flag are persisted after the single
    service call (same transaction, one commit)."""
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model", name="m1", provider="openai", protocol="openai", data={"API_KEY": "sk-old"}
        ),
        project_id=project_id,
    )

    # Create does NOT touch existing sandboxes.
    assert await _sandbox_status(db_session, sandbox_id) == "ready"

    updated = await svc.update(
        cred.id,
        UpdateCredentialRequest(data={"API_KEY": "sk-new"}),
        project_id=project_id,
    )

    # New credential material persisted...
    assert svc.get_credential_data(updated)["API_KEY"] == "sk-new"

    # ...and BOTH the credential change and the sandbox pending flag are durably
    # committed together — verified through a fresh session/connection.
    async with _fresh_session(postgres_url) as other:
        assert await _sandbox_status(other, sandbox_id) == "pending"
        reloaded = await CredentialService(other, audit_actor=CredentialAuditActor.system("test")).get(
            cred.id, project_id=project_id
        )
        assert (
            CredentialService(other, audit_actor=CredentialAuditActor.system("test")).get_credential_data(reloaded)[
                "API_KEY"
            ]
            == "sk-new"
        )


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_mutation_and_durable_pending(db_session, project_id, monkeypatch):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="audit-rollback", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    credential_id = credential.id

    async def fail_audit(_entry):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(application.uow.audit, "append", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await application.resource_service.update(
            credential_id,
            UpdateCredentialRequest(data={"TOKEN": "new"}),
            project_id=project_id,
        )

    db_session.expire_all()
    persisted = (
        await db_session.execute(select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id))
    ).scalar_one()
    assert application.resource_service.get_credential_data(persisted)["TOKEN"] == "old"
    assert await _sandbox_status(db_session, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_late_commit_failure_rolls_back_written_mutation_audit_and_pending(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="late-failure", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    credential_id = credential.id
    db_session.add(
        JoySafeterEnvironment(
            id=EnvironmentId.new(),
            project_id=project_id,
            name=f"env-{uuid.uuid4()}",
            config={
                "egress_services": [
                    {
                        "name": "api",
                        "base_url": "https://api.example.com",
                        "credential_ref": str(credential_id),
                        "inject": {"type": "bearer", "credential_field": "TOKEN"},
                    }
                ]
            },
        )
    )
    await db_session.commit()
    observed_before_failure: dict[str, object] = {}

    async def fail_after_all_sql_writes(_uow):
        await db_session.flush()
        persisted = (
            await db_session.execute(select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id))
        ).scalar_one()
        audit_rows = (
            (
                await db_session.execute(
                    select(SecurityAuditLog.id).where(
                        SecurityAuditLog.event_type == "credential.updated",
                        SecurityAuditLog.details["target_id"].astext == str(credential_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        observed_before_failure.update(
            material=application.resource_service.get_credential_data(persisted)["TOKEN"],
            audit_count=len(audit_rows),
            sandbox_status=await _sandbox_status(db_session, sandbox_id),
        )
        raise RuntimeError("commit failed after flush")

    monkeypatch.setattr(type(application.uow), "commit", fail_after_all_sql_writes)
    with pytest.raises(RuntimeError, match="commit failed after flush"):
        await application.resource_service.update(
            credential_id,
            UpdateCredentialRequest(data={"TOKEN": "new"}),
            project_id=project_id,
        )

    assert observed_before_failure == {
        "material": "new",
        "audit_count": 1,
        "sandbox_status": "pending",
    }
    async with _fresh_session(postgres_url) as fresh:
        persisted = (
            await fresh.execute(select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id))
        ).scalar_one()
        audit_rows = (
            (
                await fresh.execute(
                    select(SecurityAuditLog.id).where(
                        SecurityAuditLog.event_type == "credential.updated",
                        SecurityAuditLog.details["target_id"].astext == str(credential_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert application.resource_service.get_credential_data(persisted)["TOKEN"] == "old"
        assert audit_rows == []
        assert await _sandbox_status(fresh, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_direct_rotation_rolls_back_mutation_audit_and_restart_required_on_commit_failure(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="direct-rollback", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    environment = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        project_id=project_id,
        name=f"env-{uuid.uuid4()}",
        config={"environment_credential_ids": [str(credential.id)]},
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add_all([environment, agent])
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=environment.id,
        runtime_config_generation=5,
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {"config": {"environment_credential_ids": [str(credential.id)]}},
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
    credential_id = credential.id
    session_id = session.id
    sandbox_id = sandbox.id
    observed_before_failure: dict[str, object] = {}

    async def fail_after_all_sql_writes(_uow):
        await db_session.flush()
        persisted = await db_session.scalar(
            select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id)
        )
        audit_count = await db_session.scalar(
            select(text("count(*)"))
            .select_from(SecurityAuditLog)
            .where(
                SecurityAuditLog.event_type == "credential.updated",
                SecurityAuditLog.details["target_id"].astext == str(credential_id),
            )
        )
        stale_status = await db_session.scalar(
            select(JoySafeterSandbox.runtime_config_status).where(JoySafeterSandbox.id == sandbox_id)
        )
        runtime_generation = await db_session.scalar(
            select(JoySafeterSession.runtime_config_generation).where(JoySafeterSession.id == session_id)
        )
        runtime_generation_reason = await db_session.scalar(
            select(JoySafeterSession.runtime_config_generation_reason).where(JoySafeterSession.id == session_id)
        )
        runtime_generation_updated_at = await db_session.scalar(
            select(JoySafeterSession.runtime_config_generation_updated_at).where(JoySafeterSession.id == session_id)
        )
        observed_before_failure.update(
            material=application.resource_service.get_credential_data(persisted)["TOKEN"],
            audit_count=audit_count,
            runtime_config_status=stale_status,
            runtime_config_generation=runtime_generation,
            runtime_config_generation_reason=runtime_generation_reason,
            runtime_config_generation_updated_at=runtime_generation_updated_at,
        )
        raise RuntimeError("commit failed after direct stale mark")

    monkeypatch.setattr(type(application.uow), "commit", fail_after_all_sql_writes)
    with pytest.raises(RuntimeError, match="commit failed after direct stale mark"):
        await application.resource_service.update(
            credential_id,
            UpdateCredentialRequest(data={"TOKEN": "new"}),
            project_id=project_id,
        )

    assert observed_before_failure == {
        "material": "new",
        "audit_count": 1,
        "runtime_config_status": "restart_required",
        "runtime_config_generation": 6,
        "runtime_config_generation_reason": "credential_updated",
        "runtime_config_generation_updated_at": observed_before_failure["runtime_config_generation_updated_at"],
    }
    assert observed_before_failure["runtime_config_generation_updated_at"] is not None
    async with _fresh_session(postgres_url) as fresh:
        persisted = await fresh.scalar(select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id))
        assert (
            CredentialService(fresh, audit_actor=CredentialAuditActor.system("test")).get_credential_data(persisted)[
                "TOKEN"
            ]
            == "old"
        )
        assert (
            await fresh.scalar(
                select(JoySafeterSandbox.runtime_config_status).where(JoySafeterSandbox.id == sandbox_id)
            )
            == "ready"
        )
        assert (
            await fresh.scalar(
                select(JoySafeterSession.runtime_config_generation).where(JoySafeterSession.id == session_id)
            )
            == 5
        )
        assert (
            await fresh.scalar(
                select(JoySafeterSession.runtime_config_generation_reason).where(JoySafeterSession.id == session_id)
            )
            is None
        )
        assert (
            await fresh.scalar(
                select(JoySafeterSession.runtime_config_generation_updated_at).where(JoySafeterSession.id == session_id)
            )
            is None
        )
        assert (
            await fresh.scalar(
                select(text("count(*)"))
                .select_from(SecurityAuditLog)
                .where(
                    SecurityAuditLog.event_type == "credential.updated",
                    SecurityAuditLog.details["target_id"].astext == str(credential_id),
                )
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("update_request", "expected_name"),
    [
        (UpdateCredentialRequest(), "no-op"),
        (UpdateCredentialRequest(data={"TOKEN": "old"}), "no-op"),
        (UpdateCredentialRequest(name="renamed"), "renamed"),
    ],
)
async def test_credential_noop_and_rename_only_emit_no_runtime_impact(
    db_session,
    project_id,
    monkeypatch,
    update_request,
    expected_name,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="no-op", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    impacts = []

    async def capture_impact(impact):
        impacts.append(impact)
        return impact

    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)

    updated = await application.resource_service.update(
        credential.id,
        update_request,
        project_id=project_id,
    )

    assert updated.name == expected_name
    assert impacts == []
    audit_count = await db_session.scalar(
        select(text("count(*)"))
        .select_from(SecurityAuditLog)
        .where(
            SecurityAuditLog.event_type == "credential.updated",
            SecurityAuditLog.details["target_id"].astext == str(credential.id),
        )
    )
    assert audit_count == (1 if expected_name == "renamed" else 0)


@pytest.mark.asyncio
async def test_service_credential_restore_recomputes_direct_and_egress_impacts_once(
    db_session,
    project_id,
    monkeypatch,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="restore-service", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    credential.archived_at = datetime.now(timezone.utc)
    environment = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        project_id=project_id,
        name=f"env-{uuid.uuid4()}",
        config={
            "environment_credential_ids": [str(credential.id)],
            "egress_services": [
                {
                    "name": "api",
                    "base_url": "https://api.example.com",
                    "credential_ref": str(credential.id),
                    "inject": {"type": "bearer", "credential_field": "TOKEN"},
                }
            ],
        },
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add_all([environment, agent])
    await db_session.flush()
    session = JoySafeterSession(
        id=SessionId.new(),
        project_id=project_id,
        agent_id=agent.id,
        status="running",
        environment_id=environment.id,
        runtime_config_generation=3,
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
    unrelated = _limited_sandbox(project_id)
    db_session.add_all([attached, unrelated])
    await db_session.commit()
    impacts = []
    original_mark = application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)

    await application.resource_service.restore(credential.id, project_id=project_id)

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
    assert session.runtime_config_generation == 4
    assert session.runtime_config_generation_reason == "credential_restored"
    assert attached.runtime_config_status == "restart_required"
    assert attached.networking_status == "pending"
    assert unrelated.networking_status == "pending"


@pytest.mark.asyncio
async def test_group_and_member_auto_commit_false_respect_outer_rollback(db_session, postgres_url, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    group = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialGroupRequest(name="outer-transaction-group"),
        project_id=project_id,
    )
    group_id = group.id
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )

    await application.group_service.update(
        group_id,
        UpdateCredentialGroupRequest(name="must-roll-back"),
        project_id=project_id,
    )
    await application.group_service.add_credential(
        group_id,
        AddGroupCredentialRequest(
            name="outer-member",
            mcp_server_url="https://outer-transaction.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    await db_session.rollback()

    async with _fresh_session(postgres_url) as fresh:
        persisted_group = (
            await fresh.execute(select(JoySafeterCredentialGroup).where(JoySafeterCredentialGroup.id == group_id))
        ).scalar_one()
        persisted_member = (
            await fresh.execute(
                select(JoySafeterCredential.id).where(
                    JoySafeterCredential.project_id == project_id,
                    JoySafeterCredential.name == "outer-member",
                )
            )
        ).scalar_one_or_none()
        audit_count = (
            (
                await fresh.execute(
                    select(SecurityAuditLog.id).where(
                        SecurityAuditLog.event_type.in_(["credential_group.updated", "credential_group.member_added"]),
                        SecurityAuditLog.details["project_id"].astext == str(project_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert persisted_group.name == "outer-transaction-group"
        assert persisted_member is None
        assert audit_count == []
        assert await _sandbox_status(fresh, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_concurrent_default_changes_serialize_per_project_protocol(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    first = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="concurrent-default-a",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "a"},
        ),
        project_id=project_id,
    )
    second = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="concurrent-default-b",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "b"},
        ),
        project_id=project_id,
    )

    original_lock_default_scope = SqlAlchemyCredentialRepository.lock_default_scope
    contenders_ready = asyncio.Barrier(2)

    async def synchronized_scope_lock(repository, *, project_id, protocol):
        await contenders_ready.wait()
        await original_lock_default_scope(repository, project_id=project_id, protocol=protocol)

    monkeypatch.setattr(
        SqlAlchemyCredentialRepository,
        "lock_default_scope",
        synchronized_scope_lock,
    )

    async def set_default(credential_id):
        async with _fresh_session(postgres_url) as session:
            await asyncio.wait_for(
                CredentialService(session, audit_actor=CredentialAuditActor.system("test")).set_default(
                    credential_id, project_id=project_id
                ),
                timeout=5,
            )

    await asyncio.gather(set_default(first.id), set_default(second.id))
    await db_session.rollback()
    defaults = (
        (
            await db_session.execute(
                select(JoySafeterCredential.id).where(
                    JoySafeterCredential.project_id == project_id,
                    JoySafeterCredential.protocol == "openai",
                    JoySafeterCredential.is_default.is_(True),
                    JoySafeterCredential.archived_at.is_(None),
                    JoySafeterCredential.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(defaults) == 1


@pytest.mark.asyncio
async def test_default_scope_lock_does_not_serialize_other_project_or_protocol(
    db_session,
    postgres_url,
    project_id,
    other_project_id,
):
    same_project_other_protocol = await CredentialService(
        db_session, audit_actor=CredentialAuditActor.system("test")
    ).create(
        CreateCredentialRequest(
            kind="model",
            name="independent-protocol",
            provider="anthropic",
            protocol="anthropic",
            data={"API_KEY": "protocol"},
        ),
        project_id=project_id,
    )
    other_project_same_protocol = await CredentialService(
        db_session, audit_actor=CredentialAuditActor.system("test")
    ).create(
        CreateCredentialRequest(
            kind="model",
            name="independent-project",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "project"},
        ),
        project_id=other_project_id,
    )

    async with _fresh_session(postgres_url) as blocker:
        scope = f"joysafeter:credential-default:{project_id}:openai"
        await blocker.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": scope},
        )

        async def set_default(credential_id, target_project_id):
            async with _fresh_session(postgres_url) as session:
                await CredentialService(session, audit_actor=CredentialAuditActor.system("test")).set_default(
                    credential_id,
                    project_id=target_project_id,
                )

        await asyncio.wait_for(
            asyncio.gather(
                set_default(same_project_other_protocol.id, project_id),
                set_default(other_project_same_protocol.id, other_project_id),
            ),
            timeout=2,
        )
        await blocker.rollback()

    await db_session.rollback()
    for target_project_id, protocol, credential_id in (
        (project_id, "anthropic", same_project_other_protocol.id),
        (other_project_id, "openai", other_project_same_protocol.id),
    ):
        defaults = (
            (
                await db_session.execute(
                    select(JoySafeterCredential.id).where(
                        JoySafeterCredential.project_id == target_project_id,
                        JoySafeterCredential.protocol == protocol,
                        JoySafeterCredential.is_default.is_(True),
                        JoySafeterCredential.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert defaults == [credential_id]


@pytest.mark.asyncio
async def test_generic_mcp_create_marks_sandbox_pending(db_session, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    group = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialGroupRequest(name="mcp-group"), project_id=project_id
    )
    await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp-member",
            mcp_server_url="https://mcp.example.com/sse",
            group_id=group.id,
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )

    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_mark_live_sandboxes_pending_does_not_commit(db_session, project_id):
    """The primitive itself must NOT commit: after calling it and rolling back,
    the sandbox flag must NOT have persisted."""
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    marked = await mark_live_sandboxes_pending(
        db_session,
        project_id=project_id,
        source_type="credential",
        source_id=str(uuid.uuid4()),
    )
    assert sandbox_id in marked

    # Roll back the (uncommitted) mark; the flag must revert.
    await db_session.rollback()
    assert await _sandbox_status(db_session, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_unreferenced_archive_and_delete_emit_no_impact_while_set_default_still_refreshes(
    db_session,
    project_id,
    monkeypatch,
):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    impacts = []
    original_mark = svc._application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    monkeypatch.setattr(svc._application.uow.impacts, "mark_pending", capture_impact)

    for method in ("archive", "soft_delete", "set_default"):
        # Fresh sandbox (ready) + fresh credential per method.
        sandbox = _limited_sandbox(project_id)
        db_session.add(sandbox)
        await db_session.commit()
        sandbox_id = sandbox.id

        cred = await svc.create(
            CreateCredentialRequest(
                kind="model",
                name=f"m-{method}",
                provider="openai",
                protocol="openai",
                data={"API_KEY": "sk"},
            ),
            project_id=project_id,
        )
        assert await _sandbox_status(db_session, sandbox_id) == "ready"

        await getattr(svc, method)(cred.id, project_id=project_id)
        expected = "pending" if method == "set_default" else "ready"
        assert await _sandbox_status(db_session, sandbox_id) == expected, method

        # Reset the sandbox flag for the next iteration.
        sandbox.networking_status = "ready"
        db_session.add(sandbox)
        await db_session.commit()

    assert [impact.reason for impact in impacts] == ["credential_default_set"]


@pytest.mark.asyncio
async def test_concurrent_direct_rotations_lock_sessions_in_id_order_and_serialize(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    first_credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="concurrent-one", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    second_credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="concurrent-two", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    environment = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        project_id=project_id,
        name=f"env-{uuid.uuid4()}",
        config={"environment_credential_ids": [str(first_credential.id), str(second_credential.id)]},
    )
    agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
    db_session.add_all([environment, agent])
    await db_session.flush()
    sessions = [
        JoySafeterSession(
            id=SessionId.new(),
            project_id=project_id,
            agent_id=agent.id,
            status="running",
            environment_id=environment.id,
            runtime_config_generation=40 + index,
        )
        for index in range(2)
    ]
    db_session.add_all(sessions)
    await db_session.commit()
    session_ids = [session.id for session in sessions]

    original_mark = SqlAlchemyCredentialRepository._mark_sandboxes_pending_for
    arrival_lock = asyncio.Lock()
    both_ready = asyncio.Event()
    arrivals = 0

    async def synchronized_mark(repository, credential, *, reason):
        nonlocal arrivals
        async with arrival_lock:
            arrivals += 1
            if arrivals == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=5)
        await original_mark(repository, credential, reason=reason)

    monkeypatch.setattr(
        SqlAlchemyCredentialRepository,
        "_mark_sandboxes_pending_for",
        synchronized_mark,
    )
    lock_statements: list[str] = []

    async def rotate(credential_id, token):
        async with _fresh_session(postgres_url) as session:
            engine = session.bind

            def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
                normalized = " ".join(statement.lower().split())
                if "joysafeter_sessions" in normalized and "for update" in normalized:
                    lock_statements.append(normalized)

            sqlalchemy_event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
            try:
                await compose_credential_application(
                    session,
                    audit_actor=CredentialAuditActor.system("test"),
                ).resource_service.update(
                    credential_id,
                    UpdateCredentialRequest(data={"TOKEN": token}),
                    project_id=project_id,
                )
            finally:
                sqlalchemy_event.remove(engine.sync_engine, "before_cursor_execute", record_statement)

    await asyncio.wait_for(
        asyncio.gather(
            rotate(first_credential.id, "new-one"),
            rotate(second_credential.id, "new-two"),
        ),
        timeout=10,
    )

    async with _fresh_session(postgres_url) as fresh:
        generations = list(
            (
                await fresh.execute(
                    select(JoySafeterSession.runtime_config_generation)
                    .where(JoySafeterSession.id.in_(session_ids))
                    .order_by(JoySafeterSession.id)
                )
            ).scalars()
        )
    assert sorted(generations) == [42, 43]
    assert len(lock_statements) == 2
    assert all("order by joysafeter_sessions.id" in statement for statement in lock_statements)


@pytest.mark.asyncio
async def test_mcp_member_lifecycle_with_active_group_session_marks_network_pending(
    db_session,
    project_id,
    monkeypatch,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await application.group_service.create(
        CreateCredentialGroupRequest(name="mcp-active-lifecycle-group"),
        project_id=project_id,
    )
    credential = await application.group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="mcp-active-lifecycle-member",
            mcp_server_url="https://mcp.example.com/sse",
            data={"token_value": "t"},
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
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        JoySafeterSessionCredentialGroup(
            session_id=session.id,
            credential_group_id=group.id,
        )
    )
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    impacts = []
    original_mark = application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    async def skip_nudge():
        return None

    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", skip_nudge)

    await application.group_service.archive_credential(
        group.id,
        credential.id,
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "pending"

    await db_session.execute(
        update(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id).values(networking_status="ready")
    )
    await db_session.commit()
    await application.resource_service.restore(credential.id, project_id=project_id)
    assert await _sandbox_status(db_session, sandbox_id) == "pending"

    await db_session.execute(
        update(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id).values(networking_status="ready")
    )
    await db_session.commit()
    await application.group_service.remove_credential(
        group.id,
        credential.id,
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "pending"
    assert [impact.source for impact in impacts] == ["credential_group"] * 3
    assert [impact.usage for impact in impacts] == [CredentialUsage.MCP_EGRESS] * 3
    assert [impact.reason for impact in impacts] == [
        "credential_archived",
        "credential_group_member_restored",
        "credential_deleted",
    ]


@pytest.mark.parametrize("inactive_binding", ["none", "archived", "terminated"])
@pytest.mark.asyncio
async def test_mcp_member_lifecycle_without_active_group_session_emits_no_impact(
    db_session,
    project_id,
    monkeypatch,
    inactive_binding,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await application.group_service.create(
        CreateCredentialGroupRequest(name="mcp-inactive-lifecycle-group"),
        project_id=project_id,
    )
    credential = await application.group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="mcp-inactive-lifecycle-member",
            mcp_server_url="https://inactive-mcp.example.com/sse",
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )
    if inactive_binding != "none":
        agent = JoySafeterAgent(id=AgentId.new(), project_id=project_id, name=f"agent-{uuid.uuid4()}")
        db_session.add(agent)
        await db_session.flush()
        session = JoySafeterSession(
            id=SessionId.new(),
            project_id=project_id,
            agent_id=agent.id,
            status="terminated" if inactive_binding == "terminated" else "running",
            archived_at=datetime.now(timezone.utc) if inactive_binding == "archived" else None,
        )
        db_session.add(session)
        await db_session.flush()
        db_session.add(
            JoySafeterSessionCredentialGroup(
                session_id=session.id,
                credential_group_id=group.id,
            )
        )
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    impacts = []
    original_mark = application.uow.impacts.mark_pending

    async def capture_impact(impact):
        resolved = await original_mark(impact)
        impacts.append(resolved)
        return resolved

    async def skip_nudge():
        return None

    monkeypatch.setattr(application.uow.impacts, "mark_pending", capture_impact)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", skip_nudge)

    await application.group_service.archive_credential(
        group.id,
        credential.id,
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "ready"

    await application.resource_service.restore(credential.id, project_id=project_id)
    assert await _sandbox_status(db_session, sandbox_id) == "ready"

    await application.group_service.remove_credential(
        group.id,
        credential.id,
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "ready"
    assert impacts == []


@pytest.mark.parametrize(
    ("operation", "event_type"),
    [
        ("archive", "credential_group.member_archived"),
        ("restore", "credential.restored"),
        ("delete", "credential_group.member_removed"),
    ],
)
@pytest.mark.asyncio
async def test_mcp_member_lifecycle_rolls_back_state_audit_and_pending_on_commit_failure(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
    operation,
    event_type,
):
    application = compose_credential_application(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await application.group_service.create(
        CreateCredentialGroupRequest(name=f"mcp-{operation}-rollback-group"),
        project_id=project_id,
    )
    credential = await application.group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name=f"mcp-{operation}-rollback-member",
            mcp_server_url=f"https://{operation}-rollback.example.com/sse",
            data={"token_value": "t"},
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
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(
        JoySafeterSessionCredentialGroup(
            session_id=session.id,
            credential_group_id=group.id,
        )
    )
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    if operation == "restore":
        credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()
    credential_id = credential.id
    sandbox_id = sandbox.id
    baseline_archived = operation == "restore"
    observed_before_failure: dict[str, object] = {}

    async def fail_after_all_sql_writes(_uow):
        await db_session.flush()
        persisted = await db_session.scalar(
            select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id)
        )
        audit_count = await db_session.scalar(
            select(text("count(*)"))
            .select_from(SecurityAuditLog)
            .where(
                SecurityAuditLog.event_type == event_type,
                SecurityAuditLog.details["target_id"].astext == str(credential_id),
            )
        )
        observed_before_failure.update(
            archived=persisted.archived_at is not None,
            deleted=persisted.deleted_at is not None,
            audit_count=audit_count,
            sandbox_status=await _sandbox_status(db_session, sandbox_id),
        )
        raise RuntimeError(f"{operation} commit failed after flush")

    monkeypatch.setattr(type(application.uow), "commit", fail_after_all_sql_writes)
    with pytest.raises(RuntimeError, match=rf"{operation} commit failed after flush"):
        if operation == "archive":
            await application.group_service.archive_credential(
                group.id,
                credential_id,
                project_id=project_id,
            )
        elif operation == "restore":
            await application.resource_service.restore(credential_id, project_id=project_id)
        else:
            await application.group_service.remove_credential(
                group.id,
                credential_id,
                project_id=project_id,
            )

    assert observed_before_failure == {
        "archived": operation == "archive",
        "deleted": operation == "delete",
        "audit_count": 1,
        "sandbox_status": "pending",
    }
    async with _fresh_session(postgres_url) as fresh:
        persisted = await fresh.scalar(select(JoySafeterCredential).where(JoySafeterCredential.id == credential_id))
        audit_count = await fresh.scalar(
            select(text("count(*)"))
            .select_from(SecurityAuditLog)
            .where(
                SecurityAuditLog.event_type == event_type,
                SecurityAuditLog.details["target_id"].astext == str(credential_id),
            )
        )
        assert (persisted.archived_at is not None) is baseline_archived
        assert persisted.deleted_at is None
        assert audit_count == 0
        assert await _sandbox_status(fresh, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_refresh_wrapper_marks_and_returns_count(db_session, project_id):
    """The self-committing wrapper still marks live limited sandboxes pending and
    returns the count (behavior unchanged for non-atomic callers)."""
    a = _limited_sandbox(project_id)
    b = _limited_sandbox(project_id)
    # A non-limited sandbox must be ignored.
    c = JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "full"}}},
    )
    db_session.add_all([a, b, c])
    await db_session.commit()
    a_id, b_id, c_id = a.id, b.id, c.id

    count = await refresh_live_limited_sandbox_network_policies(
        db_session,
        project_id=project_id,
        reason="credential_rotated",
        source_type="credential",
        source_id=str(uuid.uuid4()),
    )
    assert count == 2

    assert await _sandbox_status(db_session, a_id) == "pending"
    assert await _sandbox_status(db_session, b_id) == "pending"
    # Non-limited sandbox untouched.
    assert await _sandbox_status(db_session, c_id) == "ready"
