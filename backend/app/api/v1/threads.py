"""Threads API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, require_workspace_role
from app.common.exceptions import BadRequestException, ForbiddenException
from app.core.database import get_db
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.models.agent_run import AgentRun
from app.models.auth import AuthUser as User
from app.models.execution import Artifact, Execution
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.artifact import ArtifactResponse
from app.schemas.thread import (
    ChatRequest,
    ChatResponse,
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


# ---------------------------------------------------------------------------
# Chat: send message + dispatch agent run (single call)
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/chat", response_model=BaseResponse[ChatResponse])
async def chat(
    thread_id: uuid.UUID,
    request: ChatRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ChatResponse]:
    """Send a user message and dispatch an agent run in one call.

    The user message is NOT written directly to ThreadMessage.
    Instead it flows through the event bus as a `user_message` event,
    and MessageProjectionSubscriber materializes it into ThreadMessage.
    ExecutionEvent is the single source of truth.
    """
    has_access = await check_workspace_access(
        db, workspace_id, current_user, WorkspaceMemberRole.member,
    )
    if not has_access:
        raise ForbiddenException("No access to workspace")

    active_run = (await db.execute(
        select(AgentRun).where(
            AgentRun.thread_id == thread_id,
            AgentRun.status.in_(["pending", "running"]),
        )
    )).scalar_one_or_none()
    if active_run:
        raise BadRequestException("Thread has an active run, please wait for it to complete")

    # 1. Create run + execution first (so we have execution_id for the event)
    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_chat(
        thread_id=thread_id,
        message=request.message,
        user_id=str(current_user.id),
    )

    # 2. Emit user_message as the first event in this execution.
    #    MessageProjectionSubscriber will project it into ThreadMessage.
    from app.core.events import ExecutionEventEnvelope, execution_event_bus
    from app.utils.datetime import utc_now

    user_msg_envelope = ExecutionEventEnvelope(
        execution_id=run.current_execution_id,
        run_id=run.id,
        workspace_id=workspace_id,
        event_type="user_message",
        payload={"text": request.message},
        created_at=utc_now(),
        trigger_source="chat",
        thread_id=thread_id,
    )
    await execution_event_bus.publish(user_msg_envelope, db)

    return BaseResponse(
        success=True,
        code=200,
        msg="Chat dispatched",
        data=ChatResponse(
            run_id=run.id,
            execution_id=run.current_execution_id,
        ),
    )


# ---------------------------------------------------------------------------
# Thread artifacts: aggregate across all runs/executions
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/artifacts", response_model=BaseResponse[List[ArtifactResponse]])
async def list_thread_artifacts(
    thread_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ArtifactResponse]]:
    """List all artifacts produced by runs in this thread."""
    artifacts = (await db.execute(
        select(Artifact)
        .join(Execution, Artifact.execution_id == Execution.id)
        .join(AgentRun, Execution.run_id == AgentRun.id)
        .where(AgentRun.thread_id == thread_id)
        .order_by(Artifact.created_at.desc())
    )).scalars().all()
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[ArtifactResponse.model_validate(a) for a in artifacts],
    )
