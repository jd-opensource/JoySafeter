"""Repository for Security Dept tasks."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security_dept_task import SecurityDeptTask


class SecurityDeptTaskRepository:
    """Data access methods for security department tasks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, task: SecurityDeptTask) -> SecurityDeptTask:
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def get(self, task_id: uuid.UUID) -> Optional[SecurityDeptTask]:
        result = await self.db.execute(select(SecurityDeptTask).where(SecurityDeptTask.id == task_id))
        return result.scalar_one_or_none()

    async def get_for_user(self, task_id: uuid.UUID, user_id: str) -> Optional[SecurityDeptTask]:
        result = await self.db.execute(
            select(SecurityDeptTask).where(SecurityDeptTask.id == task_id, SecurityDeptTask.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        status: Optional[str] = None,
    ) -> list[SecurityDeptTask]:
        query = select(SecurityDeptTask).where(SecurityDeptTask.user_id == user_id)
        if status:
            query = query.where(SecurityDeptTask.status == status)
        query = query.order_by(SecurityDeptTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_user(self, *, user_id: str, status: Optional[str] = None) -> int:
        query = select(func.count()).select_from(SecurityDeptTask).where(SecurityDeptTask.user_id == user_id)
        if status:
            query = query.where(SecurityDeptTask.status == status)
        result = await self.db.execute(query)
        total = result.scalar_one_or_none() or 0
        return int(total)
