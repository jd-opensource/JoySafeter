"""Executions API."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.common.dependencies import CurrentUser, get_current_user
from app.common.workspace_permission import check_workspace_access
from app.core.database import get_db
from app.models.agent_run import AgentRun
from app.models.auth import AuthUser as User
from app.models.execution import Artifact, Execution
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.artifact import ArtifactResponse
from app.schemas.execution import (
    ExecutionEventItemResponse,
    ExecutionEventResponse,
    ExecutionEventsPageResponse,
    ExecutionResponse,
)
from app.schemas.task import InjectMessageRequest
from app.services.dispatch_service import DispatchService
from app.services.execution_service import ExecutionService


class DebugRunRequest(BaseModel):
    agent_version_id: uuid.UUID
    agent_id: uuid.UUID
    prompt: str
    workspace_id: uuid.UUID
    thread_id: uuid.UUID
    variables: Optional[Dict[str, Any]] = None


router = APIRouter(prefix="/v1/executions", tags=["Executions"])


@router.post("/debug", response_model=BaseResponse)
async def dispatch_debug_run(
    body: DebugRunRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Start a debug run with observation tracing enabled."""
    from app.services.execution_orchestrator import ExecutionOrchestrator

    has_access = await check_workspace_access(db, body.workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise AccessDeniedError("Insufficient workspace permission", code="WORKSPACE_PERMISSION_DENIED")

    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_debug(
        agent_id=body.agent_id,
        version_id=body.agent_version_id,
        prompt=body.prompt,
        user_id=str(current_user.id),
        workspace_id=body.workspace_id,
        thread_id=body.thread_id,
        variables=body.variables,
    )

    execution_id = run.current_execution_id
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data={
            "execution_id": str(execution_id),
            "run_id": str(run.id),
            "ws_topic": f"execution:{execution_id}",
        },
    )


def _to_response(execution) -> ExecutionResponse:
    return ExecutionResponse.model_validate(execution)


def _event_to_response(event) -> ExecutionEventResponse:
    return ExecutionEventResponse.model_validate(event)


async def _get_run_workspace_id(db: AsyncSession, run_id: uuid.UUID) -> uuid.UUID | None:
    return (await db.execute(select(AgentRun.workspace_id).where(AgentRun.id == run_id))).scalar_one_or_none()


async def _get_execution_workspace_id(db: AsyncSession, execution_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await db.execute(
            select(AgentRun.workspace_id)
            .join(Execution, Execution.run_id == AgentRun.id)
            .where(Execution.id == execution_id)
        )
    ).scalar_one_or_none()


async def _require_execution_workspace_access(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    current_user: User,
    role: WorkspaceMemberRole,
) -> None:
    has_access = await check_workspace_access(db, workspace_id, current_user, role)
    if not has_access:
        raise AccessDeniedError("Insufficient workspace permission", code="WORKSPACE_PERMISSION_DENIED")


@router.get("", response_model=BaseResponse[List[ExecutionResponse]])
async def list_executions(
    current_user: User = Depends(get_current_user),
    run_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ExecutionResponse]]:
    """List all executions for a run."""
    workspace_id = await _get_run_workspace_id(db, run_id)
    if not workspace_id:
        raise NotFoundError("Run not found", code="RUN_NOT_FOUND", data={"run_id": str(run_id)})
    await _require_execution_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)

    service = ExecutionService(db)
    executions = await service.list_executions(run_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_to_response(e) for e in executions],
    )


@router.get("/{execution_id}", response_model=BaseResponse[ExecutionResponse])
async def get_execution(
    execution_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionResponse]:
    """Get an execution by ID."""
    workspace_id = await _get_execution_workspace_id(db, execution_id)
    if not workspace_id:
        raise NotFoundError(
            "Execution not found",
            code="EXECUTION_NOT_FOUND",
            data={"execution_id": str(execution_id)},
        )
    await _require_execution_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)

    service = ExecutionService(db)
    execution = await service.get_execution(execution_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(execution))


@router.get("/{execution_id}/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def list_execution_events(
    execution_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionEventsPageResponse]:
    """List execution events after a sequence number."""
    workspace_id = await _get_execution_workspace_id(db, execution_id)
    if not workspace_id:
        raise NotFoundError(
            "Execution not found",
            code="EXECUTION_NOT_FOUND",
            data={"execution_id": str(execution_id)},
        )
    await _require_execution_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)

    service = ExecutionService(db)
    events = await service.list_events_after(
        execution_id,
        str(current_user.id),
        after_seq=after_seq,
        limit=500,
    )
    items = [
        ExecutionEventItemResponse(
            id=event.id,
            execution_id=event.execution_id,
            seq=event.sequence_no,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=ExecutionEventsPageResponse(
            execution_id=execution_id,
            events=items,
            next_after_seq=max((item.seq for item in items), default=after_seq),
        ),
    )


@router.get("/{execution_id}/artifacts", response_model=BaseResponse[List[ArtifactResponse]])
async def list_artifacts(
    execution_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ArtifactResponse]]:
    """List all artifacts for an execution."""
    workspace_id = await _get_execution_workspace_id(db, execution_id)
    if not workspace_id:
        raise NotFoundError(
            "Execution not found",
            code="EXECUTION_NOT_FOUND",
            data={"execution_id": str(execution_id)},
        )
    await _require_execution_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.viewer)

    result = await db.execute(
        select(Artifact).where(Artifact.execution_id == execution_id).order_by(Artifact.created_at)
    )
    artifacts = list(result.scalars().all())
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[ArtifactResponse.model_validate(a) for a in artifacts],
    )


@router.post("/{execution_id}/message", response_model=BaseResponse)
async def inject_message(
    execution_id: uuid.UUID,
    body: InjectMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Inject a message into a running execution."""
    workspace_id = await _get_execution_workspace_id(db, execution_id)
    if not workspace_id:
        raise NotFoundError(
            "Execution not found",
            code="EXECUTION_NOT_FOUND",
            data={"execution_id": str(execution_id)},
        )

    await _require_execution_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)

    dispatch = DispatchService(db)
    try:
        await dispatch.send_message(execution_id, body.message)
    except NotImplementedError as exc:
        raise InvalidRequestError(str(exc), code="EXECUTION_MESSAGE_UNSUPPORTED")
    except RuntimeError as exc:
        raise InvalidRequestError(str(exc), code="EXECUTION_MESSAGE_REJECTED")
    return BaseResponse(success=True, code=200, msg="ok", data={"status": "sent"})
