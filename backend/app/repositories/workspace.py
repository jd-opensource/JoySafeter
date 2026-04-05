"""
Workspace Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workspace import Workspace, WorkspaceMember, WorkspaceMemberRole

from .base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    """Workspace data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(Workspace, db)

    async def list_for_user(self, user_id: str) -> List[Workspace]:
        """List all workspaces accessible to the user (owner or member)."""
        query = (
            select(Workspace)
            .outerjoin(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(or_(Workspace.owner_id == user_id, WorkspaceMember.user_id == user_id))
            .options(selectinload(Workspace.members))
            .distinct()
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_name_and_owner(self, name: str, owner_id: str) -> Optional[Workspace]:
        """Get a workspace by name and owner."""
        query = select(Workspace).where(
            Workspace.name == name,
            Workspace.owner_id == owner_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class WorkspaceMemberRepository(BaseRepository[WorkspaceMember]):
    """Workspace member data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceMember, db)

    async def get_member(self, workspace_id: uuid.UUID, user_id: str) -> Optional[WorkspaceMember]:
        query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def count_admins(self, workspace_id: uuid.UUID) -> int:
        """Count admin/owner members in the workspace."""
        query = (
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role.in_([WorkspaceMemberRole.owner, WorkspaceMemberRole.admin]),
            )
        )
        result = await self.db.execute(query)
        return int(result.scalar() or 0)

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[WorkspaceMember]:
        """List all members of a workspace, including user info."""
        query = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .options(selectinload(WorkspaceMember.user))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_member_role(
        self, workspace_id: uuid.UUID, user_id: str, role: WorkspaceMemberRole
    ) -> WorkspaceMember:
        """Update a member's role."""
        member = await self.get_member(workspace_id, user_id)
        if not member:
            raise ValueError(f"Member not found: {user_id} in workspace {workspace_id}")
        member.role = role
        await self.db.flush()
        return member

    async def delete_member(self, workspace_id: uuid.UUID, user_id: str) -> bool:
        """Remove a member."""
        stmt = delete(WorkspaceMember).where(
            and_(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        result = await self.db.execute(stmt)
        return (getattr(result, "rowcount", 0) or 0) > 0
