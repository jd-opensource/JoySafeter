import json
import logging
import uuid
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_agent_id
from app.joysafeter_api.services import JoySafeterAgentService as AgentService
from app.joysafeter_api.services import SecretService, SessionService, _split_packed_items
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_agent import (
    AgentVersionResponse,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterAgentResponse as AgentResponse,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest as CreateAgentRequest,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterUpdateAgentRequest as UpdateAgentRequest,
)
from app.joysafeter_domain.schemas.joysafeter_session import SessionResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse as TaskResponse
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-agents"])


_LOCAL_MCP_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal", "::1"}


def _validate_mcp_configs(mcp_configs: list[dict] | None) -> None:
    if not mcp_configs:
        return
    seen_names: set[str] = set()
    for cfg in mcp_configs:
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url", "")
        if url.startswith("http://"):
            # Allow http:// for clearly-local development addresses so users can
            # point MCP at a host-side dev server. Everything else must be HTTPS.
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if host not in _LOCAL_MCP_HOSTS:
                raise HTTPException(400, f"MCP server URL must use HTTPS: {url}")
        name = cfg.get("name", "")
        if name:
            if name in seen_names:
                raise HTTPException(400, f"Duplicate MCP server name: {name}")
            seen_names.add(name)


def _validate_tool_mcp_references(tools: list | None, mcp_configs: list[dict] | None) -> None:
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


def _secret_matches_engine(secret, engine_kind: str) -> bool:
    provider = (getattr(secret, "provider", "") or "").lower()
    protocol = (getattr(secret, "protocol", "") or "").lower()
    keys = set((getattr(secret, "data", None) or {}).keys())
    if engine_kind == "codex":
        return provider == "codex" or protocol in {"openai_responses", "chat_completions"} or "OPENAI_API_KEY" in keys
    if engine_kind in ("claude", "native"):
        return (
            provider in {"anthropic", "claude"}
            or protocol == "anthropic_messages"
            or "ANTHROPIC_API_KEY" in keys
            or "ANTHROPIC_AUTH_TOKEN" in keys
        )
    return True


async def _validate_secret_ref_for_engine(
    db: AsyncSession,
    *,
    secret_ref: Optional[str],
    engine_kind: str,
    project_id: Optional[str],
) -> None:
    if not secret_ref:
        return
    secret_svc = SecretService(db)
    secret = await secret_svc.get_secret_by_name(secret_ref, project_id=project_id)
    if not secret:
        raise HTTPException(400, f"Secret not found: {secret_ref}")
    if not _secret_matches_engine(secret, engine_kind):
        raise HTTPException(
            400,
            f"Secret '{secret_ref}' is not compatible with engine_kind '{engine_kind}'",
        )


def _model_from_secret_data(secret_data: dict[str, Any] | None, engine_kind: str | None) -> Optional[dict[str, str]]:
    if not secret_data:
        return None

    if (engine_kind or "claude") == "codex":
        model_id = secret_data.get("OPENAI_MODEL")
    else:
        # claude, native, and any other engine
        model_id = secret_data.get("ANTHROPIC_MODEL") or secret_data.get("MODEL")

    return {"id": str(model_id)} if model_id else None


async def _resolve_agent_model(
    agent,
    secret_svc: SecretService,
    *,
    project_id: Optional[str],
    secret_cache: Optional[dict[str, Optional[dict[str, Any]]]] = None,
) -> Optional[dict[str, Any]]:
    if agent.model:
        return cast(Optional[dict[str, Any]], agent.model)
    if not agent.secret_ref:
        return None

    if secret_cache is not None:
        if agent.secret_ref not in secret_cache:
            secret = await secret_svc.get_secret_by_name(agent.secret_ref, project_id=project_id)
            secret_cache[agent.secret_ref] = secret_svc.get_secret_data(secret) if secret else None
        secret_data = secret_cache.get(agent.secret_ref)
    else:
        secret = await secret_svc.get_secret_by_name(agent.secret_ref, project_id=project_id)
        secret_data = secret_svc.get_secret_data(secret) if secret else None

    return _model_from_secret_data(secret_data, getattr(agent, "engine_kind", None))


