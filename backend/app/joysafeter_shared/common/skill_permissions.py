"""Unified skill permission check — replaces hardcoded owner_id comparisons."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_organization import Member
from app.joysafeter_domain.models.joysafeter_project import Project, ProjectMember
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillVisibility,
)
from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectCapability,
    effective_project_capability,
)
from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId


async def resolve_skill_org_id(db: AsyncSession, skill: JoySafeterSkill) -> OrganizationId | None:
    """Return the org id that owns the skill, via its project. ``None``
    when the skill has no project binding — falls back to "not org-scoped"
    which the org-tier check then treats as a miss.
    """
    if not skill.project_id:
        return None
    result = await db.execute(select(Project.org_id).where(Project.id == skill.project_id))
    return result.scalar_one_or_none()


async def _is_org_member(db: AsyncSession, user_id: UserId, org_id: OrganizationId) -> bool:
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


async def _project_member_role(
    db: AsyncSession,
    user_id: UserId,
    project_id: ProjectId,
) -> Optional[str]:
    """Return the caller's ``ProjectMember.role`` on ``project_id``.

    Single source of the caller's per-project capability under the
    single-axis model (P2 skills redesign). ``None`` when the caller
    holds no membership row — which ``effective_project_capability``
    then maps to ``ProjectCapability.NONE`` for a non-super-user.
    """
    result = await db.execute(
        select(ProjectMember.role)
        .where(
            and_(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _effective_visibility(skill: JoySafeterSkill) -> str:
    """Return the persisted visibility tier."""
    return skill.visibility


async def check_skill_access(
    db: AsyncSession,
    skill: JoySafeterSkill,
    user_id: UserId,
    required: ProjectCapability,
    *,
    caller_org_role: JoySafeterRole,
    active_org_id: OrganizationId | None = None,
) -> None:
    """Single-axis skill permission gate.

    Raises ``AccessDeniedError`` unless the caller holds at least
    ``required`` capability on ``skill``.

    The model has exactly one authoritative source of write/admin
    capability: the caller's effective capability on the skill's OWN
    project, computed by ``effective_project_capability(caller_org_role,
    role_in_skill_project)``. Org owner/admin are super-users (ADMIN on
    every skill in their own org). There is no owner short-circuit and no
    per-skill collaborator ACL — those axes are gone.

    Org isolation: the capability path only counts inside the active org.
    A caller pinned to org B cannot
    READ/WRITE an org-A skill via project capability, even a project
    admin — that would defeat multi-tenant separation.

    READ can additionally be granted through the visibility tier:

      * ``public`` — readable from any org (the one cross-org carve-out).
      * ``organization`` — readable by any member of the skill's org,
        but only when the caller is inside that active org.

    ``project`` visibility READ is already covered by the capability path
    (a project member has >= READ). WRITE/ADMIN never come from a
    visibility tier.
    """
    skill_org_id = await resolve_skill_org_id(db, skill)
    in_active_org = skill_org_id == active_org_id

    # 1. Capability path — the single authoritative axis. A project role
    #    (or org super-user) resolves to a ProjectCapability; org
    #    isolation gates it so the capability only counts inside the
    #    skill's own org.
    role_in_project = await _project_member_role(db, user_id, skill.project_id) if skill.project_id else None
    cap = effective_project_capability(caller_org_role, role_in_project)
    if in_active_org and cap >= required:
        return

    # 2. READ-via-visibility fallback. Visibility never grants WRITE/ADMIN.
    if required == ProjectCapability.READ:
        visibility = _effective_visibility(skill)
        if visibility == JoySafeterSkillVisibility.PUBLIC.value:
            # Public is intentionally cross-org; ignore in_active_org.
            return
        if (
            visibility == JoySafeterSkillVisibility.ORGANIZATION.value
            and in_active_org
            and skill_org_id is not None
            and await _is_org_member(db, user_id, skill_org_id)
        ):
            return

    raise AccessDeniedError(
        "You don't have permission to access this skill",
        code="SKILL_ACCESS_DENIED",
        data={
            "skill_id": str(skill.id),
            "user_id": str(user_id),
            "required": int(required),
        },
    )
