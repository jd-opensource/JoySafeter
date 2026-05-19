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
        max_turns: int = 20,
    ) -> list[tuple[str, str]]:
        """Return ``(role, content)`` pairs in chronological order for a thread.

        Only succeeded runs before ``before_run_id`` contribute. Role is
        ``"user"`` for each run's goal, ``"assistant"`` for its concatenated
        ASSISTANT_TEXT event payloads.

        ``max_turns`` caps the number of *prior runs* pulled back — session
        recovery pays linear cost in history length, and feeding the CLI a
        1000-turn transcript is worse than forgetting ancient context.
        """
        # Build a before-cutoff subquery so we can do the whole history in
        # one round trip — no correlated fetch of ``before_run_id.created_at``.
        cutoff = None
        if before_run_id is not None:
            cutoff = select(AgentRun.created_at).where(AgentRun.id == before_run_id).scalar_subquery()

        runs_stmt = select(AgentRun.id, AgentRun.goal, AgentRun.created_at).where(
            AgentRun.thread_id == thread_id,
            AgentRun.status == "succeeded",
        )
        if cutoff is not None:
            runs_stmt = runs_stmt.where(AgentRun.created_at < cutoff)
        # Pull the *latest* max_turns succeeded runs, then reverse for chron
        # order. DESC limit is cheaper than ASC+OFFSET on long threads.
        runs_stmt = runs_stmt.order_by(AgentRun.created_at.desc()).limit(max_turns)
        rows = list((await self.db.execute(runs_stmt)).all())
        if not rows:
            return []
        rows.reverse()
        run_ids = [row[0] for row in rows]

        # Single IN query for all assistant-text events across those runs.
        events_stmt = (
            select(
                Execution.run_id,
                ExecutionEvent.payload,
                ExecutionEvent.created_at,
                ExecutionEvent.sequence_no,
            )
            .join(Execution, Execution.id == ExecutionEvent.execution_id)
            .where(
                Execution.run_id.in_(run_ids),
                ExecutionEvent.event_type == ExecutionEventType.ASSISTANT_TEXT.value,
            )
            .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.sequence_no.asc())
        )
        assistant_by_run: dict[uuid.UUID, list[str]] = {}
        for run_id, payload, *_ in (await self.db.execute(events_stmt)).all():
            if isinstance(payload, dict):
                content = payload.get("content")
                if content:
                    assistant_by_run.setdefault(run_id, []).append(str(content))

        history: list[tuple[str, str]] = []
        for run_id, goal, _ in rows:
            if goal:
                history.append(("user", goal))
            chunks = assistant_by_run.get(run_id)
            if chunks:
                history.append(("assistant", "".join(chunks)))
        return history
