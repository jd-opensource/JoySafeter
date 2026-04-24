"""Executions API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, require_workspace_role
from app.core.database import get_db
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.models.auth import AuthUser as User
from app.models.execution import Artifact
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.artifact import ArtifactResponse
from app.schemas.execution import (
    ExecutionEventItemResponse,
    ExecutionEventsPageResponse,
    ExecutionEventResponse,
    ExecutionResponse,
)
from app.schemas.task import InjectMessageRequest
from app.services.execution_service import ExecutionService

router = APIRouter(prefix="/v1/executions", tags=["Executions"])


def _to_response(execution) -> ExecutionResponse:
    return ExecutionResponse.model_validate(execution)


def _event_to_response(event) -> ExecutionEventResponse:
    return ExecutionEventResponse.model_validate(event)


@router.get("", response_model=BaseResponse[List[ExecutionResponse]])
async def list_executions(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    run_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ExecutionResponse]]:
    """List all executions for a run."""
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
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionResponse]:
    """Get an execution by ID."""
    service = ExecutionService(db)
    execution = await service.get_execution(execution_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(execution))


@router.get("/{execution_id}/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def list_execution_events(
    execution_id: uuid.UUID,
    after_seq: int = Query(0, ge=0),
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionEventsPageResponse]:
    """List execution events after a sequence number."""
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
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[ArtifactResponse]]:
    """List all artifacts for an execution."""
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
    orchestrator = ExecutionOrchestrator(db)
    try:
        await orchestrator.send_message(execution_id, body.message)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BaseResponse(success=True, code=200, msg="ok", data={"status": "sent"})
