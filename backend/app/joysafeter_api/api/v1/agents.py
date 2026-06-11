"""Agents API."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.common.dependencies import CurrentUser
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.models.agent import Agent, AgentRelease, AgentVersion
from app.joysafeter_domain.models.auth import AuthUser as User
from app.joysafeter_domain.schemas import BaseResponse
from app.joysafeter_domain.schemas.agent import (
    AgentResponse,
    AgentSummary,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from app.joysafeter_domain.schemas.agent_release import (
    AgentReleaseResponse,
    AgentReleaseSummary,
)
from app.joysafeter_domain.schemas.agent_version import (
    AgentVersionResponse,
    AgentVersionSummary,
    CreateAgentVersionRequest,
    UpdateAgentVersionRequest,
)
from app.joysafeter_api.services import AgentPublishService
from app.joysafeter_api.services import AgentReleaseService
from app.joysafeter_api.services import AgentService
from app.joysafeter_api.services import AgentVersionService


class RollbackRequest(PydanticBaseModel):
    release_id: uuid.UUID


class PublishAgentResponse(PydanticBaseModel):
    agent: AgentResponse
    release: AgentReleaseResponse


class RollbackAgentResponse(PydanticBaseModel):
    agent: AgentResponse


class UnpublishAgentResponse(PydanticBaseModel):
    agent: AgentResponse
    release: Optional[AgentReleaseResponse] = None


router = APIRouter(prefix="/v1/agents", tags=["Agents"])


async def _verify_agent_ownership(svc: AgentService, agent_id: uuid.UUID, project_id: str):
    agent = await svc.get_agent(agent_id)
    if agent.project_id != project_id:
        raise HTTPException(404, "Agent not found")
    return agent


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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentSummary]]:
    service = AgentService(db)
    agents = await service.list_agents_by_project(auth_ctx.project_id)
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
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    if not auth_ctx.role.can_write():
        raise AccessDeniedError("Write access required", code="WRITE_ACCESS_DENIED")

    service = AgentService(db)
    agent = await service.create_agent(auth_ctx.project_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Agent created", data=_to_response(agent))


@router.get("/{agent_id}", response_model=BaseResponse[AgentResponse])
async def get_agent(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if agent.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Agent not found")
    return BaseResponse(success=True, code=200, msg="ok", data=_to_response(agent))


@router.patch("/{agent_id}", response_model=BaseResponse[AgentResponse])
async def update_agent(
    agent_id: uuid.UUID,
    request: UpdateAgentRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentResponse]:
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if agent.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Agent not found")
    agent = await service.update_agent(agent_id, request)
    return BaseResponse(success=True, code=200, msg="Agent updated", data=_to_response(agent))


@router.delete("/{agent_id}", response_model=BaseResponse)
async def delete_agent(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse:
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if agent.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Agent not found")
    await service.delete_agent(agent_id)
    return BaseResponse(success=True, code=200, msg="Agent deleted")


# ---------------------------------------------------------------------------
# AgentVersion sub-routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/versions", response_model=BaseResponse[List[AgentVersionSummary]])
async def list_versions(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentVersionSummary]]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
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
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentVersionService(db)
    version = await service.create_version(agent_id, str(current_user.id), request)
    return BaseResponse(success=True, code=200, msg="Version created", data=_version_to_response(version))


@router.get("/{agent_id}/versions/{version_id}", response_model=BaseResponse[AgentVersionResponse])
async def get_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentVersionService(db)
    version = await service.get_version(version_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_version_to_response(version))


@router.patch("/{agent_id}/versions/{version_id}", response_model=BaseResponse[AgentVersionResponse])
async def update_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    request: UpdateAgentVersionRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentVersionResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentVersionService(db)
    version = await service.update_version(version_id, request, user_id=auth_ctx.user_id)
    return BaseResponse(success=True, code=200, msg="Version updated", data=_version_to_response(version))


# ---------------------------------------------------------------------------
# AgentRelease sub-routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/releases", response_model=BaseResponse[List[AgentReleaseSummary]])
async def list_releases(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[List[AgentReleaseSummary]]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentReleaseService(db)
    releases = await service.list_releases(agent_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=[_release_to_summary(r) for r in releases],
    )


@router.get("/{agent_id}/releases/{release_id}", response_model=BaseResponse[AgentReleaseResponse])
async def get_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentReleaseService(db)
    release = await service.get_release(release_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_release_to_response(release))


@router.post("/{agent_id}/releases/{release_id}/retire", response_model=BaseResponse[AgentReleaseResponse])
async def retire_release(
    agent_id: uuid.UUID,
    release_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[AgentReleaseResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentPublishService(db)
    result = await service.retire(agent_id, release_id)
    return BaseResponse(success=True, code=200, msg="ok", data=_release_to_response(result["release"]))


@router.post("/{agent_id}/publish", response_model=BaseResponse[PublishAgentResponse])
async def publish_agent(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[PublishAgentResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentPublishService(db)
    result = await service.publish(agent_id, auth_ctx.user_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=PublishAgentResponse(
            agent=_to_response(result["agent"]),
            release=_release_to_response(result["release"]),
        ),
    )


@router.post("/{agent_id}/rollback", response_model=BaseResponse[RollbackAgentResponse])
async def rollback_agent(
    agent_id: uuid.UUID,
    body: RollbackRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[RollbackAgentResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentPublishService(db)
    result = await service.rollback(agent_id, body.release_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=RollbackAgentResponse(
            agent=_to_response(result["agent"]),
        ),
    )


@router.post("/{agent_id}/unpublish", response_model=BaseResponse[UnpublishAgentResponse])
async def unpublish_agent(
    agent_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[UnpublishAgentResponse]:
    agent_svc = AgentService(db)
    await _verify_agent_ownership(agent_svc, agent_id, auth_ctx.project_id)
    service = AgentPublishService(db)
    result = await service.unpublish(agent_id)
    return BaseResponse(
        success=True,
        code=200,
        msg="ok",
        data=UnpublishAgentResponse(
            agent=_to_response(result["agent"]),
            release=_release_to_response(result["release"]) if result["release"] else None,
        ),
    )
