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
        """获取用户的 Skills（包括公开的）"""
        query = select(Skill).options(selectinload(Skill.files))

        conditions = []
        if user_id:
            # 用户自己的 Skills 或公开的 Skills
            if include_public:
                conditions.append(
                    or_(
                        Skill.owner_id == user_id,
                        Skill.is_public.is_(True),
                        Skill.owner_id.is_(None),  # 系统级公共 Skill
                    )
                )
            else:
                conditions.append(Skill.owner_id == user_id)
        elif include_public:
            # 只获取公开的 Skills
            conditions.append(
                or_(
                    Skill.is_public.is_(True),
                    Skill.owner_id.is_(None),  # 系统级公共 Skill
                )
            )
        else:
            # 如果 user_id 为 None 且 include_public 为 False，不返回任何结果
            conditions.append(Skill.id.is_(None))  # 永远不匹配的条件

        if tags:
            # 使用 JSONB 数组查询
            for tag in tags:
                conditions.append(Skill.tags.contains([tag]))

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_files(self, skill_id: uuid.UUID) -> Optional[Skill]:
        """获取 Skill 及其关联的文件"""
        query = select(Skill).where(Skill.id == skill_id)
        query = query.options(selectinload(Skill.files))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def count_by_user(self, user_id: str) -> int:
        """统计用户拥有的 Skill 数量"""
        result = await self.db.execute(select(Skill).where(Skill.owner_id == user_id))
        return len(list(result.scalars().all()))

    async def get_by_name_and_owner(self, name: str, owner_id: Optional[str]) -> Optional[Skill]:
        """根据名称和拥有者获取 Skill"""
        query = select(Skill).where(and_(Skill.name == name, Skill.owner_id == owner_id))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class SkillFileRepository(BaseRepository[SkillFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillFile, db)

    async def list_by_skill(self, skill_id: uuid.UUID) -> List[SkillFile]:
        """获取 Skill 的所有文件"""
        result = await self.db.execute(select(SkillFile).where(SkillFile.skill_id == skill_id))
        return list(result.scalars().all())

    async def delete_by_skill(self, skill_id: uuid.UUID) -> int:
        """删除 Skill 的所有文件"""
        from sqlalchemy import delete

        stmt = delete(SkillFile).where(SkillFile.skill_id == skill_id)
        result = await self.db.execute(stmt)
        return result.rowcount if result.rowcount is not None else 0  # type: ignore
