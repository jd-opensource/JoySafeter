import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService


async def _org_project_user(db_session):
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="P", slug="default", is_default=True)
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com")
    db_session.add_all([org, project, user])
    await db_session.flush()
    return org, project, user


@pytest.mark.asyncio
async def test_concurrent_grant_converges_instead_of_erroring(db_session, monkeypatch):
    # CB-2 regression: two concurrent grants for the same (project, user) both
    # find no existing row and both insert; the second trips the unique
    # constraint. grant_project_membership is an idempotent upsert, so it must
    # converge on the winning row and apply the requested role, not surface a 500.
    org, project, user = await _org_project_user(db_session)
    # The row a concurrent request already committed.
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="viewer"))
    await db_session.commit()

    svc = ProjectService(db_session)
    real_load = svc._load_project_member
    calls = {"n": 0}

    async def _miss_first(project_id: str, user_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # racing existence check does not see the committed row
        return await real_load(project_id, user_id)

    monkeypatch.setattr(svc, "_load_project_member", _miss_first)

    membership = await svc.grant_project_membership(project_id=project.id, user_id=user.id, role="editor", commit=True)
    assert membership.role == "editor"  # converged on the winner + applied role
    assert calls["n"] >= 2  # recovery re-fetched the winning row


@pytest.mark.asyncio
async def test_grant_updates_role_when_row_exists(db_session):
    # Non-race happy path stays intact: an existing row's role is updated.
    org, project, user = await _org_project_user(db_session)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="viewer"))
    await db_session.commit()

    membership = await ProjectService(db_session).grant_project_membership(
        project_id=project.id, user_id=user.id, role="admin", commit=True
    )
    assert membership.role == "admin"
