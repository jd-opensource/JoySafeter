"""
Skill Repository
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.skill import Skill, SkillFile
from app.models.skill_collaborator import SkillCollaborator

from .base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    def __init__(self, db: AsyncSession):
        super().__init__(Skill, db)

    async def list_by_user(
        self,
        user_id: Optional[str] = None,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
    ) -> List[Skill]:
        """List skills for a user (including public ones)."""
        query = select(Skill).options(selectinload(Skill.files))

        conditions = []
        if user_id:
            collab_subquery = (
                select(SkillCollaborator.skill_id).where(SkillCollaborator.user_id == user_id).scalar_subquery()
            )
            if include_public:
                conditions.append(
                    or_(
                        Skill.owner_id == user_id,
                        Skill.id.in_(collab_subquery),
                        Skill.is_public.is_(True),
                        Skill.owner_id.is_(None),  # system-level public skill
                    )
                )
        else:
            # if user_id is None and include_public is False, return no results
            conditions.append(Skill.id.is_(None))  # condition that never matches

        if tags:
            # use JSONB array query
            for tag in tags:
                conditions.append(Skill.tags.contains([tag]))

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_files(self, skill_id: uuid.UUID) -> Optional[Skill]:
        """Get a skill with its associated files."""
        query = select(Skill).where(Skill.id == skill_id)
        query = query.options(selectinload(Skill.files))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_by_name_and_owner(self, name: str, owner_id: Optional[str]) -> Optional[Skill]:
        """Get a skill by name and owner."""
        query = select(Skill).where(and_(Skill.name == name, Skill.owner_id == owner_id))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class SkillFileRepository(BaseRepository[SkillFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillFile, db)

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillFile]:
        """List all files for a skill."""
        result = await self.db.execute(select(SkillFile).where(SkillFile.skill_id == skill_id))
        return list(result.scalars().all())

    async def delete_by_skill(self, skill_id: uuid.UUID) -> int:
        """Delete all files for a skill."""
        from sqlalchemy import delete

        stmt = delete(SkillFile).where(SkillFile.skill_id == skill_id)
        result = await self.db.execute(stmt)
        return result.rowcount if result.rowcount is not None else 0  # type: ignore
