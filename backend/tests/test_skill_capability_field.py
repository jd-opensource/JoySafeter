"""Contract tests for the caller-capability field on the skill detail route (S3).

The GET /skills/{id} response now carries ``capability`` — the caller's
effective tier on that skill (owner/admin/editor/viewer). The frontend gates
its manage/edit affordances on this, so the value has to track the same
precedence the write/read gates enforce: owner and org super-user resolve to
full control, the per-skill collaborator ACL next, then a bare visibility-tier
viewer grant.
"""

import uuid

import pytest

from app.joysafeter_api.api.v1.skills import AddSkillCollaboratorRequest, add_skill_collaborator, get_skill
from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
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


async def _member(db, *, org_id, user_id, role="member") -> Member:
    m = Member(user_id=user_id, organization_id=org_id, role=role)
    db.add(m)
    await db.flush()
    return m


async def _skill(db, *, project_id, owner_id, visibility="private") -> JoySafeterSkill:
    skill = JoySafeterSkill(
        name=f"skill-{uuid.uuid4()}",
        description="test skill",
        content="# Skill",
        tags=[],
        created_by_id=owner_id,
        owner_id=owner_id,
        project_id=project_id,
        visibility=visibility,
    )
    db.add(skill)
    await db.flush()
    return skill


def _ctx(*, user_id, org, project, role=JoySafeterRole.MEMBER):
    return JoySafeterAuthContext(user_id=user_id, org_id=org.id, project_id=project.id, role=role)


async def _get(db, skill_id, ctx):
    return await get_skill(skill_id=skill_id, db=db, auth_ctx=ctx)


async def _grant(db, skill_id, owner_ctx, *, user_id, role):
    return await add_skill_collaborator(
        AddSkillCollaboratorRequest(user_id=user_id, role=role), None, skill_id=skill_id, db=db, auth_ctx=owner_ctx
    )


@pytest.mark.asyncio
async def test_owner_sees_owner_capability(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    await db_session.commit()

    resp = await _get(db_session, skill.id, _ctx(user_id=owner.id, org=org, project=project))
    assert resp.capability == "owner"


@pytest.mark.asyncio
async def test_collaborator_tiers_map_through(db_session):
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id)
    owner_ctx = _ctx(user_id=owner.id, org=org, project=project)

    for role in ("admin", "editor", "viewer"):
        collab = await _user(db_session, role)
        await _member(db_session, org_id=org.id, user_id=collab.id)
        await db_session.commit()
        await _grant(db_session, skill.id, owner_ctx, user_id=collab.id, role=role)
        resp = await _get(db_session, skill.id, _ctx(user_id=collab.id, org=org, project=project))
        assert resp.capability == role


@pytest.mark.asyncio
async def test_org_superuser_sees_admin_capability(db_session):
    # Organization-visibility skill: the org admin can read it (org-member
    # viewer tier), and because they super-user the skill's own org the
    # capability resolves to the full admin tier, not a bare viewer.
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    admin = await _user(db_session, "OrgAdmin")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id, visibility="organization")
    await db_session.commit()

    resp = await _get(db_session, skill.id, _ctx(user_id=admin.id, org=org, project=project, role=JoySafeterRole.ADMIN))
    assert resp.capability == "admin"


@pytest.mark.asyncio
async def test_project_visibility_member_sees_viewer(db_session):
    # A project-visibility skill: a project member who is neither owner nor
    # collaborator can read it, and reads at exactly the viewer tier.
    org, project = await _org_with_project(db_session)
    owner = await _user(db_session, "Owner")
    reader = await _user(db_session, "Reader")
    await _member(db_session, org_id=org.id, user_id=owner.id)
    await _member(db_session, org_id=org.id, user_id=reader.id)
    db_session.add(ProjectMember(project_id=project.id, user_id=reader.id, role="viewer"))
    skill = await _skill(db_session, project_id=project.id, owner_id=owner.id, visibility="project")
    await db_session.commit()

    resp = await _get(db_session, skill.id, _ctx(user_id=reader.id, org=org, project=project))
    assert resp.capability == "viewer"
