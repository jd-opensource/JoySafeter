"""Tests for CredentialGroupService.

Real-DB tests (Postgres via conftest's ``db_session``): the group service leans
on the DB's partial unique indexes — ``(project_id, name)`` on groups and
``(group_id, normalized_mcp_server_url) WHERE kind='mcp'`` on credentials — plus
the composite FK enforcing project isolation. sqlite is not a substitute.
"""

import uuid
from dataclasses import replace

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_application.credentials.application_service import (
    CredentialGroupService,
    CredentialService,
)
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_application.sessions.creation_service import SessionCreationService
from app.joysafeter_domain.credentials.dependencies import DependencyDisposition
from app.joysafeter_domain.credentials.resource import McpCredentialIdentity
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterEngineKind,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    UpdateCredentialGroupRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import OrganizationId, ProjectId, SandboxId
from app.joysafeter_shared.utils.datetime import utc_now
from tests.network_policy_test_helpers import (
    acknowledged_network_policy_fields,
    mark_network_policy_ready,
)


async def _make_project(db_session) -> str:
    org = Organization(id=OrganizationId.new(), name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(id=ProjectId.new(), org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


@pytest_asyncio.fixture
async def other_project_id(db_session) -> str:
    return await _make_project(db_session)


def _limited_sandbox(project_id: str) -> JoySafeterSandbox:
    return JoySafeterSandbox(
        id=SandboxId.new(),
        project_id=project_id,
        image="test-image:latest",
        status="running",
        **acknowledged_network_policy_fields(),
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )


async def _sandbox_status(db_session, sandbox_id) -> str:
    row = await db_session.execute(
        select(JoySafeterSandbox.networking_status).where(JoySafeterSandbox.id == sandbox_id)
    )
    return row.scalar_one()


# --- group CRUD ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_get_list_group(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(
        CreateCredentialGroupRequest(
            name="g1",
            description="first",
            metadata={"owner": "platform"},
        ),
        project_id=project_id,
    )
    assert group.name == "g1"
    assert group.description == "first"
    assert group.metadata_ == {"owner": "platform"}

    fetched = await svc.get(group.id, project_id=project_id)
    assert fetched is not None
    assert fetched.id == group.id

    groups, has_more = await svc.list(project_id=project_id)
    assert group.id in {g.id for g in groups}
    assert has_more is False


@pytest.mark.asyncio
async def test_group_member_audit_records_group_and_credential_ids(db_session, project_id):
    service = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await service.create(CreateCredentialGroupRequest(name="audit-membership"), project_id=project_id)
    credential = await service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="audited-member",
            mcp_server_url="https://audit-member.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )

    audit = await db_session.scalar(
        select(SecurityAuditLog).where(
            SecurityAuditLog.event_type == "credential_group.member_added",
            SecurityAuditLog.details["target_id"].astext == str(credential.id),
        )
    )
    assert audit is not None
    assert audit.details["credential_group_id"] == str(group.id)


@pytest.mark.asyncio
async def test_get_missing_group_raises(db_session, project_id):
    from app.joysafeter_shared.ids import CredentialGroupId

    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    with pytest.raises(AppError) as exc:
        await svc.get_or_raise(CredentialGroupId.new(), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_group_name_unique_per_project(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    await svc.create(CreateCredentialGroupRequest(name="dup"), project_id=project_id)
    with pytest.raises(AppError) as exc:
        await svc.create(CreateCredentialGroupRequest(name="dup"), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_NAME_EXISTS"


@pytest.mark.asyncio
async def test_group_name_reusable_across_projects(db_session, project_id, other_project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    await svc.create(CreateCredentialGroupRequest(name="shared"), project_id=project_id)
    # Same name in a different project is fine.
    other = await svc.create(CreateCredentialGroupRequest(name="shared"), project_id=other_project_id)
    assert other.name == "shared"


@pytest.mark.asyncio
async def test_update_group(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    updated = await svc.update(
        group.id,
        UpdateCredentialGroupRequest(
            name="g1-renamed",
            description="new",
            metadata={"purpose": "mcp"},
        ),
        project_id=project_id,
    )
    assert updated.name == "g1-renamed"
    assert updated.description == "new"
    assert updated.metadata_ == {"purpose": "mcp"}


@pytest.mark.asyncio
async def test_archive_soft_delete_group_mark_pending(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    for method in ("archive", "soft_delete"):
        sandbox = _limited_sandbox(project_id)
        db_session.add(sandbox)
        await db_session.commit()
        sandbox_id = sandbox.id

        group = await svc.create(CreateCredentialGroupRequest(name=f"g-{method}"), project_id=project_id)
        assert await _sandbox_status(db_session, sandbox_id) == "ready"

        await getattr(svc, method)(group.id, project_id=project_id)
        assert await _sandbox_status(db_session, sandbox_id) == "pending", method

        mark_network_policy_ready(sandbox)
        db_session.add(sandbox)
        await db_session.commit()

    # Soft-deleted group is not returned by get.
    deleted = await svc.create(CreateCredentialGroupRequest(name="gone"), project_id=project_id)
    await svc.soft_delete(deleted.id, project_id=project_id)
    assert await svc.get(deleted.id, project_id=project_id) is None


@pytest.mark.asyncio
async def test_soft_delete_group_soft_deletes_members_and_releases_member_name(
    db_session,
    project_id,
):
    group_service = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential_service = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await group_service.create(
        CreateCredentialGroupRequest(name="delete-with-members"),
        project_id=project_id,
    )
    member = await group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="reusable-member",
            mcp_server_url="https://deleted-group.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )

    await group_service.soft_delete(group.id, project_id=project_id)

    await db_session.refresh(member)
    assert member.deleted_at is not None
    assert member.data == {}
    assert member.material_erased_at is not None
    assert await credential_service.get(member.id, project_id=project_id) is None

    replacement_group = await group_service.create(
        CreateCredentialGroupRequest(name="replacement-group"),
        project_id=project_id,
    )
    replacement = await group_service.add_credential(
        replacement_group.id,
        AddGroupCredentialRequest(
            name="reusable-member",
            mcp_server_url="https://replacement-group.example.com/mcp",
            data={"token_value": "replacement"},
        ),
        project_id=project_id,
    )
    assert replacement.name == "reusable-member"


# --- membership (add / remove / list) --------------------------------------------


@pytest.mark.asyncio
async def test_add_credential_creates_mcp_member_with_normalized_url(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)

    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="m1",
            mcp_server_url="HTTPS://Example.com:443/mcp/",
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )
    assert cred.kind == "mcp"
    assert cred.credential_type == "static_bearer"
    assert cred.group_id == group.id
    assert cred.mcp_server_url == "HTTPS://Example.com:443/mcp/"
    assert cred.normalized_mcp_server_url == "https://example.com/mcp"

    members = await svc.list_members(group.id, project_id=project_id)
    assert [m.id for m in members] == [cred.id]


@pytest.mark.asyncio
async def test_add_credential_requires_static_bearer_token(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)

    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            group.id,
            AddGroupCredentialRequest(
                name="missing-token",
                mcp_server_url="https://a.com/mcp",
            ),
            project_id=project_id,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_add_credential_marks_sandbox_pending(db_session, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_group_lifecycle_is_idempotent_and_archived_group_rejects_mutation(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="group-matrix"), project_id=project_id)
    group_id = group.id

    first_archive = await svc.archive(group_id, project_id=project_id)
    second_archive = await svc.archive(group_id, project_id=project_id)
    assert first_archive.archived_at == second_archive.archived_at

    for operation in (
        lambda: svc.update(
            group_id,
            UpdateCredentialGroupRequest(name="must-not-change"),
            project_id=project_id,
        ),
        lambda: svc.add_credential(
            group_id,
            AddGroupCredentialRequest(
                name="must-not-add",
                mcp_server_url="https://archived.example.com/mcp",
                data={"token_value": "secret"},
            ),
            project_id=project_id,
        ),
    ):
        with pytest.raises(AppError) as exc:
            await operation()
        assert exc.value.code == "CREDENTIAL_GROUP_ARCHIVED"

    first_restore = await svc.restore(group_id, project_id=project_id)
    second_restore = await svc.restore(group_id, project_id=project_id)
    assert first_restore.archived_at is None
    assert second_restore.archived_at is None

    await svc.soft_delete(group_id, project_id=project_id)
    await svc.soft_delete(group_id, project_id=project_id)
    assert await svc.get(group_id, project_id=project_id) is None


@pytest.mark.asyncio
async def test_active_session_blocks_group_lifecycle_but_member_changes_refresh_policy(
    db_session, project_id, monkeypatch
):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    first_group = await svc.create(CreateCredentialGroupRequest(name="active-session-first"), project_id=project_id)
    second_group = await svc.create(CreateCredentialGroupRequest(name="active-session-second"), project_id=project_id)
    first_group_id = first_group.id
    second_group_id = second_group.id
    await svc.add_credential(
        second_group_id,
        AddGroupCredentialRequest(
            name="existing-url",
            mcp_server_url="https://bound.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    agent = await compose_agent_application(db_session).commands.create_agent(
        JoySafeterCreateAgentRequest(
            name="active-session-agent",
            engine_kind=JoySafeterEngineKind.CLAUDE,
            mcp_servers=[
                {
                    "type": "streamable_http",
                    "name": "bound",
                    "url": "https://bound.example.com/mcp",
                    "auth_requirement": "optional",
                }
            ],
        ),
        project_id=project_id,
    )
    await SessionCreationService(db_session, audit_actor=CredentialAuditActor.system("test")).create_from_source(
        CreateCredentialAwareSession(
            project_id=project_id,
            agent_id=agent.id,
            credential_group_ids=(first_group_id, second_group_id),
            caller="test",
        )
    )

    for lifecycle in (svc.archive, svc.soft_delete):
        with pytest.raises(AppError) as exc:
            await lifecycle(first_group_id, project_id=project_id)
        assert exc.value.code == "CREDENTIAL_IN_USE"

    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            first_group_id,
            AddGroupCredentialRequest(
                name="conflicting-url",
                mcp_server_url="HTTPS://Bound.example.com:443/mcp/",
                data={"token_value": "secret"},
            ),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"

    member = await svc.add_credential(
        first_group_id,
        AddGroupCredentialRequest(
            name="allowed-member",
            mcp_server_url="https://allowed.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "pending"
    await db_session.execute(
        update(JoySafeterSandbox)
        .where(JoySafeterSandbox.id == sandbox_id)
        .values(**acknowledged_network_policy_fields())
    )
    await db_session.commit()
    await svc.archive_credential(first_group_id, member.id, project_id=project_id)
    assert await _sandbox_status(db_session, sandbox_id) == "pending"
    await db_session.execute(
        update(JoySafeterSandbox)
        .where(JoySafeterSandbox.id == sandbox_id)
        .values(**acknowledged_network_policy_fields())
    )
    await db_session.commit()
    captured_impacts = []
    original_mark_pending = svc._application.uow.impacts.mark_pending

    async def capture_impact(impact):
        captured_impacts.append(impact)
        return await original_mark_pending(impact)

    monkeypatch.setattr(svc._application.uow.impacts, "mark_pending", capture_impact)
    await svc.remove_credential(first_group_id, member.id, project_id=project_id)

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as fresh:
        deleted_at = (
            await fresh.execute(select(JoySafeterCredential.deleted_at).where(JoySafeterCredential.id == member.id))
        ).scalar_one()
        assert deleted_at is not None
        assert await _sandbox_status(fresh, sandbox_id) == "pending"
    assert captured_impacts[-1].dispositions == frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY})


@pytest.mark.asyncio
async def test_group_restore_keeps_archived_members_archived_until_individually_restored(
    db_session,
    project_id,
):
    group_service = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential_service = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await group_service.create(
        CreateCredentialGroupRequest(name="restore-with-archived-member"),
        project_id=project_id,
    )
    member = await group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="archived-member",
            mcp_server_url="https://archived-member.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    await group_service.archive_credential(group.id, member.id, project_id=project_id)
    await group_service.archive(group.id, project_id=project_id)

    restored_group = await group_service.restore(group.id, project_id=project_id)

    assert restored_group.archived_at is None
    await db_session.refresh(member)
    assert member.archived_at is not None

    restored_member = await credential_service.restore(member.id, project_id=project_id)
    assert restored_member.archived_at is None


@pytest.mark.parametrize("invalid_case", ("scheme", "material", "project", "group"))
async def test_persisted_group_restore_rejects_invalid_loaded_member(
    db_session,
    project_id,
    other_project_id,
    invalid_case,
    monkeypatch,
):
    from app.joysafeter_infrastructure.credentials import sqlalchemy_repository

    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name=f"restore-{invalid_case}"), project_id=project_id)
    other_group = await svc.create(
        CreateCredentialGroupRequest(name=f"restore-peer-{invalid_case}"),
        project_id=project_id,
    )
    member = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name=f"restore-member-{invalid_case}",
            mcp_server_url=f"https://{invalid_case}.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    await svc.archive(group.id, project_id=project_id)

    if invalid_case == "scheme":
        await db_session.execute(
            update(JoySafeterCredential).where(JoySafeterCredential.id == member.id).values(credential_type="oauth")
        )
    elif invalid_case == "material":
        await db_session.execute(
            update(JoySafeterCredential).where(JoySafeterCredential.id == member.id).values(data={})
        )
    elif invalid_case == "project":
        await db_session.execute(text("SET session_replication_role = replica"))
        await db_session.execute(
            update(JoySafeterCredential).where(JoySafeterCredential.id == member.id).values(project_id=other_project_id)
        )
        await db_session.execute(text("SET session_replication_role = origin"))
    else:
        original_mapper = sqlalchemy_repository.map_credential_row

        def invalid_mapper(row):
            resource = original_mapper(row)
            if row.id != member.id:
                return resource
            identity = resource.identity
            assert isinstance(identity, McpCredentialIdentity)
            return replace(
                resource,
                identity=replace(identity, group_id=other_group.id),
            )

        monkeypatch.setattr(sqlalchemy_repository, "map_credential_row", invalid_mapper)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await svc.restore(group.id, project_id=project_id)
    assert exc.value.code == "CREDENTIAL_STATE_INVALID"
    await db_session.refresh(group)
    assert group.archived_at is not None


@pytest.mark.asyncio
async def test_persisted_group_restore_rejects_bound_session_normalized_url_conflict(
    db_session,
    project_id,
):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    restoring = await svc.create(CreateCredentialGroupRequest(name="restore-url-conflict"), project_id=project_id)
    peer = await svc.create(CreateCredentialGroupRequest(name="restore-url-peer"), project_id=project_id)
    restoring_member = await svc.add_credential(
        restoring.id,
        AddGroupCredentialRequest(
            name="restore-url-member",
            mcp_server_url="https://restore.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    await svc.add_credential(
        peer.id,
        AddGroupCredentialRequest(
            name="restore-url-peer-member",
            mcp_server_url="https://occupied.example.com/mcp",
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )
    agent = await compose_agent_application(db_session).commands.create_agent(
        JoySafeterCreateAgentRequest(
            name="restore-url-agent",
            engine_kind=JoySafeterEngineKind.CLAUDE,
            mcp_servers=[
                {
                    "type": "streamable_http",
                    "name": "occupied",
                    "url": "https://occupied.example.com/mcp",
                    "auth_requirement": "optional",
                }
            ],
        ),
        project_id=project_id,
    )
    await SessionCreationService(db_session, audit_actor=CredentialAuditActor.system("test")).create_from_source(
        CreateCredentialAwareSession(
            project_id=project_id,
            agent_id=agent.id,
            credential_group_ids=(restoring.id, peer.id),
            caller="test",
        )
    )
    await db_session.execute(
        update(JoySafeterCredentialGroup)
        .where(JoySafeterCredentialGroup.id == restoring.id)
        .values(archived_at=utc_now())
    )
    await db_session.execute(
        update(JoySafeterCredential)
        .where(JoySafeterCredential.id == restoring_member.id)
        .values(
            mcp_server_url="HTTPS://Occupied.example.com:443/mcp/",
            normalized_mcp_server_url="https://occupied.example.com/mcp",
        )
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await svc.restore(restoring.id, project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"
    await db_session.refresh(restoring)
    assert restoring.archived_at is not None


@pytest.mark.asyncio
async def test_add_duplicate_normalized_url_in_same_group_conflicts(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://example.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )
    # Different raw URL, SAME normalized url -> conflict.
    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            group.id,
            AddGroupCredentialRequest(
                name="m2",
                mcp_server_url="HTTPS://Example.com:443/mcp/",
                data={"token_value": "t"},
            ),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_add_credential_to_group_in_other_project_rejected(db_session, project_id, other_project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    # Attempt to add a member using the WRONG project_id -> group not found.
    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            group.id,
            AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
            project_id=other_project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_remove_credential_soft_deletes(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )
    await svc.remove_credential(group.id, cred.id, project_id=project_id)
    members = await svc.list_members(group.id, project_id=project_id)
    assert members == []

    # Soft-deleting frees the (group, normalized_url) slot for re-add.
    again = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1-again", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )
    assert again.normalized_mcp_server_url == "https://a.com/mcp"


@pytest.mark.asyncio
async def test_remove_credential_without_active_group_session_keeps_sandbox_ready(db_session, project_id):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )

    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    await svc.remove_credential(group.id, cred.id, project_id=project_id)
    assert await _sandbox_status(db_session, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_archive_credential_without_active_group_session_preserves_history_and_keeps_sandbox_ready(
    db_session,
    project_id,
):
    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp", data={"token_value": "t"}),
        project_id=project_id,
    )

    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    archived = await svc.archive_credential(group.id, cred.id, project_id=project_id)

    assert archived.archived_at is not None
    assert archived.deleted_at is None
    assert cred.id in {
        member.id for member in await svc.list_members(group.id, project_id=project_id, include_archived=True)
    }
    assert cred.id not in {
        member.id for member in await svc.list_members(group.id, project_id=project_id, include_archived=False)
    }
    assert await _sandbox_status(db_session, sandbox_id) == "ready"


@pytest.mark.asyncio
async def test_remove_credential_missing_raises(db_session, project_id):
    from app.joysafeter_shared.ids import CredentialId

    svc = CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test"))
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    with pytest.raises(AppError) as exc:
        await svc.remove_credential(group.id, CredentialId.new(), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"
