import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService
from app.joysafeter_shared.security import decode_token


@pytest.mark.asyncio
async def test_auto_org_bootstrap_uses_owner_org_wide_project_access(db_session):
    # A user with no membership triggers auto-org bootstrap during JWT issuance.
    # Owners inherit Project Admin across the organization, so bootstrap must not
    # create a redundant project-specific grant that could survive a later demotion.
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()

    await AuthService(db_session)._issue_jwt_tokens(user.id)
    await db_session.commit()

    membership = (await db_session.execute(select(Member).where(Member.user_id == user.id))).scalar_one_or_none()
    assert membership is not None and membership.role == "owner"

    organization = (
        await db_session.execute(select(Organization).where(Organization.id == membership.organization_id))
    ).scalar_one()
    assert organization.name == user.name
    assert organization.slug.startswith("u-")
    assert organization.slug != "default"

    default_project = (
        await db_session.execute(
            select(Project).where(Project.org_id == membership.organization_id, Project.is_default.is_(True))
        )
    ).scalar_one_or_none()
    assert default_project is not None
    assert default_project.name == "Main"
    assert default_project.slug == "main"
    assert default_project.created_by_user_id == user.id

    project_member = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.user_id == user.id,
                ProjectMember.project_id == default_project.id,
            )
        )
    ).scalar_one_or_none()
    assert project_member is None


@pytest.mark.asyncio
async def test_login_context_prefers_owned_organization_over_shared_membership(db_session):
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="Context Owner", email=f"{uuid.uuid4()}@example.com")
    shared_org = Organization(id=f"org-{uuid.uuid4()}", name="Shared", slug=f"shared-{uuid.uuid4()}")
    owned_org = Organization(id=f"org-{uuid.uuid4()}", name="Owned", slug=f"owned-{uuid.uuid4()}")
    shared_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=shared_org.id,
        name="Main",
        slug="main",
        is_default=True,
    )
    owned_project = Project(
        id=f"project-{uuid.uuid4()}",
        org_id=owned_org.id,
        name="Main",
        slug="main",
        is_default=True,
    )
    db_session.add_all([user, shared_org, owned_org, shared_project, owned_project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=shared_org.id, role="member"),
            Member(user_id=user.id, organization_id=owned_org.id, role="owner"),
        ]
    )
    await db_session.commit()

    access_token, *_ = await AuthService(db_session)._issue_jwt_tokens(user.id)
    payload = decode_token(access_token)

    assert payload is not None
    assert payload.org_id == owned_org.id
    assert payload.project_id == owned_project.id
