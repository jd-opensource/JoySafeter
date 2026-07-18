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
from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectCapability,
    effective_project_capability,
)


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


async def resolve_skill_org_id(db: AsyncSession, skill: JoySafeterSkill) -> Optional[str]:
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


async def _project_member_role(
    db: AsyncSession,
    user_id: str,
    project_id: str,
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
    """Resolve the visibility tier the gate should honor.

    Single-axis model reads the ``visibility`` column only, falling back
    to ``project`` (the least-permissive shareable tier) when it is
    null/empty. The legacy ``is_public`` boolean is no longer consulted
    by the gate — capability, not a boolean flag, decides write/admin,
    and the public tier is expressed solely through ``visibility``.
    """
    return skill.visibility or JoySafeterSkillVisibility.PROJECT.value


async def check_skill_access(
    db: AsyncSession,
    skill: JoySafeterSkill,
    user_id: str,
    required: ProjectCapability,
    *,
    caller_org_role: JoySafeterRole,
    active_org_id: Optional[str] = None,
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

    Org isolation: when ``active_org_id`` is supplied, the capability
    path only counts inside that org. A caller pinned to org B cannot
    READ/WRITE an org-A skill via project capability, even a project
    admin — that would defeat multi-tenant separation. ``active_org_id
    is None`` (legacy callers) disables the gate.

    READ can additionally be granted through the visibility tier:

      * ``public`` — readable from any org (the one cross-org carve-out).
      * ``organization`` — readable by any member of the skill's org,
        but only when the caller is inside that active org.

    ``project`` visibility READ is already covered by the capability path
    (a project member has >= READ). WRITE/ADMIN never come from a
    visibility tier.
    """
    skill_org_id = await resolve_skill_org_id(db, skill)
    in_active_org = active_org_id is None or skill_org_id == active_org_id

    # 1. Capability path — the single authoritative axis. A project role
    #    (or org super-user) resolves to a ProjectCapability; org
    #    isolation gates it so the capability only counts inside the
    #    skill's own org.
    role_in_project = (
        await _project_member_role(db, user_id, skill.project_id) if skill.project_id else None
    )
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
            "user_id": user_id,
            "required": int(required),
        },
    )


async def compute_skill_capability(
    db: AsyncSession,
    skill: JoySafeterSkill,
    user_id: Optional[str],
    *,
    is_superuser: bool = False,
    active_org_id: Optional[str] = None,
) -> str:
    """Resolve the caller's effective capability on ``skill``.

    Returns one of ``owner`` / ``admin`` / ``editor`` / ``viewer`` / ``none``.
    This is the read-side mirror of :func:`check_skill_access`: it never
    raises, it just reports the highest tier the caller holds so the client
    can gate its UI (show the collaborator-manage panel only for
    ``owner``/``admin``, the edit affordances for ``editor`` and up, etc.).

    The precedence matches the gate: super-user (of the skill's own org) and
    owner both resolve to full control, then the per-skill collaborator ACL,
    then the visibility tier as a bare ``viewer`` grant. Org isolation applies
    to every non-public tier exactly as the gate enforces it.
    """
    skill_org_id = await resolve_skill_org_id(db, skill) if active_org_id is not None else None
    in_active_org = active_org_id is None or skill_org_id == active_org_id

    # Super-user of the skill's own org manages it like an admin. (The caller
    # is responsible for scoping ``is_superuser`` to the skill's org; we keep
    # the same contract as the gate rather than re-deriving it here.)
    if is_superuser:
        return "admin"

    if user_id is None:
        # Anonymous: only a public skill is reachable, and only to view.
        return "viewer" if _effective_visibility(skill) == JoySafeterSkillVisibility.PUBLIC.value else "none"

    if skill.owner_id and skill.owner_id == user_id and in_active_org:
        return "owner"

    collab = await _get_collaborator(db, skill.id, user_id)
    if collab and in_active_org:
        return JoySafeterCollaboratorRole.normalize(collab.role).value

    visibility = _effective_visibility(skill)
    if visibility == JoySafeterSkillVisibility.PUBLIC.value:
        return "viewer"
    if in_active_org:
        if visibility == JoySafeterSkillVisibility.PROJECT.value:
            if skill.project_id and await _is_project_member(db, user_id, skill.project_id):
                return "viewer"
        if visibility == JoySafeterSkillVisibility.ORGANIZATION.value:
            resolved_org = skill_org_id if skill_org_id is not None else await resolve_skill_org_id(db, skill)
            if resolved_org and await _is_org_member(db, user_id, resolved_org):
                return "viewer"
    return "none"
