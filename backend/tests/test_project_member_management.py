import uuid

import pytest
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import (
    AddProjectMemberRequest,
    add_project_member,
    list_project_members,
    remove_project_member,
)
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _admin_ctx(org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id="",  # not used by these routes
        role=JoySafeterRole.ADMIN,
    )


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


async def _add_member(db_session, *, org_id: str, role: str, name: str) -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name=name, email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Member(user_id=user.id, organization_id=org_id, role=role))
    return user


@pytest.mark.asyncio
async def test_add_project_member_grants_access_to_org_member(db_session):
    org, default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    developer = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    await db_session.commit()

    response = await add_project_member(
        non_default.id,
        AddProjectMemberRequest(user_id=developer.id),
        None,  # type: ignore[arg-type]
        db_session,
        _admin_ctx(org.id),
    )

    assert response.user_id == developer.id
    assert response.access == "explicit"

    row = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == non_default.id,
                ProjectMember.user_id == developer.id,
            )
        )
    ).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_list_project_members_annotates_access_status(db_session):
    org, default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    admin = await _add_member(db_session, org_id=org.id, role="admin", name="Admin")
    granted_dev = await _add_member(db_session, org_id=org.id, role="member", name="GrantedDev")
    ungranted_dev = await _add_member(db_session, org_id=org.id, role="member", name="UngrantedViewer")
    db_session.add(ProjectMember(project_id=non_default.id, user_id=granted_dev.id, role="editor"))
    await db_session.commit()

    response = await list_project_members(
        non_default.id, q="", limit=50, after_id=None, db=db_session, auth_ctx=_admin_ctx(org.id)
    )

    access_by_user = {m.user_id: m.access for m in response.data}
    assert access_by_user[admin.id] == "org_wide"
    assert access_by_user[granted_dev.id] == "explicit"
    assert access_by_user[ungranted_dev.id] == "none"


@pytest.mark.asyncio
async def test_add_project_member_rejects_non_org_member(db_session):
    org, default_project = await _org_with_default_project(db_session)
    outsider = AuthUser(id=f"user-{uuid.uuid4()}", name="Outsider", email=f"{uuid.uuid4()}@example.com")
    db_session.add(outsider)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_project_member(
            default_project.id,
            AddProjectMemberRequest(user_id=outsider.id),
            None,  # type: ignore[arg-type]
            db_session,
            _admin_ctx(org.id),
        )
    assert exc_info.value.code == "ORGANIZATION_MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_project_member_routes_reject_project_from_other_org(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    other_org = Organization(id=f"org-{uuid.uuid4()}", name="Other", slug=f"other-{uuid.uuid4()}")
    other_project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=other_org.id,
        name="Foreign",
        slug=f"foreign-{uuid.uuid4()}",
    )
    db_session.add_all([other_org, other_project])
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_project_member(
            other_project.id,
            AddProjectMemberRequest(user_id=dev.id),
            None,  # type: ignore[arg-type]
            db_session,
            _admin_ctx(org.id),
        )
    assert exc_info.value.code == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_remove_project_member_revokes_explicit_access(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    db_session.add(ProjectMember(project_id=non_default.id, user_id=dev.id, role="editor"))
    await db_session.commit()

    await remove_project_member(
        non_default.id,
        dev.id,
        None,  # type: ignore[arg-type]
        db_session,
        _admin_ctx(org.id),
    )

    row = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == non_default.id,
                ProjectMember.user_id == dev.id,
            )
        )
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_remove_project_member_forbidden_on_default_project(db_session):
    org, default_project = await _org_with_default_project(db_session)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    db_session.add(ProjectMember(project_id=default_project.id, user_id=dev.id, role="editor"))
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_project_member(
            default_project.id,
            dev.id,
            None,  # type: ignore[arg-type]
            db_session,
            _admin_ctx(org.id),
        )
    assert exc_info.value.code == "PROJECT_MEMBER_DEFAULT_REMOVE_FORBIDDEN"


@pytest.mark.asyncio
async def test_remove_project_member_missing_row_returns_not_found(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_project_member(
            non_default.id,
            dev.id,
            None,  # type: ignore[arg-type]
            db_session,
            _admin_ctx(org.id),
        )
    assert exc_info.value.code == "PROJECT_MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_project_member_role_returns_role_or_none(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    other = await _add_member(db_session, org_id=org.id, role="member", name="Other")
    db_session.add(ProjectMember(project_id=non_default.id, user_id=dev.id, role="editor"))
    await db_session.commit()

    svc = ProjectService(db_session)
    assert await svc.get_project_member_role(non_default.id, dev.id) == "editor"
    assert await svc.get_project_member_role(non_default.id, other.id) is None
