"""
Workspace file storage Repository
"""

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_files import WorkspaceStoredFile

from .base import BaseRepository


class WorkspaceStoredFileRepository(BaseRepository[WorkspaceStoredFile]):
    """Workspace file metadata access."""

    CONTEXT_WORKSPACE = "workspace"

    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceStoredFile, db)

    async def list_workspace_files(self, workspace_id: uuid.UUID) -> List[WorkspaceStoredFile]:
        """List workspace files ordered by upload time."""
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
        """Get a record by file ID and workspace."""
        query = select(WorkspaceStoredFile).where(
            WorkspaceStoredFile.id == file_id,
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def find_by_name(self, workspace_id: uuid.UUID, original_name: str) -> Optional[WorkspaceStoredFile]:
        """Detect a file with the same name."""
        query = select(WorkspaceStoredFile).where(
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.original_name == original_name,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def sum_user_usage(self, user_id: uuid.UUID) -> int:
        """Calculate total storage used by all files of a user (bytes)."""
        query = select(func.coalesce(func.sum(WorkspaceStoredFile.size), 0)).where(
            WorkspaceStoredFile.user_id == user_id
        )
        result = await self.db.execute(query)
        total = result.scalar() or 0
        return int(total)

    async def sum_workspace_usage(self, workspace_id: uuid.UUID) -> int:
        """Calculate total storage used by files in a workspace (bytes)."""
        query = select(func.coalesce(func.sum(WorkspaceStoredFile.size), 0)).where(
            WorkspaceStoredFile.workspace_id == workspace_id,
            WorkspaceStoredFile.context == self.CONTEXT_WORKSPACE,
        )
        result = await self.db.execute(query)
        total = result.scalar() or 0
        return int(total)
