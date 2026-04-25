"""Agents API."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, require_workspace_role
from app.common.exceptions import ForbiddenException
from app.core.database import get_db
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.schemas import BaseResponse
from app.schemas.agent import (
    AgentResponse,
    AgentSummary,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from app.schemas.agent_release import (
    AgentReleaseResponse,
    AgentReleaseSummary,
    CreateAgentReleaseRequest,
)
from app.schemas.agent_version import (
    AgentVersionResponse,
    AgentVersionSummary,
    CreateAgentVersionRequest,
    UpdateAgentVersionRequest,
)
from app.services.agent_service import AgentService
from app.services.agent_release_service import AgentReleaseService
from app.services.agent_version_service import AgentVersionService
from app.services.workspace_permission import check_workspace_access

router = APIRouter(prefix="/v1/agents", tags=["Agents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(agent: Agent) -> AgentResponse:
    return AgentResponse.model_validate(agent)


def _to_summary(agent: Agent) -> AgentSummary:
    return AgentSummary.model_validate(agent)


def _version_to_response(v: AgentVersion) -> AgentVersionResponse:
    return AgentVersionResponse.model_validate(v)


def _version_to_summary(v: AgentVersion) -> AgentVersionSummary:
    return AgentVersionSummary.model_validate(v)


def _release_to_response(r: AgentRelease) -> AgentReleaseResponse:
    return AgentReleaseResponse.model_validate(r)


def _release_to_summary(r: AgentRelease) -> AgentReleaseSummary:
    return AgentReleaseSummary.model_validate(r)


# ---------------------------------------------------------------------------
# Agent routes
# ---------------------------------------------------------------------------


@router.get("", response_model=BaseResponse[List[AgentSummary]])
async def list_agents(
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentSummary]]:
    service = AgentService(db)
    agents = await service.list_agents(workspace_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_to_summary(a) for a in agents],
    )


@router.post("", response_model=BaseResponse[AgentResponse])
async def create_agent(
    request: CreateAgentRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    service = AgentService(db)
    agent = await service.create_agent(workspace_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Agent created", data=_to_response(agent))


@router.get("/{agent_id}", response_model=BaseResponse[AgentResponse])
async def get_agent(
    agent_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(agent))


@router.patch("/{agent_id}", response_model=BaseResponse[AgentResponse])
async def update_agent(
    agent_id: uuid.UUID,
    request: UpdateAgentRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    service = AgentService(db)
    agent = await service.update_agent(agent_id, request)
    return BaseResponse(success=True, code=200, msg="Agent updated", data=_to_response(agent))


@router.delete("/{agent_id}", response_model=BaseResponse)
async def delete_agent(
    agent_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    service = AgentService(db)
    await service.delete_agent(agent_id)
    return BaseResponse(success=True, code=200, msg="Agent deleted")


# ---------------------------------------------------------------------------
# AgentVersion sub-routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/versions", response_model=BaseResponse[List[AgentVersionSummary]])
async def list_versions(
    agent_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentVersionSummary]]:
    service = AgentVersionService(db)
    versions = await service.list_versions(agent_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_version_to_summary(v) for v in versions],
    )


@router.post("/{agent_id}/versions", response_model=BaseResponse[AgentVersionResponse])
async def create_version(
    agent_id: uuid.UUID,
    request: CreateAgentVersionRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    service = AgentVersionService(db)
    version = await service.create_version(agent_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Version created", data=_version_to_response(version))


@router.get("/{agent_id}/versions/{version_id}", response_model=BaseResponse[AgentVersionResponse])
async def get_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    service = AgentVersionService(db)
    version = await service.get_version(version_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_version_to_response(version))


@router.patch("/{agent_id}/versions/{version_id}", response_model=BaseResponse[AgentVersionResponse])
async def update_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    request: UpdateAgentVersionRequest,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    service = AgentVersionService(db)
    version = await service.update_version(version_id, request)
    return BaseResponse(success=True, code=200, msg="Version updated", data=_version_to_response(version))


@router.post("/{agent_id}/versions/{version_id}/freeze", response_model=BaseResponse[AgentVersionResponse])
async def freeze_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    service = AgentVersionService(db)
    version = await service.freeze_version(version_id)
    return BaseResponse(success=True, code=200, msg="Version frozen", data=_version_to_response(version))


@router.post("/{agent_id}/versions/{version_id}/unfreeze", response_model=BaseResponse[AgentVersionResponse])
async def unfreeze_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    """Revert a frozen version back to draft.

    This endpoint exists to allow rollback when a freeze succeeds but the
    subsequent publish operation fails, preventing the version from being
    stuck in an uneditable frozen state.
    """
    service = AgentVersionService(db)
    version = await service.unfreeze_version(version_id)
    return BaseResponse(success=True, code=200, msg="Version reverted to draft", data=_version_to_response(version))


# ---------------------------------------------------------------------------
# AgentRelease sub-routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/releases", response_model=BaseResponse[List[AgentReleaseSummary]])
async def list_releases(
    agent_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentReleaseSummary]]:
    service = AgentReleaseService(db)
    releases = await service.list_releases(agent_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_release_to_summary(r) for r in releases],
    )


@router.post("/{agent_id}/releases", response_model=BaseResponse[AgentReleaseResponse])
async def publish_release(
    agent_id: uuid.UUID,
    request: CreateAgentReleaseRequest,
    current_user: CurrentUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    has_access = await check_workspace_access(db, workspace_id, current_user, WorkspaceMemberRole.member)
    if not has_access:
        raise ForbiddenException("No access to workspace")

    service = AgentReleaseService(db)
    release = await service.publish_release(agent_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Release published", data=_release_to_response(release))


@router.get("/{agent_id}/releases/{release_id}", response_model=BaseResponse[AgentReleaseResponse])
async def get_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.viewer),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    service = AgentReleaseService(db)
    release = await service.get_release(release_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_release_to_response(release))


@router.post("/{agent_id}/releases/{release_id}/activate", response_model=BaseResponse[AgentReleaseResponse])
async def activate_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    service = AgentReleaseService(db)
    release = await service.activate_release(agent_id, release_id)
    return BaseResponse(success=True, code=200, msg="Release activated", data=_release_to_response(release))


@router.post("/{agent_id}/releases/{release_id}/retire", response_model=BaseResponse[AgentReleaseResponse])
async def retire_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    current_user: User = require_workspace_role(WorkspaceMemberRole.member),
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    service = AgentReleaseService(db)
    release = await service.retire_release(agent_id, release_id)
    return BaseResponse(success=True, code=200, msg="Release retired", data=_release_to_response(release))
