"""
Skill Repository
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_domain.models.skill import Skill, SkillFile
from app.joysafeter_domain.models.skill_collaborator import SkillCollaborator

from .base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    def __init__(self, db: AsyncSession):
        super().__init__(Skill, db)

    async def list_by_user(
        self,
        user_id: Optional[str] = None,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[List[Skill], bool]:
        """List skills for a user with cursor pagination."""
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
                        Skill.owner_id.is_(None),
                    )
                )
        else:
            conditions.append(Skill.id.is_(None))

        if project_id is not None:
            conditions.append(Skill.project_id == project_id)

        if tags:
            for tag in tags:
                conditions.append(Skill.tags.contains([tag]))

        if after_id:
            conditions.append(Skill.id < after_id)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(Skill.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        has_more = len(items) > limit
        return items[:limit], has_more

    async def get_with_files(self, skill_id: uuid.UUID) -> Optional[Skill]:
        """Get a skill with its associated files."""
        query = select(Skill).where(Skill.id == skill_id)
        query = query.options(selectinload(Skill.files))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_by_ids(self, skill_ids: List[uuid.UUID]) -> List[Skill]:
        """Get multiple skills by their IDs, with files eagerly loaded."""
        if not skill_ids:
            return []
        query = select(Skill).options(selectinload(Skill.files)).where(Skill.id.in_(skill_ids))
        result = await self.db.execute(query)
        return list(result.scalars().all())

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
