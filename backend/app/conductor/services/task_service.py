import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.task import ConductorTask, TaskStatus, TERMINAL_STATUSES
from app.utils.datetime import utc_now


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task(
        self,
        agent_id: uuid.UUID,
        prompt: str,
        system_prompt: Optional[str] = None,
        chat_session_id: Optional[uuid.UUID] = None,
        timeout_sec: int = 7200,
        max_retries: int = 2,
    ) -> ConductorTask:
        task = ConductorTask(
            agent_id=agent_id,
            prompt=prompt,
            system_prompt=system_prompt,
            chat_session_id=chat_session_id,
            status=TaskStatus.PENDING.value,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get_task(self, task_id: uuid.UUID) -> Optional[ConductorTask]:
        result = await self.db.execute(
            select(ConductorTask).where(ConductorTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def list_tasks_by_agent(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[ConductorTask], bool]:
        q = select(ConductorTask).where(ConductorTask.agent_id == agent_id)
        if after_id:
            q = q.where(ConductorTask.id < after_id)
        q = q.order_by(ConductorTask.created_at.desc()).limit(limit + 1)
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
    ) -> tuple[list[ConductorTask], bool]:
        q = select(ConductorTask)
        conditions = []
        if agent_id:
            conditions.append(ConductorTask.agent_id == agent_id)
        if session_id:
            conditions.append(ConductorTask.chat_session_id == session_id)
        if status:
            conditions.append(ConductorTask.status == status)
        if after_id:
            conditions.append(ConductorTask.id < after_id)
        if conditions:
            q = q.where(and_(*conditions))
        q = q.order_by(ConductorTask.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        tasks = list(result.scalars().all())
        has_more = len(tasks) > limit
        return tasks[:limit], has_more

    async def cancel_task(self, task_id: uuid.UUID) -> Optional[ConductorTask]:
        task = await self.get_task(task_id)
        if not task:
            return None
        status = TaskStatus(task.status)
        if status.is_terminal():
            raise ValueError(f"Task already in terminal state: {task.status}")
        task.status = TaskStatus.CANCELLED.value
        task.completed_at = utc_now()
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def claim_task_for_scheduling(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status == TaskStatus.PENDING.value,
                )
            )
            .values(status=TaskStatus.SCHEDULING.value, started_at=func.now())
        )
        await self.db.commit()
        return result.rowcount > 0

    async def append_task_output(self, task_id: uuid.UUID, chunk: str) -> None:
        await self.db.execute(
            text("UPDATE conductor_tasks SET output = output || :chunk WHERE id = :id"),
            {"chunk": chunk, "id": task_id},
        )
        await self.db.commit()

    async def update_task_chat_session(self, task_id: uuid.UUID, session_id: uuid.UUID) -> None:
        await self.db.execute(
            update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(chat_session_id=session_id)
        )
        await self.db.commit()

    async def reset_sandbox_tasks_to_pending(self, sandbox_id: uuid.UUID) -> int:
        result = await self.db.execute(
            update(ConductorTask)
            .where(
                and_(
                    ConductorTask.status == TaskStatus.SCHEDULING.value,
                    ConductorTask.sandbox_id == sandbox_id,
                )
            )
            .values(
                status=TaskStatus.PENDING.value,
                started_at=None,
                retry_count=ConductorTask.retry_count + 1,
            )
        )
        await self.db.commit()
        return result.rowcount

    async def list_running_tasks(self) -> list:
        result = await self.db.execute(
            select(ConductorTask)
            .where(ConductorTask.status == TaskStatus.RUNNING.value)
            .order_by(ConductorTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending_tasks(self) -> list:
        result = await self.db.execute(
            select(ConductorTask)
            .where(ConductorTask.status == TaskStatus.PENDING.value)
            .order_by(ConductorTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        new_status: TaskStatus,
    ) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        now = utc_now()

        if new_status == TaskStatus.RUNNING:
            result = await self.db.execute(
                update(ConductorTask)
                .where(
                    and_(
                        ConductorTask.id == task_id,
                        ConductorTask.status.in_([TaskStatus.PENDING.value, TaskStatus.SCHEDULING.value]),
                    )
                )
                .values(status=new_status.value, started_at=now)
            )
        elif new_status.is_terminal():
            task_row = (await self.db.execute(
                select(ConductorTask.started_at).where(ConductorTask.id == task_id)
            )).scalar_one_or_none()
            duration_ms = None
            if task_row is not None:
                duration_ms = int((now - task_row).total_seconds() * 1000)
            result = await self.db.execute(
                update(ConductorTask)
                .where(
                    and_(
                        ConductorTask.id == task_id,
                        ConductorTask.status.notin_(terminal_values),
                    )
                )
                .values(status=new_status.value, completed_at=now, duration_ms=duration_ms)
            )
        else:
            result = await self.db.execute(
                update(ConductorTask)
                .where(
                    and_(
                        ConductorTask.id == task_id,
                        ConductorTask.status.notin_(terminal_values),
                    )
                )
                .values(status=new_status.value)
            )
        await self.db.commit()
        return result.rowcount > 0

    async def update_task_error(
        self,
        task_id: uuid.UUID,
        error: str,
        new_status: TaskStatus,
    ) -> bool:
        """CAS-guarded error update. Status must be terminal. Returns True if the row was updated."""
        assert new_status.is_terminal(), f"update_task_error called with non-terminal status: {new_status}"
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        now = utc_now()
        task_row = (await self.db.execute(
            select(ConductorTask.started_at).where(ConductorTask.id == task_id)
        )).scalar_one_or_none()
        duration_ms = None
        if task_row is not None:
            duration_ms = int((now - task_row).total_seconds() * 1000)
        result = await self.db.execute(
            update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status.notin_(terminal_values),
                )
            )
            .values(error=error, status=new_status.value, completed_at=now, duration_ms=duration_ms)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def update_task_output(self, task_id: uuid.UUID, output: str) -> None:
        await self.db.execute(
            update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(output=output)
        )
        await self.db.commit()

    async def update_task_usage(self, task_id: uuid.UUID, usage: dict) -> None:
        await self.db.execute(
            update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(usage=usage)
        )
        await self.db.commit()

    async def update_task_sandbox(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> None:
        await self.db.execute(
            update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(sandbox_id=sandbox_id)
        )
        await self.db.commit()

    async def increment_retry(self, task_id: uuid.UUID) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        result = await self.db.execute(
            update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status.notin_(terminal_values),
                )
            )
            .values(
                retry_count=ConductorTask.retry_count + 1,
                status=TaskStatus.PENDING.value,
                started_at=None,
                sandbox_id=None,
            )
        )
        await self.db.commit()
        return result.rowcount > 0

    async def agent_has_active_tasks(self, agent_id: uuid.UUID) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        result = await self.db.execute(
            select(func.count())
            .select_from(ConductorTask)
            .where(
                and_(
                    ConductorTask.agent_id == agent_id,
                    ConductorTask.status.notin_(terminal_values),
                )
            )
        )
        return result.scalar() > 0

    async def find_overdue_tasks(self, cutoff: datetime) -> list[ConductorTask]:
        result = await self.db.execute(
            select(ConductorTask).where(
                and_(
                    ConductorTask.status == TaskStatus.RUNNING.value,
                    ConductorTask.started_at.isnot(None),
                    text(
                        "started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                    ),
                )
            )
        )
        return list(result.scalars().all())

    async def find_stuck_scheduling(self, cutoff: datetime) -> list[ConductorTask]:
        result = await self.db.execute(
            select(ConductorTask).where(
                and_(
                    ConductorTask.status == TaskStatus.SCHEDULING.value,
                    ConductorTask.updated_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())
