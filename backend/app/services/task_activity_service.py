"""
Task activity service — create/read/update/delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import NotFoundError
from app.models.task import Task, TaskStatus
from app.models.task_activity import ActivityAuthorType, ActivityType, TaskActivity
from app.repositories.task import TaskRepository
from app.repositories.task_activity import TaskActivityRepository


class TaskActivityService:
    """Manages task activities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskActivityRepository(db)
        self.task_repo = TaskRepository(db)

    async def create_activity(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_type: ActivityAuthorType,
        author_id: str,
        content: str,
        activity_type: ActivityType = ActivityType.COMMENT,
        parent_activity_id: Optional[uuid.UUID] = None,
    ) -> tuple[TaskActivity, Task, bool, list[uuid.UUID]]:
        """Returns (activity, task, should_dispatch_agent, mentioned_agent_ids)."""
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})

        if parent_activity_id is not None:
            parent = await self.repo.get(parent_activity_id)
            if parent and parent.parent_activity_id is not None:
                parent_activity_id = parent.parent_activity_id

        activity = TaskActivity(
            task_id=task_id,
            workspace_id=workspace_id,
            author_type=author_type,
            author_id=author_id,
            content=content,
            type=activity_type,
            parent_activity_id=parent_activity_id,
        )
        self.db.add(activity)
        await self.db.commit()
        await self.db.refresh(activity)

        should_dispatch = False
        mentioned_agent_ids: list[uuid.UUID] = []

        if author_type == ActivityAuthorType.MEMBER and activity_type == ActivityType.COMMENT:
            should_dispatch = self._should_enqueue_on_activity(task)

            from app.utils.mentions import agent_mentions

            mentions = agent_mentions(content)
            seen: set[uuid.UUID] = set()
            for m in mentions:
                if m.id != task.agent_id and m.id not in seen:
                    seen.add(m.id)
                    mentioned_agent_ids.append(m.id)

        return activity, task, should_dispatch, mentioned_agent_ids

    async def list_activities(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[TaskActivity], bool, Optional[str]]:
        """Return (activities, has_more, next_cursor)."""
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND", data={"task_id": str(task_id)})

        cursor_dt = None
        if cursor:
            cursor_dt = datetime.fromisoformat(cursor)

        activities = list(await self.repo.list_by_task(task_id, cursor=cursor_dt, limit=limit + 1, order_asc=True))

        has_more = len(activities) > limit
        if has_more:
            activities = activities[:limit]

        next_cursor = activities[-1].created_at.isoformat() if has_more and activities else None
        return activities, has_more, next_cursor

    async def _get_owned_activity(
        self,
        activity_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> Optional[TaskActivity]:
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            return None
        activity = await self.repo.get_by_id_and_task(activity_id, task_id)
        if not activity:
            return None
        if activity.author_id != author_id:
            raise PermissionError("Only the author can modify this activity")
        return activity

    async def update_activity(
        self,
        *,
        activity_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
        content: str,
    ) -> Optional[TaskActivity]:
        activity = await self._get_owned_activity(activity_id, task_id, workspace_id, author_id)
        if not activity:
            return None
        activity.content = content
        await self.db.commit()
        await self.db.refresh(activity)
        return activity

    async def delete_activity(
        self,
        *,
        activity_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> bool:
        activity = await self._get_owned_activity(activity_id, task_id, workspace_id, author_id)
        if not activity:
            return False
        await self.db.delete(activity)
        await self.db.commit()
        return True

    @staticmethod
    def _should_enqueue_on_activity(task: Task) -> bool:
        if task.agent_id is None:
            return False
        if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BACKLOG}:
            return False
        if task.latest_run_id is not None and task.status == TaskStatus.IN_PROGRESS:
            return False
        return True

    async def post_run_activity(
        self,
        *,
        run,
        result_status: str,
        result_output: str = "",
        error_message: str = "",
    ) -> Optional[TaskActivity]:
        """Auto-post agent activity after run completion."""
        if not run.task_id:
            return None

        agent_id = str(run.created_by) if run.created_by else None
        if not agent_id:
            return None

        if result_status == "succeeded":
            if run.started_at:
                already = await self.repo.has_agent_posted_since(run.task_id, agent_id, run.started_at)
                if already:
                    return None
            content = result_output.strip() if result_output else "Run completed."
            activity_type = ActivityType.PROGRESS_UPDATE
        elif result_status == "failed":
            content = error_message.strip() if error_message else "Run failed."
            activity_type = ActivityType.SYSTEM
        else:
            return None

        # Need workspace_id — fetch task
        from sqlalchemy import select

        from app.models.task import Task

        result = await self.db.execute(select(Task).where(Task.id == run.task_id))
        task = result.scalar_one_or_none()
        if not task:
            return None

        activity = TaskActivity(
            task_id=run.task_id,
            workspace_id=task.workspace_id,
            author_type=ActivityAuthorType.AGENT,
            author_id=agent_id,
            content=content[:5000],
            type=activity_type,
            parent_activity_id=None,
        )
        self.db.add(activity)
        await self.db.commit()
        await self.db.refresh(activity)
        logger.info(f"Auto-posted {activity_type.value} activity {activity.id} for run {run.id}")
        return activity

    async def post_execution_activity(
        self,
        *,
        execution,
        task_id: uuid.UUID,
        result_status: str,
        result_output: str = "",
        error_message: str = "",
    ) -> Optional[TaskActivity]:
        """Post an activity after execution completion."""
        agent_id = str(execution.agent_id) if hasattr(execution, "agent_id") and execution.agent_id else None
        if not agent_id:
            # Try to get from created_by
            agent_id = str(execution.created_by) if hasattr(execution, "created_by") and execution.created_by else None
        if not agent_id:
            return None

        if result_status == "succeeded":
            if hasattr(execution, "started_at") and execution.started_at:
                already = await self.repo.has_agent_posted_since(task_id, agent_id, execution.started_at)
                if already:
                    return None
            content = result_output.strip() if result_output else "Execution completed."
            activity_type = ActivityType.PROGRESS_UPDATE
        elif result_status == "failed":
            content = error_message.strip() if error_message else "Execution failed."
            activity_type = ActivityType.SYSTEM
        else:
            return None

        # Need workspace_id — fetch task
        from sqlalchemy import select

        from app.models.task import Task

        result = await self.db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return None

        activity = TaskActivity(
            task_id=task_id,
            workspace_id=task.workspace_id,
            author_type=ActivityAuthorType.AGENT,
            author_id=agent_id,
            content=content[:5000],
            type=activity_type,
            parent_activity_id=None,
        )
        self.db.add(activity)
        await self.db.commit()
        await self.db.refresh(activity)
        logger.info(f"Auto-posted {activity_type.value} activity {activity.id} for execution {execution.id}")
        return activity
