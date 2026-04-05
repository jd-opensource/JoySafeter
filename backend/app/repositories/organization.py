"""
Organization and member Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Member, Organization

from .base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """Organization data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(Organization, db)

    async def get_with_members(self, org_id: uuid.UUID) -> Optional[Organization]:
        """Get an organization with its members and user info."""
        query = (
            select(Organization)
            .where(Organization.id == org_id)
            .options(selectinload(Organization.members).selectinload(Member.user))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str, exclude_id: Optional[uuid.UUID] = None) -> bool:
        """Check whether a slug exists (optionally excluding a given ID)."""
        query = select(Organization).where(Organization.slug == slug)
        if exclude_id:
            query = query.where(Organization.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None


class MemberRepository(BaseRepository[Member]):
    """Member data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(Member, db)

    async def get_by_user_and_org(self, user_id: str | uuid.UUID, org_id: uuid.UUID) -> Optional[Member]:
        """Get a member by user and organization."""
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
        """List all members of an organization, including user info."""
        query = select(Member).where(Member.organization_id == org_id).options(selectinload(Member.user))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_by_org(self, org_id: uuid.UUID) -> int:
        """Count members in an organization."""
        query = select(func.count()).select_from(Member).where(Member.organization_id == org_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_with_user(self, member_id: uuid.UUID) -> Optional[Member]:
        """Get a member by ID, including user info."""
        query = select(Member).where(Member.id == member_id).options(selectinload(Member.user))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
