"""
Repository for Execution and ExecutionEvent.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Execution, ExecutionEvent

from .base import BaseRepository


class ExecutionRepository(BaseRepository[Execution]):
    def __init__(self, db: AsyncSession):
        super().__init__(Execution, db)

    async def list_by_run(self, run_id: uuid.UUID) -> List[Execution]:
        """List all executions for a run, ordered by attempt_index."""
        query = (
            select(Execution)
            .where(Execution.run_id == run_id)
            .order_by(Execution.attempt_index.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_max_attempt(self, run_id: uuid.UUID) -> int:
        """Get the max attempt_index for a given run."""
        query = select(func.coalesce(func.max(Execution.attempt_index), 0)).where(
            Execution.run_id == run_id
        )
        result = await self.db.execute(query)
        return result.scalar() or 0


class ExecutionEventRepository(BaseRepository[ExecutionEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(ExecutionEvent, db)

    async def list_by_execution(
        self, execution_id: uuid.UUID, limit: int = 500
    ) -> List[ExecutionEvent]:
        """List events for an execution, ordered by sequence_no."""
        query = (
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.sequence_no.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
