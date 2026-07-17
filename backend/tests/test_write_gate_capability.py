import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.common.joysafeter_auth.dependencies import _require_write_context


async def _setup(db_session, project_role: str) -> JoySafeterAuthContext:
    org_id = f"org-{uuid.uuid4()}"
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="Dev", email=f"{uuid.uuid4()}@example.com")
    org = Organization(id=org_id, name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="P", slug="default", is_default=True)
    db_session.add_all([user, org, project])
    await db_session.flush()
    db_session.add_all(
        [
            Member(user_id=user.id, organization_id=org_id, role="developer"),
            ProjectMember(project_id=project.id, user_id=user.id, role=project_role),
        ]
    )
    await db_session.commit()
    return JoySafeterAuthContext(
        user_id=user.id, org_id=org_id, project_id=project.id, role=JoySafeterRole.DEVELOPER
    )


@pytest.mark.asyncio
async def test_write_gate_denies_project_viewer(db_session):
    ctx = await _setup(db_session, project_role="viewer")
    with pytest.raises(AccessDeniedError) as exc_info:
        await _require_write_context(db_session, ctx)
    assert exc_info.value.code == "JOYSAFETER_WRITE_REQUIRED"


@pytest.mark.asyncio
async def test_write_gate_allows_project_editor(db_session):
    ctx = await _setup(db_session, project_role="editor")
    verified = await _require_write_context(db_session, ctx)
    assert verified.project_role == "editor"
