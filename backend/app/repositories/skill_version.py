"""Skill Version Repository."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.skill_version import SkillVersion, SkillVersionFile

from .base import BaseRepository


class SkillVersionRepository(BaseRepository[SkillVersion]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillVersion, db)

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .options(selectinload(SkillVersion.files))
            .order_by(SkillVersion.published_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest(self, skill_id: uuid.UUID) -> Optional[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill_id)
            .options(selectinload(SkillVersion.files))
            .order_by(SkillVersion.published_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_version(
        self, skill_id: uuid.UUID, version: str
    ) -> Optional[SkillVersion]:
        result = await self.db.execute(
            select(SkillVersion)
            .where(
                and_(
                    SkillVersion.skill_id == skill_id,
                    SkillVersion.version == version,
                )
            )
            .options(selectinload(SkillVersion.files))
        )
        return result.scalar_one_or_none()

    async def get_highest_version_str(self, skill_id: uuid.UUID) -> Optional[str]:
        """Return the highest semver version string for a skill."""
        import semver

        result = await self.db.execute(
            select(SkillVersion.version)
            .where(SkillVersion.skill_id == skill_id)
        )
        version_strs = list(result.scalars().all())
        if not version_strs:
            return None
        version_strs.sort(key=lambda v: semver.Version.parse(v), reverse=True)
        return version_strs[0]


class SkillVersionFileRepository(BaseRepository[SkillVersionFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillVersionFile, db)

    async def list_by_version(self, version_id: uuid.UUID) -> List[SkillVersionFile]:
        result = await self.db.execute(
            select(SkillVersionFile).where(
                SkillVersionFile.version_id == version_id
            )
        )
        return list(result.scalars().all())
