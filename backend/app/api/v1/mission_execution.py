"""Mission-scoped execution endpoints — the frontend's primary interface."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_workspace_role
from app.common.exceptions import NotFoundException
from app.core.agent.cli_backends.session_registry import session_registry
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.execution import MissionExecutionStatus
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.execution import (
    ApproveActionRequest,
    ExecutionEventsPageResponse,
    ExecutionSnapshotResponse,
    ExecutionSummary,
    InjectMessageRequest,
)
from app.services.execution_service import ExecutionService
from app.services.mission_service import MissionService

router = APIRouter(prefix="/v1/missions/{mission_id}/execution", tags=["Mission Execution"])


async def _get_current_execution_id(
    mission_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession,
) -> uuid.UUID:
    svc = MissionService(db)
    mission = await svc.get_mission(mission_id, workspace_id)
    if not mission or not mission.current_execution_id:
        raise NotFoundException("No active execution for this mission")
    return mission.current_execution_id


@router.post("/message", response_model=BaseResponse)
async def inject_message(
    mission_id: uuid.UUID,
    request: InjectMessageRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    session = session_registry.get(exec_id)
    if not session:
        raise NotFoundException("Execution session not found")

    svc = ExecutionService(db)
    await session.inject_message(request.message)
    await svc.append_event(
        execution_id=exec_id,
        event_type="user_message",
        payload={"content": request.message},
    )
    return BaseResponse(success=True, code=200, msg="Message injected")


@router.post("/approve", response_model=BaseResponse)
async def approve_action(
    mission_id: uuid.UUID,
    request: ApproveActionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    session = session_registry.get(exec_id)
    if not session:
        raise NotFoundException("Execution session not found")

    svc = ExecutionService(db)
    snapshot = await svc.repo.get_snapshot(exec_id)
    if not snapshot:
        raise NotFoundException("Execution snapshot not found")

    from app.core.agent.cli_backends.base import build_control_response
    pending = (snapshot.projection or {}).get("meta", {}).get("pending_approval", {})
    request_id = pending.get("request_id", "")

    if request.approved:
        await session.inject_message(build_control_response(request_id, "allow"))
        await svc.append_event(
            execution_id=exec_id,
            event_type="approval_resolved",
            payload={"decision": "approved"},
        )
        await svc.mark_status(execution_id=exec_id, status=MissionExecutionStatus.RUNNING)
    else:
        await session.inject_message(build_control_response(request_id, "deny"))
        await svc.append_event(
            execution_id=exec_id,
            event_type="approval_resolved",
            payload={"decision": "rejected"},
        )

    return BaseResponse(success=True, code=200, msg="Action processed")


@router.get("/events", response_model=BaseResponse[ExecutionEventsPageResponse])
async def get_events(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    after_seq: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    svc = ExecutionService(db)
    events = list(await svc.repo.list_events_after(exec_id, after_seq=after_seq, limit=limit))
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=ExecutionEventsPageResponse(
            execution_id=exec_id,
            events=events,
            next_after_seq=events[-1].seq if events else after_seq,
        ),
    )


@router.get("/snapshot", response_model=BaseResponse[ExecutionSnapshotResponse])
async def get_snapshot(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    exec_id = await _get_current_execution_id(mission_id, workspace_id, db)
    svc = ExecutionService(db)
    snapshot = await svc.repo.get_snapshot(exec_id)
    if not snapshot:
        raise NotFoundException("Snapshot not found")
    return BaseResponse(success=True, code=200, msg="ok", data=snapshot)
