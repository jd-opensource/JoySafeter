import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.agent import (
    AgentResponse,
    AgentVersionResponse,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.agent_service import AgentService, _split_packed_items

router = APIRouter(tags=["conductor-agents"])


def _validate_mcp_configs(mcp_configs: list[dict] | None) -> None:
    if not mcp_configs:
        return
    seen_names: set[str] = set()
    for cfg in mcp_configs:
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url", "")
        if url.startswith("http://"):
            raise HTTPException(400, f"MCP server URL must use HTTPS: {url}")
        name = cfg.get("name", "")
        if name:
            if name in seen_names:
                raise HTTPException(400, f"Duplicate MCP server name: {name}")
            seen_names.add(name)


def _agent_to_response(agent) -> AgentResponse:
    skills, agents, commands = _split_packed_items(agent.skills or [])
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        engine_kind=agent.engine_kind,
        model=agent.model,
        system=agent.system_prompt,
        description=agent.description,
        metadata=agent.metadata_,
        env=agent.env,
        mcp_servers=agent.mcp_configs,
        skills=skills,
        agents=agents,
        commands=commands,
        tools=agent.tools,
        multiagent=agent.multiagent,
        version=agent.version,
        environment_ref=agent.environment_ref,
        secret_ref=agent.secret_ref,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        archived_at=agent.archived_at,
    )


@router.post("", status_code=201)
async def create_agent(
    req: CreateAgentRequest, db: AsyncSession = Depends(get_db)
) -> AgentResponse:
    _validate_mcp_configs([s.model_dump() for s in req.mcp_servers] if req.mcp_servers else None)
    svc = AgentService(db)
    agent = await svc.create_agent(req)
    return _agent_to_response(agent)


@router.get("")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AgentResponse]:
    svc = AgentService(db)
    agents, has_more = await svc.list_agents(limit, after_id)
    data = [_agent_to_response(a) for a in agents]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> AgentResponse:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return _agent_to_response(agent)


@router.post("/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    req: UpdateAgentRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    if req.mcp_servers is not None:
        _validate_mcp_configs([s.model_dump() for s in req.mcp_servers])
    svc = AgentService(db)
    try:
        agent = await svc.update_agent(agent_id, req)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not agent:
        raise HTTPException(404, "Agent not found")
    return _agent_to_response(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = AgentService(db)
    try:
        ok = await svc.delete_agent(agent_id, force)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not ok:
        raise HTTPException(404, "Agent not found")


@router.post("/{agent_id}/archive", status_code=200)
async def archive_agent(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = AgentService(db)
    ok = await svc.archive_agent(agent_id)
    if not ok:
        raise HTTPException(404, "Agent not found")
    return {"status": "archived"}


@router.get("/{agent_id}/versions")
async def list_agent_versions(
    agent_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    before_version: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AgentVersionResponse]:
    svc = AgentService(db)
    versions, has_more = await svc.list_versions(agent_id, limit, before_version)
    data = [AgentVersionResponse.model_validate(v) for v in versions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )
