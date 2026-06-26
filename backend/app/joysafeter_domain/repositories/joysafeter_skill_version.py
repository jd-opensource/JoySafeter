"""Skill Version Repository."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillVersion, JoySafeterSkillVersionFile

from .base import BaseRepository


class SkillVersionRepository(BaseRepository[JoySafeterSkillVersion]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillVersion, db)

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[JoySafeterSkillVersion]:
        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(JoySafeterSkillVersion.skill_id == skill_id)
            .options(selectinload(JoySafeterSkillVersion.files))
            .order_by(JoySafeterSkillVersion.published_at.desc())
        )
        return list(result.scalars().all())  # type: ignore[return-value]

    async def get_latest(self, skill_id: uuid.UUID) -> Optional[JoySafeterSkillVersion]:
        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(JoySafeterSkillVersion.skill_id == skill_id)
            .options(selectinload(JoySafeterSkillVersion.files))
            .order_by(JoySafeterSkillVersion.published_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_by_version(self, skill_id: uuid.UUID, version: str) -> Optional[JoySafeterSkillVersion]:
        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(
                and_(
                    JoySafeterSkillVersion.skill_id == skill_id,
                    JoySafeterSkillVersion.version == version,
                )
            )
            .options(selectinload(JoySafeterSkillVersion.files))
        )
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_highest_version_str(self, skill_id: uuid.UUID) -> Optional[str]:
        """Return the highest semver version string for a skill."""
        import semver

        result = await self.db.execute(
            select(JoySafeterSkillVersion.version).where(JoySafeterSkillVersion.skill_id == skill_id)
        )
        version_strs = list(result.scalars().all())
        if not version_strs:
            return None
        version_strs.sort(key=lambda v: semver.Version.parse(v), reverse=True)
        return version_strs[0]


class SkillVersionFileRepository(BaseRepository[JoySafeterSkillVersionFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillVersionFile, db)

    async def list_by_version(self, version_id: uuid.UUID) -> List[JoySafeterSkillVersionFile]:
        result = await self.db.execute(
            select(JoySafeterSkillVersionFile).where(JoySafeterSkillVersionFile.version_id == version_id)
        )
        return list(result.scalars().all())
