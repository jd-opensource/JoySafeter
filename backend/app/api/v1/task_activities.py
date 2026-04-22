"""Task Activities API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_workspace_role
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.task_activity import ActivityAuthorType, ActivityType
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.task_activity import (
    CreateTaskActivityRequest,
    TaskActivityListResponse,
    TaskActivityResponse,
    UpdateTaskActivityRequest,
)
from app.services.task_activity_service import TaskActivityService
from app.websocket.notification_manager import NotificationType, notification_manager

router = APIRouter(prefix="/v1/tasks/{task_id}/activities", tags=["Task Activities"])


@router.get("", response_model=BaseResponse[TaskActivityListResponse])
async def list_activities(
    task_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityListResponse]:
    service = TaskActivityService(db)
    activities, has_more, next_cursor = await service.list_activities(
        task_id=task_id,
        workspace_id=workspace_id,
        cursor=cursor,
        limit=limit,
    )

    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=TaskActivityListResponse(
            items=[TaskActivityResponse.model_validate(a) for a in activities],
            has_more=has_more,
            next_cursor=next_cursor,
        ),
    )


@router.post("", response_model=BaseResponse[TaskActivityResponse])
async def create_activity(
    task_id: uuid.UUID,
    request: CreateTaskActivityRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityResponse]:
    service = TaskActivityService(db)
    activity, task, should_dispatch, mentioned_agent_ids = await service.create_activity(
        task_id=task_id,
        workspace_id=workspace_id,
        author_type=ActivityAuthorType.MEMBER,
        author_id=str(current_user.id),
        content=request.content,
        activity_type=ActivityType.COMMENT,
        parent_activity_id=request.parent_activity_id,
    )

    # Trigger executions via orchestrator
    if should_dispatch or mentioned_agent_ids:
        from app.core.engine.orchestrator import ExecutionOrchestrator

        orchestrator = ExecutionOrchestrator(db)
        if should_dispatch:
            await orchestrator.dispatch_task(
                task_id=task.id,
                user_id=str(current_user.id),
                prompt_override=activity.content,
            )
        if mentioned_agent_ids:
            # For mentioned agents, dispatch the same task
            await orchestrator.dispatch_task(
                task_id=task.id,
                user_id=str(current_user.id),
            )

    # Push notification to task creator (if not the commenter)
    if task.creator_id != str(current_user.id):
        await notification_manager.send_to_user(
            task.creator_id,
            {
                "type": NotificationType.TASK_ACTIVITY_ADDED.value,
                "task_id": str(task_id),
                "activity_id": str(activity.id),
                "author_type": activity.author_type.value,
                "author_id": activity.author_id,
            },
        )

    return BaseResponse(
        success=True,
        code=200,
        msg="Activity created",
        data=TaskActivityResponse.model_validate(activity),
    )


@router.patch("/{activity_id}", response_model=BaseResponse[TaskActivityResponse])
async def update_activity(
    task_id: uuid.UUID,
    activity_id: uuid.UUID,
    request: UpdateTaskActivityRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityResponse]:
    service = TaskActivityService(db)
    activity = await service.update_activity(
        activity_id=activity_id,
        task_id=task_id,
        workspace_id=workspace_id,
        author_id=str(current_user.id),
        content=request.content,
    )

    if not activity:
        return BaseResponse(success=False, code=404, msg="Activity not found", data=None)

    return BaseResponse(
        success=True,
        code=200,
        msg="Activity updated",
        data=TaskActivityResponse.model_validate(activity),
    )


@router.delete("/{activity_id}", response_model=BaseResponse[None])
async def delete_activity(
    task_id: uuid.UUID,
    activity_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[None]:
    service = TaskActivityService(db)
    deleted = await service.delete_activity(
        activity_id=activity_id,
        task_id=task_id,
        workspace_id=workspace_id,
        author_id=str(current_user.id),
    )

    if not deleted:
        return BaseResponse(success=False, code=404, msg="Activity not found", data=None)
    return BaseResponse(success=True, code=200, msg="Activity deleted", data=None)
