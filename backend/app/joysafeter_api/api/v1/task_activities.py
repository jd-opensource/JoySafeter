"""Task Activities API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import NotFoundError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.task_activity import ActivityAuthorType, ActivityType
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.task_activity import (
    CreateTaskActivityRequest,
    TaskActivityListResponse,
    TaskActivityResponse,
    UpdateTaskActivityRequest,
)
from app.joysafeter_api.services import TaskActivityService
from app.joysafeter_api.websocket.notification_manager import NotificationType, notification_manager

router = APIRouter(prefix="/v1/tasks/{task_id}/activities", tags=["Task Activities"])


@router.get("", response_model=BaseResponse[TaskActivityListResponse])
async def list_activities(
    task_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityListResponse]:
    service = TaskActivityService(db)
    activities, has_more, next_cursor = await service.list_activities(
        task_id=task_id,
        project_id=auth_ctx.project_id,
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityResponse]:
    service = TaskActivityService(db)
    activity, task, should_dispatch, mentioned_agent_ids = await service.create_activity(
        task_id=task_id,
        project_id=auth_ctx.project_id,
        author_type=ActivityAuthorType.MEMBER,
        author_id=auth_ctx.user_id,
        content=request.content,
        activity_type=ActivityType.COMMENT,
        parent_activity_id=request.parent_activity_id,
    )

    # Trigger executions via orchestrator
    if should_dispatch or mentioned_agent_ids:
        from app.joysafeter_api.services import DispatchService

        dispatch = DispatchService(db)
        if should_dispatch:
            await dispatch.dispatch_task(
                task_id=task.id,
                user_id=auth_ctx.user_id,
                prompt_override=activity.content,
            )
        if mentioned_agent_ids:
            # For mentioned agents, dispatch the same task
            await dispatch.dispatch_task(
                task_id=task.id,
                user_id=auth_ctx.user_id,
            )

    # Push notification to task creator (if not the commenter)
    if task.creator_id != auth_ctx.user_id:
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[TaskActivityResponse]:
    service = TaskActivityService(db)
    activity = await service.update_activity(
        activity_id=activity_id,
        task_id=task_id,
        project_id=auth_ctx.project_id,
        author_id=auth_ctx.user_id,
        content=request.content,
    )

    if not activity:
        raise NotFoundError(
            "Activity not found", code="TASK_ACTIVITY_NOT_FOUND", data={"activity_id": str(activity_id)}
        )

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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[None]:
    service = TaskActivityService(db)
    deleted = await service.delete_activity(
        activity_id=activity_id,
        task_id=task_id,
        project_id=auth_ctx.project_id,
        author_id=auth_ctx.user_id,
    )

    if not deleted:
        raise NotFoundError(
            "Activity not found", code="TASK_ACTIVITY_NOT_FOUND", data={"activity_id": str(activity_id)}
        )
    return BaseResponse(success=True, code=200, msg="Activity deleted", data=None)