def _agent_to_response(agent, *, model: Optional[dict[str, Any]] = None) -> AgentResponse:
    skills, agents, commands = _split_packed_items(agent.skills or [])
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        engine_kind=agent.engine_kind,
        model=cast(Any, model if model is not None else agent.model),
        system=agent.system_prompt,
        description=agent.description,
        metadata=agent.metadata_,
        env=agent.env,
        mcp_servers=agent.mcp_configs,
        skills=cast(Any, skills),
        agents=cast(Any, agents),
        commands=cast(Any, commands),
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
    req: CreateAgentRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> AgentResponse:
    mcp_dicts = [s.model_dump() for s in req.mcp_servers] if req.mcp_servers else None
    _validate_mcp_configs(mcp_dicts)
    _validate_tool_mcp_references(req.tools, mcp_dicts)
    await _validate_secret_ref_for_engine(
        db,
        secret_ref=req.secret_ref,
        engine_kind=req.engine_kind.value,
        project_id=auth_ctx.project_id,
    )
    svc = AgentService(db)
    agent = await svc.create_agent(req, project_id=auth_ctx.project_id)
    secret_svc = SecretService(db)
    model = await _resolve_agent_model(agent, secret_svc, project_id=auth_ctx.project_id)
    return _agent_to_response(agent, model=model)


