"""Skill Collaborator Repository."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_collaborator import SkillCollaborator

from .base import BaseRepository


class SkillCollaboratorRepository(BaseRepository[SkillCollaborator]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillCollaborator, db)

    async def get_by_skill_and_user(self, skill_id: uuid.UUID, user_id: str) -> Optional[SkillCollaborator]:
        result = await self.db.execute(
            select(SkillCollaborator).where(
                and_(
                    SkillCollaborator.skill_id == skill_id,
                    SkillCollaborator.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillCollaborator]:
        result = await self.db.execute(select(SkillCollaborator).where(SkillCollaborator.skill_id == skill_id))
        return list(result.scalars().all())  # type: ignore[return-value]

    async def delete_by_skill_and_user(self, skill_id: uuid.UUID, user_id: str) -> bool:
        collab = await self.get_by_skill_and_user(skill_id, user_id)
        if not collab:
            return False
        await self.db.delete(collab)
        await self.db.flush()
        return True
