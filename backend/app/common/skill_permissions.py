"""Unified skill permission check — replaces hardcoded owner_id comparisons."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenException
from app.models.skill import Skill
from app.models.skill_collaborator import CollaboratorRole, SkillCollaborator


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
    token_scopes: Optional[List[str]] = None,
    required_scope: Optional[str] = None,
) -> None:
    """
    Unified permission check.

    Raises ForbiddenException if the user lacks sufficient access.
    """
    # 1. Superuser bypass
    if is_superuser:
        _check_token_scope(token_scopes, required_scope)
        return

    # 2. Owner always passes
    if skill.owner_id and skill.owner_id == user_id:
        _check_token_scope(token_scopes, required_scope)
        return

    # 3. Public skill + viewer access (skip DB query)
    if skill.is_public and min_role == CollaboratorRole.viewer:
        _check_token_scope(token_scopes, required_scope)
        return

    # 4. Check collaborator role
    collab = await _get_collaborator(db, skill.id, user_id)
    if collab and collab.role >= min_role:
        _check_token_scope(token_scopes, required_scope)
        return

    raise ForbiddenException("You don't have permission to access this skill")


def _check_token_scope(
    token_scopes: Optional[List[str]],
    required_scope: Optional[str],
) -> None:
    """If request came via PlatformToken, verify scope."""
    if token_scopes is not None and required_scope is not None:
        if required_scope not in token_scopes:
            raise ForbiddenException(f"Token missing required scope: {required_scope}")
