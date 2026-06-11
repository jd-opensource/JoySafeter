"""Executions API."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.agent_run import AgentRun
from app.joysafeter_domain.models.execution import Artifact, Execution
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.artifact import ArtifactResponse
from app.joysafeter_domain.schemas.execution import (
    ExecutionEventItemResponse,
    ExecutionEventResponse,
    ExecutionEventsPageResponse,
    ExecutionResponse,
)
from app.joysafeter_domain.schemas.task import InjectMessageRequest
from app.joysafeter_api.services import DispatchService
from app.joysafeter_api.services import ExecutionService


class DebugRunRequest(BaseModel):
    agent_version_id: uuid.UUID
    agent_id: uuid.UUID
    prompt: str
    thread_id: uuid.UUID
    variables: Optional[Dict[str, Any]] = None


router = APIRouter(prefix="/v1/executions", tags=["Executions"])


@router.post("/debug", response_model=BaseResponse)
async def dispatch_debug_run(
    body: DebugRunRequest,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Start a debug run with observation tracing enabled."""
    from app.joysafeter_api.services import ExecutionOrchestrator

    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")

    orchestrator = ExecutionOrchestrator(db)
    run = await orchestrator.dispatch_debug(
        agent_id=body.agent_id,
        version_id=body.agent_version_id,
        prompt=body.prompt,
        user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
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


@router.get("", response_model=BaseResponse[List[ExecutionResponse]])
async def list_executions(
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    run_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ExecutionResponse]]:
    """List all executions for a run."""
    from app.joysafeter_api.services import AgentRunService
    run_svc = AgentRunService(db)
    run = await run_svc.get_run(run_id)
    if run.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Run not found")
    service = ExecutionService(db)
    executions = await service.list_executions(run_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_to_response(e) for e in executions],
    )


async def _verify_execution_project(execution_id: uuid.UUID, project_id: str, db: AsyncSession):
    """Verify execution belongs to caller's project via its parent run."""
    result = await db.execute(
        select(AgentRun.project_id)
        .join(Execution, Execution.run_id == AgentRun.id)
        .where(Execution.id == execution_id)
    )
    row = result.scalar_one_or_none()
    if row != project_id:
        raise HTTPException(404, "Execution not found")


@router.get("/{execution_id}", response_model=BaseResponse[ExecutionResponse])
async def get_execution(
    execution_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionResponse]:
    """Get an execution by ID."""
    await _verify_execution_project(execution_id, auth_ctx.project_id, db)
    service = ExecutionService(db)
    execution = await service.get_execution(execution_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(execution))


@router.get("/{execution_id}/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def list_execution_events(
    execution_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionEventsPageResponse]:
    """List execution events after a sequence number."""
    await _verify_execution_project(execution_id, auth_ctx.project_id, db)
    service = ExecutionService(db)
    events = await service.list_events_after(
        execution_id,
        auth_ctx.user_id,
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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ArtifactResponse]]:
    """List all artifacts for an execution."""
    await _verify_execution_project(execution_id, auth_ctx.project_id, db)
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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Inject a message into a running execution."""
    await _verify_execution_project(execution_id, auth_ctx.project_id, db)
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")
    dispatch = DispatchService(db)
    try:
        await dispatch.send_message(execution_id, body.message)
    except NotImplementedError as exc:
        raise InvalidRequestError(str(exc), code="EXECUTION_MESSAGE_UNSUPPORTED")
    except RuntimeError as exc:
        raise InvalidRequestError(str(exc), code="EXECUTION_MESSAGE_REJECTED")
    return BaseResponse(success=True, code=200, msg="ok", data={"status": "sent"})
