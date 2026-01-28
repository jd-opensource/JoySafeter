"""
工作流文件夹 Repository
"""

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import WorkspaceFolder

from .base import BaseRepository


class WorkflowFolderRepository(BaseRepository[WorkspaceFolder]):
    """文件夹数据访问"""

    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceFolder, db)

    async def list_by_workspace(self, workspace_id: uuid.UUID) -> List[WorkspaceFolder]:
        query = (
            select(WorkspaceFolder)
            .where(
                WorkspaceFolder.workspace_id == workspace_id,
                WorkspaceFolder.deleted_at.is_(None),
            )
            .order_by(WorkspaceFolder.sort_order.asc(), WorkspaceFolder.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def max_sort_order(self, workspace_id: uuid.UUID, parent_id: Optional[uuid.UUID]) -> int:
        """
        返回指定 workspace + parent 下最大的 sort_order。
        若不存在任何记录，返回 -1（方便上层 next_sort = max + 1 使首个为 0）。
        """
        conditions = [
            WorkspaceFolder.workspace_id == workspace_id,
            WorkspaceFolder.parent_id.is_(None) if parent_id is None else WorkspaceFolder.parent_id == parent_id,
            WorkspaceFolder.deleted_at.is_(None),
        ]

        query = (
            select(WorkspaceFolder.sort_order).where(*conditions).order_by(WorkspaceFolder.sort_order.desc()).limit(1)
        )
        result = await self.db.execute(query)
        current = result.scalar_one_or_none()
        return current if current is not None else -1

    async def list_children(self, parent_id: uuid.UUID) -> List[WorkspaceFolder]:
        query = select(WorkspaceFolder).where(
            WorkspaceFolder.parent_id == parent_id,
            WorkspaceFolder.deleted_at.is_(None),
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_relations_by_workspace(self, workspace_id: uuid.UUID) -> List[Tuple[uuid.UUID, Optional[uuid.UUID]]]:
        """获取 workspace 内所有 folder 的 (id, parent_id) 关系，用于构建树/子树。"""
        query = select(WorkspaceFolder.id, WorkspaceFolder.parent_id).where(
            WorkspaceFolder.workspace_id == workspace_id,
            WorkspaceFolder.deleted_at.is_(None),
        )

        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result.fetchall()]

    async def ensure_same_workspace(self, folder_id: uuid.UUID, workspace_id: uuid.UUID) -> WorkspaceFolder:
        folder = await self.get(folder_id)
        if not folder or folder.workspace_id != workspace_id:
            from app.common.exceptions import NotFoundException

            raise NotFoundException("Folder not found in workspace")
        return folder
