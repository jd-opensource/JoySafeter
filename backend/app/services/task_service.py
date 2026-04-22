"""
Task service layer — pure CRUD + status machine.

Execution dispatch logic lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestException, NotFoundException
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

    MANUAL_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.BACKLOG: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
        TaskStatus.IN_PROGRESS: {
            TaskStatus.IN_REVIEW,
            TaskStatus.DONE,
            TaskStatus.CANCELLED,
        },
        TaskStatus.IN_REVIEW: {
            TaskStatus.IN_PROGRESS,
            TaskStatus.DONE,
            TaskStatus.CANCELLED,
        },
        TaskStatus.DONE: {TaskStatus.BACKLOG},
        TaskStatus.CANCELLED: {TaskStatus.BACKLOG},
    }

    @classmethod
    def get_transitions(cls) -> dict[str, list[str]]:
        return {status.value: sorted(t.value for t in targets) for status, targets in cls.MANUAL_TRANSITIONS.items()}

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
                raise BadRequestException(f"Invalid status: {new_status}")

            if new_status != task.status:
                allowed_targets = self.MANUAL_TRANSITIONS.get(task.status, set())
                if new_status not in allowed_targets:
                    raise BadRequestException(f"Cannot transition from {task.status.value} to {new_status.value}")

        allowed = {
            "title",
            "description",
            "goal",
            "priority",
            "status",
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

    async def assign_to_agent(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Task:
        """Assign a task to an agent."""
        task = await self.repo.get_for_update(task_id, workspace_id)
        if not task:
            raise NotFoundException(f"Task not found: {task_id}")

        task.agent_id = agent_id
        if task.status == TaskStatus.BACKLOG:
            task.status = TaskStatus.IN_PROGRESS
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"Assigned task {task_id} to agent {agent_id}")
        return task

    async def sync_status_from_run(self, task_id: uuid.UUID, workspace_id: uuid.UUID, run: Any) -> Optional[Task]:
        """Auto-update task status based on run status."""
        task = await self.repo.get_for_update(task_id, workspace_id)
        if not task:
            return None

        if run.status in ("queued", "running"):
            task.status = TaskStatus.IN_PROGRESS
        elif run.status == "succeeded":
            task.status = TaskStatus.DONE
        elif run.status == "failed":
            task.status = TaskStatus.IN_REVIEW
        elif run.status == "cancelled":
            task.status = TaskStatus.BACKLOG

        task.latest_run_id = run.id
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(f"Synced task {task_id} status to {task.status.value} from run {run.id}")
        return task
