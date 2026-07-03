"""
Task service layer — pure CRUD + status machine (v2 JoySafeterTask).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, cast

from sqlalchemy import and_, func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES as TERMINAL_STATUSES,
)
from app.joysafeter_domain.models.joysafeter_task import (
    JoySafeterTask,
    JoySafeterTaskStatus,
)
from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine


class JoySafeterTaskService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.state_machine = JoySafeterTaskStateMachine(db)

    async def create_task(
        self,
        agent_id: uuid.UUID,
        prompt: str,
        system_prompt: Optional[str] = None,
        chat_session_id: Optional[uuid.UUID] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
        project_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> JoySafeterTask:
        values: dict[str, Any] = dict(
            agent_id=agent_id,
            prompt=prompt,
            system_prompt=system_prompt,
            chat_session_id=chat_session_id,
            status=JoySafeterTaskStatus.PENDING.value,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
        if project_id is not None:
            values["project_id"] = project_id

        if idempotency_key is None:
            task = JoySafeterTask(**values)
            self.db.add(task)
            await self.db.commit()
            await self.db.refresh(task)
            return task

        # Idempotent submission: one key -> one task, even under concurrent
        # retries from HA API replicas. INSERT ... ON CONFLICT DO NOTHING makes
        # the unique constraint the arbiter; on conflict we return the existing task.
        values["idempotency_key"] = idempotency_key
        stmt = (
            pg_insert(JoySafeterTask)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(JoySafeterTask.id)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        row = result.first()
        if row is not None:
            task_id = row[0]
        else:
            task_id = (
                await self.db.execute(
                    select(JoySafeterTask.id).where(JoySafeterTask.idempotency_key == idempotency_key)
                )
            ).scalar_one()
        fetched = await self.get_task(task_id)
        assert fetched is not None
        return fetched

    async def get_by_idempotency_key(
        self, idempotency_key: str, project_id: Optional[str] = None
    ) -> Optional[JoySafeterTask]:
        """Return the task previously created with this idempotency key, if any.

        Lets the API short-circuit a retried submission before doing other work
        (e.g. auto-creating a ChatSession), keeping the whole endpoint idempotent,
        not just the task INSERT.
        """
        conditions = [JoySafeterTask.idempotency_key == idempotency_key]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(select(JoySafeterTask).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def get_task(self, task_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterTask]:
        conditions = [JoySafeterTask.id == task_id]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(select(JoySafeterTask).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_tasks_by_agent(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[JoySafeterTask], bool]:
        q = select(JoySafeterTask).where(JoySafeterTask.agent_id == agent_id)
        if after_id:
            q = q.where(JoySafeterTask.id < after_id)
        q = q.order_by(JoySafeterTask.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        tasks = list(result.scalars().all())
        has_more = len(tasks) > limit
        return tasks[:limit], has_more

    async def list_tasks(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
        agent_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterTask], bool]:
        q = select(JoySafeterTask)
        conditions = []
        if agent_id:
            conditions.append(JoySafeterTask.agent_id == agent_id)
        if session_id:
            conditions.append(JoySafeterTask.chat_session_id == session_id)
        if status:
            conditions.append(JoySafeterTask.status == status)
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        if after_id:
            conditions.append(JoySafeterTask.id < after_id)
        if conditions:
            q = q.where(and_(*conditions))
        q = q.order_by(JoySafeterTask.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        tasks = list(result.scalars().all())
        has_more = len(tasks) > limit
        return tasks[:limit], has_more

    async def cancel_task(self, task_id: uuid.UUID) -> Optional[JoySafeterTask]:
        return await self.state_machine.cancel(task_id)

    async def claim_task_for_scheduling(self, task_id: uuid.UUID) -> bool:
        return await self.state_machine.claim_for_scheduling(task_id)

    async def claim_pending_tasks_for_scheduling(self, limit: int) -> list[uuid.UUID]:
        return await self.state_machine.claim_pending_batch(limit)

    async def append_task_output(self, task_id: uuid.UUID, chunk: str) -> None:
        await self.db.execute(
            text("UPDATE joysafeter_tasks SET output = output || :chunk WHERE id = :id"),
            {"chunk": chunk, "id": task_id},
        )
        await self.db.commit()

    async def update_task_chat_session(self, task_id: uuid.UUID, session_id: uuid.UUID) -> None:
        await self.db.execute(
            sa_update(JoySafeterTask).where(JoySafeterTask.id == task_id).values(chat_session_id=session_id)
        )
        await self.db.commit()

    async def reset_sandbox_tasks_to_pending(self, sandbox_id: uuid.UUID) -> int:
        return await self.state_machine.reset_sandbox_scheduling_to_pending(sandbox_id)

    async def list_running_tasks(self) -> list:
        result = await self.db.execute(
            select(JoySafeterTask)
            .where(JoySafeterTask.status == JoySafeterTaskStatus.RUNNING.value)
            .order_by(JoySafeterTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending_tasks(self) -> list:
        result = await self.db.execute(
            select(JoySafeterTask)
            .where(JoySafeterTask.status == JoySafeterTaskStatus.PENDING.value)
            .order_by(JoySafeterTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def next_scheduling_task_for_sandbox(self, sandbox_id: uuid.UUID) -> Optional[uuid.UUID]:
        result = await self.db.execute(
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.sandbox_id == sandbox_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                )
            )
            .order_by(JoySafeterTask.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_next_sandbox_task_for_running(self, sandbox_id: uuid.UUID) -> Optional[tuple[uuid.UUID, int]]:
        return await self.state_machine.claim_next_sandbox_task_for_running(sandbox_id)

    async def list_recoverable_tasks_by_sandbox(self, sandbox_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.db.execute(
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.sandbox_id == sandbox_id,
                    JoySafeterTask.status.in_(
                        [
                            JoySafeterTaskStatus.SCHEDULING.value,
                            JoySafeterTaskStatus.RUNNING.value,
                        ]
                    ),
                )
            )
            .order_by(JoySafeterTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_active_tasks_by_session(
        self,
        session_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> list[JoySafeterTask]:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        conditions = [
            JoySafeterTask.chat_session_id == session_id,
            JoySafeterTask.status.notin_(terminal_values),
        ]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterTask).where(and_(*conditions)).order_by(JoySafeterTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        new_status: JoySafeterTaskStatus,
        expected_epoch: Optional[int] = None,
    ) -> bool:
        return await self.state_machine.transition_to(task_id, new_status, expected_epoch=expected_epoch)

    async def update_task_error(
        self,
        task_id: uuid.UUID,
        error: str,
        new_status: JoySafeterTaskStatus,
        expected_epoch: Optional[int] = None,
    ) -> bool:
        return await self.state_machine.fail_with_error(task_id, error, new_status, expected_epoch=expected_epoch)

    async def update_task_output(self, task_id: uuid.UUID, output: str, expected_epoch: Optional[int] = None) -> bool:
        return await self.state_machine.update_output(task_id, output, expected_epoch=expected_epoch)

    async def update_task_usage(self, task_id: uuid.UUID, usage: dict, expected_epoch: Optional[int] = None) -> bool:
        return await self.state_machine.update_usage(task_id, usage, expected_epoch=expected_epoch)

    async def update_task_sandbox(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> None:
        await self.db.execute(
            sa_update(JoySafeterTask).where(JoySafeterTask.id == task_id).values(sandbox_id=sandbox_id)
        )
        await self.db.commit()

    async def attach_sandbox_if_scheduling(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> bool:
        return await self.state_machine.attach_sandbox_if_scheduling(task_id, sandbox_id)

    async def increment_retry(self, task_id: uuid.UUID) -> bool:
        return await self.state_machine.retry(task_id)

    async def agent_has_active_tasks(self, agent_id: uuid.UUID) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.notin_(terminal_values),
                )
            )
        )
        return cast(int, result.scalar()) > 0

    async def count_active_tasks_for_project(self, project_id: str) -> int:
        """Count the project's non-terminal tasks (pending/scheduling/running).

        This is the quantity admission control is gated on: a single tenant
        (project) must not occupy unbounded fleet capacity. Terminal tasks
        (completed/failed/cancelled) do not count against the live budget.
        """
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.project_id == project_id,
                    JoySafeterTask.status.notin_(terminal_values),
                )
            )
        )
        return cast(int, result.scalar())

    async def resolve_project_task_limit(self, project_id: str, default_limit: int) -> int:
        """The effective concurrent-task limit for a project.

        A project may carry a per-project override (``max_concurrent_tasks``);
        when unset (NULL) the caller's global default applies. Kept free of the
        global settings singleton so the decision is a pure function of the row
        plus the passed default — trivially testable.
        """
        override = await self.db.execute(select(Project.max_concurrent_tasks).where(Project.id == project_id))
        value = override.scalar_one_or_none()
        if value is None:
            return default_limit
        return cast(int, value)

    async def find_overdue_tasks(self, cutoff: datetime) -> list[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.status == JoySafeterTaskStatus.RUNNING.value,
                    JoySafeterTask.started_at.isnot(None),
                    text("started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"),
                )
            )
        )
        return list(result.scalars().all())

    async def find_stuck_scheduling(self, cutoff: datetime) -> list[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                    JoySafeterTask.updated_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())
