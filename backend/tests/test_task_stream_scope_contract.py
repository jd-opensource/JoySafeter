import uuid

import pytest

from app.joysafeter_api.api.v1.tasks import _authorize_task_stream
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember


async def _org_project(db_session, *, is_default: bool = False) -> tuple[Organization, Project]:
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="P",
        slug="default" if is_default else f"project-{uuid.uuid4()}",
        is_default=is_default,
    )
    db_session.add_all([org, project])
    await db_session.flush()
    return org, project


async def _user(db_session, *, is_active: bool = True) -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name="U", email=f"{uuid.uuid4()}@example.com", is_active=is_active)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_org_member_without_project_row_is_denied(db_session):
    # CB-5 regression: a non-super-user who is an org member but has NO
    # ProjectMember row on the project must NOT be able to stream that project's
    # task output, exactly as the HTTP read path denies them.
    org, project = await _org_project(db_session)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection == (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")


@pytest.mark.asyncio
async def test_org_member_without_project_row_can_stream_default_project(db_session):
    org, project = await _org_project(db_session, is_default=True)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection is None


@pytest.mark.asyncio
async def test_project_member_is_authorized(db_session):
    org, project = await _org_project(db_session)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="viewer"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection is None


@pytest.mark.asyncio
async def test_org_superuser_without_row_is_authorized(db_session):
    # Org admin/owner reach every project in the org without a ProjectMember row,
    # consistent with the HTTP path's org-wide access.
    org, project = await _org_project(db_session)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection is None


@pytest.mark.asyncio
async def test_non_member_is_denied(db_session):
    org, project = await _org_project(db_session)
    user = await _user(db_session)  # no Member row at all
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection == (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")


@pytest.mark.asyncio
async def test_inactive_user_is_denied(db_session):
    org, project = await _org_project(db_session)
    user = await _user(db_session, is_active=False)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="admin"))
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=project.id)
    assert rejection == (4001, "TASK_STREAM_AUTH_REQUIRED")


@pytest.mark.asyncio
async def test_project_in_other_org_is_denied(db_session):
    # A task/project that belongs to a different org than the token claims must
    # not be reachable even for an org member of the claimed org.
    org, project = await _org_project(db_session)
    other_org, other_project = await _org_project(db_session)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="admin"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=other_project.id)
    assert rejection == (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")


@pytest.mark.asyncio
async def test_project_member_on_different_project_is_denied(db_session):
    # Cross-project isolation: a non-super-user with a ProjectMember row on
    # ANOTHER project in the same org must not stream the target project.
    org, target = await _org_project(db_session)
    other = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="Other", slug=f"other-{uuid.uuid4()}")
    db_session.add(other)
    user = await _user(db_session)
    db_session.add(Member(user_id=user.id, organization_id=org.id, role="member"))
    await db_session.flush()
    db_session.add(ProjectMember(project_id=other.id, user_id=user.id, role="editor"))
    await db_session.commit()

    rejection = await _authorize_task_stream(db_session, user_id=user.id, org_id=org.id, project_id=target.id)
    assert rejection == (4003, "TASK_STREAM_PROJECT_ACCESS_DENIED")
