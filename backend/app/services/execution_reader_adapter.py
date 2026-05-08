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

from app.common.app_errors import NotFoundError
from app.core.events.event_types import ExecutionEventType
from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution, ExecutionEvent
from app.models.task import Task


class ExecutionReaderAdapter:
    """Implements ExecutionReaderPort — read-only DB queries for core/."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_execution(self, execution_id: uuid.UUID) -> Execution:
        result = await self.db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if not execution:
            raise NotFoundError(
                "Execution not found",
                code="EXECUTION_NOT_FOUND",
                data={"execution_id": str(execution_id)},
            )
        return execution

    async def get_run_for_execution(self, execution_id: uuid.UUID) -> AgentRun:
        result = await self.db.execute(
            select(AgentRun).join(Execution, Execution.run_id == AgentRun.id).where(Execution.id == execution_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundError(
                "Agent run not found for execution",
                code="AGENT_RUN_NOT_FOUND",
                data={"execution_id": str(execution_id)},
            )
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

    async def load_thread_history(
        self,
        thread_id: uuid.UUID,
        *,
        before_run_id: Optional[uuid.UUID] = None,
    ) -> list[tuple[str, str]]:
        """Return ``(role, content)`` pairs in chronological order for a thread.

        Only completed runs before ``before_run_id`` contribute. ``role`` is
        ``"user"`` for USER_MESSAGE events and ``"assistant"`` for
        ASSISTANT_TEXT events.
        """
        completed_runs_stmt = select(AgentRun.id, AgentRun.goal, AgentRun.created_at).where(
            AgentRun.thread_id == thread_id,
            AgentRun.status == "completed",
        )
        if before_run_id is not None:
            # Exclude the current run and any that were created after it.
            before_stmt = select(AgentRun.created_at).where(AgentRun.id == before_run_id)
            before_created = (await self.db.execute(before_stmt)).scalar_one_or_none()
            if before_created is not None:
                completed_runs_stmt = completed_runs_stmt.where(AgentRun.created_at < before_created)
        completed_runs_stmt = completed_runs_stmt.order_by(AgentRun.created_at.asc())
        runs = (await self.db.execute(completed_runs_stmt)).all()

        history: list[tuple[str, str]] = []
        for run_id, goal, _ in runs:
            # Goal carries the user's turn input.
            if goal:
                history.append(("user", goal))

            # Drain assistant text events for this run's executions, in order.
            events_stmt = (
                select(ExecutionEvent.payload)
                .join(Execution, Execution.id == ExecutionEvent.execution_id)
                .where(
                    Execution.run_id == run_id,
                    ExecutionEvent.event_type == ExecutionEventType.ASSISTANT_TEXT.value,
                )
                .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.sequence_no.asc())
            )
            payloads = (await self.db.execute(events_stmt)).scalars().all()
            assistant_chunks = [
                str(p.get("content", "")) for p in payloads if isinstance(p, dict) and p.get("content")
            ]
            if assistant_chunks:
                history.append(("assistant", "".join(assistant_chunks)))

        return history
