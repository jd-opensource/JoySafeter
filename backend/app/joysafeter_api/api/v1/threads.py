"""Threads API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.agent_run import AgentRun
from app.joysafeter_domain.models.execution import Artifact, Execution
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.artifact import ArtifactResponse
from app.joysafeter_domain.schemas.thread import (
    ChatRequest,
    ChatResponse,
    CreateThreadRequest,
    ThreadEventResponse,
    ThreadEventsListResponse,
    ThreadResponse,
    ThreadSummary,
    UpdateThreadRequest,
)
from app.joysafeter_api.services import DispatchService
from app.joysafeter_api.services import ThreadService

router = APIRouter(prefix="/v1/threads", tags=["Threads"])


# ---------------------------------------------------------------------------
# Thread routes
# ---------------------------------------------------------------------------


@router.get("", response_model=BaseResponse[List[ThreadSummary]])
async def list_threads(
    agent_id: uuid.UUID = Query(...),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ThreadSummary]]:
    from app.joysafeter_api.services import AgentService
    agent_svc = AgentService(db)
    agent = await agent_svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")

    service = ThreadService(db)
    thread = await service.create_thread(auth_ctx.project_id, auth_ctx.user_id, request)
    return BaseResponse(success=True, code=200, msg="Thread created", data=ThreadResponse.model_validate(thread))


@router.get("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def get_thread(
    thread_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")
    return BaseResponse(success=True, code=200, msg="ok", data=ThreadResponse.model_validate(thread))


@router.patch("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def update_thread(
    thread_id: uuid.UUID,
    request: UpdateThreadRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")
    thread = await service.update_thread(thread_id, request)
    return BaseResponse(success=True, code=200, msg="Thread updated", data=ThreadResponse.model_validate(thread))


@router.delete("/{thread_id}", response_model=BaseResponse[ThreadResponse])
async def archive_thread(
    thread_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadResponse]:
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")
    thread = await service.archive_thread(thread_id)
    return BaseResponse(success=True, code=200, msg="Thread archived", data=ThreadResponse.model_validate(thread))


# ---------------------------------------------------------------------------
# Chat: send message + dispatch agent run (single call)
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/chat", response_model=BaseResponse[ChatResponse])
async def chat(
    thread_id: uuid.UUID,
    request: ChatRequest,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ChatResponse]:
    """Send a user message and dispatch an agent run in one call."""
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")

    # 1. Create run + execution first (so we have execution_id for the event)
    #    Orchestrator enforces the "one active run per thread" invariant.
    dispatch = DispatchService(db)
    run = await dispatch.dispatch_chat(
        thread_id=thread_id,
        message=request.message,
        user_id=auth_ctx.user_id,
    )

    # 2. Emit user_message as the first event in this execution.
    attachments = [att.model_dump() for att in request.attachments] if request.attachments else None
    # dispatch_chat always creates an execution
    assert run.current_execution_id is not None
    await dispatch.emit_user_message(
        run=run,
        execution_id=run.current_execution_id,
        message=request.message,
        attachments=attachments,
    )

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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ArtifactResponse]]:
    """List all artifacts produced by runs in this thread."""
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")
    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .join(Execution, Artifact.execution_id == Execution.id)
                .join(AgentRun, Execution.run_id == AgentRun.id)
                .where(AgentRun.thread_id == thread_id)
                .order_by(Artifact.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[ArtifactResponse.model_validate(a) for a in artifacts],
    )


# ---------------------------------------------------------------------------
# Thread events: aggregate execution events across all runs
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/events", response_model=BaseResponse[ThreadEventsListResponse])
async def list_thread_events(
    thread_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    after: uuid.UUID | None = Query(None, description="Cursor: event ID to paginate after"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ThreadEventsListResponse]:
    """List aggregated execution events across all runs in this thread."""
    service = ThreadService(db)
    thread = await service.get_thread(thread_id)
    if thread.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Thread not found")
    events, total = await service.list_thread_events(thread_id, after_id=after, limit=limit)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=ThreadEventsListResponse(
            events=[ThreadEventResponse(**e) for e in events],
            total=total,
        ),
    )
