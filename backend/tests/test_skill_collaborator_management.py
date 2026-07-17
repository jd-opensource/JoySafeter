"""Contract/demo tests for the skill-collaborator management routes (S2).

Exercises the real route handlers end-to-end: grant/list/revoke, the admin
gate across capability tiers, owner-forbidden, non-member rejection, role
validation, 404 semantics, org isolation, and the org super-user path.
"""

import uuid

import pytest

from app.joysafeter_api.api.v1.skills import (
    AddSkillCollaboratorRequest,
    add_skill_collaborator,
    list_skill_collaborators,
    remove_skill_collaborator,
)
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_shared.common.app_errors import AccessDeniedError, AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


async def _user(db, name="U") -> AuthUser:
    user = AuthUser(id=f"user-{uuid.uuid4()}", name=name, email=f"{uuid.uuid4()}@example.com")
    db.add(user)
    await db.flush()
    return user


async def _org_with_project(db) -> tuple[Organization, Project]:
    org = Organization(id=f"org-{uuid.uuid4()}", name="Org", slug=f"org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org.id, name="P", slug=f"p-{uuid.uuid4()}", is_default=True)
    db.add_all([org, project])
    await db.flush()
    return org, project


async def _member(db, *, org_id: str, user_id: str, role: str = "member") -> Member:
    m = Member(user_id=user_id, organization_id=org_id, role=role)
    db.add(m)
    await db.flush()
    return m


async def _skill(db, *, project_id: str, owner_id: str) -> JoySafeterSkill:
    skill = JoySafeterSkill(
        name=f"skill-{uuid.uuid4()}",
        description="test skill",
        content="# Skill",
        tags=[],
        created_by_id=owner_id,
        owner_id=owner_id,
        project_id=project_id,
    )
    db.add(skill)
    await db.flush()
    return skill


def _ctx(*, user_id: str, org: Organization, project: Project, role: JoySafeterRole = JoySafeterRole.MEMBER):
    return JoySafeterAuthContext(user_id=user_id, org_id=org.id, project_id=project.id, role=role)


async def _list(db, skill_id, ctx):
    return await list_skill_collaborators(skill_id=skill_id, db=db, auth_ctx=ctx)


async def _add(db, skill_id, ctx, *, user_id, role="editor"):
    return await add_skill_collaborator(
        AddSkillCollaboratorRequest(user_id=user_id, role=role), None, skill_id=skill_id, db=db, auth_ctx=ctx
    )


async def _remove(db, skill_id, ctx, *, user_id):
    return await remove_skill_collaborator(user_id=user_id, request=None, skill_id=skill_id, db=db, auth_ctx=ctx)


@pytest.mark.asyncio
async def test_owner_grants_lists_and_revokes(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    collab = await _user(db_session, "Collab")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=collab.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    resp = await _add(db_session, skill.id, owner_ctx, user_id=collab.id, role="editor")
    assert resp.user_id == collab.id and resp.role == "editor"

    listed = await _list(db_session, skill.id, owner_ctx)
    assert [(r.user_id, r.role) for r in listed] == [(collab.id, "editor")]

    await _remove(db_session, skill.id, owner_ctx, user_id=collab.id)
    assert await _list(db_session, skill.id, owner_ctx) == []


@pytest.mark.asyncio
async def test_editor_collaborator_cannot_manage_but_admin_can(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    b = await _user(db_session, "B")
    c = await _user(db_session, "C")
    for u in (owner, b, c):
        await _member(db_session, org_id=org.id, user_id=u.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    # B as an editor collaborator cannot manage collaborators.
    await _add(db_session, skill.id, owner_ctx, user_id=b.id, role="editor")
    b_ctx = _ctx(user_id=b.id, org=org, project=project)
    with pytest.raises(AccessDeniedError) as exc:
        await _add(db_session, skill.id, b_ctx, user_id=c.id, role="viewer")
    assert exc.value.code == "SKILL_ACCESS_DENIED"

    # Promote B to admin; now B can grant C.
    await _add(db_session, skill.id, owner_ctx, user_id=b.id, role="admin")
    resp = await _add(db_session, skill.id, b_ctx, user_id=c.id, role="viewer")
    assert resp.role == "viewer"
    assert len(await _list(db_session, skill.id, owner_ctx)) == 2


@pytest.mark.asyncio
async def test_grant_to_non_org_member_rejected(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    outsider = await _user(db_session, "Outsider")  # deliberately NOT an org member
    await _member(db_session, org_id=org.id, user_id=owner.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _add(db_session, skill.id, _ctx(user_id=owner.id, org=org, project=project), user_id=outsider.id)
    assert exc.value.code == "ORGANIZATION_MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_owner_cannot_be_added_or_removed_as_collaborator(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    with pytest.raises(AppError) as add_exc:
        await _add(db_session, skill.id, owner_ctx, user_id=owner.id, role="admin")
    assert add_exc.value.code == "SKILL_COLLABORATOR_OWNER_FORBIDDEN"

    with pytest.raises(AppError) as del_exc:
        await _remove(db_session, skill.id, owner_ctx, user_id=owner.id)
    assert del_exc.value.code == "SKILL_COLLABORATOR_OWNER_FORBIDDEN"


@pytest.mark.asyncio
async def test_invalid_role_rejected_and_publisher_folds_to_admin(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    collab = await _user(db_session, "Collab")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=collab.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    with pytest.raises(AppError) as exc:
        await _add(db_session, skill.id, owner_ctx, user_id=collab.id, role="wizard")
    assert exc.value.code == "SKILL_COLLABORATOR_ROLE_INVALID"

    resp = await _add(db_session, skill.id, owner_ctx, user_id=collab.id, role="publisher")
    assert resp.role == "admin"


@pytest.mark.asyncio
async def test_revoke_missing_collaborator_returns_404(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    collab = await _user(db_session, "Collab")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=collab.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    await _add(db_session, skill.id, owner_ctx, user_id=collab.id, role="editor")
    await _remove(db_session, skill.id, owner_ctx, user_id=collab.id)
    with pytest.raises(AppError) as exc:
        await _remove(db_session, skill.id, owner_ctx, user_id=collab.id)
    assert exc.value.code == "SKILL_COLLABORATOR_NOT_FOUND"


@pytest.mark.asyncio
async def test_org_superuser_can_manage_without_being_owner(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    admin = await _user(db_session, "OrgAdmin")
    collab = await _user(db_session, "Collab")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=admin.id, role="admin")
    await _member(db_session, org_id=org.id, user_id=collab.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()

    admin_ctx = _ctx(user_id=admin.id, org=org, project=project, role=JoySafeterRole.ADMIN)
    resp = await _add(db_session, skill.id, admin_ctx, user_id=collab.id, role="editor")
    assert resp.role == "editor"


@pytest.mark.asyncio
async def test_cross_org_admin_cannot_reach_skill(db_session):
    # Skill lives in org A; an admin acting in org B must get a 404, not manage it.
    org_a, project_a = await _org_with_project(db_session)
    org_b, project_b = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    b_admin = await _user(db_session, "BAdmin")
    await _member(db_session, org_id=org_a.id, user_id=owner.id)
    await _member(db_session, org_id=org_b.id, user_id=b_admin.id, role="admin")
    skill = await _skill(db_session, project_id=project_a.id, owner_id=owner.id)
    await db_session.commit()

    b_ctx = _ctx(user_id=b_admin.id, org=org_b, project=project_b, role=JoySafeterRole.ADMIN)
    with pytest.raises(AppError) as exc:
        await _list(db_session, skill.id, b_ctx)
    assert exc.value.code == "SKILL_NOT_FOUND"


@pytest.mark.asyncio
async def test_plain_member_cannot_list(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    bystander = await _user(db_session, "Bystander")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=bystander.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()

    with pytest.raises(AccessDeniedError) as exc:
        await _list(db_session, skill.id, _ctx(user_id=bystander.id, org=org, project=project))
    assert exc.value.code == "SKILL_ACCESS_DENIED"
