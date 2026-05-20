import json
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
from app.conductor.schemas.task import TaskResponse
from app.conductor.schemas.session import SessionResponse
from app.conductor.services.agent_service import AgentService, _split_packed_items
from app.conductor.services.session_service import SessionService

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


def _validate_tool_mcp_references(
    tools: list | None, mcp_configs: list[dict] | None
) -> None:
    """Ensure each tool's mcp_server_name references a declared mcp_server in mcp_configs."""
    if not tools:
        return
    declared_names: set[str] = set()
    if mcp_configs:
        for cfg in mcp_configs:
            name = cfg.get("name", "") if isinstance(cfg, dict) else ""
            if name:
                declared_names.add(name)
    for tool in tools:
        tool_dict = tool.model_dump() if hasattr(tool, "model_dump") else tool
        if tool_dict.get("type") == "mcp_toolset":
            server_name = tool_dict.get("mcp_server_name", "")
            if server_name and server_name not in declared_names:
                raise HTTPException(
                    400,
                    f"Tool references undeclared MCP server: {server_name}",
                )


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
    mcp_dicts = [s.model_dump() for s in req.mcp_servers] if req.mcp_servers else None
    _validate_mcp_configs(mcp_dicts)
    _validate_tool_mcp_references(req.tools, mcp_dicts)
    svc = AgentService(db)
    agent = await svc.create_agent(req)
    return _agent_to_response(agent)


@router.get("")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AgentResponse]:
    svc = AgentService(db)
    agents, has_more = await svc.list_agents(limit, after_id, include_archived=include_archived)
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
    svc = AgentService(db)
    # Fetch current agent first for MCP cross-validation context
    current_agent = await svc.get_agent(agent_id)
    if not current_agent:
        raise HTTPException(404, "Agent not found")

    # Optimistic concurrency check
    if current_agent.version != req.version:
        raise HTTPException(
            409,
            f"Version conflict: expected {req.version}, got {current_agent.version}",
        )

    # Resolve the effective mcp_configs for cross-validation
    if req.mcp_servers is not None:
        mcp_dicts = [s.model_dump() for s in req.mcp_servers]
        _validate_mcp_configs(mcp_dicts)
    else:
        mcp_dicts = current_agent.mcp_configs or []

    # Validate tool -> mcp_server references
    effective_tools = req.tools if req.tools is not None else (current_agent.tools or [])
    _validate_tool_mcp_references(effective_tools, mcp_dicts)

    # No-op detection: compare serialized JSON minus version/updated_at
    def _agent_snapshot(agent) -> str:
        skills, agents_list, commands = _split_packed_items(agent.skills or [])
        snap = {
            "name": agent.name,
            "engine_kind": agent.engine_kind,
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "description": agent.description,
            "metadata": agent.metadata_,
            "env": agent.env,
            "mcp_configs": agent.mcp_configs,
            "skills": skills,
            "agents": agents_list,
            "commands": commands,
            "tools": agent.tools,
            "multiagent": agent.multiagent,
            "environment_ref": agent.environment_ref,
            "secret_ref": agent.secret_ref,
        }
        return json.dumps(snap, sort_keys=True, default=str)

    before_snapshot = _agent_snapshot(current_agent)

    try:
        agent = await svc.update_agent(agent_id, req)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not agent:
        raise HTTPException(404, "Agent not found")

    after_snapshot = _agent_snapshot(agent)
    if before_snapshot == after_snapshot:
        # No real change — return existing agent without bumping version
        return _agent_to_response(current_agent)

    return _agent_to_response(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    await svc.hard_delete_agent(agent_id)


@router.post("/{agent_id}/archive", status_code=200)
async def archive_agent(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    archived_session_ids = await svc.archive_sessions_for_agent(agent_id)
    return {
        "status": "archived",
        "archived_sessions": len(archived_session_ids),
    }


@router.get("/{agent_id}/tasks")
async def list_agent_tasks(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[TaskResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    tasks = await svc.list_active_tasks_for_agent(agent_id)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("/{agent_id}/sessions")
async def list_agent_sessions(
    agent_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SessionResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    session_svc = SessionService(db)
    sessions, has_more = await session_svc.list_sessions_by_agent(agent_id, limit, after_id)

    def _session_to_response(session) -> SessionResponse:
        from app.conductor.api.sessions import _session_to_response as _s2r
        return _s2r(session, agent)

    data = [_session_to_response(s) for s in sessions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


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
