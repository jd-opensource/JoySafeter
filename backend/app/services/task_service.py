"""
Task service layer — pure CRUD + status machine.

Execution dispatch logic lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.core.state_machines.engine import InvalidTransition
from app.core.state_machines.transitions import transition_task
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.thread import Thread
from app.repositories.task import TaskRepository


class TaskService:
    """Manages task CRUD and status transitions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskRepository(db)

    async def create_task(
        self,
        *,
        workspace_id: uuid.UUID,
        creator_id: str,
        title: str,
        agent_id: uuid.UUID,
        description: Optional[str] = None,
        goal: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NONE,
        parent_task_id: Optional[uuid.UUID] = None,
        tags: Optional[list] = None,
        position: float = 0.0,
        auto_approve: bool = False,
    ) -> Task:
        # Every Task owns exactly one Thread — the session root for all of its
        # runs (first attempt + retries). Built synchronously so the FK is
        # populated before the insert.
        thread = Thread(
            agent_id=agent_id,
            workspace_id=workspace_id,
            title=title,
            status="active",
            created_by=creator_id,
        )
        self.db.add(thread)
        await self.db.flush()

        task = Task(
            workspace_id=workspace_id,
            creator_id=creator_id,
            title=title,
            description=description,
            goal=goal,
            priority=priority,
            status=TaskStatus.BACKLOG,
            agent_id=agent_id,
            thread_id=thread.id,
            parent_task_id=parent_task_id,
            tags=tags,
            position=position,
            auto_approve=auto_approve,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"Created task: {task.id} ({title}) with thread {thread.id}")
        return task

    async def get_task(self, task_id: uuid.UUID, workspace_id: uuid.UUID) -> Optional[Task]:
        return await self.repo.get_by_id_and_workspace(task_id, workspace_id)

    async def list_tasks(
        self,
        *,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
        agent_id: Optional[uuid.UUID] = None,
        parent_task_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[Task]:
        return list(
            await self.repo.list_by_workspace(
                workspace_id=workspace_id,
                status=status,
                creator_id=creator_id,
                agent_id=agent_id,
                parent_task_id=parent_task_id,
                limit=limit,
            )
        )

    @classmethod
    def get_transitions(cls) -> dict[str, list[str]]:
        from app.core.state_machines.definitions import TASK_STATES

        return {status: sorted(targets) for status, targets in TASK_STATES.items()}

    async def update_task(
        self,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        **kwargs: Any,
    ) -> Optional[Task]:
        task = await self.repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            return None

        new_status = kwargs.get("status")
        if new_status is not None:
            try:
                new_status = TaskStatus(new_status)
            except ValueError:
                raise InvalidRequestError(
                    f"Invalid status: {new_status}",
                    code="TASK_STATUS_INVALID",
                    data={"status": str(new_status)},
                )

            if new_status != task.status:
                try:
                    await transition_task(task, new_status, self.db)
                except InvalidTransition:
                    from_status = task.status.value if hasattr(task.status, "value") else str(task.status)
                    to_status = new_status.value if hasattr(new_status, "value") else str(new_status)
                    raise InvalidRequestError(
                        f"Cannot transition from '{task.status}' to '{new_status}'",
                        code="TASK_STATUS_TRANSITION_INVALID",
                        data={"from_status": from_status, "to_status": to_status},
                    )

        allowed = {
            "title",
            "description",
            "goal",
            "priority",
            "agent_id",
            "parent_task_id",
            "due_date",
            "position",
            "tags",
            "auto_approve",
        }
        for key, value in kwargs.items():
            if key in allowed:
                setattr(task, key, value)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def cancel_task(self, task: Task) -> None:
        """Cancel a task that has no active run."""
        await transition_task(task, "cancelled", self.db)
        await self.db.commit()

    async def assign_to_agent(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Task:
        """Assign a task to an agent."""
        from app.core.state_machines.transitions import transition_task

        task = await self.repo.get_for_update(task_id, workspace_id)
        if not task:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})

        task.agent_id = agent_id
        # Only auto-transition to IN_PROGRESS from dispatchable states.
        # Tasks in DONE or CANCELLED must be moved back to BACKLOG explicitly
        # before they can be reassigned and re-dispatched.
        if task.status in (TaskStatus.BACKLOG, TaskStatus.TODO):
            await transition_task(task, "in_progress", self.db)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"Assigned task {task_id} to agent {agent_id}")
        return task


