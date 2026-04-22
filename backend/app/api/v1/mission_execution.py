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
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.execution import (
    ApproveActionRequest,
    InjectMessageRequest,
)
from app.services.mission_service import MissionService

router = APIRouter(prefix="/v1/missions/{mission_id}/execution", tags=["Mission Execution"])


async def _get_current_execution_id(
    mission_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
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

    await session.inject_message(request.message)
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

    from app.core.agent.cli_backends.base import build_control_response

    if request.approved:
        await session.inject_message(build_control_response("", "allow"))
    else:
        await session.inject_message(build_control_response("", "deny"))

    return BaseResponse(success=True, code=200, msg="Action processed")
