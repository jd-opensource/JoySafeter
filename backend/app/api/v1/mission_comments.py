"""Mission Comments API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.common.exceptions import BadRequestException
from app.core.database import get_db
from app.models.mission_comment import CommentAuthorType, CommentType
from app.schemas import BaseResponse
from app.schemas.mission_comment import (
    CreateMissionCommentRequest,
    MissionCommentListResponse,
    MissionCommentResponse,
    UpdateMissionCommentRequest,
)
from app.services.mission_comment_service import MissionCommentService
from app.websocket.notification_manager import NotificationType, notification_manager

router = APIRouter(prefix="/v1/missions/{mission_id}/comments", tags=["Mission Comments"])


@router.get("", response_model=BaseResponse[MissionCommentListResponse])
async def list_comments(
    mission_id: uuid.UUID,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionCommentListResponse]:
    service = MissionCommentService(db)
    try:
        comments, has_more, next_cursor = await service.list_comments(
            mission_id=mission_id,
            workspace_id=workspace_id,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise BadRequestException(str(exc))

    return BaseResponse(
        success=True, code=200, msg="ok",
        data=MissionCommentListResponse(
            items=[MissionCommentResponse.model_validate(c) for c in comments],
            has_more=has_more,
            next_cursor=next_cursor,
        ),
    )


@router.post("", response_model=BaseResponse[MissionCommentResponse])
async def create_comment(
    mission_id: uuid.UUID,
    request: CreateMissionCommentRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionCommentResponse]:
    service = MissionCommentService(db)
    try:
        comment, mission = await service.create_comment(
            mission_id=mission_id,
            workspace_id=workspace_id,
            author_type=CommentAuthorType.MEMBER,
            author_id=str(current_user.id),
            content=request.content,
            comment_type=CommentType.COMMENT,
            parent_comment_id=request.parent_comment_id,
        )
    except ValueError as exc:
        raise BadRequestException(str(exc))

    # Push notification to mission creator (if not the commenter)
    if mission.creator_id != str(current_user.id):
        await notification_manager.send_to_user(mission.creator_id, {
            "type": NotificationType.MISSION_COMMENT_ADDED.value,
            "mission_id": str(mission_id),
            "comment_id": str(comment.id),
            "author_type": comment.author_type.value,
            "author_id": comment.author_id,
        })

    return BaseResponse(
        success=True, code=200, msg="Comment created",
        data=MissionCommentResponse.model_validate(comment),
    )


@router.patch("/{comment_id}", response_model=BaseResponse[MissionCommentResponse])
async def update_comment(
    mission_id: uuid.UUID,
    comment_id: uuid.UUID,
    request: UpdateMissionCommentRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionCommentResponse]:
    service = MissionCommentService(db)
    try:
        comment = await service.update_comment(
            comment_id=comment_id,
            mission_id=mission_id,
            workspace_id=workspace_id,
            author_id=str(current_user.id),
            content=request.content,
        )
    except PermissionError as exc:
        raise BadRequestException(str(exc))

    if not comment:
        return BaseResponse(success=False, code=404, msg="Comment not found", data=None)

    return BaseResponse(
        success=True, code=200, msg="Comment updated",
        data=MissionCommentResponse.model_validate(comment),
    )


@router.delete("/{comment_id}", response_model=BaseResponse[None])
async def delete_comment(
    mission_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[None]:
    service = MissionCommentService(db)
    try:
        deleted = await service.delete_comment(
            comment_id=comment_id,
            mission_id=mission_id,
            workspace_id=workspace_id,
            author_id=str(current_user.id),
        )
    except PermissionError as exc:
        raise BadRequestException(str(exc))

    if not deleted:
        return BaseResponse(success=False, code=404, msg="Comment not found", data=None)
    return BaseResponse(success=True, code=200, msg="Comment deleted", data=None)
