"""
组织与成员 Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Member, Organization

from .base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """组织数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(Organization, db)

    async def get_with_members(self, org_id: uuid.UUID) -> Optional[Organization]:
        """获取组织，包含成员及用户信息"""
        query = (
            select(Organization)
            .where(Organization.id == org_id)
            .options(selectinload(Organization.members).selectinload(Member.user))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str, exclude_id: Optional[uuid.UUID] = None) -> bool:
        """检查 slug 是否存在（可排除自身）"""
        query = select(Organization).where(Organization.slug == slug)
        if exclude_id:
            query = query.where(Organization.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        """根据 slug 获取组织"""
        query = select(Organization).where(Organization.slug == slug)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class MemberRepository(BaseRepository[Member]):
    """成员数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(Member, db)

    async def get_by_user_and_org(self, user_id: str | uuid.UUID, org_id: uuid.UUID) -> Optional[Member]:
        """根据用户和组织获取成员"""
        # Convert user_id to string if it's UUID
        user_id_str = str(user_id) if isinstance(user_id, uuid.UUID) else user_id
        query = (
            select(Member)
            .where(Member.user_id == user_id_str, Member.organization_id == org_id)
            .options(selectinload(Member.user))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: uuid.UUID) -> List[Member]:
        """获取组织下所有成员，包含用户信息"""
        query = select(Member).where(Member.organization_id == org_id).options(selectinload(Member.user))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_org(self, org_id: uuid.UUID) -> int:
        """统计组织成员数量"""
        query = select(func.count()).select_from(Member).where(Member.organization_id == org_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_with_user(self, member_id: uuid.UUID) -> Optional[Member]:
        """根据成员 ID 获取，包含用户"""
        query = select(Member).where(Member.id == member_id).options(selectinload(Member.user))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
