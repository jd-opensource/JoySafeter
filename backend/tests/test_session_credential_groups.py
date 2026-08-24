"""Service-level tests for Task 9d: the Session consumer slice + the unified
cross-consumer dependency scan.

Two things are exercised here, both against real Postgres via conftest's
``db_session`` (the full app is intentionally un-loadable mid-cutover, so there
is no TestClient):

1. Session binds mcp credential GROUPS through the
   ``joysafeter_session_credential_groups`` association table (the legacy
   ``vault_ids`` JSONB column is gone). Binding validates group existence /
   project / archived state and rejects a cross-group normalized-url collision.

2. ``CredentialService.dependencies`` + ``CREDENTIAL_IN_USE`` rejection on
   archive/soft-delete, scanning agents, triggers, environment config, the
   session→group association, and — the audit Blocker-1 case — ACTIVE session
   ``agent_snapshot`` blobs (so a credential a live session pinned in its
   snapshot cannot be deleted even after the agent has been rebound away).
"""

import ast
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_application.credentials.application_service import (
    CredentialGroupService,
    CredentialService,
)
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_application.sessions.creation_service import SessionCreationService
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterSessionCredentialGroup
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterEngineKind,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
)
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import CredentialGroupId, CredentialId


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


async def _make_model_credential(db_session, project_id: str) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider="anthropic",
            protocol="anthropic_messages",
            data={"API_KEY": "sk-secret"},
        ),
        project_id=project_id,
    )
    return cred.id


async def _make_service_credential(db_session, project_id: str) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(kind="service", name=f"s-{uuid.uuid4()}", data={"TOKEN": "t"}),
        project_id=project_id,
    )
    return cred.id


async def _make_group(db_session, project_id: str) -> CredentialGroupId:
    group = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialGroupRequest(name=f"g-{uuid.uuid4()}"),
        project_id=project_id,
    )
    return group.id


async def _add_mcp_member(db_session, group_id, project_id: str, url: str) -> CredentialId:
    cred = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).add_credential(
        group_id,
        AddGroupCredentialRequest(
            name=f"mcp-{uuid.uuid4()}",
            mcp_server_url=url,
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )
    return cred.id


async def _make_agent(db_session, project_id: str, model_credential_id=None):
    return await compose_agent_application(db_session).commands.create_agent(
        JoySafeterCreateAgentRequest(
            name=f"agent-{uuid.uuid4()}",
            engine_kind=JoySafeterEngineKind.CLAUDE,
            model_credential_id=model_credential_id,
        ),
        project_id=project_id,
    )


async def _make_session(db_session, agent, project_id: str, group_ids=None):
    return await SessionCreationService(db_session, audit_actor=CredentialAuditActor.system("test")).create_from_source(
        CreateCredentialAwareSession(
            project_id=project_id,
            agent_id=agent.id,
            credential_group_ids=tuple(group_ids or ()),
            caller="test",
        )
    )


# --- Session → credential-group binding (Task 9d part 1) ----------------------


def test_vault_ids_removed_from_model_and_schema():
    assert not hasattr(JoySafeterSession, "vault_ids")
    assert "vault_ids" not in CreateSessionRequest.model_fields
    assert "credential_group_ids" in CreateSessionRequest.model_fields


def test_session_group_binding_uses_live_mcp_policy_service() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app/joysafeter_application/credentials/snapshot_service.py"
    ).read_text()
    assert "McpGroupBinding" in source
    assert "validate_mcp_group_binding" in source
    assert "from app.joysafeter_domain.services.joysafeter_credential_group_service import" not in source

    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"NormalizedMcpUrl", "McpGroupBinding"}
    ]
    assert calls
    for call in calls:
        parent = parents.get(call)
        while parent is not None and not isinstance(parent, ast.Try):
            parent = parents.get(parent)
        assert isinstance(parent, ast.Try), ast.unparse(call)


