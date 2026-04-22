"""
Mission comment service — create/read/update/delete with auto-enqueue and auto-comment.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
# TODO: Phase 4/5 cleanup - MissionExecutionStatus removed; migrate to string literals
# from app.models.execution import MissionExecutionStatus
MissionExecutionStatus = type("MissionExecutionStatus", (), {
    "QUEUED": "queued", "DISPATCHED": "dispatched", "RUNNING": "running",
    "INTERRUPT_WAIT": "interrupt_wait", "APPROVAL_WAIT": "approval_wait",
    "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"
})()
from app.models.mission import AssigneeType, Mission, MissionStatus
from app.models.mission_comment import CommentAuthorType, CommentType, MissionComment
from app.repositories.mission import MissionRepository
from app.repositories.mission_comment import MissionCommentRepository


class MissionCommentService:
    """Manages mission comments and the comment→execution enqueue flow."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MissionCommentRepository(db)
        self.mission_repo = MissionRepository(db)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_comment(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_type: CommentAuthorType,
        author_id: str,
        content: str,
        comment_type: CommentType = CommentType.COMMENT,
        parent_comment_id: Optional[uuid.UUID] = None,
    ) -> tuple[MissionComment, Mission, bool, list[uuid.UUID]]:
        """Returns (comment, mission, should_dispatch_assignee, mentioned_agent_ids)."""
        mission = await self.mission_repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            raise NotFoundException(f"Mission not found: {mission_id}")

        if parent_comment_id is not None:
            parent = await self.repo.get(parent_comment_id)
            if parent and parent.parent_comment_id is not None:
                parent_comment_id = parent.parent_comment_id

        comment = MissionComment(
            mission_id=mission_id,
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
            should_dispatch = self._should_enqueue_on_comment(mission)

            from app.utils.mentions import agent_mentions

            mentions = agent_mentions(content)
            seen: set[uuid.UUID] = set()
            for m in mentions:
                if m.id != mission.assignee_id and m.id not in seen:
                    seen.add(m.id)
                    mentioned_agent_ids.append(m.id)

        return comment, mission, should_dispatch, mentioned_agent_ids

    async def list_comments(
        self,
        *,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[MissionComment], bool, Optional[str]]:
        """Return (comments, has_more, next_cursor)."""
        mission = await self.mission_repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            raise NotFoundException(f"Mission not found: {mission_id}")

        cursor_dt = None
        if cursor:
            cursor_dt = datetime.fromisoformat(cursor)

        comments = list(await self.repo.list_by_mission(mission_id, cursor=cursor_dt, limit=limit + 1, order_asc=True))

        has_more = len(comments) > limit
        if has_more:
            comments = comments[:limit]

        next_cursor = comments[-1].created_at.isoformat() if has_more and comments else None
        return comments, has_more, next_cursor

    async def _get_owned_comment(
        self,
        comment_id: uuid.UUID,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> Optional[MissionComment]:
        """Return the comment if it exists and belongs to the author, else None.
        Raises PermissionError if the comment exists but belongs to another user."""
        mission = await self.mission_repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            return None
        comment = await self.repo.get_by_id_and_mission(comment_id, mission_id)
        if not comment:
            return None
        if comment.author_id != author_id:
            raise PermissionError("Only the author can modify this comment")
        return comment

    async def update_comment(
        self,
        *,
        comment_id: uuid.UUID,
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
        content: str,
    ) -> Optional[MissionComment]:
        comment = await self._get_owned_comment(comment_id, mission_id, workspace_id, author_id)
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
        mission_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_id: str,
    ) -> bool:
        comment = await self._get_owned_comment(comment_id, mission_id, workspace_id, author_id)
        if not comment:
            return False
        await self.db.delete(comment)
        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Enqueue logic
    # ------------------------------------------------------------------

    @staticmethod
    def _should_enqueue_on_comment(mission: Mission) -> bool:
        if mission.assignee_type != AssigneeType.AGENT or mission.assignee_id is None:
            return False
        if mission.status in {MissionStatus.DONE, MissionStatus.CANCELLED, MissionStatus.BACKLOG}:
            return False
        # If there's already a running execution, skip — the dedup index only
        # covers queued/dispatched. We avoid creating a second concurrent execution.
        if mission.current_execution_id is not None and mission.status == MissionStatus.IN_PROGRESS:
            return False
        return True

    # ------------------------------------------------------------------
    # Auto-comment on execution completion/failure
    # ------------------------------------------------------------------

    async def post_execution_comment(
        self,
        *,
        execution,
        result_status: MissionExecutionStatus,
        result_output: str = "",
        error_message: str = "",
    ) -> Optional[MissionComment]:
        """Called by ExecutionRunner after finalization to auto-post agent comments."""
        if not execution.mission_id or not execution.agent_profile_id:
            return None

        agent_id = str(execution.agent_profile_id)

        if result_status == MissionExecutionStatus.COMPLETED:
            # Skip auto-comment for comment-triggered assignee executions
            # (the assignee is continuing conversational work).
            # Mention executions (non-assignee agents) still get auto-comments.
            if execution.trigger_comment_id:
                mission = await self.mission_repo.get_by_id_and_workspace(execution.mission_id, execution.workspace_id)
                if mission and str(mission.assignee_id) == agent_id:
                    return None
            if execution.started_at:
                already = await self.repo.has_agent_commented_since(
                    execution.mission_id, agent_id, execution.started_at
                )
                if already:
                    return None
            content = result_output.strip() if result_output else "Execution completed."
            comment_type = CommentType.PROGRESS_UPDATE

        elif result_status == MissionExecutionStatus.FAILED:
            content = error_message.strip() if error_message else "Execution failed."
            comment_type = CommentType.SYSTEM

        else:
            return None

        comment = MissionComment(
            mission_id=execution.mission_id,
            workspace_id=execution.workspace_id,
            author_type=CommentAuthorType.AGENT,
            author_id=agent_id,
            content=content[:5000],
            type=comment_type,
            parent_comment_id=None,
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)
        logger.info(f"Auto-posted {comment_type.value} comment {comment.id} for execution {execution.id}")
        return comment
