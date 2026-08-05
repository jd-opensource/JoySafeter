import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService


@pytest.mark.asyncio
async def test_auto_org_bootstrap_grants_owner_project_member(db_session):
    # A user with no membership triggers auto-org bootstrap during JWT issuance.
    # That path must grant an explicit ProjectMember row on the default project,
    # consistent with every other bootstrap path (so the owner is not reliant on
    # the org-wide bypass alone).
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.commit()

    await AuthService(db_session)._issue_jwt_tokens(user.id)
    await db_session.commit()

    membership = (await db_session.execute(select(Member).where(Member.user_id == user.id))).scalar_one_or_none()
    assert membership is not None and membership.role == "owner"

    default_project = (
        await db_session.execute(
            select(Project).where(Project.org_id == membership.organization_id, Project.is_default.is_(True))
        )
    ).scalar_one_or_none()
    assert default_project is not None

    project_member = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.user_id == user.id,
                ProjectMember.project_id == default_project.id,
            )
        )
    ).scalar_one_or_none()
    assert project_member is not None
    assert project_member.role == "admin"
