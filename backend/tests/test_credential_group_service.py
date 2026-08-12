"""Tests for CredentialGroupService (Task 6).

Real-DB tests (Postgres via conftest's ``db_session``): the group service leans
on the DB's partial unique indexes — ``(project_id, name)`` on groups and
``(group_id, normalized_mcp_server_url) WHERE kind='mcp'`` on credentials — plus
the composite FK enforcing project isolation. sqlite is not a substitute.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    UpdateCredentialGroupRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_group_service import (
    CredentialGroupService,
)
from app.joysafeter_shared.common.app_errors import AppError


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


@pytest_asyncio.fixture
async def other_project_id(db_session) -> str:
    return await _make_project(db_session)


def _limited_sandbox(project_id: str) -> JoySafeterSandbox:
    return JoySafeterSandbox(
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
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
    svc = CredentialGroupService(db_session)
    group = await svc.create(
        CreateCredentialGroupRequest(name="g1", description="first"),
        project_id=project_id,
    )
    assert group.name == "g1"
    assert group.description == "first"

    fetched = await svc.get(group.id, project_id=project_id)
    assert fetched is not None
    assert fetched.id == group.id

    groups, has_more = await svc.list(project_id=project_id)
    assert group.id in {g.id for g in groups}
    assert has_more is False


@pytest.mark.asyncio
async def test_get_missing_group_raises(db_session, project_id):
    from app.joysafeter_shared.ids import CredentialGroupId

    svc = CredentialGroupService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.get_or_raise(CredentialGroupId.new(), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_group_name_unique_per_project(db_session, project_id):
    svc = CredentialGroupService(db_session)
    await svc.create(CreateCredentialGroupRequest(name="dup"), project_id=project_id)
    with pytest.raises(AppError) as exc:
        await svc.create(CreateCredentialGroupRequest(name="dup"), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_NAME_EXISTS"


@pytest.mark.asyncio
async def test_group_name_reusable_across_projects(db_session, project_id, other_project_id):
    svc = CredentialGroupService(db_session)
    await svc.create(CreateCredentialGroupRequest(name="shared"), project_id=project_id)
    # Same name in a different project is fine.
    other = await svc.create(CreateCredentialGroupRequest(name="shared"), project_id=other_project_id)
    assert other.name == "shared"


@pytest.mark.asyncio
async def test_update_group(db_session, project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    updated = await svc.update(
        group.id,
        UpdateCredentialGroupRequest(name="g1-renamed", description="new"),
        project_id=project_id,
    )
    assert updated.name == "g1-renamed"
    assert updated.description == "new"


@pytest.mark.asyncio
async def test_archive_soft_delete_group_mark_pending(db_session, project_id):
    svc = CredentialGroupService(db_session)
    for method in ("archive", "soft_delete"):
        sandbox = _limited_sandbox(project_id)
        db_session.add(sandbox)
        await db_session.commit()
        sandbox_id = sandbox.id

        group = await svc.create(
            CreateCredentialGroupRequest(name=f"g-{method}"), project_id=project_id
        )
        assert await _sandbox_status(db_session, sandbox_id) == "ready"

        await getattr(svc, method)(group.id, project_id=project_id)
        assert await _sandbox_status(db_session, sandbox_id) == "pending", method

        sandbox.networking_status = "ready"
        db_session.add(sandbox)
        await db_session.commit()

    # Soft-deleted group is not returned by get.
    deleted = await svc.create(CreateCredentialGroupRequest(name="gone"), project_id=project_id)
    await svc.soft_delete(deleted.id, project_id=project_id)
    assert await svc.get(deleted.id, project_id=project_id) is None


# --- membership (add / remove / list) --------------------------------------------


@pytest.mark.asyncio
async def test_add_credential_creates_mcp_member_with_normalized_url(db_session, project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)

    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="m1",
            mcp_server_url="HTTPS://Example.com:443/mcp/",
            data={"AUTH_TOKEN": "t"},
        ),
        project_id=project_id,
    )
    assert cred.kind == "mcp"
    assert cred.group_id == group.id
    assert cred.mcp_server_url == "HTTPS://Example.com:443/mcp/"
    assert cred.normalized_mcp_server_url == "https://example.com/mcp"

    members = await svc.list_members(group.id, project_id=project_id)
    assert [m.id for m in members] == [cred.id]


@pytest.mark.asyncio
async def test_add_credential_marks_sandbox_pending(db_session, project_id):
    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp"),
        project_id=project_id,
    )
    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_add_duplicate_normalized_url_in_same_group_conflicts(db_session, project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://example.com/mcp"),
        project_id=project_id,
    )
    # Different raw URL, SAME normalized url -> conflict.
    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            group.id,
            AddGroupCredentialRequest(name="m2", mcp_server_url="HTTPS://Example.com:443/mcp/"),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_add_credential_to_group_in_other_project_rejected(db_session, project_id, other_project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    # Attempt to add a member using the WRONG project_id -> group not found.
    with pytest.raises(AppError) as exc:
        await svc.add_credential(
            group.id,
            AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp"),
            project_id=other_project_id,
        )
    assert exc.value.code == "CREDENTIAL_GROUP_NOT_FOUND"


@pytest.mark.asyncio
async def test_remove_credential_soft_deletes(db_session, project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp"),
        project_id=project_id,
    )
    await svc.remove_credential(group.id, cred.id, project_id=project_id)
    members = await svc.list_members(group.id, project_id=project_id)
    assert members == []

    # Soft-deleting frees the (group, normalized_url) slot for re-add.
    again = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1-again", mcp_server_url="https://a.com/mcp"),
        project_id=project_id,
    )
    assert again.normalized_mcp_server_url == "https://a.com/mcp"


@pytest.mark.asyncio
async def test_remove_credential_marks_sandbox_pending(db_session, project_id):
    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    cred = await svc.add_credential(
        group.id,
        AddGroupCredentialRequest(name="m1", mcp_server_url="https://a.com/mcp"),
        project_id=project_id,
    )

    sandbox = _limited_sandbox(project_id)
    db_session.add(sandbox)
    await db_session.commit()
    sandbox_id = sandbox.id

    await svc.remove_credential(group.id, cred.id, project_id=project_id)
    assert await _sandbox_status(db_session, sandbox_id) == "pending"


@pytest.mark.asyncio
async def test_remove_credential_missing_raises(db_session, project_id):
    from app.joysafeter_shared.ids import CredentialId

    svc = CredentialGroupService(db_session)
    group = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    with pytest.raises(AppError) as exc:
        await svc.remove_credential(group.id, CredentialId.new(), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


# --- cross-group URL-conflict check (session bind) -------------------------------


@pytest.mark.asyncio
async def test_check_url_conflict_for_session_disjoint_ok(db_session, project_id):
    svc = CredentialGroupService(db_session)
    g1 = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    g2 = await svc.create(CreateCredentialGroupRequest(name="g2"), project_id=project_id)
    await svc.add_credential(
        g1.id, AddGroupCredentialRequest(name="a", mcp_server_url="https://a.com/mcp"), project_id=project_id
    )
    await svc.add_credential(
        g2.id, AddGroupCredentialRequest(name="b", mcp_server_url="https://b.com/mcp"), project_id=project_id
    )
    # Disjoint urls across the two groups -> no conflict.
    await svc.check_url_conflict_for_session([g1.id, g2.id], project_id=project_id)


@pytest.mark.asyncio
async def test_check_url_conflict_for_session_shared_url_conflicts(db_session, project_id):
    svc = CredentialGroupService(db_session)
    g1 = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    g2 = await svc.create(CreateCredentialGroupRequest(name="g2"), project_id=project_id)
    await svc.add_credential(
        g1.id, AddGroupCredentialRequest(name="a", mcp_server_url="https://dup.com/mcp"), project_id=project_id
    )
    # Same normalized url lives in a DIFFERENT group -> nondeterministic at bind.
    await svc.add_credential(
        g2.id,
        AddGroupCredentialRequest(name="b", mcp_server_url="HTTPS://Dup.com:443/mcp/"),
        project_id=project_id,
    )
    with pytest.raises(AppError) as exc:
        await svc.check_url_conflict_for_session([g1.id, g2.id], project_id=project_id)
    assert exc.value.code == "CREDENTIAL_GROUP_URL_CONFLICT"


@pytest.mark.asyncio
async def test_check_url_conflict_single_group_ok(db_session, project_id):
    svc = CredentialGroupService(db_session)
    g1 = await svc.create(CreateCredentialGroupRequest(name="g1"), project_id=project_id)
    await svc.add_credential(
        g1.id, AddGroupCredentialRequest(name="a", mcp_server_url="https://a.com/mcp"), project_id=project_id
    )
    # A single group can never conflict with itself.
    await svc.check_url_conflict_for_session([g1.id], project_id=project_id)
