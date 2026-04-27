"""
Task service layer — pure CRUD + status machine.

Execution dispatch logic lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.core.state_machines.engine import InvalidTransition
from app.core.state_machines.transitions import transition_task
from app.models.task import Task, TaskPriority, TaskStatus
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
        description: Optional[str] = None,
        goal: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NONE,
        agent_id: Optional[uuid.UUID] = None,
        parent_task_id: Optional[uuid.UUID] = None,
        tags: Optional[list] = None,
        position: float = 0.0,
        auto_approve: bool = False,
    ) -> Task:
        task = Task(
            workspace_id=workspace_id,
            creator_id=creator_id,
            title=title,
            description=description,
            goal=goal,
            priority=priority,
            status=TaskStatus.BACKLOG,
            agent_id=agent_id,
            parent_task_id=parent_task_id,
            tags=tags,
            position=position,
            auto_approve=auto_approve,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"Created task: {task.id} ({title})")
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