@router.get("")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentResponse]:
    svc = AgentService(db)
    agents, has_more = await svc.list_agents(
        limit, after_id, include_archived=include_archived, project_id=auth_ctx.project_id
    )

    secret_svc = SecretService(db)
    secret_cache: dict[str, Optional[dict]] = {}
    data = [
        _agent_to_response(
            agent,
            model=await _resolve_agent_model(
                agent,
                secret_svc,
                project_id=auth_ctx.project_id,
                secret_cache=secret_cache,
            ),
        )
        for agent in agents
    ]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID = Depends(parse_agent_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> AgentResponse:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Agent not found")
    secret_svc = SecretService(db)
    model = await _resolve_agent_model(agent, secret_svc, project_id=auth_ctx.project_id)
    return _agent_to_response(agent, model=model)


@router.post("/{agent_id}")
async def update_agent(
    req: UpdateAgentRequest,
    agent_id: uuid.UUID = Depends(parse_agent_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> AgentResponse:
    svc = AgentService(db)
    # Fetch current agent first for MCP cross-validation context
    current_agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not current_agent:
        raise HTTPException(404, "Agent not found")

    # Archived guard: reject updates on archived agents
    if current_agent.archived_at is not None:
        raise HTTPException(409, "Agent is archived and read-only. Updates are not allowed.")

    # Optimistic concurrency check -- only if version is provided
    if req.version is not None and current_agent.version != req.version:
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

    effective_engine_kind = req.engine_kind.value if req.engine_kind is not None else current_agent.engine_kind
    effective_secret_ref = req.secret_ref if req.secret_ref is not None else current_agent.secret_ref
    await _validate_secret_ref_for_engine(
        db,
        secret_ref=effective_secret_ref,
        engine_kind=effective_engine_kind,
        project_id=auth_ctx.project_id,
    )

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
        agent = await svc.update_agent(agent_id, req, project_id=auth_ctx.project_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not agent:
        raise HTTPException(404, "Agent not found")

    after_snapshot = _agent_snapshot(agent)
    secret_svc = SecretService(db)
    if before_snapshot == after_snapshot:
        # No real change — return existing agent without bumping version
        model = await _resolve_agent_model(current_agent, secret_svc, project_id=auth_ctx.project_id)
        return _agent_to_response(current_agent, model=model)

    model = await _resolve_agent_model(agent, secret_svc, project_id=auth_ctx.project_id)
    return _agent_to_response(agent, model=model)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID = Depends(parse_agent_id),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    if not force:
        # Check for active tasks before soft delete
        active_tasks = await svc.list_active_tasks_for_agent(agent_id)
        if active_tasks:
            raise HTTPException(
                409,
                "Agent has active tasks (pending/running). Use ?force=true to force delete.",
            )
        await svc.hard_delete_agent(agent_id)
        return

    # Force delete: cascade cleanup
    await _cancel_active_tasks_for_agent(agent_id, db)
    await svc.hard_delete_agent(agent_id)


async def _cancel_active_tasks_for_agent(agent_id: uuid.UUID, db: AsyncSession) -> None:
    """Cancel all active tasks, send gRPC Shutdown to sandboxes, archive sessions,
    stop containers. Mirrors the Rust cancel_active_tasks_for_agent."""
    from app.joysafeter_api.services import JoySafeterTaskService as TaskService
    from app.joysafeter_api.services import SandboxService
    from app.joysafeter_orchestrator.lifespan import (
        get_bridge_registry,
        get_sandbox_provider,
        get_session_broadcaster,
    )

    svc = AgentService(db)
    task_svc = TaskService(db)
    sandbox_svc = SandboxService(db)

    active_tasks = await svc.list_active_tasks_for_agent(agent_id)
    sandbox_ids_to_stop: set[uuid.UUID] = set()
    cancelled = 0
    bridge_registry = get_bridge_registry()

    for task in active_tasks:
        # Send CancelTask to the sandbox bridge
        sandbox_id = getattr(task, "sandbox_id", None)
        if sandbox_id and bridge_registry:
            bridge = await bridge_registry.get(sandbox_id)
            if bridge:
                from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2

                cancel_msg = joysafeter_pb2.OrchestratorMessage(
                    cancel=joysafeter_pb2.CancelTask(reason="Agent archived")
                )
                try:
                    await bridge.write_to_runner(cancel_msg)
                except Exception:
                    pass
            sandbox_ids_to_stop.add(sandbox_id)

        # Mark task as cancelled in DB
        try:
            await task_svc.cancel_task(task.id)
            cancelled += 1
        except Exception:
            logger.debug("Failed to cancel task %s during agent force delete", task.id)

    # Archive sessions for the agent
    session_broadcaster = get_session_broadcaster()
    try:
        archived_session_ids = await svc.archive_sessions_for_agent(agent_id)
        if archived_session_ids and session_broadcaster:
            for sid in archived_session_ids:
                stop_reason_event = {
                    "type": "session.status_terminated",
                    "stop_reason": {"type": "agent_archived"},
                }
                await session_broadcaster.send(sid, stop_reason_event)
    except Exception:
        logger.warning("Failed to archive sessions for agent %s", agent_id, exc_info=True)

    # Send Shutdown to each sandbox and stop containers
    provider = get_sandbox_provider()
    for sandbox_id in sandbox_ids_to_stop:
        if bridge_registry:
            bridge = await bridge_registry.get(sandbox_id)
            if bridge:
                from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2

                shutdown_msg = joysafeter_pb2.OrchestratorMessage(
                    shutdown=joysafeter_pb2.Shutdown(reason="Agent archived")
                )
                try:
                    await bridge.write_to_runner(shutdown_msg)
                except Exception:
                    pass
            await bridge_registry.remove(sandbox_id)

        # Stop container via provider
        if provider:
            sandbox = await sandbox_svc.get_sandbox(sandbox_id)
            if sandbox and sandbox.external_id:
                status = getattr(sandbox, "status", "")
                if status not in ("destroyed", "stopped", "error"):
                    try:
                        await provider.stop(sandbox.external_id)
                    except Exception:
                        pass
                    try:
                        await sandbox_svc.update_status_cas(sandbox_id, status, "stopped")
                    except Exception:
                        pass

    if cancelled > 0:
        logger.info(
            "Cancelled %d active tasks and stopped %d sandboxes for agent %s",
            cancelled,
            len(sandbox_ids_to_stop),
            agent_id,
        )


@router.post("/{agent_id}/archive", status_code=200)
async def archive_agent(
    agent_id: uuid.UUID = Depends(parse_agent_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    from datetime import datetime, timezone

    agent.archived_at = datetime.now(timezone.utc)
    await db.commit()
    archived_session_ids = await svc.archive_sessions_for_agent(agent_id)
    return {
        "status": "archived",
        "archived_sessions": len(archived_session_ids),
    }


@router.get("/{agent_id}/tasks")
async def list_agent_tasks(
    agent_id: uuid.UUID = Depends(parse_agent_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[TaskResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    tasks = await svc.list_active_tasks_for_agent(agent_id)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("/{agent_id}/sessions")
async def list_agent_sessions(
    agent_id: uuid.UUID = Depends(parse_agent_id),
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    session_svc = SessionService(db)
    sessions, has_more = await session_svc.list_sessions_by_agent(
        agent_id,
        limit,
        after_id,
        project_id=auth_ctx.project_id,
        include_archived=include_archived,
    )

    def _session_to_response(session) -> SessionResponse:
        from app.joysafeter_api.api.v1.sessions import _session_to_response as _s2r

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
    agent_id: uuid.UUID = Depends(parse_agent_id),
    limit: int = Query(20, ge=1, le=100),
    before_version: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentVersionResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    versions, has_more = await svc.list_versions(agent_id, limit, before_version)
    data = [AgentVersionResponse.model_validate(v) for v in versions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )
