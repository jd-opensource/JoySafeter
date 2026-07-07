import uuid
from types import SimpleNamespace

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.auth import (
    CreateOrganizationRequest,
    InviteMemberRequest,
    SwitchContextRequest,
    archive_project,
    create_organization,
    get_project,
    invite_member,
    revoke_api_key,
    switch_context,
)
from app.joysafeter_api.api.v1.organizations import (
    AddMemberRequest,
    TransferOwnershipRequest,
    UpdateMemberRequest,
    add_member,
    transfer_ownership,
    update_member_role,
)
from app.joysafeter_api.api.v1.organizations import (
    remove_member as remove_organization_member,
)
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


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
async def test_add_member_returns_structured_duplicate_member_error(db_session):
    org = await _org(db_session)
    actor = AuthUser(name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    target = AuthUser(name="Target User", email=f"target-{uuid.uuid4()}@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=actor.id, organization_id=org.id, role="admin"),
            Member(user_id=target.id, organization_id=org.id, role="developer"),
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
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="developer"))
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
async def test_update_organization_member_missing_member_returns_structured_error(db_session):
    org = await _org(db_session)
    actor = AuthUser(name="Actor User", email=f"actor-{uuid.uuid4()}@example.com")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(Member(user_id=actor.id, organization_id=org.id, role="admin"))
    await db_session.commit()
    missing_member_id = f"member-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await update_member_role(
            org.id,
            missing_member_id,
            UpdateMemberRequest(role="viewer"),
            SimpleNamespace(id=actor.id),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "ORGANIZATION_MEMBER_NOT_FOUND",
        "message": "Member not found",
        "data": {"organization_id": org.id, "member_id": missing_member_id},
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
        "data": {"role": "super-admin", "allowed": ["admin", "developer", "member", "owner", "viewer"]},
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
    member = Member(user_id=owner.id, organization_id=org.id, role="owner")
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)

    with pytest.raises(AppError) as exc_info:
        await remove_organization_member(org.id, member.id, SimpleNamespace(id=owner.id), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "ORGANIZATION_OWNER_REMOVE_FORBIDDEN",
        "message": "Cannot remove the owner",
        "data": {"organization_id": org.id, "member_id": member.id},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
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
    db_session.add(Member(user_id=actor.id, organization_id=org.id, role="viewer"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_member(
            org.id,
            AddMemberRequest(user_id="target-user", role="viewer"),
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