# ---------------------------------------------------------------------------
# Conductor Task Service (appended from app/conductor/services/task_service.py)
# ---------------------------------------------------------------------------

from datetime import datetime  # noqa: E402
from sqlalchemy import and_, func, text, update as sa_update  # noqa: E402

from app.models.task import ConductorTask, ConductorTaskStatus, CONDUCTOR_TERMINAL_STATUSES as TERMINAL_STATUSES  # noqa: E402
from app.utils.datetime import utc_now  # noqa: E402


class ConductorTaskService:
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
            status=ConductorTaskStatus.PENDING.value,
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
        status = ConductorTaskStatus(task.status)
        if status.is_terminal():
            raise ValueError(f"Task already in terminal state: {task.status}")
        task.status = ConductorTaskStatus.CANCELLED.value
        task.completed_at = utc_now()
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def claim_task_for_scheduling(self, task_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            sa_update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status == ConductorTaskStatus.PENDING.value,
                )
            )
            .values(status=ConductorTaskStatus.SCHEDULING.value, started_at=func.now())
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
            sa_update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(chat_session_id=session_id)
        )
        await self.db.commit()

    async def reset_sandbox_tasks_to_pending(self, sandbox_id: uuid.UUID) -> int:
        result = await self.db.execute(
            sa_update(ConductorTask)
            .where(
                and_(
                    ConductorTask.status == ConductorTaskStatus.SCHEDULING.value,
                    ConductorTask.sandbox_id == sandbox_id,
                )
            )
            .values(
                status=ConductorTaskStatus.PENDING.value,
                started_at=None,
                retry_count=ConductorTask.retry_count + 1,
            )
        )
        await self.db.commit()
        return result.rowcount

    async def list_running_tasks(self) -> list:
        result = await self.db.execute(
            select(ConductorTask)
            .where(ConductorTask.status == ConductorTaskStatus.RUNNING.value)
            .order_by(ConductorTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending_tasks(self) -> list:
        result = await self.db.execute(
            select(ConductorTask)
            .where(ConductorTask.status == ConductorTaskStatus.PENDING.value)
            .order_by(ConductorTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        new_status: ConductorTaskStatus,
    ) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        now = utc_now()

        if new_status == ConductorTaskStatus.RUNNING:
            result = await self.db.execute(
                sa_update(ConductorTask)
                .where(
                    and_(
                        ConductorTask.id == task_id,
                        ConductorTask.status.in_([ConductorTaskStatus.PENDING.value, ConductorTaskStatus.SCHEDULING.value]),
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
                sa_update(ConductorTask)
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
                sa_update(ConductorTask)
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
        new_status: ConductorTaskStatus,
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
            sa_update(ConductorTask)
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
            sa_update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(output=output)
        )
        await self.db.commit()

    async def update_task_usage(self, task_id: uuid.UUID, usage: dict) -> None:
        await self.db.execute(
            sa_update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(usage=usage)
        )
        await self.db.commit()

    async def update_task_sandbox(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> None:
        await self.db.execute(
            sa_update(ConductorTask)
            .where(ConductorTask.id == task_id)
            .values(sandbox_id=sandbox_id)
        )
        await self.db.commit()

    async def increment_retry(self, task_id: uuid.UUID) -> bool:
        terminal_values = [s.value for s in TERMINAL_STATUSES]
        result = await self.db.execute(
            sa_update(ConductorTask)
            .where(
                and_(
                    ConductorTask.id == task_id,
                    ConductorTask.status.notin_(terminal_values),
                )
            )
            .values(
                retry_count=ConductorTask.retry_count + 1,
                status=ConductorTaskStatus.PENDING.value,
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
                    ConductorTask.status == ConductorTaskStatus.RUNNING.value,
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
                    ConductorTask.status == ConductorTaskStatus.SCHEDULING.value,
                    ConductorTask.updated_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())
