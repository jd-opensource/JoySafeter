"""
工作空间文件存储 Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_files import WorkspaceStoredFile

from .base import BaseRepository


class WorkspaceStoredFileRepository(BaseRepository[WorkspaceStoredFile]):
    """工作空间文件元数据访问"""

    CONTEXT_WORKSPACE = "workspace"

    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceStoredFile, db)

    async def list_workspace_files(self, workspace_id: uuid.UUID) -> List[WorkspaceStoredFile]:
        """按上传时间顺序获取工作空间文件列表"""
        query = (
            select(WorkspaceStoredFile)
            .where(
                WorkspaceStoredFile.workspace_id == workspace_id,
                WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
            )
            .order_by(WorkspaceStoredFile.uploaded_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id_and_workspace(
        self, file_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Optional[WorkspaceStoredFile]:
        """根据文件 ID 与工作空间获取记录"""
        query = select(WorkspaceStoredFile).where(
            WorkspaceStoredFile.id == file_id,
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def find_by_name(self, workspace_id: uuid.UUID, original_name: str) -> Optional[WorkspaceStoredFile]:
        """检测同名文件"""
        query = select(WorkspaceStoredFile).where(
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.original_name == original_name,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def sum_user_usage(self, user_id: uuid.UUID) -> int:
        """计算用户所有文件占用空间（字节）"""
        query = select(func.coalesce(func.sum(WorkspaceStoredFile.size), 0)).where(
            WorkspaceStoredFile.user_id == user_id
        )
        result = await self.db.execute(query)
        total = result.scalar() or 0
        return int(total)

    async def sum_workspace_usage(self, workspace_id: uuid.UUID) -> int:
        """计算工作空间下文件占用空间（字节）"""
        query = select(func.coalesce(func.sum(WorkspaceStoredFile.size), 0)).where(
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        total = result.scalar() or 0
        return int(total)
