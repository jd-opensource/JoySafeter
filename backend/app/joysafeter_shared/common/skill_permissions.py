"""Unified skill permission check — replaces hardcoded owner_id comparisons."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterCollaboratorRole,
    JoySafeterSkill,
    JoySafeterSkillCollaborator,
    JoySafeterSkillVisibility,
)
from app.joysafeter_shared.common.app_errors import AccessDeniedError


async def _get_collaborator(
    db: AsyncSession,
    skill_id,
    user_id: str,
) -> Optional[JoySafeterSkillCollaborator]:
    result = await db.execute(
        select(JoySafeterSkillCollaborator).where(
            and_(
                JoySafeterSkillCollaborator.skill_id == skill_id,
                JoySafeterSkillCollaborator.user_id == user_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def _skill_org_id(db: AsyncSession, skill: JoySafeterSkill) -> Optional[str]:
    """Return the org id that owns the skill, via its project. ``None``
    when the skill has no project binding — falls back to "not org-scoped"
    which the org-tier check then treats as a miss.
    """
    if not skill.project_id:
        return None
    result = await db.execute(select(Project.org_id).where(Project.id == skill.project_id))
    return result.scalar_one_or_none()


async def _is_org_member(db: AsyncSession, user_id: str, org_id: str) -> bool:
    """Single-row lookup against the org-member table. Covers the
    ``organization`` visibility tier — "anyone in this org can see it"."""
    result = await db.execute(
        select(Member.id)
        .where(
            and_(
                Member.organization_id == org_id,
                Member.user_id == user_id,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _is_project_member(db: AsyncSession, user_id: str, project_id: str) -> bool:
    """Single-row lookup against the project_members table. Covers the
    ``project`` visibility tier — "only members of THIS project can see it".

    Introduced in P2.8 to actually distinguish ``project`` from
    ``organization``. Before this, both tiers fell back to "is the user
    in the same org", which made the ``project`` value cosmetic.
    """
    result = await db.execute(
        select(ProjectMember.id)
        .where(
            and_(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _effective_visibility(skill: JoySafeterSkill) -> str:
    """Resolve the visibility value the gate should honor.

    P1 dual-writes ``visibility`` and ``is_public`` so reading either is
    consistent for a skill written in this version. But pre-P1 rows
    backfilled by ``20260625_000003_skill_visibility`` are also possible,
    as is any inconsistency from an outside writer that forgot ``visibility``.
    Prefer the new column; fall back to deriving from ``is_public`` so
    pre-migration writers stay correct.
    """
    if skill.visibility:
        return skill.visibility
    if skill.is_public:
        return JoySafeterSkillVisibility.PUBLIC.value
    return JoySafeterSkillVisibility.PRIVATE.value


async def check_skill_access(
    db: AsyncSession,
    skill: JoySafeterSkill,
    user_id: str,
    min_role: JoySafeterCollaboratorRole,
    *,
    is_superuser: bool = False,
    active_org_id: Optional[str] = None,
) -> None:
    """
    Unified permission check.

    Raises AccessDeniedError if the user lacks sufficient access.

    Walks the visibility tiers in order of cost: cheap in-memory checks
    (superuser, owner) before any database hit, then collaborator lookup,
    then the visibility tier (project / organization / public).

    Strict org isolation (P2.9): when ``active_org_id`` is supplied,
    every non-public match also has to belong to that org. A user who
    owns a skill in org A doesn't get to read it while their session is
    pinned to org B — that would defeat the multi-tenant separation
    the list query already enforces. ``public`` is the one carve-out;
    public skills cross every org boundary by definition.

    ``active_org_id=None`` keeps the pre-P2.9 behavior: owner short-
    circuits without an org check. Used by legacy callers that haven't
    been wired through ``JoySafeterAuthContext.org_id`` yet.
    """
    # 1. Superuser bypass — platform admin sees everything everywhere.
    if is_superuser:
        return

        # Resolve the skill's org once; reused by both the owner short-
        # circuit and the visibility-tier branches below.
    skill_org_id = await _skill_org_id(db, skill) if active_org_id is not None else None
    in_active_org = active_org_id is None or skill_org_id == active_org_id

    # 2. Owner short-circuit — still subject to active-org isolation
    #    when the caller has supplied an active org. The owner can
    #    fetch the skill via direct GET from inside the right org;
    #    they just can't reach across org contexts to pull it.
    if skill.owner_id and skill.owner_id == user_id and in_active_org:
        return

        # 3. Collaborator role on this skill (the per-skill ACL,
        #    independent of the visibility tier). Same org-scope rule:
        #    a collaborator entry only counts inside the active org so
        #    a multi-org admin can't "phase through" by switching context.
    collab = await _get_collaborator(db, skill.id, user_id)
    if collab and JoySafeterCollaboratorRole.normalize(collab.role) >= min_role and in_active_org:
        return

        # Beyond this point we only let viewer-tier callers through —
        # higher roles (editor/admin) require either ownership or a real
        # collaborator entry, never visibility-tier auto-grants.
    if min_role != JoySafeterCollaboratorRole.VIEWER:
        raise AccessDeniedError(
            "You don't have permission to access this skill",
            code="SKILL_ACCESS_DENIED",
            data={"skill_id": str(skill.id), "user_id": user_id, "min_role": min_role.value},
        )

        # 4. Visibility-tier viewer grants
    visibility = _effective_visibility(skill)

    if visibility == JoySafeterSkillVisibility.PUBLIC.value:
        # Public is intentionally cross-org. The list query lets it
        # through everywhere, and so do we.
        return

        # Project / Organization tiers — must be inside the active org
        # (when supplied). For ``active_org_id=None`` the in_active_org
        # short-circuit returns True and the original P2.8 behavior holds.
    if visibility == JoySafeterSkillVisibility.PROJECT.value and in_active_org:
        if skill.project_id and await _is_project_member(db, user_id, skill.project_id):
            return

    if visibility == JoySafeterSkillVisibility.ORGANIZATION.value and in_active_org:
        if skill_org_id is None:
            skill_org_id = await _skill_org_id(db, skill)
        if skill_org_id and await _is_org_member(db, user_id, skill_org_id):
            return

    raise AccessDeniedError(
        "You don't have permission to access this skill",
        code="SKILL_ACCESS_DENIED",
        data={"skill_id": str(skill.id), "user_id": user_id, "min_role": min_role.value},
    )
