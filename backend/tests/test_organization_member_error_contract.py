import re
import uuid
from types import SimpleNamespace

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import (
    SwitchContextRequest,
    SwitchContextResponse,
    archive_project,
    get_me,
    get_project,
    list_projects,
    revoke_api_key,
    switch_context,
)
from app.joysafeter_api.api.v1.organizations import (
    AddMemberRequest,
    TransferOwnershipRequest,
    UpdateMemberRoleRequest,
    add_member,
    delete_organization,
    get_organization,
    list_organizations,
    remove_member,
    transfer_ownership,
    update_member_role,
)
from app.joysafeter_api.api.v1.organizations import (
    CreateOrganizationRequest as OrganizationCreateRequest,
)
from app.joysafeter_api.api.v1.organizations import (
    create_organization as create_scoped_organization,
)
from app.joysafeter_api.api.v1.organizations import (
    list_members as list_organization_members,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    AgentId,
    ApiKeyId,
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    UserId,
)
from app.joysafeter_shared.utils.datetime import utc_now

ADMIN_USER_ID = UserId.from_uuid(uuid.uuid5(uuid.NAMESPACE_URL, "test:admin-user"))


def _user_id(label: str) -> UserId:
    return UserId.from_uuid(uuid.uuid5(uuid.NAMESPACE_URL, f"test:user:{label}"))


def _organization_id(label: str) -> OrganizationId:
    return OrganizationId.from_uuid(uuid.uuid5(uuid.NAMESPACE_URL, f"test:organization:{label}"))


def _project_id(label: str) -> ProjectId:
    return ProjectId.from_uuid(uuid.uuid5(uuid.NAMESPACE_URL, f"test:project:{label}"))


def _auth_ctx(org_id: OrganizationId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=ADMIN_USER_ID,
        org_id=org_id,
        project_id=None,
        role=JoySafeterRole.ADMIN,
    )


async def _org(db_session) -> Organization:
    org = Organization(id=OrganizationId.new(), name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


def _request():
    return SimpleNamespace(client=None, headers={})


async def _organization_actor(db_session, organization_id: OrganizationId, *, role: str = "admin") -> AuthUser:
    actor = AuthUser(id=UserId.new(), name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=organization_id, role=role))
    await db_session.commit()
    return actor


@pytest.mark.asyncio
async def test_scoped_create_organization_uses_same_slug_and_default_project_contract(db_session):
    user = AuthUser(id=UserId.new(), name="Scoped User", email=f"scoped-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()

    response = await create_scoped_organization(
        OrganizationCreateRequest(name="Ignored Name", slug="Explicit Slug!!"),
        SimpleNamespace(id=user.id),
        db_session,
    )

    assert response.name == "Ignored Name"
    assert re.fullmatch(r"explicit-slug-[0-9a-f]{6}", response.slug)
    assert response.project_id
    assert response.created_at

    member_result = await db_session.execute(
        select(Member).where(Member.organization_id == response.id, Member.user_id == user.id)
    )
    owner = member_result.scalar_one_or_none()
    assert owner is not None
    assert owner.role == "owner"

    project_result = await db_session.execute(select(Project).where(Project.id == response.project_id))
    project = project_result.scalar_one()
    assert project.org_id == response.id
    assert project.name == "Main"
    assert project.slug == "main"
    assert project.is_default is True

    project_member_result = await db_session.execute(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
    )
    project_member = project_member_result.scalar_one_or_none()
    assert project_member is None
    assert project.created_by_user_id == user.id


@pytest.mark.asyncio
async def test_list_organizations_exposes_viewer_role_and_current_owner_identity(db_session):
    viewer = AuthUser(id=UserId.new(), name="Viewer", email=f"viewer-{uuid.uuid4()}@example.com")
    owner = AuthUser(id=UserId.new(), name="Workspace Owner", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=OrganizationId.new(), name="Shared Org", slug=f"shared-{uuid.uuid4()}")
    db_session.add_all([viewer, owner, org])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=viewer.id, organization_id=org.id, role="member"),
            Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"),
        ]
    )
    await db_session.commit()

    response = await list_organizations(
        SimpleNamespace(id=viewer.id),
        q="",
        limit=50,
        after_id=None,
        db=db_session,
    )

    assert len(response.data) == 1
    assert response.data[0].role == "member"
    assert response.data[0].owner_name == owner.name
    assert response.data[0].owner_email == owner.email

    detail = await get_organization(org.id, SimpleNamespace(id=viewer.id), db_session)
    assert detail.role == "member"
    assert detail.owner_name == owner.name
    assert detail.owner_email == owner.email


