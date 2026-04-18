"""Missions API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, require_workspace_role
from app.common.exceptions import BadRequestException, ForbiddenException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.mission import Mission, MissionPriority
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.execution import (
    AssignMissionRequest,
    CreateMissionRequest,
    DispatchMissionRequest,
    MissionListResponse,
    MissionSummary,
    UpdateMissionRequest,
)
from app.services.mission_service import MissionService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/missions", tags=["Missions"])


def _to_summary(m: Mission) -> MissionSummary:
    return MissionSummary(
        id=m.id,
        workspace_id=m.workspace_id,
        title=m.title,
        description=m.description,
        objective=m.objective,
        status=m.status.value if hasattr(m.status, "value") else str(m.status),
        priority=m.priority.value if hasattr(m.priority, "value") else str(m.priority),
        assignee_type=m.assignee_type,
        assignee_id=m.assignee_id,
        creator_id=m.creator_id,
        current_execution_id=m.current_execution_id,
        parent_mission_id=m.parent_mission_id,
        tags=m.tags,
        position=m.position,
        auto_approve=m.auto_approve,
        due_date=m.due_date,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=BaseResponse[MissionListResponse])
async def list_missions(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    parent_mission_id: uuid.UUID | None = Query(None),
    assignee_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionListResponse]:
    service = MissionService(db)
    missions = await service.list_missions(
        workspace_id=workspace_id,
        status=status,
        parent_mission_id=parent_mission_id,
        assignee_id=assignee_id,
        limit=limit,
    )
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=MissionListResponse(items=[_to_summary(m) for m in missions]),
    )


@router.post("", response_model=BaseResponse[MissionSummary])
async def create_mission(
    request: CreateMissionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    service = MissionService(db)

    try:
        priority = MissionPriority(request.priority)
    except ValueError:
        raise BadRequestException(f"Invalid priority: {request.priority}")

    has_access = await check_workspace_access(db, request.workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    mission = await service.create_mission(
        workspace_id=request.workspace_id,
        creator_id=str(current_user.id),
        title=request.title,
        description=request.description,
        objective=request.objective,
        priority=priority,
        parent_mission_id=request.parent_mission_id,
        tags=request.tags,
        position=request.position,
        auto_approve=request.auto_approve,
    )
    return BaseResponse(success=True, code=200, msg="Mission created", data=_to_summary(mission))


@router.get("/{mission_id}", response_model=BaseResponse[MissionSummary])
async def get_mission(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    service = MissionService(db)
    mission = await service.get_mission(mission_id, workspace_id)
    if not mission:
        return BaseResponse(success=False, code=404, msg="Mission not found", data=None)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_summary(mission))


@router.patch("/{mission_id}", response_model=BaseResponse[MissionSummary])
async def update_mission(
    mission_id: uuid.UUID,
    request: UpdateMissionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    service = MissionService(db)
    updates = request.model_dump(exclude_unset=True)
    mission = await service.update_mission(mission_id, workspace_id, **updates)
    if not mission:
        return BaseResponse(success=False, code=404, msg="Mission not found", data=None)
    return BaseResponse(success=True, code=200, msg="Mission updated", data=_to_summary(mission))


@router.post("/{mission_id}/assign", response_model=BaseResponse[MissionSummary])
async def assign_mission(
    mission_id: uuid.UUID,
    request: AssignMissionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    service = MissionService(db)
    mission = await service.assign_to_agent(
        mission_id=mission_id,
        workspace_id=workspace_id,
        agent_profile_id=request.agent_profile_id,
    )
    return BaseResponse(success=True, code=200, msg="Mission assigned", data=_to_summary(mission))


@router.post("/{mission_id}/dispatch", response_model=BaseResponse[MissionSummary])
async def dispatch_mission(
    mission_id: uuid.UUID,
    request: DispatchMissionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    lifecycle = ExecutionLifecycleService(db)
    mission, _execution = await lifecycle.dispatch_mission(
        mission_id=mission_id,
        workspace_id=workspace_id,
        user_id=str(current_user.id),
        runtime_config=request.runtime_config,
    )
    return BaseResponse(success=True, code=200, msg="Mission dispatched", data=_to_summary(mission))


@router.post("/{mission_id}/cancel", response_model=BaseResponse[MissionSummary])
async def cancel_mission(
    mission_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[MissionSummary]:
    from app.services.execution_lifecycle_service import ExecutionLifecycleService
    lifecycle = ExecutionLifecycleService(db)
    mission = await lifecycle.cancel_mission(mission_id=mission_id, workspace_id=workspace_id)
    if not mission:
        return BaseResponse(success=False, code=404, msg="Mission not found", data=None)
    return BaseResponse(success=True, code=200, msg="Mission cancelled", data=_to_summary(mission))
