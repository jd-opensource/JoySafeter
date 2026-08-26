"""list_skills / list_by_user must mirror check_skill_access for org super-users.

Single-axis skill redesign: an org owner/admin is ADMIN on every skill in their
active org (``effective_project_capability``), so ``check_skill_access`` lets
them GET/edit any skill in the org — even in projects they hold no
``ProjectMember`` row for. The listing endpoint must surface those same skills,
otherwise "what a user can GET" diverges from "what they can list". These tests
pin that invariant (and its org-isolation + non-super-user boundaries).
"""

from __future__ import annotations

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.ids import OrganizationId, OrganizationMemberId, ProjectId, SkillId, UserId

pytestmark = pytest.mark.asyncio


async def _user(db, *, name: str = "U") -> AuthUser:
    user = AuthUser(id=UserId.new(), name=name, email=f"{uuid.uuid4()}@example.com")
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    org = Organization(id=OrganizationId.new(), name="Org", slug=f"org-{uuid.uuid4()}")
    db.add(org)
    await db.flush()
    return org


async def _project(db, *, org_id: OrganizationId) -> Project:
    proj = Project(id=ProjectId.new(), org_id=org_id, name="P", slug=f"p-{uuid.uuid4()}")
    db.add(proj)
    await db.flush()
    return proj


async def _org_member(db, *, org_id: OrganizationId, user_id: UserId, role: str) -> None:
    db.add(Member(id=OrganizationMemberId.new(), organization_id=org_id, user_id=user_id, role=role))
    await db.flush()


async def _skill(db, *, owner_id: UserId, project_id: ProjectId, visibility: str = "project") -> JoySafeterSkill:
    skill = JoySafeterSkill(
        id=SkillId.new(),
        name=f"skill-{uuid.uuid4()}",
        description="test",
        content="# Skill\nbody",
        tags=[],
        created_by_id=owner_id,
        owner_id=owner_id,
        project_id=project_id,
        visibility=visibility,
        lifecycle_status="approved",
        security_status="passed",
    )
    db.add(skill)
    await db.flush()
    return skill


async def test_org_owner_lists_project_skill_without_project_membership(db_session):
    """RED before fix: the org OWNER is not a ProjectMember of the project, so the
    project-tier skill is invisible to the listing even though the owner can GET
    and edit it. It must appear."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    # owner is an ORG owner but has NO ProjectMember row on proj
    await _org_member(db_session, org_id=org.id, user_id=owner.id, role="owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    skill_id = skill.id
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    skills, _ = await svc.list_skills(current_user_id=owner.id, limit=50)
    assert skill_id in {s.id for s in skills}


async def test_org_admin_lists_project_skill_without_project_membership(db_session):
    """Same invariant for an org ADMIN (also an org super-user)."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    admin = await _user(db_session, name="Admin")
    await _org_member(db_session, org_id=org.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    skill_id = skill.id
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org.id, caller_org_role=JoySafeterRole.ADMIN)
    skills, _ = await svc.list_skills(current_user_id=admin.id, limit=50)
    assert skill_id in {s.id for s in skills}


async def test_plain_org_member_does_not_list_foreign_project_skill(db_session):
    """The super-user clause must NOT leak to a plain org MEMBER: a member who is
    not on the project sees no project-tier skill from it. Guards against the fix
    over-broadening the listing."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    member = await _user(db_session, name="Member")
    await _org_member(db_session, org_id=org.id, user_id=member.id, role="member")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    skill_id = skill.id
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    skills, _ = await svc.list_skills(current_user_id=member.id, limit=50)
    assert skill_id not in {s.id for s in skills}


async def test_org_owner_does_not_list_other_org_project_skill(db_session):
    """The super-user clause is org-isolated: an owner of org A must not see a
    project-tier skill living in org B (owner-of-two-orgs context switch)."""
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    proj_b = await _project(db_session, org_id=org_b.id)
    author = await _user(db_session, name="AuthorB")
    owner = await _user(db_session, name="OwnerA")
    # owner is an owner in BOTH orgs, but is currently active in org A
    await _org_member(db_session, org_id=org_a.id, user_id=owner.id, role="owner")
    await _org_member(db_session, org_id=org_b.id, user_id=owner.id, role="owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj_b.id, visibility="project")
    skill_id = skill.id
    await db_session.commit()

    svc = SkillService(db_session, active_org_id=org_a.id, caller_org_role=JoySafeterRole.OWNER)
    skills, _ = await svc.list_skills(current_user_id=owner.id, limit=50)
    assert skill_id not in {s.id for s in skills}