@pytest.mark.asyncio
async def test_delete_organization_rejects_project_resources_before_db_delete(db_session):
    owner = AuthUser(id=UserId.new(), name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=OrganizationId.new(), name="Delete Org", slug=f"delete-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([owner, org, project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"))
    db_session.add(JoySafeterAgent(id=AgentId.new(), name=f"org-delete-agent-{uuid.uuid4()}", project_id=project.id))
    await db_session.commit()
    org_id = org.id
    project_id = project.id

    with pytest.raises(AppError) as exc_info:
        await delete_organization(org_id, SimpleNamespace(id=owner.id), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_PROJECT_RESOURCES_EXIST",
        "message": "Organization has project resources. Delete or archive project resources before deleting the organization.",
        "data": {"organization_id": str(org_id), "resources": ["agents"]},
        "source": "api",
        "retryable": False,
        "user_action": "delete_resources",
    }

    db_session.expire_all()
    assert (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    assert (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_delete_empty_organization_deletes_default_project_and_membership(db_session):
    owner = AuthUser(id=UserId.new(), name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=OrganizationId.new(), name="Empty Delete Org", slug=f"empty-delete-org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([owner, org, project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"))
    await db_session.commit()
    org_id = org.id
    project_id = project.id
    owner_id = owner.id

    await delete_organization(org_id, SimpleNamespace(id=owner_id), db_session)

    assert (
        await db_session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none() is None
    assert (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Member).where(Member.organization_id == org_id, Member.user_id == owner_id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_add_member_returns_structured_duplicate_member_error(db_session):
    org = await _org(db_session)
    actor = AuthUser(id=UserId.new(), name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    target = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=org.id, role="admin"),
            Member(id=OrganizationMemberId.new(), user_id=target.id, organization_id=org.id, role="member"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email=target.email),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_MEMBER_ALREADY_EXISTS",
        "message": "User is already a member of this organization",
        "data": {"organization_id": str(org.id), "user_id": str(target.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_add_existing_member_returns_structured_duplicate_member_error(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    user = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org.id, role="member"))
    await db_session.commit()
    await db_session.refresh(user)

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email=user.email),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_MEMBER_ALREADY_EXISTS",
        "message": "User is already a member of this organization",
        "data": {"organization_id": str(org.id), "user_id": str(user.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_add_existing_member_missing_user_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    missing_email = f"missing-{uuid.uuid4()}@example.com"

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email=missing_email),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "AUTH_USER_NOT_FOUND",
        "message": "User not found with the given email",
        "data": {"email": missing_email},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_add_existing_member_matches_registered_email_case_insensitively(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    user = AuthUser(id=UserId.new(), name="Target User", email=f"Target-{uuid.uuid4()}@Example.COM")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    response = await add_member(
        org.id,
        AddMemberRequest(email=user.email.lower(), role="member"),
        _request(),  # type: ignore[arg-type]
        SimpleNamespace(id=actor.id),
        db_session,
    )

    assert response.user_id == user.id
    assert response.user_email == user.email


@pytest.mark.asyncio
async def test_organization_member_response_identifies_organization_scope(db_session):
    org = await _org(db_session)
    user = AuthUser(id=ADMIN_USER_ID, name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    membership = Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org.id, role="admin")
    db_session.add(membership)
    await db_session.commit()

    response = await list_organization_members(
        org.id,
        SimpleNamespace(id=user.id),
        q="",
        limit=50,
        after_id=None,
        db=db_session,
    )

    assert response.data[0].id == membership.id
    assert response.data[0].organization_id == org.id


@pytest.mark.asyncio
async def test_add_existing_member_uses_implicit_default_project_membership(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    user = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([project, user])
    await db_session.commit()
    await db_session.refresh(user)

    response = await add_member(
        org.id,
        AddMemberRequest(email=user.email, role="member"),
        _request(),  # type: ignore[arg-type]
        SimpleNamespace(id=actor.id),
        db_session,
    )

    assert response.user_id == user.id
    project_member = (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    assert project_member is None


@pytest.mark.asyncio
async def test_promoting_member_clears_redundant_project_grants(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    project = Project(id=ProjectId.new(), org_id=org.id, name="Project", slug=f"project-{uuid.uuid4()}")
    target = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([project, target])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=target.id, organization_id=org.id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=target.id, role="admin"),
        ]
    )
    await db_session.commit()

    await update_member_role(
        org.id,
        target.id,
        UpdateMemberRoleRequest(role="admin"),
        _request(),  # type: ignore[arg-type]
        SimpleNamespace(id=actor.id),
        db_session,
    )

    remaining = (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id)
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_demoting_admin_does_not_reactivate_hidden_project_grants(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id, role="owner")
    default_project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    other_project = Project(id=ProjectId.new(), org_id=org.id, name="Other", slug=f"other-{uuid.uuid4()}")
    target = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([default_project, other_project, target])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=target.id, organization_id=org.id, role="admin"))
    db_session.add(
        ProjectMember(id=ProjectMemberId.new(), project_id=other_project.id, user_id=target.id, role="admin")
    )
    await db_session.commit()

    await update_member_role(
        org.id,
        target.id,
        UpdateMemberRoleRequest(role="member"),
        _request(),  # type: ignore[arg-type]
        SimpleNamespace(id=actor.id),
        db_session,
    )

    projects = await ProjectService(db_session).list_accessible_projects(
        org_id=org.id,
        user_id=target.id,
        org_role="member",
    )
    assert [project.id for project in projects] == [default_project.id]


@pytest.mark.asyncio
async def test_remove_member_cleans_project_memberships(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    target = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([target, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=target.id, organization_id=org.id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=target.id, role="editor"),
        ]
    )
    await db_session.commit()

    await remove_member(
        org.id,
        target.id,
        _request(),  # type: ignore[arg-type]
        SimpleNamespace(id=actor.id),
        db_session,
    )

    assert (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id)
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_update_organization_member_missing_member_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    missing_user_id = UserId.new()

    with pytest.raises(AppError) as exc_info:
        await update_member_role(
            org.id,
            missing_user_id,
            UpdateMemberRoleRequest(role="member"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "ORGANIZATION_MEMBER_NOT_FOUND",
        "message": "Member not found",
        "data": {"organization_id": str(org.id), "user_id": str(missing_user_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_project_missing_project_returns_structured_error(db_session):
    org_id = OrganizationId.new()
    project_id = ProjectId.new()

    with pytest.raises(AppError) as exc_info:
        await get_project(project_id, db_session, _auth_ctx(org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project not found",
        "data": {"project_id": str(project_id), "organization_id": str(org_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_revoke_api_key_missing_key_returns_structured_error(db_session):
    org_id = OrganizationId.new()
    key_id = ApiKeyId.new()

    with pytest.raises(AppError) as exc_info:
        await revoke_api_key(key_id, None, db_session, _auth_ctx(org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "API_KEY_NOT_FOUND",
        "message": "API key not found",
        "data": {"key_id": str(key_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_add_member_invalid_role_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email="target@example.com", role="super-admin"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AUTH_INVALID_ASSIGNABLE_ROLE",
        "message": "Invalid role. Must be one of: admin, member",
        "data": {"role": "super-admin", "allowed": ["admin", "member"]},
        "source": "auth",
        "retryable": False,
        "user_action": "correct_request",
    }


@pytest.mark.asyncio
async def test_transfer_ownership_to_self_returns_structured_error(db_session):
    org = await _org(db_session)
    owner = AuthUser(id=UserId.new(), name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await transfer_ownership(
            org.id,
            TransferOwnershipRequest(new_owner_user_id=owner.id),
            SimpleNamespace(id=owner.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ORGANIZATION_OWNER_TRANSFER_SELF",
        "message": "Cannot transfer ownership to yourself",
        "data": {"organization_id": str(org.id), "user_id": str(owner.id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_remove_owner_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = await _organization_actor(db_session, org.id)
    owner = AuthUser(id=UserId.new(), name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_member(
            org.id,
            owner.id,
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    # The owner is protected on the auth surface via the same gate that blocks
    # any change to an owner's role (removal == demote-to-member internally).
    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "AUTH_OWNER_ROLE_CHANGE_FORBIDDEN",
        "message": "Cannot change the owner's role",
        "data": {"actor_role": "admin", "current_role": "owner", "target_role": "member"},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_admin_cannot_change_own_role_from_member_management(db_session):
    org = await _org(db_session)
    actor = AuthUser(id=ADMIN_USER_ID, name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await update_member_role(
            org.id,
            actor.id,
            UpdateMemberRoleRequest(role="member"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "AUTH_MEMBER_SELF_MANAGEMENT_FORBIDDEN",
        "message": "Cannot change your own organization membership from member management",
        "data": {"organization_id": str(org.id), "member_id": str(actor.id)},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_admin_cannot_remove_self_from_member_management(db_session):
    org = await _org(db_session)
    actor = AuthUser(id=ADMIN_USER_ID, name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_member(
            org.id,
            actor.id,
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "AUTH_MEMBER_SELF_MANAGEMENT_FORBIDDEN",
        "message": "Cannot change your own organization membership from member management",
        "data": {"organization_id": str(org.id), "member_id": str(actor.id)},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_archive_default_project_returns_structured_error(db_session):
    org = await _org(db_session)
    project = Project(id=ProjectId.new(), org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    with pytest.raises(AppError) as exc_info:
        await archive_project(project.id, db_session, _auth_ctx(org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
        "message": "Cannot archive the default project",
        "data": {"project_id": str(project.id), "organization_id": str(org.id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_organization_blank_name_returns_structured_error(db_session):
    with pytest.raises(AppError) as exc_info:
        await create_scoped_organization(
            OrganizationCreateRequest(name=" "),
            SimpleNamespace(id=ADMIN_USER_ID),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ORGANIZATION_NAME_REQUIRED",
        "message": "Organization name is required",
        "data": {"field": "name"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_add_member_without_admin_permission_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = AuthUser(id=UserId.new(), name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=org.id, role="member"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email="target@example.com", role="member"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "ORGANIZATION_PERMISSION_DENIED",
        "message": "Insufficient permission",
        "data": {"organization_id": str(org.id)},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_admin_must_use_transfer_flow_for_owner_role(db_session):
    org = await _org(db_session)
    actor = AuthUser(id=UserId.new(), name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=actor.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email="target@example.com", role="owner"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AUTH_INVALID_ASSIGNABLE_ROLE",
        "message": "Invalid role. Must be one of: admin, member",
        "data": {"role": "owner", "allowed": ["admin", "member"]},
        "source": "auth",
        "retryable": False,
        "user_action": "correct_request",
    }


@pytest.mark.asyncio
async def test_owner_must_use_transfer_flow_for_owner_role(db_session):
    org = await _org(db_session)
    owner = AuthUser(id=UserId.new(), name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    target = AuthUser(id=UserId.new(), name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([owner, target])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=owner.id, organization_id=org.id, role="owner"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(email=target.email, role="owner"),
            _request(),  # type: ignore[arg-type]
            SimpleNamespace(id=owner.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AUTH_INVALID_ASSIGNABLE_ROLE",
        "message": "Invalid role. Must be one of: admin, member",
        "data": {"role": "owner", "allowed": ["admin", "member"]},
        "source": "auth",
        "retryable": False,
        "user_action": "correct_request",
    }


@pytest.mark.asyncio
async def test_switch_context_requires_target_org_membership(db_session):
    target_org_id = OrganizationId.new()

    with pytest.raises(AppError) as exc_info:
        await switch_context(
            SwitchContextRequest(org_id=target_org_id), db_session, _auth_ctx(_organization_id("current"))
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "AUTH_ORGANIZATION_MEMBERSHIP_REQUIRED",
        "message": "User is not a member of the target organization",
        "data": {"organization_id": str(target_org_id)},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_switch_context_uses_active_project_when_default_is_archived(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Switch Org", slug=f"switch-org-{uuid.uuid4()}")
    db_session.add_all([user, org])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=ADMIN_USER_ID, organization_id=org_id, role="admin"))
    archived_default = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Archived Default",
        slug=f"archived-default-{uuid.uuid4()}",
        is_default=True,
        archived_at=utc_now(),
    )
    active_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Active",
        slug=f"active-{uuid.uuid4()}",
    )
    db_session.add_all([archived_default, active_project])
    await db_session.commit()

    response = await switch_context(
        SwitchContextRequest(org_id=org_id), db_session, _auth_ctx(_organization_id("current"))
    )

    assert response.project_id == active_project.id
    assert response.project.id == active_project.id
    assert len(response.projects) == 1
    assert response.projects[0].id == active_project.id
    assert response.projects[0].org_id == org_id
    assert response.projects[0].name == active_project.name
    assert response.projects[0].slug == active_project.slug
    assert response.projects[0].is_default is active_project.is_default
    assert response.projects[0].archived_at is None


@pytest.mark.asyncio
async def test_switch_context_reports_implicit_default_project_viewer_capability(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Member User", email=f"member-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Member Org", slug=f"member-org-{uuid.uuid4()}")
    default_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Default",
        slug=f"default-{uuid.uuid4()}",
        is_default=True,
    )
    db_session.add_all([user, org, default_project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"))
    await db_session.commit()

    response = await switch_context(
        SwitchContextRequest(org_id=org_id), db_session, _auth_ctx(_organization_id("current"))
    )
    validated = SwitchContextResponse.model_validate(response)

    assert response.project_id == default_project.id
    assert response.project.project_role is None
    assert response.project.capability == "read"
    assert validated.project.capability == "read"


@pytest.mark.asyncio
async def test_switch_context_rejects_inaccessible_project_for_non_admin_member(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project ACL Org", slug=f"project-acl-org-{uuid.uuid4()}")
    allowed_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=allowed_project.id, user_id=user.id, role="editor"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await switch_context(
            SwitchContextRequest(org_id=org_id, project_id=blocked_project.id),
            db_session,
            _auth_ctx(_organization_id("current")),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project not found in the target organization",
        "data": {"project_id": str(blocked_project.id), "organization_id": str(org_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_me_lists_only_accessible_projects_for_non_admin_member(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project List ACL Org", slug=f"project-list-acl-org-{uuid.uuid4()}")
    allowed_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=allowed_project.id, user_id=user.id, role="editor"),
        ]
    )
    await db_session.commit()

    response = await get_me(
        db_session,
        JoySafeterAuthContext(
            user_id=user.id,
            org_id=org_id,
            project_id=allowed_project.id,
            role=JoySafeterRole.MEMBER,
        ),
    )

    assert response.project.id == allowed_project.id
    assert {project.id for project in response.projects} == {allowed_project.id}
    assert blocked_project.id not in {project.id for project in response.projects}


@pytest.mark.asyncio
async def test_list_projects_filters_to_accessible_projects_for_non_admin_member(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project List Route ACL Org", slug=f"project-list-route-{uuid.uuid4()}")
    allowed_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=allowed_project.id, user_id=user.id, role="editor"),
        ]
    )
    await db_session.commit()

    response = await list_projects(
        include_archived=False,
        limit=50,
        after_id=None,
        db=db_session,
        auth_ctx=JoySafeterAuthContext(
            user_id=user.id,
            org_id=org_id,
            project_id=allowed_project.id,
            role=JoySafeterRole.MEMBER,
        ),
    )

    assert [project.id for project in response.data] == [allowed_project.id]
    assert blocked_project.id not in {project.id for project in response.data}
    assert response.data[0].project_role == "editor"
    assert response.data[0].capability == "write"


@pytest.mark.asyncio
async def test_list_projects_reports_inherited_admin_capability_for_org_admin(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="Org Admin", email=f"admin-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Inherited Admin Org", slug=f"inherited-admin-{uuid.uuid4()}")
    project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Managed Project",
        slug=f"managed-{uuid.uuid4()}",
        is_default=True,
    )
    db_session.add_all([user, org, project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="admin"))
    await db_session.commit()

    response = await list_projects(
        include_archived=False,
        limit=50,
        after_id=None,
        db=db_session,
        auth_ctx=JoySafeterAuthContext(
            user_id=user.id,
            org_id=org_id,
            project_id=project.id,
            role=JoySafeterRole.ADMIN,
        ),
    )

    assert response.data[0].project_role is None
    assert response.data[0].capability == "admin"


@pytest.mark.asyncio
async def test_get_project_rejects_inaccessible_project_for_non_admin_member(db_session):
    org_id = OrganizationId.new()
    user = AuthUser(id=ADMIN_USER_ID, name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project Detail ACL Org", slug=f"project-detail-acl-{uuid.uuid4()}")
    allowed_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=ProjectId.new(),
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(id=ProjectMemberId.new(), project_id=allowed_project.id, user_id=user.id, role="editor"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await get_project(
            blocked_project.id,
            db_session,
            JoySafeterAuthContext(
                user_id=user.id,
                org_id=org_id,
                project_id=allowed_project.id,
                role=JoySafeterRole.MEMBER,
            ),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project not found",
        "data": {"project_id": str(blocked_project.id), "organization_id": str(org_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
