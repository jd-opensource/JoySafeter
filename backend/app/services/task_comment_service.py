"""
Task comment service — create/read/update/delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.models.task import Task, TaskStatus
from app.models.task_comment import CommentAuthorType, CommentType, TaskComment
from app.repositories.task import TaskRepository
from app.repositories.task_comment import TaskCommentRepository


class TaskCommentService:
    """Manages task comments."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TaskCommentRepository(db)
        self.task_repo = TaskRepository(db)

    async def create_comment(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_type: CommentAuthorType,
        author_id: str,
        content: str,
        comment_type: CommentType = CommentType.COMMENT,
        parent_comment_id: Optional[uuid.UUID] = None,
    ) -> tuple[TaskComment, Task, bool, list[uuid.UUID]]:
        """Returns (comment, task, should_dispatch_agent, mentioned_agent_ids)."""
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            raise NotFoundException(f"Task not found: {task_id}")

        if parent_comment_id is not None:
            parent = await self.repo.get(parent_comment_id)
            if parent and parent.parent_comment_id is not None:
                parent_comment_id = parent.parent_comment_id

        comment = TaskComment(
            task_id=task_id,
            workspace_id=workspace_id,
            author_type=author_type,
            author_id=author_id,
            content=content,
            type=comment_type,
            parent_comment_id=parent_comment_id,
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)

        should_dispatch = False
        mentioned_agent_ids: list[uuid.UUID] = []

        if author_type == CommentAuthorType.MEMBER and comment_type == CommentType.COMMENT:
            should_dispatch = self._should_enqueue_on_comment(task)

            from app.utils.mentions import agent_mentions

            mentions = agent_mentions(content)
            seen: set[uuid.UUID] = set()
            for m in mentions:
                if m.id != task.agent_id and m.id not in seen:
                    seen.add(m.id)
                    mentioned_agent_ids.append(m.id)

        return comment, task, should_dispatch, mentioned_agent_ids

    async def list_comments(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[TaskComment], bool, Optional[str]]:
        """Return (comments, has_more, next_cursor)."""
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            raise NotFoundException(f"Task not found: {task_id}")

        cursor_dt = None
        if cursor:
            cursor_dt = datetime.fromisoformat(cursor)

        comments = list(await self.repo.list_by_task(task_id, cursor=cursor_dt, limit=limit + 1, order_asc=True))

        has_more = len(comments) > limit
        if has_more:
            comments = comments[:limit]

        next_cursor = comments[-1].created_at.isoformat() if has_more and comments else None
        return comments, has_more, next_cursor

    async def _get_owned_comment(
        self,
        comment_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> Optional[TaskComment]:
        task = await self.task_repo.get_by_id_and_workspace(task_id, workspace_id)
        if not task:
            return None
        comment = await self.repo.get_by_id_and_task(comment_id, task_id)
        if not comment:
            return None
        if comment.author_id != author_id:
            raise PermissionError("Only the author can modify this comment")
        return comment

    async def update_comment(
        self,
        *,
        comment_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
        content: str,
    ) -> Optional[TaskComment]:
        comment = await self._get_owned_comment(comment_id, task_id, workspace_id, author_id)
        if not comment:
            return None
        comment.content = content
        await self.db.commit()
        await self.db.refresh(comment)
        return comment

    async def delete_comment(
        self,
        *,
        comment_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> bool:
        comment = await self._get_owned_comment(comment_id, task_id, workspace_id, author_id)
        if not comment:
            return False
        await self.db.delete(comment)
        await self.db.commit()
        return True

    @staticmethod
    def _should_enqueue_on_comment(task: Task) -> bool:
        if task.agent_id is None:
            return False
        if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BACKLOG}:
            return False
        if task.latest_run_id is not None and task.status == TaskStatus.IN_PROGRESS:
            return False
        return True

    async def post_run_comment(
        self,
        *,
        run,
        result_status: str,
        result_output: str = "",
        error_message: str = "",
    ) -> Optional[TaskComment]:
        """Auto-post agent comment after run completion."""
        if not run.task_id:
            return None

        agent_id = str(run.created_by) if run.created_by else None
        if not agent_id:
            return None

        if result_status == "succeeded":
            if run.started_at:
                already = await self.repo.has_agent_commented_since(run.task_id, agent_id, run.started_at)
                if already:
                    return None
            content = result_output.strip() if result_output else "Run completed."
            comment_type = CommentType.PROGRESS_UPDATE
        elif result_status == "failed":
            content = error_message.strip() if error_message else "Run failed."
            comment_type = CommentType.SYSTEM
        else:
            return None

        # Need workspace_id — fetch task
        from sqlalchemy import select
        from app.models.task import Task
        result = await self.db.execute(select(Task).where(Task.id == run.task_id))
        task = result.scalar_one_or_none()
        if not task:
            return None

        comment = TaskComment(
            task_id=run.task_id,
            workspace_id=task.workspace_id,
            author_type=CommentAuthorType.AGENT,
            author_id=agent_id,
            content=content[:5000],
            type=comment_type,
            parent_comment_id=None,
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)
        logger.info(f"Auto-posted {comment_type.value} comment {comment.id} for run {run.id}")
        return comment
