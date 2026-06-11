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

from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError
from app.joysafeter_domain.state_machines.engine import InvalidTransition
from app.joysafeter_domain.state_machines.transitions import transition_task
from app.joysafeter_domain.models.task import Task, TaskPriority, TaskStatus
from app.joysafeter_domain.models.thread import Thread
from app.joysafeter_domain.repositories.task import TaskRepository


class TaskService:
    """Manages task CRUD and status transitions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskRepository(db)

    async def create_task(
        self,
        *,
        project_id: str,
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
        thread = Thread(
            agent_id=agent_id,
            project_id=project_id,
            title=title,
            status="active",
            created_by=creator_id,
        )
        self.db.add(thread)
        await self.db.flush()

        task = Task(
            project_id=project_id,
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

    async def get_task(self, task_id: uuid.UUID, project_id: str) -> Optional[Task]:
        return await self.repo.get_by_id_and_project(task_id, project_id)

    async def list_tasks(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
        agent_id: Optional[uuid.UUID] = None,
        parent_task_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[Task]:
        if project_id:
            return list(
                await self.repo.list_by_project(
                    project_id=project_id,
                    status=status,
                    creator_id=creator_id,
                    agent_id=agent_id,
                    limit=limit,
                )
            )
        return []

    @classmethod
    def get_transitions(cls) -> dict[str, list[str]]:
        from app.joysafeter_domain.state_machines.definitions import TASK_STATES

        return {status: sorted(targets) for status, targets in TASK_STATES.items()}

    async def update_task(
        self,
        task_id: uuid.UUID,
        project_id: str,
        **kwargs: Any,
    ) -> Optional[Task]:
        task = await self.repo.get_by_id_and_project(task_id, project_id)
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
        project_id: str,
        agent_id: uuid.UUID,
    ) -> Task:
        """Assign a task to an agent."""
        from app.joysafeter_domain.state_machines.transitions import transition_task

        task = await self.repo.get_for_update_by_project(task_id, project_id)
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
# JoySafeter Task Service
# ---------------------------------------------------------------------------

from datetime import datetime  # noqa: E402
from sqlalchemy import and_, func, text, update as sa_update  # noqa: E402

from app.joysafeter_domain.models.task import JoySafeterTask, JoySafeterTaskStatus, JOYSAFETER_TERMINAL_STATUSES as TERMINAL_STATUSES  # noqa: E402
from app.joysafeter_shared.utils.datetime import utc_now  # noqa: E402
from app.joysafeter_domain.services.joysafeter_task_state_machine import JoySafeterTaskStateMachine  # noqa: E402


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
    ) -> JoySafeterTask:
        kwargs = dict(
            agent_id=agent_id,
            prompt=prompt,
            system_prompt=system_prompt,
            chat_session_id=chat_session_id,
            status=JoySafeterTaskStatus.PENDING.value,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
        if project_id is not None:
            kwargs["project_id"] = project_id
        task = JoySafeterTask(**kwargs)
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def get_task(
        self, task_id: uuid.UUID, project_id: Optional[str] = None
    ) -> Optional[JoySafeterTask]:
        conditions = [JoySafeterTask.id == task_id]
        if project_id is not None:
            conditions.append(JoySafeterTask.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterTask).where(and_(*conditions))
        )
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
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id == task_id)
            .values(chat_session_id=session_id)
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

    async def next_scheduling_task_for_sandbox(
        self, sandbox_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
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

    async def claim_next_sandbox_task_for_running(
        self, sandbox_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        return await self.state_machine.claim_next_sandbox_task_for_running(sandbox_id)

    async def list_recoverable_tasks_by_sandbox(
        self, sandbox_id: uuid.UUID
    ) -> list[uuid.UUID]:
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
            select(JoySafeterTask)
            .where(and_(*conditions))
            .order_by(JoySafeterTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        new_status: JoySafeterTaskStatus,
    ) -> bool:
        return await self.state_machine.transition_to(task_id, new_status)

    async def update_task_error(
        self,
        task_id: uuid.UUID,
        error: str,
        new_status: JoySafeterTaskStatus,
    ) -> bool:
        return await self.state_machine.fail_with_error(task_id, error, new_status)

    async def update_task_output(self, task_id: uuid.UUID, output: str) -> None:
        await self.db.execute(
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id == task_id)
            .values(output=output)
        )
        await self.db.commit()

    async def update_task_usage(self, task_id: uuid.UUID, usage: dict) -> None:
        await self.db.execute(
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id == task_id)
            .values(usage=usage)
        )
        await self.db.commit()

    async def update_task_sandbox(self, task_id: uuid.UUID, sandbox_id: uuid.UUID) -> None:
        await self.db.execute(
            sa_update(JoySafeterTask)
            .where(JoySafeterTask.id == task_id)
            .values(sandbox_id=sandbox_id)
        )
        await self.db.commit()

    async def attach_sandbox_if_scheduling(
        self, task_id: uuid.UUID, sandbox_id: uuid.UUID
    ) -> bool:
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
        return result.scalar() > 0

    async def find_overdue_tasks(self, cutoff: datetime) -> list[JoySafeterTask]:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.status == JoySafeterTaskStatus.RUNNING.value,
                    JoySafeterTask.started_at.isnot(None),
                    text(
                        "started_at + (COALESCE(timeout_sec, 7200) * interval '1 second') < NOW()"
                    ),
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
