"""Agent Runs API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, get_current_user, require_workspace_role
from app.common.app_errors import AccessDeniedError
from app.core.database import get_db
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.agent_run import (
    AgentRunResponse,
    CreateAgentRunRequest,
    CreateDraftAgentRunRequest,
)
from app.services.dispatch_service import DispatchService
from app.services.agent_run_service import AgentRunService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


def _to_response(run) -> AgentRunResponse:
    return AgentRunResponse.model_validate(run)


async def _get_release_workspace_id(db: AsyncSession, release_id: uuid.UUID) -> uuid.UUID | None:
    return (await db.execute(
        select(Agent.workspace_id)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .join(AgentRelease, AgentRelease.agent_version_id == AgentVersion.id)
        .where(AgentRelease.id == release_id)
    )).scalar_one_or_none()


async def _require_workspace_access(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: User,
    role: WorkspaceMemberRole,
) -> None:
    has_access = await check_workspace_access(db, workspace_id, current_user, role)
    if not has_access:
        raise AccessDeniedError("Insufficient workspace permission", code="WORKSPACE_PERMISSION_DENIED")


@router.get("", response_model=BaseResponse[List[AgentRunResponse]])
async def list_runs(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID | None = Query(None),
    release_id: uuid.UUID | None = Query(None),
    task_id: uuid.UUID | None = Query(None),
    agent_id: uuid.UUID | None = Query(None),
    trigger_source: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentRunResponse]]:
    """List runs filtered by workspace_id, release_id, task_id, or agent_id."""
    service = AgentRunService(db)
    runs = await service.list_runs(
        workspace_id=workspace_id,
        release_id=release_id,
        task_id=task_id,
        agent_id=agent_id,
        trigger_source=trigger_source,
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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Create a new agent run via the unified orchestrator."""
    workspace_id = await _get_release_workspace_id(db, request.release_id)
    if not workspace_id:
        raise AccessDeniedError("Insufficient workspace permission", code="WORKSPACE_PERMISSION_DENIED")
    await _require_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)

    dispatch = DispatchService(db)
    run = await dispatch.dispatch_direct(
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


@router.post("/draft", response_model=BaseResponse[AgentRunResponse])
async def create_draft_run(
    request: CreateDraftAgentRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Create a Test Lab run against an agent draft version, not an active release."""
    await _require_workspace_access(db, request.workspace_id, current_user, WorkspaceMemberRole.member)

    dispatch = DispatchService(db)
    run = await dispatch.dispatch_draft(
        agent_id=request.agent_id,
        version_id=request.version_id,
        prompt=request.goal or "",
        user_id=str(current_user.id),
        workspace_id=request.workspace_id,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Get a run by ID."""
    service = AgentRunService(db)
    run = await service.get_run(run_id)
    await _require_workspace_access(db, run.workspace_id, current_user, WorkspaceMemberRole.viewer)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(run))


@router.post("/{run_id}/cancel", response_model=BaseResponse[AgentRunResponse])
async def cancel_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Cancel a run."""
    service = AgentRunService(db)
    existing_run = await service.get_run(run_id)
    await _require_workspace_access(
        db,
        existing_run.workspace_id,
        current_user,
        WorkspaceMemberRole.member,
    )

    dispatch = DispatchService(db)
    run = await dispatch.cancel_run(run_id)
    return BaseResponse(success=True, code=200, msg="Run cancelled", data=_to_response(run))


@router.post("/{run_id}/retry", response_model=BaseResponse[AgentRunResponse])
async def retry_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentRunResponse]:
    """Retry a run by creating a new execution attempt."""
    service = AgentRunService(db)
    existing_run = await service.get_run(run_id)
    await _require_workspace_access(
        db,
        existing_run.workspace_id,
        current_user,
        WorkspaceMemberRole.member,
    )

    dispatch = DispatchService(db)
    run = await dispatch.retry_run(run_id, str(current_user.id))
    return BaseResponse(success=True, code=200, msg="Run retried", data=_to_response(run))
