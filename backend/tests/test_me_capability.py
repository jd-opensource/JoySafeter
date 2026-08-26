import uuid

import pytest

from app.joysafeter_api.api.v1.auth import get_me
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import (
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    UserId,
)


async def _ctx(db_session, *, org_role: str, project_role: str | None) -> JoySafeterAuthContext:
    org_id = OrganizationId.new()
    user = AuthUser(id=UserId.new(), name="U", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=ProjectId.new(), org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([user, org, project])
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role=org_role))
    if project_role is not None:
        db_session.add(
            ProjectMember(id=ProjectMemberId.new(), project_id=project.id, user_id=user.id, role=project_role)
        )
    await db_session.commit()
    return JoySafeterAuthContext(
        user_id=user.id,
        org_id=org_id,
        project_id=project.id,
        role=JoySafeterRole.normalize(org_role),
        project_role=project_role,
    )


@pytest.mark.asyncio
async def test_me_reports_write_capability_for_project_editor(db_session):
    ctx = await _ctx(db_session, org_role="member", project_role="editor")
    me = await get_me(db_session, ctx)
    assert me.project.capability == "write"
    assert me.project.project_role == "editor"


@pytest.mark.asyncio
async def test_me_reports_admin_capability_for_org_admin_without_row(db_session):
    ctx = await _ctx(db_session, org_role="admin", project_role=None)
    me = await get_me(db_session, ctx)
    assert me.project.capability == "admin"


@pytest.mark.asyncio
async def test_me_reports_read_capability_for_project_viewer(db_session):
    ctx = await _ctx(db_session, org_role="member", project_role="viewer")
    me = await get_me(db_session, ctx)
    assert me.project.capability == "read"
