"""
ExecutionReaderAdapter — implements ExecutionReaderPort.

Wraps the DB queries that ExecutionRunner previously did inline,
so core/ no longer needs direct ORM access.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.models.task import Task


class ExecutionReaderAdapter:
    """Implements ExecutionReaderPort — read-only DB queries for core/."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_execution(self, execution_id: uuid.UUID) -> Execution:
        result = await self.db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")
        return execution

    async def get_run_for_execution(self, execution_id: uuid.UUID) -> AgentRun:
        result = await self.db.execute(
            select(AgentRun).join(Execution, Execution.run_id == AgentRun.id).where(Execution.id == execution_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"AgentRun not found for execution: {execution_id}")
        return run

    async def get_release_for_run(self, run_id: uuid.UUID) -> Optional[AgentRelease]:
        result = await self.db.execute(
            select(AgentRelease).join(AgentRun, AgentRun.release_id == AgentRelease.id).where(AgentRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_task_auto_approve(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(select(Task.auto_approve).where(Task.id == task_id))
        val = result.scalar_one_or_none()
        return val if val is not None else True
