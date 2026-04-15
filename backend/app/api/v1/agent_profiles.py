"""Agent Profiles API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.core.database import get_db
from app.models.agent_profile import AgentProfile
from app.schemas import BaseResponse
from app.schemas.execution import (
    AgentProfileListResponse,
    AgentProfileSummary,
    CreateAgentProfileRequest,
    UpdateAgentProfileRequest,
)
from app.services.agent_profile_service import AgentProfileService

router = APIRouter(prefix="/v1/agent-profiles", tags=["Agent Profiles"])


def _to_summary(p: AgentProfile) -> AgentProfileSummary:
    return AgentProfileSummary(
        id=p.id,
        workspace_id=p.workspace_id,
        name=p.name,
        runtime_type=p.runtime_type,
        status=p.status.value if hasattr(p.status, "value") else str(p.status),
        description=p.description,
        avatar=p.avatar,
        max_concurrent_tasks=p.max_concurrent_tasks,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=BaseResponse[AgentProfileListResponse])
async def list_agent_profiles(
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    runtime_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentProfileListResponse]:
    service = AgentProfileService(db)
    profiles = await service.list_profiles(
        workspace_id=workspace_id,
        status=status,
        runtime_type=runtime_type,
        limit=limit,
    )
    return BaseResponse(
        success=True, code=200, msg="ok",
        data=AgentProfileListResponse(items=[_to_summary(p) for p in profiles]),
    )


@router.post("", response_model=BaseResponse[AgentProfileSummary])
async def create_agent_profile(
    request: CreateAgentProfileRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentProfileSummary]:
    service = AgentProfileService(db)
    profile = await service.create_profile(
        workspace_id=request.workspace_id,
        name=request.name,
        runtime_type=request.runtime_type,
        description=request.description,
        avatar=request.avatar,
        instructions=request.instructions,
        skill_ids=request.skill_ids,
        custom_env=request.custom_env,
        runtime_config=request.runtime_config,
        max_concurrent_tasks=request.max_concurrent_tasks,
    )
    return BaseResponse(success=True, code=200, msg="Agent profile created", data=_to_summary(profile))


@router.get("/{profile_id}", response_model=BaseResponse[AgentProfileSummary])
async def get_agent_profile(
    profile_id: uuid.UUID,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentProfileSummary]:
    service = AgentProfileService(db)
    profile = await service.get_profile(profile_id, workspace_id)
    if not profile:
        return BaseResponse(success=False, code=404, msg="Agent profile not found", data=None)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_summary(profile))


@router.patch("/{profile_id}", response_model=BaseResponse[AgentProfileSummary])
async def update_agent_profile(
    profile_id: uuid.UUID,
    request: UpdateAgentProfileRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentProfileSummary]:
    service = AgentProfileService(db)
    updates = request.model_dump(exclude_unset=True)
    profile = await service.update_profile(profile_id, workspace_id, **updates)
    if not profile:
        return BaseResponse(success=False, code=404, msg="Agent profile not found", data=None)
    return BaseResponse(success=True, code=200, msg="Agent profile updated", data=_to_summary(profile))
