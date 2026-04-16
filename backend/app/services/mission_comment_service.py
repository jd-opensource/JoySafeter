"""
Mission comment service — create/read/update/delete with auto-enqueue and auto-comment.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionSource, MissionExecutionStatus
from app.models.mission import Mission, MissionStatus
from app.models.mission_comment import CommentAuthorType, CommentType, MissionComment
from app.repositories.agent_profile import AgentProfileRepository
from app.repositories.mission import MissionRepository
from app.repositories.mission_comment import MissionCommentRepository
from app.services.execution_service import ExecutionService


class MissionCommentService:
    """Manages mission comments and the comment→execution enqueue flow."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MissionCommentRepository(db)
        self.mission_repo = MissionRepository(db)
        self.agent_repo = AgentProfileRepository(db)
        self.execution_service = ExecutionService(db)

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
    ) -> tuple[MissionComment, Mission]:
        mission = await self.mission_repo.get_by_id_and_workspace(mission_id, workspace_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")

        # Single-level threading: collapse reply-to-reply to the root
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

        # Auto-enqueue: only member comments of type COMMENT trigger execution
        if author_type == CommentAuthorType.MEMBER and comment_type == CommentType.COMMENT:
            if self._should_enqueue_on_comment(mission):
                await self._enqueue_comment_execution(
                    mission=mission,
                    trigger_comment=comment,
                    user_id=author_id,
                )

        return comment, mission

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
            raise ValueError(f"Mission not found: {mission_id}")

        cursor_dt = None
        if cursor:
            cursor_dt = datetime.fromisoformat(cursor)

        comments = list(
            await self.repo.list_by_mission(
                mission_id, cursor=cursor_dt, limit=limit + 1, order_asc=True
            )
        )

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
        if mission.assignee_type != "agent" or mission.assignee_id is None:
            return False
        if mission.status in {MissionStatus.DONE, MissionStatus.CANCELLED}:
            return False
        # If there's already a running execution, skip — the dedup index only
        # covers queued/dispatched. We avoid creating a second concurrent execution.
        if mission.current_execution_id is not None and mission.status == MissionStatus.IN_PROGRESS:
            return False
        return True

    async def _enqueue_comment_execution(
        self,
        *,
        mission: Mission,
        trigger_comment: MissionComment,
        user_id: str,
    ) -> None:
        agent = await self.agent_repo.get_by_id_and_workspace(
            mission.assignee_id, mission.workspace_id  # type: ignore[arg-type]
        )
        if not agent:
            logger.warning(f"Agent {mission.assignee_id} not found, skipping enqueue")
            return

        try:
            execution = await self.execution_service.create_execution(
                workspace_id=mission.workspace_id,
                user_id=user_id,
                source=ExecutionSource.MISSION,
                source_id=str(mission.id),
                runtime_type=agent.runtime_type,
                title=mission.title,
                mission_id=mission.id,
                agent_profile_id=mission.assignee_id,
                runtime_config=agent.runtime_config,
                trigger_comment_id=trigger_comment.id,
            )
        except IntegrityError:
            await self.db.rollback()
            logger.info(
                f"Dedup: skipped enqueue for mission {mission.id}, "
                f"pending execution already exists"
            )
            return

        # Update mission state
        mission_for_update = await self.mission_repo.get_for_update(mission.id, mission.workspace_id)
        if mission_for_update:
            mission_for_update.current_execution_id = execution.id
            if mission_for_update.status not in {MissionStatus.IN_PROGRESS, MissionStatus.IN_REVIEW}:
                mission_for_update.status = MissionStatus.IN_PROGRESS
            await self.db.commit()

        # Build prompt with comment and fire runner
        from app.services.mission_service import build_execution_prompt, _start_execution_runner

        prompt = build_execution_prompt(mission, trigger_comment=trigger_comment)
        credentials = dict(agent.custom_env or {})
        _start_execution_runner(execution.id, prompt, credentials or None)

        logger.info(
            f"Comment-triggered execution {execution.id} for mission {mission.id} "
            f"(comment={trigger_comment.id})"
        )

    # ------------------------------------------------------------------
    # Auto-comment on execution completion/failure
    # ------------------------------------------------------------------

    @classmethod
    async def post_execution_comment(
        cls,
        *,
        db: AsyncSession,
        execution,
        result_status: MissionExecutionStatus,
        result_output: str = "",
        error_message: str = "",
    ) -> Optional[MissionComment]:
        """Called by ExecutionRunner after finalization to auto-post agent comments."""
        if not execution.mission_id or not execution.agent_profile_id:
            return None

        repo = MissionCommentRepository(db)
        agent_id = str(execution.agent_profile_id)

        if result_status == MissionExecutionStatus.COMPLETED:
            # Skip auto-comment if this was a comment-triggered execution
            if execution.trigger_comment_id:
                return None
            # Skip if agent already commented during this execution
            if execution.started_at:
                already = await repo.has_agent_commented_since(
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
        db.add(comment)
        await db.commit()
        await db.refresh(comment)
        logger.info(
            f"Auto-posted {comment_type.value} comment {comment.id} "
            f"for execution {execution.id}"
        )
        return comment
