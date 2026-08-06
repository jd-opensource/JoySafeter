import re
import uuid
from types import SimpleNamespace

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import (
    CreateOrganizationRequest,
    InviteMemberRequest,
    SwitchContextRequest,
    UpdateMemberRoleRequest,
    archive_project,
    create_organization,
    get_me,
    get_project,
    invite_member,
    list_projects,
    remove_member,
    revoke_api_key,
    switch_context,
    update_member_role,
)
from app.joysafeter_api.api.v1.organizations import (
    AddMemberRequest,
    TransferOwnershipRequest,
    add_member,
    delete_organization,
    transfer_ownership,
)
from app.joysafeter_api.api.v1.organizations import (
    CreateOrganizationRequest as OrganizationCreateRequest,
)
from app.joysafeter_api.api.v1.organizations import (
    create_organization as create_scoped_organization,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx(org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.ADMIN,
    )


async def _org(db_session) -> Organization:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest.mark.asyncio
async def test_auth_create_organization_uses_domain_creation_contract(db_session):
    user = AuthUser(id="admin-user", name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()

    response = await create_organization(
        CreateOrganizationRequest(name="My Org!!"),
        db_session,
        _auth_ctx("existing-org"),
    )

    assert response.name == "My Org!!"
    assert re.fullmatch(r"my-org-[0-9a-f]{6}", response.slug)
    assert response.project_id

    member_result = await db_session.execute(
        select(Member).where(Member.organization_id == response.id, Member.user_id == user.id)
    )
    owner = member_result.scalar_one_or_none()
    assert owner is not None
    assert owner.role == "owner"

    project_result = await db_session.execute(select(Project).where(Project.id == response.project_id))
    project = project_result.scalar_one()
    assert project.org_id == response.id
    assert project.name == "Default"
    assert project.slug == "default"
    assert project.is_default is True

    project_member_result = await db_session.execute(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
    )
    project_member = project_member_result.scalar_one_or_none()
    assert project_member is not None
    assert project_member.role == "admin"


@pytest.mark.asyncio
async def test_scoped_create_organization_uses_same_slug_and_default_project_contract(db_session):
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="Scoped User", email=f"scoped-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()

    response = await create_scoped_organization(
        OrganizationCreateRequest(name="Ignored Name", slug="Explicit Slug!!"),
        SimpleNamespace(id=user.id),
        db_session,
    )

    assert response["name"] == "Ignored Name"
    assert re.fullmatch(r"explicit-slug-[0-9a-f]{6}", response["slug"])
    assert response["project_id"]
    assert response["created_at"]

    member_result = await db_session.execute(
        select(Member).where(Member.organization_id == response["id"], Member.user_id == user.id)
    )
    owner = member_result.scalar_one_or_none()
    assert owner is not None
    assert owner.role == "owner"

    project_result = await db_session.execute(select(Project).where(Project.id == response["project_id"]))
    project = project_result.scalar_one()
    assert project.org_id == response["id"]
    assert project.name == "Default"
    assert project.slug == "default"
    assert project.is_default is True

    project_member_result = await db_session.execute(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
    )
    project_member = project_member_result.scalar_one_or_none()
    assert project_member is not None
    assert project_member.role == "admin"


@pytest.mark.asyncio
async def test_delete_organization_rejects_project_resources_before_db_delete(db_session):
    owner = AuthUser(id=f"user-{uuid.uuid4()}", name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=f"org-{uuid.uuid4()}", name="Delete Org", slug=f"delete-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([owner, org, project])
    await db_session.flush()
    db_session.add(Member(user_id=owner.id, organization_id=org.id, role="owner"))
    db_session.add(JoySafeterAgent(name=f"org-delete-agent-{uuid.uuid4()}", project_id=project.id))
    await db_session.commit()
    org_id = org.id
    project_id = project.id

    with pytest.raises(AppError) as exc_info:
        await delete_organization(org_id, SimpleNamespace(id=owner.id), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_PROJECT_RESOURCES_EXIST",
        "message": "Organization has project resources. Delete or archive project resources before deleting the organization.",
        "data": {"organization_id": org_id, "resources": ["agents"]},
        "source": "api",
        "retryable": False,
        "user_action": "delete_resources",
    }

    db_session.expire_all()
    assert (await db_session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    assert (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_delete_empty_organization_deletes_default_project_and_membership(db_session):
    owner = AuthUser(id=f"user-{uuid.uuid4()}", name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    org = Organization(id=f"org-{uuid.uuid4()}", name="Empty Delete Org", slug=f"empty-delete-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([owner, org, project])
    await db_session.flush()
    db_session.add(Member(user_id=owner.id, organization_id=org.id, role="owner"))
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
    actor = AuthUser(name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    target = AuthUser(name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=actor.id, organization_id=org.id, role="admin"),
            Member(user_id=target.id, organization_id=org.id, role="member"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(org.id, AddMemberRequest(user_id=target.id), SimpleNamespace(id=actor.id), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_MEMBER_ALREADY_EXISTS",
        "message": "User is already a member",
        "data": {"organization_id": org.id, "user_id": target.id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_invite_member_returns_structured_duplicate_member_error(db_session):
    org = await _org(db_session)
    user = AuthUser(name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))
    await db_session.commit()
    await db_session.refresh(user)

    with pytest.raises(AppError) as exc_info:
        await invite_member(InviteMemberRequest(email=user.email), None, db_session, _auth_ctx(org.id))  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ORGANIZATION_MEMBER_ALREADY_EXISTS",
        "message": "User is already a member of this organization",
        "data": {"organization_id": org.id, "user_id": user.id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_invite_member_missing_user_returns_structured_error(db_session):
    org = await _org(db_session)
    missing_email = f"missing-{uuid.uuid4()}@example.com"

    with pytest.raises(AppError) as exc_info:
        await invite_member(InviteMemberRequest(email=missing_email), None, db_session, _auth_ctx(org.id))  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "AUTH_USER_NOT_FOUND",
        "message": "User not found with the given email",
        "data": {"email": missing_email},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_invite_member_grants_default_project_membership(db_session):
    org = await _org(db_session)
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="Default", slug="default", is_default=True)
    user = AuthUser(name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([project, user])
    await db_session.commit()
    await db_session.refresh(user)

    response = await invite_member(
        InviteMemberRequest(email=user.email, role="member"),
        None,  # type: ignore[arg-type]
        db_session,
        _auth_ctx(org.id),
    )

    assert response.user_id == user.id
    project_member = (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    assert project_member is not None
    # Ordinary members seed the default project at viewer (least privilege) under
    # the 3-tier org model; higher access is granted explicitly.
    assert project_member.role == "viewer"


@pytest.mark.asyncio
async def test_remove_member_cleans_project_memberships(db_session):
    org = await _org(db_session)
    target = AuthUser(name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add_all([target, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=target.id, organization_id=org.id, role="member"),
            ProjectMember(project_id=project.id, user_id=target.id, role="editor"),
        ]
    )
    await db_session.commit()

    await remove_member(target.id, None, db_session, _auth_ctx(org.id))  # type: ignore[arg-type]

    assert (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id)
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_update_organization_member_missing_member_returns_structured_error(db_session):
    org = await _org(db_session)
    missing_user_id = f"user-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await update_member_role(
            missing_user_id,
            UpdateMemberRoleRequest(role="member"),
            None,  # type: ignore[arg-type]
            db_session,
            _auth_ctx(org.id),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "ORGANIZATION_MEMBER_NOT_FOUND",
        "message": "Member not found",
        "data": {"organization_id": org.id, "user_id": missing_user_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_project_missing_project_returns_structured_error(db_session):
    org_id = f"org-{uuid.uuid4()}"
    project_id = f"project-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await get_project(project_id, db_session, _auth_ctx(org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project not found",
        "data": {"project_id": project_id, "organization_id": org_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_revoke_api_key_missing_key_returns_structured_error(db_session):
    org_id = f"org-{uuid.uuid4()}"
    key_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        await revoke_api_key(key_id, None, db_session, _auth_ctx(org_id))  # type: ignore[arg-type]

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

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(user_id="target-user", role="super-admin"),
            SimpleNamespace(id="actor-user"),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ORGANIZATION_MEMBER_ROLE_INVALID",
        "message": "Invalid member role",
        "data": {"role": "super-admin", "allowed": ["admin", "member", "owner"]},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_transfer_ownership_to_self_returns_structured_error(db_session):
    org = await _org(db_session)
    owner = AuthUser(name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(Member(user_id=owner.id, organization_id=org.id, role="owner"))
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
        "data": {"organization_id": org.id, "user_id": owner.id},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_remove_owner_returns_structured_error(db_session):
    org = await _org(db_session)
    owner = AuthUser(name="Owner User", email=f"owner-{uuid.uuid4()}@example.com")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(Member(user_id=owner.id, organization_id=org.id, role="owner"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_member(owner.id, None, db_session, _auth_ctx(org.id))  # type: ignore[arg-type]

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
async def test_archive_default_project_returns_structured_error(db_session):
    org = await _org(db_session)
    project = Project(org_id=org.id, name="Default", slug="default", is_default=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    with pytest.raises(AppError) as exc_info:
        await archive_project(project.id, db_session, _auth_ctx(org.id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
        "message": "Cannot archive the default project",
        "data": {"project_id": project.id, "organization_id": org.id},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_organization_blank_name_returns_structured_error(db_session):
    with pytest.raises(AppError) as exc_info:
        await create_organization(CreateOrganizationRequest(name=" "), db_session, _auth_ctx("org-1"))

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
    actor = AuthUser(name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(user_id=actor.id, organization_id=org.id, role="member"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(user_id="target-user", role="member"),
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "ORGANIZATION_PERMISSION_DENIED",
        "message": "Insufficient permission",
        "data": {"organization_id": org.id},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_admin_cannot_assign_owner_role_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = AuthUser(name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(user_id=actor.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(user_id="target-user", role="owner"),
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "ORGANIZATION_OWNER_ROLE_ASSIGN_FORBIDDEN",
        "message": "Only organization owners can assign owner role",
        "data": {"actor_role": "admin", "target_role": "owner"},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_switch_context_requires_target_org_membership(db_session):
    target_org_id = f"org-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await switch_context(SwitchContextRequest(org_id=target_org_id), db_session, _auth_ctx("current-org"))

    assert await handled_app_error_payload(exc_info.value, status_code=403) == {
        "code": "AUTH_ORGANIZATION_MEMBERSHIP_REQUIRED",
        "message": "User is not a member of the target organization",
        "data": {"organization_id": target_org_id},
        "source": "auth",
        "retryable": False,
        "user_action": "request_access",
    }


@pytest.mark.asyncio
async def test_switch_context_uses_active_project_when_default_is_archived(db_session):
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id="admin-user", name="Admin User", email=f"admin-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Switch Org", slug=f"switch-org-{uuid.uuid4()}")
    db_session.add_all([user, org])
    await db_session.flush()
    db_session.add(Member(user_id="admin-user", organization_id=org_id, role="admin"))
    archived_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Archived Default",
        slug=f"archived-default-{uuid.uuid4()}",
        is_default=True,
        archived_at=utc_now(),
    )
    active_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Active",
        slug=f"active-{uuid.uuid4()}",
    )
    db_session.add_all([archived_default, active_project])
    await db_session.commit()

    response = await switch_context(SwitchContextRequest(org_id=org_id), db_session, _auth_ctx("current-org"))

    assert response["project_id"] == active_project.id
    assert response["project"]["id"] == active_project.id
    assert response["projects"] == [
        {
            "id": active_project.id,
            "org_id": org_id,
            "name": active_project.name,
            "slug": active_project.slug,
            "is_default": active_project.is_default,
            "archived_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_switch_context_rejects_inaccessible_project_for_non_admin_member(db_session):
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id="admin-user", name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project ACL Org", slug=f"project-acl-org-{uuid.uuid4()}")
    allowed_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(project_id=allowed_project.id, user_id=user.id, role="editor"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await switch_context(
            SwitchContextRequest(org_id=org_id, project_id=blocked_project.id),
            db_session,
            _auth_ctx("current-org"),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project not found in the target organization",
        "data": {"project_id": blocked_project.id, "organization_id": org_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_get_me_lists_only_accessible_projects_for_non_admin_member(db_session):
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id="admin-user", name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project List ACL Org", slug=f"project-list-acl-org-{uuid.uuid4()}")
    allowed_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(project_id=allowed_project.id, user_id=user.id, role="editor"),
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

    assert response["project"]["id"] == allowed_project.id
    assert {project["id"] for project in response["projects"]} == {allowed_project.id}
    assert blocked_project.id not in {project["id"] for project in response["projects"]}


@pytest.mark.asyncio
async def test_list_projects_filters_to_accessible_projects_for_non_admin_member(db_session):
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id="admin-user", name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project List Route ACL Org", slug=f"project-list-route-{uuid.uuid4()}")
    allowed_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(project_id=allowed_project.id, user_id=user.id, role="editor"),
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


@pytest.mark.asyncio
async def test_get_project_rejects_inaccessible_project_for_non_admin_member(db_session):
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id="admin-user", name="Developer User", email=f"developer-{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Project Detail ACL Org", slug=f"project-detail-acl-{uuid.uuid4()}")
    allowed_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Allowed",
        slug=f"allowed-{uuid.uuid4()}",
        is_default=True,
    )
    blocked_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org_id,
        name="Blocked",
        slug=f"blocked-{uuid.uuid4()}",
    )
    db_session.add_all([user, org, allowed_project, blocked_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=org_id, role="member"),
            ProjectMember(project_id=allowed_project.id, user_id=user.id, role="editor"),
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
        "data": {"project_id": blocked_project.id, "organization_id": org_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
