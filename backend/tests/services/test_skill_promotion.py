"""DB-backed tests for the version-level tiered promotion flow.

Single-axis skill model. Skill = project resource. Promotion to
the ``organization`` / ``public`` visibility tiers is version-level and goes
through a four-eyes approval by the org OWNER:

  submit_promotion  — ADMIN capability on the skill; flips the version to ``pending_review`` and
                      records ``review_target_visibility``.
  approve_promotion — org OWNER/admin, approver != publisher;
                      sets skill.{org,public}_version_id + raises visibility.
  reject_promotion  — org OWNER; version -> ``rejected``, pointer untouched.
  takedown          — org OWNER; clears a tier pointer + recomputes visibility.
  rescans           — informational; never pull down a published version.

These run against the real ephemeral Postgres (see conftest) because the flow
spans the skill row, a version row, the tier pointers (nullable FKs) and the
visibility recompute — exercising them end-to-end is the point.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_organization import Member, Organization
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillVersion,
)
from app.joysafeter_domain.services.joysafeter_skill_service import (
    SkillPromotionService,
    SkillVersionService,
)
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterRole
from app.joysafeter_shared.ids import (
    OrganizationId,
    OrganizationMemberId,
    ProjectId,
    ProjectMemberId,
    SkillId,
    SkillSecurityScanId,
    SkillVersionId,
    UserId,
)

pytestmark = pytest.mark.asyncio


# ── seeding helpers ─────────────────────────────────────────────


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


async def _project_member(db, *, project_id: ProjectId, user_id: UserId, role: str) -> None:
    db.add(ProjectMember(id=ProjectMemberId.new(), project_id=project_id, user_id=user_id, role=role))
    await db.flush()


async def _skill(
    db,
    *,
    owner_id: UserId,
    project_id: ProjectId,
    visibility: str = "project",
    security_status: str = "passed",
) -> JoySafeterSkill:
    from app.joysafeter_domain.services.joysafeter_skill_security import build_scan_files, target_hash

    name = f"skill-{uuid.uuid4()}"
    description = "test skill"
    content = "# Skill\nbody"
    # Seed realistic scan metadata for promotion audit fixtures.
    scan_files = build_scan_files(name=name, description=description, content=content, tags=[], license=None, files=[])
    scan_hash = target_hash(
        name=name, description=description, content=content, tags=[], license=None, files=scan_files
    )
    skill = JoySafeterSkill(
        id=SkillId.new(),
        name=name,
        description=description,
        content=content,
        tags=[],
        created_by_id=owner_id,
        owner_id=owner_id,
        project_id=project_id,
        visibility=visibility,
        lifecycle_status="approved",
        security_status=security_status,
        security_scan_hash=scan_hash,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _version(
    db,
    *,
    skill: JoySafeterSkill,
    version: str,
    published_by_id: UserId,
    lifecycle_status: str = "approved",
) -> JoySafeterSkillVersion:
    sv = JoySafeterSkillVersion(
        id=SkillVersionId.new(),
        skill_id=skill.id,
        version=version,
        skill_name=skill.name,
        skill_description=skill.description,
        content=skill.content,
        tags=[],
        meta_data={},
        allowed_tools=[],
        published_by_id=published_by_id,
        published_at=datetime.now(timezone.utc),
        lifecycle_status=lifecycle_status,
    )
    db.add(sv)
    await db.flush()
    return sv


def _svc(db, *, org_id: OrganizationId, caller_org_role: JoySafeterRole) -> SkillPromotionService:
    return SkillPromotionService(db, active_org_id=org_id, caller_org_role=caller_org_role)


# ── submit_promotion ────────────────────────────────────────────


@pytest.mark.parametrize("project_role", ["viewer", "editor"])
async def test_submit_promotion_requires_admin(db_session, project_role):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    await _org_member(db_session, org_id=org.id, user_id=author.id, role="member")
    await _project_member(db_session, project_id=proj.id, user_id=author.id, role=project_role)
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id)
    sv = await _version(db_session, skill=skill, version="1.0.0", published_by_id=author.id)
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    with pytest.raises(AccessDeniedError):
        await svc.submit_promotion(version_id=sv.id, target_tier="organization", current_user_id=author.id)


async def test_submit_promotion_ignores_current_skill_scan_status(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _org_member(db_session, org_id=org.id, user_id=admin.id, role="member")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id, security_status="failed")
    sv = await _version(db_session, skill=skill, version="1.0.0", published_by_id=admin.id)
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    await svc.submit_promotion(version_id=sv.id, target_tier="organization", current_user_id=admin.id)

    await db_session.refresh(sv)
    assert sv.lifecycle_status == "pending_review"
    assert sv.review_target_visibility == "organization"


async def test_submit_promotion_happy_marks_pending(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _org_member(db_session, org_id=org.id, user_id=admin.id, role="member")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id)
    sv = await _version(db_session, skill=skill, version="1.0.0", published_by_id=admin.id)
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    await svc.submit_promotion(version_id=sv.id, target_tier="organization", current_user_id=admin.id)
    sv_id = sv.id
    db_session.expire_all()
    reloaded = (
        await db_session.execute(select(JoySafeterSkillVersion).where(JoySafeterSkillVersion.id == sv_id))
    ).scalar_one()
    assert reloaded.lifecycle_status == "pending_review"
    assert reloaded.review_target_visibility == "organization"


# ── approve_promotion ───────────────────────────────────────────


async def test_approve_promotion_non_superuser_denied(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id)
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=admin.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    await db_session.commit()

    # caller is a plain org MEMBER (not owner/admin) — approval needs an org
    # superuser (owner OR admin).
    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    with pytest.raises(AccessDeniedError):
        await svc.approve_promotion(version_id=sv.id, current_user_id=UserId.new())


async def test_approve_promotion_admin_allowed(db_session):
    # An org ADMIN who is NOT the publisher can approve (four-eyes satisfied) —
    # this is what unblocks orgs whose owner authored the version.
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    approver = await _user(db_session, name="Approver")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    sv_id = sv.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.ADMIN)
    await svc.approve_promotion(version_id=sv_id, current_user_id=approver.id)
    skill_id = skill.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.org_version_id == sv_id
    assert reloaded.visibility == "organization"


async def test_approve_promotion_four_eyes_denied(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=owner.id, project_id=proj.id)
    # publisher == approver
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=owner.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    with pytest.raises(AccessDeniedError) as ei:
        await svc.approve_promotion(version_id=sv.id, current_user_id=owner.id)
    assert ei.value.code == "SKILL_PROMOTION_FOUR_EYES"


async def test_approve_promotion_org_happy(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.approve_promotion(version_id=sv.id, current_user_id=owner.id)

    skill_id, sv_id, owner_id = skill.id, sv.id, owner.id
    db_session.expire_all()
    reloaded_skill = (
        await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))
    ).scalar_one()
    reloaded_ver = (
        await db_session.execute(select(JoySafeterSkillVersion).where(JoySafeterSkillVersion.id == sv_id))
    ).scalar_one()
    assert reloaded_skill.org_version_id == sv_id
    assert reloaded_skill.visibility == "organization"
    assert reloaded_ver.lifecycle_status == "approved"
    assert reloaded_ver.approved_by_id == owner_id
    assert reloaded_ver.review_target_visibility is None


async def test_approve_promotion_public_happy(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="organization")
    sv = await _version(
        db_session,
        skill=skill,
        version="2.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "public"
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.approve_promotion(version_id=sv.id, current_user_id=owner.id)

    skill_id, sv_id = skill.id, sv.id
    db_session.expire_all()
    reloaded_skill = (
        await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))
    ).scalar_one()
    assert reloaded_skill.public_version_id == sv_id
    assert reloaded_skill.visibility == "public"


# ── reject_promotion ────────────────────────────────────────────


async def test_reject_promotion(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.reject_promotion(version_id=sv.id, current_user_id=owner.id, reason="nope")

    skill_id, sv_id = skill.id, sv.id
    db_session.expire_all()
    reloaded_skill = (
        await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))
    ).scalar_one()
    reloaded_ver = (
        await db_session.execute(select(JoySafeterSkillVersion).where(JoySafeterSkillVersion.id == sv_id))
    ).scalar_one()
    assert reloaded_ver.lifecycle_status == "rejected"
    assert reloaded_ver.review_target_visibility is None
    # pointer never set
    assert reloaded_skill.org_version_id is None
    assert reloaded_skill.visibility == "project"


# ── takedown ────────────────────────────────────────────────────


async def test_takedown_public_drops_to_organization(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="public")
    org_ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=author.id)
    pub_ver = await _version(db_session, skill=skill, version="2.0.0", published_by_id=author.id)
    skill.org_version_id = org_ver.id
    skill.public_version_id = pub_ver.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.takedown(skill_id=skill.id, tier="public", current_user_id=owner.id)

    skill_id, org_ver_id = skill.id, org_ver.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.public_version_id is None
    assert reloaded.org_version_id == org_ver_id
    assert reloaded.visibility == "organization"


async def test_takedown_org_only_floors_to_project(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    owner = await _user(db_session, name="Owner")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="organization")
    org_ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=author.id)
    skill.org_version_id = org_ver.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.takedown(skill_id=skill.id, tier="organization", current_user_id=owner.id)

    skill_id = skill.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.org_version_id is None
    assert reloaded.visibility == "project"


# ── rescans are informational after publication ────────────────


async def test_rescan_failed_verdict_does_not_demote_published_version(db_session):
    from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillSecurityScan
    from app.joysafeter_domain.services.joysafeter_skill_security import SkillSecurityService

    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="organization")
    org_ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=author.id)
    skill.org_version_id = org_ver.id
    org_version_id = org_ver.id
    await db_session.commit()

    failed_scan = JoySafeterSkillSecurityScan(
        id=SkillSecurityScanId.new(),
        skill_id=skill.id,
        created_by_id=author.id,
        trigger="manual",
        target_hash="cafef00d",
        status="failed",
    )
    db_session.add(failed_scan)
    await db_session.flush()

    sec = SkillSecurityService(db_session)
    sec.apply_latest_scan(skill, failed_scan)
    await db_session.commit()

    skill_id = skill.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.org_version_id == org_version_id
    assert reloaded.visibility == "organization"


# ── adversarial: prove the fixes are REAL, not just "looks fixed" ──


async def test_delete_org_served_version_actually_drops_visibility(db_session):
    """Deleting the version an org tier POINTS AT must not leave visibility
    stuck at 'organization' with a null pointer. This would have FAILED before
    this fix (delete_version cleared the FK but never recomputed visibility)."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id, visibility="organization")
    ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=admin.id)
    skill.org_version_id = ver.id
    skill_id = skill.id
    await db_session.commit()

    svc = SkillVersionService(db_session, active_org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    await svc.delete_version(skill_id, "1.0.0", current_user_id=admin.id, force=True)

    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.org_version_id is None
    assert reloaded.visibility == "project"  # not stuck at 'organization'


async def test_delete_public_served_version_drops_to_org_not_project(db_session):
    """Deleting the PUBLIC-served version drops visibility exactly one tier — to
    'organization' — because the org pointer is still live. Proves the recompute
    is tier-accurate, not a blunt reset to project."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id, visibility="public")
    org_ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=admin.id)
    pub_ver = await _version(db_session, skill=skill, version="2.0.0", published_by_id=admin.id)
    skill.org_version_id = org_ver.id
    skill.public_version_id = pub_ver.id
    skill_id = skill.id
    org_ver_id = org_ver.id
    await db_session.commit()

    svc = SkillVersionService(db_session, active_org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    await svc.delete_version(skill_id, "2.0.0", current_user_id=admin.id, force=True)

    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.public_version_id is None
    assert reloaded.org_version_id == org_ver_id
    assert reloaded.visibility == "organization"


async def test_approve_promotion_cross_tenant_denied(db_session):
    """An org-A superuser must NOT be able to approve a promotion for a skill
    that belongs to org B. ``_require_org_approver`` only proves the caller is a
    superuser in their OWN active org; without an org-isolation check on the
    target skill this is a cross-tenant privilege escalation (an org-A admin
    approving/exposing org-B content by version id). ``submit_promotion`` gets
    this right via ``check_skill_access(active_org_id=...)``; approve did not."""
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    proj_b = await _project(db_session, org_id=org_b.id)
    author = await _user(db_session, name="AuthorB")
    approver_a = await _user(db_session, name="ApproverA")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj_b.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    sv_id = sv.id
    await db_session.commit()

    # Caller is a superuser in org A, but the skill lives in org B.
    svc = _svc(db_session, org_id=org_a.id, caller_org_role=JoySafeterRole.OWNER)
    with pytest.raises(AccessDeniedError):
        await svc.approve_promotion(version_id=sv_id, current_user_id=approver_a.id)


async def test_reject_promotion_cross_tenant_denied(db_session):
    """Same cross-tenant escalation guard for reject: an org-A superuser cannot
    reject a promotion belonging to org B."""
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    proj_b = await _project(db_session, org_id=org_b.id)
    author = await _user(db_session, name="AuthorB")
    approver_a = await _user(db_session, name="ApproverA")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj_b.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    sv_id = sv.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org_a.id, caller_org_role=JoySafeterRole.OWNER)
    with pytest.raises(AccessDeniedError):
        await svc.reject_promotion(version_id=sv_id, current_user_id=approver_a.id, reason="x")


async def test_takedown_cross_tenant_denied(db_session):
    """Same cross-tenant escalation guard for takedown: an org-A superuser cannot
    pull down a tier of a skill belonging to org B."""
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    proj_b = await _project(db_session, org_id=org_b.id)
    author = await _user(db_session, name="AuthorB")
    approver_a = await _user(db_session, name="ApproverA")
    skill = await _skill(db_session, owner_id=author.id, project_id=proj_b.id, visibility="organization")
    org_ver = await _version(db_session, skill=skill, version="1.0.0", published_by_id=author.id)
    skill.org_version_id = org_ver.id
    skill_id = skill.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org_a.id, caller_org_role=JoySafeterRole.OWNER)
    with pytest.raises(AccessDeniedError):
        await svc.takedown(skill_id=skill_id, tier="organization", current_user_id=approver_a.id)


async def test_four_eyes_still_blocks_admin_who_published(db_session):
    """Widening the approver to org admin must NOT defeat four-eyes: an admin who
    is themselves the version's publisher still cannot self-approve. Guards
    against the widening accidentally opening a self-approval hole."""
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="AdminAuthor")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=admin.id,
        lifecycle_status="pending_review",
    )
    sv.review_target_visibility = "organization"
    sv_id = sv.id
    await db_session.commit()

    # Caller is an org ADMIN (can approve in general) but IS the publisher.
    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.ADMIN)
    with pytest.raises(AccessDeniedError) as ei:
        await svc.approve_promotion(version_id=sv_id, current_user_id=admin.id)
    assert ei.value.code == "SKILL_PROMOTION_FOUR_EYES"


# ── promotion depends on the published version, not later scan state ──


async def test_approve_promotion_ignores_later_skill_scan_drift(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    author = await _user(db_session, name="Author")
    approver = await _user(db_session, name="Approver")
    # skill head = clean content Y (helper seeds a passing, non-drifted scan over it)
    skill = await _skill(db_session, owner_id=author.id, project_id=proj.id, visibility="project")
    sv = await _version(
        db_session,
        skill=skill,
        version="1.0.0",
        published_by_id=author.id,
        lifecycle_status="pending_review",
    )
    # version freezes DIFFERENT content X — never itself scanned clean
    sv.content = "# Skill\nDIFFERENT UNSCANNED PAYLOAD"
    sv.review_target_visibility = "organization"
    sv_id = sv.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.OWNER)
    await svc.approve_promotion(version_id=sv_id, current_user_id=approver.id)

    skill_id = skill.id
    db_session.expire_all()
    reloaded = (await db_session.execute(select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id))).scalar_one()
    assert reloaded.org_version_id == sv_id
    assert reloaded.visibility == "organization"


async def test_submit_promotion_ignores_later_skill_scan_drift(db_session):
    org = await _org(db_session)
    proj = await _project(db_session, org_id=org.id)
    admin = await _user(db_session, name="Admin")
    await _org_member(db_session, org_id=org.id, user_id=admin.id, role="member")
    await _project_member(db_session, project_id=proj.id, user_id=admin.id, role="admin")
    skill = await _skill(db_session, owner_id=admin.id, project_id=proj.id)
    sv = await _version(db_session, skill=skill, version="1.0.0", published_by_id=admin.id)
    sv.content = "# Skill\nDIFFERENT UNSCANNED PAYLOAD"
    sv_id = sv.id
    await db_session.commit()

    svc = _svc(db_session, org_id=org.id, caller_org_role=JoySafeterRole.MEMBER)
    await svc.submit_promotion(version_id=sv_id, target_tier="organization", current_user_id=admin.id)

    await db_session.refresh(sv)
    assert sv.lifecycle_status == "pending_review"
    assert sv.review_target_visibility == "organization"
