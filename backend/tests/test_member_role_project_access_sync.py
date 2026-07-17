import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_organization_member_service import OrganizationMemberService
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.joysafeter_auth.context import JoySafeterRole


async def _org_with_default_project(db_session) -> tuple[Organization, Project]:
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    default_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, default_project])
    await db_session.flush()
    return org, default_project


async def _member(db_session, *, org_id: str, role: str) -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Member(user_id=user.id, organization_id=org_id, role=role))
    return user


@pytest.mark.asyncio
async def test_demoting_admin_to_member_grants_default_project_access(db_session):
    org, default_project = await _org_with_default_project(db_session)
    # Admin org-wide members have no ProjectMember row; after demotion they would
    # otherwise be locked out of every project including the default one.
    target = await _member(db_session, org_id=org.id, role="admin")
    await db_session.commit()

    svc = OrganizationMemberService(db_session)
    await svc.update_member_role_by_user_id(
        organization_id=org.id,
        user_id=target.id,
        actor_role=JoySafeterRole.OWNER,
        role="member",
    )

    row = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == default_project.id,
                ProjectMember.user_id == target.id,
            )
        )
    ).scalar_one_or_none()
    assert row is not None

    accessible = await ProjectService(db_session).get_accessible_project(
        project_id=default_project.id,
        org_id=org.id,
        user_id=target.id,
        org_role=JoySafeterRole.MEMBER,
    )
    assert accessible is not None


@pytest.mark.asyncio
async def test_demotion_preserves_existing_non_default_project_grants(db_session):
    org, default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    target = await _member(db_session, org_id=org.id, role="admin")
    # An explicit grant on a non-default project that must survive the demotion.
    db_session.add(ProjectMember(project_id=non_default.id, user_id=target.id, role="editor"))
    await db_session.commit()

    await OrganizationMemberService(db_session).update_member_role_by_user_id(
        organization_id=org.id,
        user_id=target.id,
        actor_role=JoySafeterRole.OWNER,
        role="member",
    )

    surviving = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == non_default.id,
                ProjectMember.user_id == target.id,
            )
        )
    ).scalar_one_or_none()
    assert surviving is not None


@pytest.mark.asyncio
async def test_promotion_to_admin_grants_org_wide_access_without_row(db_session):
    org, default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    target = await _member(db_session, org_id=org.id, role="member")
    await db_session.commit()

    await OrganizationMemberService(db_session).update_member_role_by_user_id(
        organization_id=org.id,
        user_id=target.id,
        actor_role=JoySafeterRole.OWNER,
        role="admin",
    )

    # As an org-wide admin, the user reaches a project with no ProjectMember row.
    accessible = await ProjectService(db_session).get_accessible_project(
        project_id=non_default.id,
        org_id=org.id,
        user_id=target.id,
        org_role=JoySafeterRole.ADMIN,
    )
    assert accessible is not None

