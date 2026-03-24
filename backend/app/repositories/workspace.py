"""
工作空间 Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workspace import Workspace, WorkspaceMember, WorkspaceMemberRole

from .base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    """工作空间数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(Workspace, db)

    async def list_for_user(self, user_id: str) -> List[Workspace]:
        """获取用户可访问的所有工作空间（拥有者或成员）"""
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
        """根据名称和拥有者获取工作空间"""
        query = select(Workspace).where(
            Workspace.name == name,
            Workspace.owner_id == owner_id,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class WorkspaceMemberRepository(BaseRepository[WorkspaceMember]):
    """工作空间成员数据访问"""

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
        """统计 workspace 中 admin/owner 数量"""
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
        """获取工作空间的所有成员，包含用户信息"""
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
        """更新成员角色"""
        member = await self.get_member(workspace_id, user_id)
        if not member:
            raise ValueError(f"Member not found: {user_id} in workspace {workspace_id}")
        member.role = role
        await self.db.flush()
        return member

    async def delete_member(self, workspace_id: uuid.UUID, user_id: str) -> bool:
        """删除成员"""
        stmt = delete(WorkspaceMember).where(
            and_(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        result = await self.db.execute(stmt)
        return (getattr(result, "rowcount", 0) or 0) > 0
