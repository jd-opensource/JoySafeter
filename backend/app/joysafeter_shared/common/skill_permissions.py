"""Unified skill permission check — replaces hardcoded owner_id comparisons."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_domain.models.skill import Skill
from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole, SkillCollaborator


async def _get_collaborator(
    db: AsyncSession,
    skill_id,
    user_id: str,
) -> Optional[SkillCollaborator]:
    result = await db.execute(
        select(SkillCollaborator).where(
            and_(
                SkillCollaborator.skill_id == skill_id,
                SkillCollaborator.user_id == user_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def check_skill_access(
    db: AsyncSession,
    skill: Skill,
    user_id: str,
    min_role: CollaboratorRole,
    *,
    is_superuser: bool = False,
) -> None:
    """
    Unified permission check.

    Raises AccessDeniedError if the user lacks sufficient access.
    """
    # 1. Superuser bypass
    if is_superuser:
        return

    # 2. Owner always passes
    if skill.owner_id and skill.owner_id == user_id:
        return

    # 3. Public skill + viewer access (skip DB query)
    if skill.is_public and min_role == CollaboratorRole.viewer:
        return

    # 4. Check collaborator role
    collab = await _get_collaborator(db, skill.id, user_id)
    if collab and collab.role >= min_role:
        return

    raise AccessDeniedError(
        "You don't have permission to access this skill",
        code="SKILL_ACCESS_DENIED",
        data={"skill_id": str(skill.id), "user_id": user_id, "min_role": min_role.value},
    )