@pytest.mark.asyncio
async def test_create_session_binds_credential_groups(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    session = await _make_session(db_session, agent, project_id, group_ids=[group_id])

    svc = SessionService(db_session)
    assert await svc.get_credential_group_ids(session.id) == [group_id]

    rows = (
        (
            await db_session.execute(
                select(JoySafeterSessionCredentialGroup.credential_group_id).where(
                    JoySafeterSessionCredentialGroup.session_id == session.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert list(rows) == [group_id]


@pytest.mark.asyncio
async def test_create_session_dedupes_group_ids(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    session = await _make_session(db_session, agent, project_id, group_ids=[group_id, group_id])
    assert await SessionService(db_session).get_credential_group_ids(session.id) == [group_id]


@pytest.mark.asyncio
async def test_create_session_unknown_group_rejected(db_session, project_id):
    agent = await _make_agent(db_session, project_id)
    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[CredentialGroupId.new()])
    assert exc.value.code == "SESSION_CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_session_group_from_other_project_rejected(db_session, project_id):
    other_project = await _make_project(db_session)
    other_group = await _make_group(db_session, other_project)
    agent = await _make_agent(db_session, project_id)
    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[other_group])
    assert exc.value.code == "SESSION_CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_session_archived_group_rejected(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive(
        group_id, project_id=project_id
    )
    agent = await _make_agent(db_session, project_id)
    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[group_id])
    assert exc.value.code == "SESSION_CREDENTIAL_GROUP_ARCHIVED"


@pytest.mark.asyncio
async def test_create_session_deleted_group_rejected(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    group = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).get(
        group_id, project_id=project_id
    )
    group.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    agent = await _make_agent(db_session, project_id)

    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[group_id])

    assert exc.value.code == "SESSION_CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_session_cross_group_url_conflict_rejected(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await _add_mcp_member(db_session, g2, project_id, "https://mcp.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[g1, g2])
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_create_session_rejects_declared_and_live_group_url_conflict(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    await _add_mcp_member(db_session, group_id, project_id, "https://mcp.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    agent.mcp_servers = [
        {
            "type": "streamable_http",
            "url": "HTTPS://MCP.example.com:443/sse/",
            "auth_requirement": "optional",
        }
    ]
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[group_id])

    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_create_session_maps_malformed_declared_mcp_url_to_conflict(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    agent.mcp_servers = [{"type": "streamable_http", "url": "not-a-url", "auth_requirement": "optional"}]
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[group_id])

    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_create_session_maps_non_string_declared_mcp_url_to_conflict(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    agent.mcp_servers = [{"type": "streamable_http", "url": 123, "auth_requirement": "optional"}]
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _make_session(db_session, agent, project_id, group_ids=[group_id])

    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_create_session_ignores_archived_member_url_conflict(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    archived_credential_id = await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive_credential(
        g1,
        archived_credential_id,
        project_id=project_id,
    )
    await _add_mcp_member(db_session, g2, project_id, "https://mcp.example.com/sse")
    agent = await _make_agent(db_session, project_id)

    session = await _make_session(db_session, agent, project_id, group_ids=[g1, g2])

    assert session.id is not None


@pytest.mark.asyncio
async def test_add_member_rejects_url_conflict_for_already_bound_session(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await _add_mcp_member(db_session, g2, project_id, "https://other.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[g1, g2])

    with pytest.raises(AppError) as exc:
        await _add_mcp_member(db_session, g2, project_id, "HTTPS://MCP.example.com:443/sse/")
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_add_member_ignores_archived_peer_url_for_bound_session(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    archived_credential_id = await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await _add_mcp_member(db_session, g2, project_id, "https://other.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[g1, g2])
    await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive_credential(
        g1,
        archived_credential_id,
        project_id=project_id,
    )

    credential_id = await _add_mcp_member(db_session, g2, project_id, "HTTPS://MCP.example.com:443/sse/")

    assert credential_id is not None


@pytest.mark.asyncio
async def test_restore_mcp_member_rejects_url_conflict_for_bound_session(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    archived_credential_id = await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive_credential(
        g1,
        archived_credential_id,
        project_id=project_id,
    )
    await _add_mcp_member(db_session, g2, project_id, "https://mcp.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[g1, g2])

    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).restore(
            archived_credential_id,
            project_id=project_id,
        )

    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_generic_mcp_create_rejects_url_conflict_for_already_bound_session(db_session, project_id):
    g1 = await _make_group(db_session, project_id)
    g2 = await _make_group(db_session, project_id)
    await _add_mcp_member(db_session, g1, project_id, "https://mcp.example.com/sse")
    await _add_mcp_member(db_session, g2, project_id, "https://other.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[g1, g2])

    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
            CreateCredentialRequest(
                kind="mcp",
                name=f"mcp-{uuid.uuid4()}",
                mcp_server_url="HTTPS://MCP.example.com:443/sse/",
                group_id=g2,
                data={"token_value": "t"},
            ),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


# --- Cross-consumer dependency scan + in-use rejection (Task 9d part 2) --------


@pytest.mark.asyncio
async def test_unused_credential_can_be_soft_deleted(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    assert (await svc.dependencies(cred_id, project_id)).in_use is False
    deleted = await svc.soft_delete(cred_id, project_id=project_id)
    assert deleted.deleted_at is not None


@pytest.mark.asyncio
async def test_soft_delete_credential_referenced_by_agent_rejected(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id)
    await _make_agent(db_session, project_id, model_credential_id=cred_id)
    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).soft_delete(
            cred_id, project_id=project_id
        )
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_archive_credential_referenced_by_agent_rejected(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id)
    await _make_agent(db_session, project_id, model_credential_id=cred_id)
    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).archive(
            cred_id, project_id=project_id
        )
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_soft_delete_credential_referenced_by_environment_config_rejected(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    env = JoySafeterEnvironment(
        project_id=project_id,
        name=f"env-{uuid.uuid4()}",
        config={"secret_refs": [str(cred_id)]},
    )
    db_session.add(env)
    await db_session.commit()
    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).soft_delete(
            cred_id, project_id=project_id
        )
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_soft_delete_credential_pinned_only_by_active_session_snapshot_rejected(db_session, project_id):
    """Audit Blocker 1: a live session's ``agent_snapshot`` pins the credential id.

    Even after the agent is rebound away (its live column no longer points at the
    credential), the snapshot of the running session still references it, so the
    credential must NOT be deletable.
    """
    cred_id = await _make_model_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id, model_credential_id=cred_id)
    await _make_session(db_session, agent, project_id)

    # Rebind the live agent away from the credential; only the session snapshot
    # keeps the reference now.
    agent.model_credential_id = None
    await db_session.commit()

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    assert (await svc.dependencies(cred_id, project_id)).in_use is True
    with pytest.raises(AppError) as exc:
        await svc.soft_delete(cred_id, project_id=project_id)
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_service_credential_pinned_only_by_frozen_session_environment_rejected(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    session = await _make_session(db_session, agent, project_id)
    session.agent_snapshot = {
        **(session.agent_snapshot or {}),
        "environment": {
            "config": {
                "egress_services": [
                    {
                        "name": "secocean",
                        "base_url": "https://secocean.example.com/api",
                        "service_credential_id": str(cred_id),
                    }
                ]
            }
        },
    }
    await db_session.commit()

    dependencies = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).dependencies(
        cred_id, project_id
    )

    assert dependencies.environment_ids == []
    assert dependencies.session_ids == [session.id]
    with pytest.raises(AppError) as exc:
        await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).soft_delete(
            cred_id, project_id=project_id
        )
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_terminated_session_snapshot_does_not_pin_credential(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id, model_credential_id=cred_id)
    session = await _make_session(db_session, agent, project_id)
    agent.model_credential_id = None
    session.status = "terminated"
    await db_session.commit()

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    assert (await svc.dependencies(cred_id, project_id)).in_use is False
    deleted = await svc.soft_delete(cred_id, project_id=project_id)
    assert deleted.deleted_at is not None


@pytest.mark.asyncio
async def test_live_mcp_group_member_can_be_removed_after_session_binding(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    mcp_cred_id = await _add_mcp_member(db_session, group_id, project_id, "https://mcp.example.com/sse")
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[group_id])

    deleted = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).soft_delete(
        mcp_cred_id, project_id=project_id
    )
    assert deleted.deleted_at is not None


@pytest.mark.asyncio
async def test_group_archive_rejected_when_bound_to_active_session(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    await _make_session(db_session, agent, project_id, group_ids=[group_id])
    with pytest.raises(AppError) as exc:
        await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive(
            group_id, project_id=project_id
        )
    assert exc.value.code == "CREDENTIAL_IN_USE"


@pytest.mark.asyncio
async def test_group_archive_allowed_after_session_terminated(db_session, project_id):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    session = await _make_session(db_session, agent, project_id, group_ids=[group_id])
    session.status = "terminated"
    await db_session.commit()
    archived = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).archive(
        group_id, project_id=project_id
    )
    assert archived.archived_at is not None


@pytest.mark.asyncio
async def test_group_archive_serializes_against_concurrent_session_binding(
    db_session,
    postgres_url,
    project_id,
):
    group_id = await _make_group(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    archive_locked = asyncio.Event()
    release_archive = asyncio.Event()

    try:
        async with session_factory() as archive_db, session_factory() as binding_db:
            group_service = CredentialGroupService(archive_db, audit_actor=CredentialAuditActor.system("test"))
            original_lock = group_service._application.uow.groups.lock_credential_group

            async def pause_after_group_lock(candidate_group_id, *, project_id=None):
                await original_lock(candidate_group_id, project_id=project_id)
                archive_locked.set()
                await release_archive.wait()

            group_service._application.uow.groups.lock_credential_group = pause_after_group_lock

            session_creation_service = SessionCreationService(
                binding_db, audit_actor=CredentialAuditActor.system("test")
            )

            archive_task = asyncio.create_task(group_service.archive(group_id, project_id=project_id))
            await asyncio.wait_for(archive_locked.wait(), timeout=2)
            binding_task = asyncio.create_task(
                session_creation_service.create_from_source(
                    CreateCredentialAwareSession(
                        project_id=project_id,
                        agent_id=agent.id,
                        credential_group_ids=(group_id,),
                    )
                )
            )

            try:
                await asyncio.wait_for(asyncio.shield(binding_task), timeout=0.25)
                binding_completed_while_archive_was_locked = True
            except TimeoutError:
                binding_completed_while_archive_was_locked = False

            release_archive.set()
            archive_result, binding_result = await asyncio.gather(
                archive_task,
                binding_task,
                return_exceptions=True,
            )

            assert not isinstance(archive_result, Exception)
            assert binding_completed_while_archive_was_locked is False
            assert isinstance(binding_result, AppError)
            assert binding_result.code == "SESSION_CREDENTIAL_GROUP_ARCHIVED"
    finally:
        await engine.dispose()
