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
from app.joysafeter_shared.ids import (
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    UserId,
)


def _admin_ctx(org_id: OrganizationId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=UserId.new(),
        org_id=org_id,
        project_id=None,
        role=JoySafeterRole.ADMIN,
    )


def _project_admin_ctx(*, user_id: UserId, org_id: OrganizationId, project_id: ProjectId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


async def _org_with_default_project(db_session) -> tuple[Organization, Project]:
    org = Organization(id=OrganizationId.new(), name="Org", slug=f"org-{uuid.uuid4()}")
    default_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add_all([org, default_project])
    await db_session.flush()
    return org, default_project


async def _add_member(db_session, *, org_id: OrganizationId, role: str, name: str) -> AuthUser:
    user = AuthUser(id=UserId.new(), name=name, email=f"{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Member(id=OrganizationMemberId.new(), user_id=user.id, organization_id=org_id, role=role))
    return user


@pytest.mark.asyncio
async def test_add_project_member_grants_access_to_org_member(db_session):
    org, default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=ProjectId.new(),
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
        id=ProjectId.new(),
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    admin = await _add_member(db_session, org_id=org.id, role="admin", name="Admin")
    granted_dev = await _add_member(db_session, org_id=org.id, role="member", name="GrantedDev")
    ungranted_dev = await _add_member(db_session, org_id=org.id, role="member", name="UngrantedViewer")
    db_session.add(
        ProjectMember(id=ProjectMemberId.new(), project_id=non_default.id, user_id=granted_dev.id, role="editor")
    )
    await db_session.commit()

    response = await list_project_members(
        non_default.id, q="", limit=50, after_id=None, db=db_session, auth_ctx=_admin_ctx(org.id)
    )

    access_by_user = {m.user_id: m.access for m in response.data}
    assert access_by_user[admin.id] == "org_wide"
    assert access_by_user[granted_dev.id] == "explicit"
    assert access_by_user[ungranted_dev.id] == "none"


@pytest.mark.asyncio
async def test_default_project_is_implicitly_accessible_to_ordinary_org_member(db_session):
    org, default_project = await _org_with_default_project(db_session)
    member = await _add_member(db_session, org_id=org.id, role="member", name="Default Viewer")
    await db_session.commit()

    projects = await ProjectService(db_session).list_accessible_projects(
        org_id=org.id,
        user_id=member.id,
        org_role="member",
    )

    assert [project.id for project in projects] == [default_project.id]
    assert await ProjectService(db_session).get_project_member_role(default_project.id, member.id) is None
    assert (
        await ProjectService(db_session).user_has_project_access(
            project_id=default_project.id,
            user_id=member.id,
            org_role="member",
        )
        is True
    )


@pytest.mark.asyncio
async def test_switching_default_moves_implicit_member_access_without_membership_rows(db_session):
    org, old_default = await _org_with_default_project(db_session)
    new_default = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="New Default",
        slug=f"new-default-{uuid.uuid4()}",
    )
    db_session.add(new_default)
    member = await _add_member(db_session, org_id=org.id, role="member", name="Default Viewer")
    await db_session.commit()

    await ProjectService(db_session).set_default_project(new_default.id, org.id)
    projects = await ProjectService(db_session).list_accessible_projects(
        org_id=org.id,
        user_id=member.id,
        org_role="member",
    )

    assert [project.id for project in projects] == [new_default.id]
    assert await ProjectService(db_session).get_project_member_role(old_default.id, member.id) is None
    assert await ProjectService(db_session).get_project_member_role(new_default.id, member.id) is None
    assert (
        await ProjectService(db_session).user_has_project_access(
            project_id=old_default.id,
            user_id=member.id,
            org_role="member",
        )
        is False
    )
    assert (
        await ProjectService(db_session).user_has_project_access(
            project_id=new_default.id,
            user_id=member.id,
            org_role="member",
        )
        is True
    )


@pytest.mark.asyncio
async def test_add_project_member_rejects_non_org_member(db_session):
    org, default_project = await _org_with_default_project(db_session)
    outsider = AuthUser(id=UserId.new(), name="Outsider", email=f"{uuid.uuid4()}@example.com")
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
    other_org = Organization(id=OrganizationId.new(), name="Other", slug=f"other-{uuid.uuid4()}")
    other_project = Project(
        id=ProjectId.new(),
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
async def test_project_admin_cannot_list_access_for_another_project(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    managed_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Managed",
        slug=f"managed-{uuid.uuid4()}",
    )
    other_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Other",
        slug=f"other-{uuid.uuid4()}",
    )
    db_session.add_all([managed_project, other_project])
    actor = await _add_member(db_session, org_id=org.id, role="member", name="ProjectAdmin")
    db_session.add(
        ProjectMember(id=ProjectMemberId.new(), project_id=managed_project.id, user_id=actor.id, role="admin")
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await list_project_members(
            other_project.id,
            q="",
            limit=50,
            after_id=None,
            db=db_session,
            auth_ctx=_project_admin_ctx(user_id=actor.id, org_id=org.id, project_id=managed_project.id),
        )

    assert exc_info.value.code == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_project_admin_cannot_grant_access_for_another_project(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    managed_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Managed",
        slug=f"managed-{uuid.uuid4()}",
    )
    other_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Other",
        slug=f"other-{uuid.uuid4()}",
    )
    db_session.add_all([managed_project, other_project])
    actor = await _add_member(db_session, org_id=org.id, role="member", name="ProjectAdmin")
    target = await _add_member(db_session, org_id=org.id, role="member", name="Target")
    db_session.add(
        ProjectMember(id=ProjectMemberId.new(), project_id=managed_project.id, user_id=actor.id, role="admin")
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await add_project_member(
            other_project.id,
            AddProjectMemberRequest(user_id=target.id),
            None,  # type: ignore[arg-type]
            db_session,
            _project_admin_ctx(user_id=actor.id, org_id=org.id, project_id=managed_project.id),
        )

    assert exc_info.value.code == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_project_admin_cannot_revoke_access_for_another_project(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    managed_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Managed",
        slug=f"managed-{uuid.uuid4()}",
    )
    other_project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Other",
        slug=f"other-{uuid.uuid4()}",
    )
    db_session.add_all([managed_project, other_project])
    actor = await _add_member(db_session, org_id=org.id, role="member", name="ProjectAdmin")
    target = await _add_member(db_session, org_id=org.id, role="member", name="Target")
    db_session.add_all(
        [
            ProjectMember(id=ProjectMemberId.new(), project_id=managed_project.id, user_id=actor.id, role="admin"),
            ProjectMember(id=ProjectMemberId.new(), project_id=other_project.id, user_id=target.id, role="viewer"),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await remove_project_member(
            other_project.id,
            target.id,
            None,  # type: ignore[arg-type]
            db_session,
            _project_admin_ctx(user_id=actor.id, org_id=org.id, project_id=managed_project.id),
        )

    assert exc_info.value.code == "JOYSAFETER_PROJECT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_remove_project_member_revokes_explicit_access(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    db_session.add(ProjectMember(id=ProjectMemberId.new(), project_id=non_default.id, user_id=dev.id, role="editor"))
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
async def test_remove_explicit_default_project_role_falls_back_to_implicit_viewer(db_session):
    org, default_project = await _org_with_default_project(db_session)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    db_session.add(
        ProjectMember(id=ProjectMemberId.new(), project_id=default_project.id, user_id=dev.id, role="editor")
    )
    await db_session.commit()

    await remove_project_member(
        default_project.id,
        dev.id,
        None,  # type: ignore[arg-type]
        db_session,
        _admin_ctx(org.id),
    )

    assert await ProjectService(db_session).get_project_member_role(default_project.id, dev.id) is None
    projects = await ProjectService(db_session).list_accessible_projects(
        org_id=org.id,
        user_id=dev.id,
        org_role="member",
    )
    assert [project.id for project in projects] == [default_project.id]


@pytest.mark.asyncio
async def test_remove_project_member_missing_row_returns_not_found(db_session):
    org, _default_project = await _org_with_default_project(db_session)
    non_default = Project(
        id=ProjectId.new(),
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
        id=ProjectId.new(),
        org_id=org.id,
        name="Second",
        slug=f"second-{uuid.uuid4()}",
    )
    db_session.add(non_default)
    dev = await _add_member(db_session, org_id=org.id, role="member", name="Dev")
    other = await _add_member(db_session, org_id=org.id, role="member", name="Other")
    db_session.add(ProjectMember(id=ProjectMemberId.new(), project_id=non_default.id, user_id=dev.id, role="editor"))
    await db_session.commit()

    svc = ProjectService(db_session)
    assert await svc.get_project_member_role(non_default.id, dev.id) == "editor"
    assert await svc.get_project_member_role(non_default.id, other.id) is None
