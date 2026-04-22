"""Agent Runs API."""

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
from app.schemas.agent_run import AgentRunResponse, CreateAgentRunRequest
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.services.agent_run_service import AgentRunService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


def _to_response(run) -> AgentRunResponse:
    return AgentRunResponse.model_validate(run)


@router.get("", response_model=BaseResponse[List[AgentRunResponse]])
async def list_runs(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID | None = Query(None),
    release_id: uuid.UUID | None = Query(None),
    task_id: uuid.UUID | None = Query(None, alias="task_id"),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentRunResponse]]:
    """List runs filtered by workspace_id, release_id, or mission_id."""
    service = AgentRunService(db)
    runs = await service.list_runs(
        workspace_id=workspace_id,
        release_id=release_id,
        task_id=task_id,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Create a new agent run via the unified orchestrator."""
    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_direct(
        release_id=request.release_id,
        prompt=request.goal or "",
        user_id=str(current_user.id),
        trigger_source=request.trigger_source,
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


@router.get("/{run_id}", response_model=BaseResponse[AgentRunResponse])
async def get_run(
    run_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Get a run by ID."""
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(run))


@router.post("/{run_id}/cancel", response_model=BaseResponse[AgentRunResponse])
async def cancel_run(
    run_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Cancel a run."""
    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.cancel_run(run_id)
    return BaseResponse(success=True, code=200, msg="Run cancelled", data=_to_response(run))


@router.post("/{run_id}/retry", response_model=BaseResponse[AgentRunResponse])
async def retry_run(
    run_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Retry a run by creating a new execution attempt."""
    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.retry_run(run_id, str(current_user.id))
    return BaseResponse(success=True, code=200, msg="Run retried", data=_to_response(run))
