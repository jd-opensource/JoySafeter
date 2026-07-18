"""Per-skill collaborator management (admin/editor/viewer).

Mirrors ``ProjectService`` member management: an idempotent grant/upsert, a
revoke, a listing joined to users, and a read helper. The stored role is the
plain project-capability vocabulary string; ``JoySafeterCollaboratorRole``
provides the ordering the read gate (``check_skill_access``) needs.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterCollaboratorRole,
    JoySafeterSkillCollaborator,
)


class SkillCollaboratorService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load(self, skill_id: uuid.UUID, user_id: str) -> JoySafeterSkillCollaborator | None:
        result = await self.db.execute(
            select(JoySafeterSkillCollaborator)
            .where(
                JoySafeterSkillCollaborator.skill_id == skill_id,
                JoySafeterSkillCollaborator.user_id == user_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_collaborators(
        self, skill_id: uuid.UUID
    ) -> list[tuple[JoySafeterSkillCollaborator, AuthUser | None]]:
        result = await self.db.execute(
            select(JoySafeterSkillCollaborator, AuthUser)
            .outerjoin(AuthUser, JoySafeterSkillCollaborator.user_id == AuthUser.id)
            .where(JoySafeterSkillCollaborator.skill_id == skill_id)
            .order_by(JoySafeterSkillCollaborator.created_at)
        )
        return [(collab, user) for collab, user in result.all()]

    async def grant_collaborator(
        self,
        *,
        skill_id: uuid.UUID,
        user_id: str,
        role: str,
        invited_by: str,
        commit: bool = False,
    ) -> JoySafeterSkillCollaborator:
        # Store the plain vocabulary string (admin/editor/viewer); normalize
        # folds legacy/unknown values to the least-privilege viewer.
        role_value = JoySafeterCollaboratorRole.normalize(role).value

        existing = await self._load(skill_id, user_id)
        if existing is not None:
            if existing.role != role_value:
                existing.role = role_value
                if commit:
                    await self.db.commit()
                    await self.db.refresh(existing)
                else:
                    await self.db.flush()
            return existing

        membership = JoySafeterSkillCollaborator(
            skill_id=skill_id, user_id=user_id, role=role_value, invited_by=invited_by
        )
        self.db.add(membership)
        if not commit:
            await self.db.flush()
            return membership
        try:
            await self.db.commit()
        except IntegrityError:
            # A concurrent grant inserted the same (skill_id, user_id) first.
            # Converge on the winning row and apply the requested role.
            await self.db.rollback()
            winner = await self._load(skill_id, user_id)
            if winner is None:
                raise
            if winner.role != role_value:
                winner.role = role_value
            membership = winner
            await self.db.commit()
        await self.db.refresh(membership)
        return membership

    async def revoke_collaborator(self, *, skill_id: uuid.UUID, user_id: str, commit: bool = False) -> bool:
        existing = await self._load(skill_id, user_id)
        if existing is None:
            return False
        await self.db.execute(
            delete(JoySafeterSkillCollaborator).where(
                JoySafeterSkillCollaborator.skill_id == skill_id,
                JoySafeterSkillCollaborator.user_id == user_id,
            )
        )
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return True
