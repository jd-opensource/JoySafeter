"""
ExecutionService — manages Execution and ExecutionEvent entities.
"""

from __future__ import annotations

import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.models.execution import Execution, ExecutionEvent
from app.repositories.execution import ExecutionEventRepository, ExecutionRepository


class ExecutionService:
    """Manages Execution and ExecutionEvent entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.execution_repo = ExecutionRepository(db)
        self.event_repo = ExecutionEventRepository(db)

    async def get_execution(self, execution_id: uuid.UUID) -> Execution:
        """Get an execution by ID."""
        execution = await self.execution_repo.get(execution_id)
        if not execution:
            raise NotFoundException(f"Execution {execution_id} not found")
        return execution

    async def list_executions(self, run_id: uuid.UUID) -> List[Execution]:
        """List all executions for a run."""
        return await self.execution_repo.list_by_run(run_id)

    async def list_events(self, execution_id: uuid.UUID) -> List[ExecutionEvent]:
        """List all events for an execution."""
        return await self.event_repo.list_by_execution(execution_id)
