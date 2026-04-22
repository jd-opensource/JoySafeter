"""Threads API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, require_workspace_role
from app.common.exceptions import ForbiddenException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.thread import (
    CreateMessageRequest,
    CreateThreadRequest,
    MessageResponse,
    ThreadDetailResponse,
    ThreadResponse,
    ThreadSummary,
    UpdateThreadRequest,
)
from app.services.thread_service import ThreadService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/threads", tags=["Threads"])


# ---------------------------------------------------------------------------
# Thread routes
# ---------------------------------------------------------------------------


@router.get("", response_model=BaseResponse[List[ThreadSummary]])
async def list_threads(
    agent_id: uuid.UUID = Query(...),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ThreadSummary]]:
    service = ThreadService(db)
    threads = await service.list_threads(agent_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[ThreadSummary.model_validate(t) for t in threads],
    )


@router.post("", response_model=BaseResponse[ThreadResponse])
async def create_thread(
    request: CreateThreadRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    service = ThreadService(db)
    thread = await service.create_thread(workspace_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Thread created", data=ThreadResponse.model_validate(thread))


@router.get("/{thread_id}", response_model=BaseResponse[ThreadDetailResponse])
async def get_thread(
    thread_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadDetailResponse]:
    service = ThreadService(db)
    thread = await service.get_thread_with_messages(thread_id)
    return BaseResponse(success=True, code=200, msg="ok", data=ThreadDetailResponse.model_validate(thread))


@router.patch("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def update_thread(
    thread_id: uuid.UUID,
    request: UpdateThreadRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.update_thread(thread_id, request)
    return BaseResponse(success=True, code=200, msg="Thread updated", data=ThreadResponse.model_validate(thread))


@router.delete("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def archive_thread(
    thread_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.archive_thread(thread_id)
    return BaseResponse(success=True, code=200, msg="Thread archived", data=ThreadResponse.model_validate(thread))


# ---------------------------------------------------------------------------
# Message sub-routes
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/messages", response_model=BaseResponse[List[MessageResponse]])
async def list_messages(
    thread_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[MessageResponse]]:
    service = ThreadService(db)
    messages = await service.list_messages(thread_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[MessageResponse.model_validate(m) for m in messages],
    )


@router.post("/{thread_id}/messages", response_model=BaseResponse[MessageResponse])
async def create_message(
    thread_id: uuid.UUID,
    request: CreateMessageRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MessageResponse]:
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    service = ThreadService(db)
    message = await service.create_message(thread_id, request)
    return BaseResponse(success=True, code=200, msg="Message created", data=MessageResponse.model_validate(message))
