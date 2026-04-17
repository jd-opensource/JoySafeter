"""Executions API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, require_workspace_role
from app.common.exceptions import NotFoundException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.execution import Execution, MissionExecutionStatus
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.execution import (
    ApproveActionRequest,
    ExecutionEventsPageResponse,
    ExecutionEventResponse,
    ExecutionListResponse,
    ExecutionSnapshotResponse,
    ExecutionSummary,
    InjectMessageRequest,
)
from app.services.execution_service import ExecutionService

router = APIRouter(prefix="/v1/executions", tags=["Executions"])


def _to_summary(e: Execution) -> ExecutionSummary:
    return ExecutionSummary(
        id=e.id,
        workspace_id=e.workspace_id,
        user_id=e.user_id,
        source=e.source.value if hasattr(e.source, "value") else str(e.source),
        status=e.status.value if hasattr(e.status, "value") else str(e.status),
        title=e.title,
        mission_id=e.mission_id,
        agent_profile_id=e.agent_profile_id,
        runtime_type=e.runtime_type,
        container_id=e.container_id,
        session_id=e.session_id,
        started_at=e.started_at,
        finished_at=e.finished_at,
        last_seq=e.last_seq,
        error_code=e.error_code,
        error_message=e.error_message,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.get("", response_model=BaseResponse[ExecutionListResponse])
async def list_executions(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    source: str | None = Query(None),
    mission_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionListResponse]:
    service = ExecutionService(db)
    executions = await service.list_executions(
        workspace_id=workspace_id,
        user_id=str(current_user.id),
        status=status,
        source=source,
        mission_id=mission_id,
        limit=limit,
    )
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionListResponse(items=[_to_summary(e) for e in executions]),
    )


@router.get("/{execution_id}", response_model=BaseResponse[ExecutionSummary])
async def get_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionSummary]:
    service = ExecutionService(db)
    execution = await service.get_execution(execution_id, str(current_user.id))
    if not execution:
        return BaseResponse(success=False, code=404, msg="Execution not found", data=None)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_summary(execution))


@router.get("/{execution_id}/children", response_model=BaseResponse[ExecutionListResponse])
async def list_child_executions(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionListResponse]:
    """List child executions spawned by a coordinator."""
    service = ExecutionService(db)
    # Verify the parent execution belongs to the user
    parent = await service.get_execution(execution_id, str(current_user.id))
    if not parent:
        return BaseResponse(success=False, code=404, msg="Execution not found", data=None)
    children = await service.list_children(execution_id)
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionListResponse(items=[_to_summary(e) for e in children]),
    )


@router.get("/{execution_id}/snapshot", response_model=BaseResponse[ExecutionSnapshotResponse])
async def get_execution_snapshot(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionSnapshotResponse]:
    service = ExecutionService(db)
    snapshot = await service.get_snapshot(execution_id, str(current_user.id))
    if not snapshot:
        return BaseResponse(success=False, code=404, msg="Snapshot not found", data=None)
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionSnapshotResponse(
            execution_id=execution_id,
            status=snapshot.status,
            last_seq=snapshot.last_seq,
            projection=snapshot.projection or {},
        ),
    )


@router.get("/{execution_id}/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def get_execution_events(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionEventsPageResponse]:
    service = ExecutionService(db)
    events = await service.list_events_after(
        execution_id, str(current_user.id), after_seq=after_seq, limit=limit,
    )
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionEventsPageResponse(
            execution_id=execution_id,
            events=[
                ExecutionEventResponse(
                    seq=event.seq,
                    event_type=event.event_type,
                    payload=event.payload or {},
                    created_at=event.created_at,
                )
                for event in events
            ],
            next_after_seq=events[-1].seq if events else after_seq,
        ),
    )


@router.post("/{execution_id}/cancel", response_model=BaseResponse[ExecutionSummary])
async def cancel_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ExecutionSummary]:
    service = ExecutionService(db)
    execution = await service.mark_status(
        execution_id=execution_id,
        user_id=str(current_user.id),
        status=MissionExecutionStatus.CANCELLED,
        error_code="cancelled",
        error_message="Cancelled by user",
    )
    if not execution:
        return BaseResponse(success=False, code=404, msg="Execution not found", data=None)

    # Cascade: update parent mission if this was the active execution
    if execution.mission_id:
        from app.repositories.mission import MissionRepository
        from app.models.mission import MissionStatus
        mission_repo = MissionRepository(db)
        mission = await mission_repo.get_for_update(execution.mission_id)
        if mission and mission.current_execution_id == execution_id:
            mission.current_execution_id = None
            if mission.status == MissionStatus.IN_PROGRESS:
                mission.status = MissionStatus.TODO
            await db.commit()

    # Terminate the running container process
    from app.core.agent.cli_backends.session_registry import session_registry
    session = session_registry.get(execution_id)
    if session:
        await session.cancel()

    return BaseResponse(success=True, code=200, msg="Execution cancelled", data=_to_summary(execution))


@router.post("/{execution_id}/message", response_model=BaseResponse)
async def inject_message(
    execution_id: uuid.UUID,
    request: InjectMessageRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Inject a user message into a running execution."""
    svc = ExecutionService(db)
    execution = await svc.get_execution(execution_id, str(current_user.id))
    if not execution:
        raise NotFoundException("Execution not found")

    from app.core.agent.cli_backends.session_registry import session_registry

    session = session_registry.get(execution_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session for this execution")

    await session.inject_message(request.message)

    await svc.append_event(
        execution_id=execution_id,
        event_type="user_message",
        payload={"content": request.message},
    )

    return BaseResponse(success=True, code=200, msg="Message injected")


@router.post("/{execution_id}/approve", response_model=BaseResponse)
async def approve_action(
    execution_id: uuid.UUID,
    request: ApproveActionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    """Approve or reject a pending approval request."""
    svc = ExecutionService(db)
    execution = await svc.get_execution(execution_id, str(current_user.id))
    if not execution:
        raise NotFoundException("Execution not found")

    from app.core.agent.cli_backends.session_registry import session_registry

    session = session_registry.get(execution_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session for this execution")

    if request.approved:
        msg = request.message or "Approved. Continue."
        await session.inject_message(msg)
        await svc.append_event(
            execution_id=execution_id,
            event_type="approval_resolved",
            payload={"decision": "approved", "content": msg},
        )
        await svc.mark_status(
            execution_id=execution_id,
            status=MissionExecutionStatus.RUNNING,
        )
    else:
        msg = request.message or "Rejected. Stop this action."
        await session.inject_message(msg)
        await svc.append_event(
            execution_id=execution_id,
            event_type="approval_resolved",
            payload={"decision": "rejected", "content": msg},
        )
        # Keep running — the agent will decide how to handle the rejection

    return BaseResponse(success=True, code=200, msg="Action processed")
