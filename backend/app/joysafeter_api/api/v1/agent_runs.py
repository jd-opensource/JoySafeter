"""Agent Runs API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.agent_run import (
    AgentRunResponse,
    CreateAgentRunRequest,
    CreateDraftAgentRunRequest,
)
from app.joysafeter_api.services import AgentRunService
from app.joysafeter_api.services import DispatchService

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


def _to_response(run) -> AgentRunResponse:
    return AgentRunResponse.model_validate(run)


@router.get("", response_model=BaseResponse[List[AgentRunResponse]])
async def list_runs(
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    release_id: uuid.UUID | None = Query(None),
    task_id: uuid.UUID | None = Query(None),
    agent_id: uuid.UUID | None = Query(None),
    trigger_medium: str | None = Query(None),
    run_purpose: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentRunResponse]]:
    """List runs filtered by project context."""
    service = AgentRunService(db)
    runs = await service.list_runs(
        project_id=auth_ctx.project_id,
        release_id=release_id,
        task_id=task_id,
        agent_id=agent_id,
        trigger_medium=trigger_medium,
        run_purpose=run_purpose,
        status=status,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_to_response(r) for r in runs],
    )


@router.post("", response_model=BaseResponse[AgentRunResponse])
async def create_run(
    request: CreateAgentRunRequest,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Create a new agent run via the unified orchestrator."""
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")

    dispatch = DispatchService(db)
    run = await dispatch.dispatch_direct(
        release_id=request.release_id,
        prompt=request.goal or "",
        user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        trigger_medium=request.trigger_medium,
        run_purpose=request.run_purpose,
        thread_id=request.thread_id,
        task_id=request.task_id,
        input_payload=request.input_payload,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="Run created",
        data=_to_response(run),
    )


@router.post("/draft", response_model=BaseResponse[AgentRunResponse])
async def create_draft_run(
    request: CreateDraftAgentRunRequest,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Create a Test Lab run against an agent draft version, not an active release."""
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")

    dispatch = DispatchService(db)
    run = await dispatch.dispatch_draft(
        agent_id=request.agent_id,
        version_id=request.version_id,
        prompt=request.goal or "",
        user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        thread_id=request.thread_id,
        input_payload=request.input_payload,
    )
    return BaseResponse(
        success=True,
        code=200,
        msg="Draft run created",
        data=_to_response(run),
    )


@router.get("/{run_id}", response_model=BaseResponse[AgentRunResponse])
async def get_run(
    run_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Get a run by ID."""
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    if run.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Run not found")
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(run))


@router.post("/{run_id}/cancel", response_model=BaseResponse[AgentRunResponse])
async def cancel_run(
    run_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Cancel a run."""
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    if run.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Run not found")
    dispatch = DispatchService(db)
    run = await dispatch.cancel_run(run_id)
    return BaseResponse(success=True, code=200, msg="Run cancelled", data=_to_response(run))


@router.post("/{run_id}/retry", response_model=BaseResponse[AgentRunResponse])
async def retry_run(
    run_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Retry a run by creating a new execution attempt."""
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    if run.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Run not found")
    dispatch = DispatchService(db)
    run = await dispatch.retry_run(run_id, auth_ctx.user_id)
    return BaseResponse(success=True, code=200, msg="Run retried", data=_to_response(run))
