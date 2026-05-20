import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select, update, func
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
            .values(status=TaskStatus.SCHEDULING.value, updated_at=utc_now())
        )
        await self.db.commit()
        return result.rowcount > 0

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        new_status: TaskStatus,
        output: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[dict] = None,
        sandbox_id: Optional[uuid.UUID] = None,
    ) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        values: dict = {
            "status": new_status.value,
            "updated_at": utc_now(),
        }
        if output is not None:
            values["output"] = output
        if error is not None:
            values["error"] = error
        if usage is not None:
            values["usage"] = usage
        if sandbox_id is not None:
            values["sandbox_id"] = sandbox_id

        if new_status == TaskStatus.RUNNING:
            values["started_at"] = utc_now()
        if new_status.is_terminal():
            now = utc_now()
            values["completed_at"] = now
            from sqlalchemy import cast, extract, Integer as SAInteger
            values["duration_ms"] = cast(
                extract("epoch", func.now() - ConductorTask.started_at) * 1000,
                SAInteger,
            )

        result = await self.db.execute(
            update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status.notin_(terminal_values),
                )
            )
            .values(**values)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def increment_retry(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(
                retry_count=ConductorTask.retry_count + 1,
                status=TaskStatus.PENDING.value,
                updated_at=utc_now(),
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
                    ConductorTask.started_at < cutoff,
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
