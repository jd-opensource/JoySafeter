"""Task Comments API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_workspace_role
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.task_comment import CommentAuthorType, CommentType
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.task_comment import (
    CreateTaskCommentRequest,
    TaskCommentListResponse,
    TaskCommentResponse,
    UpdateTaskCommentRequest,
)
from app.services.task_comment_service import TaskCommentService
from app.websocket.notification_manager import NotificationType, notification_manager

router = APIRouter(prefix="/v1/tasks/{task_id}/comments", tags=["Task Comments"])


@router.get("", response_model=BaseResponse[TaskCommentListResponse])
async def list_comments(
    task_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskCommentListResponse]:
    service = TaskCommentService(db)
    comments, has_more, next_cursor = await service.list_comments(
        task_id=task_id,
        workspace_id=workspace_id,
        cursor=cursor,
        limit=limit,
    )

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=TaskCommentListResponse(
            items=[TaskCommentResponse.model_validate(c) for c in comments],
            has_more=has_more,
            next_cursor=next_cursor,
        ),
    )


@router.post("", response_model=BaseResponse[TaskCommentResponse])
async def create_comment(
    task_id: uuid.UUID,
    request: CreateTaskCommentRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskCommentResponse]:
    service = TaskCommentService(db)
    comment, task, should_dispatch, mentioned_agent_ids = await service.create_comment(
        task_id=task_id,
        workspace_id=workspace_id,
        author_type=CommentAuthorType.MEMBER,
        author_id=str(current_user.id),
        content=request.content,
        comment_type=CommentType.COMMENT,
        parent_comment_id=request.parent_comment_id,
    )

    # Trigger executions via lifecycle service
    if should_dispatch or mentioned_agent_ids:
        from app.services.execution_lifecycle_service import ExecutionLifecycleService

        lifecycle = ExecutionLifecycleService(db)
        if should_dispatch:
            await lifecycle.dispatch_for_comment(
                task=task,
                trigger_comment=comment,
                user_id=str(current_user.id),
            )
        if mentioned_agent_ids:
            await lifecycle.dispatch_for_mention(
                task=task,
                trigger_comment=comment,
                user_id=str(current_user.id),
            )

    # Push notification to task creator (if not the commenter)
    if task.creator_id != str(current_user.id):
        await notification_manager.send_to_user(
            task.creator_id,
            {
                "type": NotificationType.TASK_COMMENT_ADDED.value,
                "task_id": str(task_id),
                "comment_id": str(comment.id),
                "author_type": comment.author_type.value,
                "author_id": comment.author_id,
            },
        )

    return BaseResponse(
        success=True,
        code=200,
        msg="Comment created",
        data=TaskCommentResponse.model_validate(comment),
    )


@router.patch("/{comment_id}", response_model=BaseResponse[TaskCommentResponse])
async def update_comment(
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    request: UpdateTaskCommentRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskCommentResponse]:
    service = TaskCommentService(db)
    comment = await service.update_comment(
        comment_id=comment_id,
        task_id=task_id,
        workspace_id=workspace_id,
        author_id=str(current_user.id),
        content=request.content,
    )

    if not comment:
        return BaseResponse(success=False, code=404, msg="Comment not found", data=None)

    return BaseResponse(
        success=True,
        code=200,
        msg="Comment updated",
        data=TaskCommentResponse.model_validate(comment),
    )


@router.delete("/{comment_id}", response_model=BaseResponse[None])
async def delete_comment(
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[None]:
    service = TaskCommentService(db)
    deleted = await service.delete_comment(
        comment_id=comment_id,
        task_id=task_id,
        workspace_id=workspace_id,
        author_id=str(current_user.id),
    )

    if not deleted:
        return BaseResponse(success=False, code=404, msg="Comment not found", data=None)
    return BaseResponse(success=True, code=200, msg="Comment deleted", data=None)
