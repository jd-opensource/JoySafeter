import json
import logging
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.llm.compatibility import (
    validate_engine,
)
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
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService as AgentService
from app.joysafeter_domain.services.joysafeter_agent_service import _split_agent_assets
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import AgentId, SessionId
from app.joysafeter_shared.orchestrator_bridge.runtime_commands import (
    relay_sandbox_destroy_via_redis,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-agents"])


_LOCAL_MCP_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal", "::1"}


def _agent_config_error(*, code: str, message: str, data: dict[str, Any]) -> AppError:
    return InvalidRequestError(
        code=code,
        message=message,
        data=data,
        user_action="fix_input",
    )


def _agent_not_found_error(agent_id: AgentId) -> AppError:
    return NotFoundError(
        code="AGENT_NOT_FOUND",
        message="Agent not found",
        data={"agent_id": str(agent_id)},
        user_action="refresh",
    )


def _validate_mcp_servers(mcp_servers: list[dict] | None) -> None:
    if not mcp_servers:
        return
    seen_names: set[str] = set()
    for cfg in mcp_servers:
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url", "")
        if url.startswith("http://"):
            # Allow http:// for clearly-local development addresses so users can
            # point MCP at a host-side dev server. Everything else must be HTTPS.
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if host not in _LOCAL_MCP_HOSTS:
                raise _agent_config_error(
                    code="AGENT_MCP_URL_SCHEME_INVALID",
                    message=f"MCP server URL must use HTTPS: {url}",
                    data={"url": url, "host": host},
                )
        name = cfg.get("name", "")
        if name:
            if name in seen_names:
                raise _agent_config_error(
                    code="AGENT_MCP_SERVER_NAME_DUPLICATE",
                    message=f"Duplicate MCP server name: {name}",
                    data={"mcp_server_name": name},
                )
            seen_names.add(name)


def _validate_tool_mcp_references(tools: list | None, mcp_servers: list[dict] | None) -> None:
    """Ensure each tool's mcp_server_name references a declared MCP server."""
    if not tools:
        return
    declared_names: set[str] = set()
    if mcp_servers:
        for cfg in mcp_servers:
            name = cfg.get("name", "") if isinstance(cfg, dict) else ""
            if name:
                declared_names.add(name)
    for tool in tools:
        tool_dict = tool.model_dump() if hasattr(tool, "model_dump") else tool
        if tool_dict.get("type") == "mcp_toolset":
            server_name = tool_dict.get("mcp_server_name", "")
            if server_name and server_name not in declared_names:
                raise _agent_config_error(
                    code="AGENT_TOOL_MCP_SERVER_UNDECLARED",
                    message=f"Tool references undeclared MCP server: {server_name}",
                    data={"mcp_server_name": server_name, "declared_mcp_server_names": sorted(declared_names)},
                )


async def _validate_environment_ref(
    db: AsyncSession,
    *,
    environment_ref: Optional[str],
    project_id: Optional[str],
) -> None:
    if not environment_ref:
        return
    env_svc = EnvironmentService(db)
    environment = await env_svc.get_environment_by_ref(environment_ref, project_id=project_id)
    if not environment:
        raise _agent_config_error(
            code="AGENT_ENVIRONMENT_NOT_FOUND",
            message=f"Environment not found: {environment_ref}",
            data={"environment_ref": environment_ref},
        )
    if environment.archived_at is not None:
        raise ResourceConflictError(
            code="ENVIRONMENT_ARCHIVED",
            message=f"Environment is archived: {environment_ref}",
            data={"environment_ref": environment_ref, "environment_id": str(environment.id)},
            user_action="refresh",
        )


def _agent_to_response(agent) -> AgentResponse:
    skills, agents, commands = _split_agent_assets(agent.skills or [])
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        engine_kind=agent.engine_kind,
        model=cast(Any, agent.model),
        system=agent.system_prompt,
        description=agent.description,
        metadata=agent.metadata_,
        env=agent.env,
        mcp_servers=agent.mcp_servers,
        skills=cast(Any, skills),
        agents=cast(Any, agents),
        commands=cast(Any, commands),
        tools=agent.tools,
        multiagent=agent.multiagent,
        version=agent.version,
        environment_ref=agent.environment_ref,
        model_credential_id=agent.model_credential_id,
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
    _validate_mcp_servers(mcp_dicts)
    _validate_tool_mcp_references(req.tools, mcp_dicts)
    validate_engine(req.engine_kind.value)
    await _validate_environment_ref(
        db,
        environment_ref=req.environment_ref,
        project_id=auth_ctx.project_id,
    )
    svc = AgentService(db)
    agent = await svc.create_agent(req, project_id=auth_ctx.project_id)
    return _agent_to_response(agent)


@router.get("")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[AgentId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentResponse]:
    svc = AgentService(db)
    agents, has_more = await svc.list_agents(
        limit, after_id, include_archived=include_archived, project_id=auth_ctx.project_id
    )

    data = [_agent_to_response(agent) for agent in agents]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> AgentResponse:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    return _agent_to_response(agent)


@router.post("/{agent_id}")
async def update_agent(
    req: UpdateAgentRequest,
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> AgentResponse:
    svc = AgentService(db)
    # Fetch current agent first for MCP cross-validation context
    current_agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not current_agent:
        raise _agent_not_found_error(agent_id)

    # Archived guard: reject updates on archived agents
    if current_agent.archived_at is not None:
        raise ResourceConflictError(
            code="AGENT_ARCHIVED",
            message="Agent is archived and read-only. Updates are not allowed.",
            data={"agent_id": str(agent_id)},
            user_action="refresh",
        )

    # Optimistic concurrency check -- only if version is provided
    if req.version is not None and current_agent.version != req.version:
        raise ResourceConflictError(
            code="AGENT_VERSION_CONFLICT",
            message=f"Version conflict: expected {req.version}, got {current_agent.version}",
            data={
                "agent_id": str(agent_id),
                "expected_version": req.version,
                "actual_version": current_agent.version,
            },
            user_action="refresh",
        )

    # Resolve the effective MCP servers for cross-validation.
    if req.mcp_servers is not None:
        mcp_dicts = [s.model_dump() for s in req.mcp_servers]
        _validate_mcp_servers(mcp_dicts)
    else:
        mcp_dicts = current_agent.mcp_servers or []

    # Validate tool -> mcp_server references
    effective_tools = req.tools if req.tools is not None else (current_agent.tools or [])
    _validate_tool_mcp_references(effective_tools, mcp_dicts)

    effective_engine_kind = req.engine_kind.value if req.engine_kind is not None else current_agent.engine_kind
    model_credential_supplied = "model_credential_id" in req.model_fields_set
    effective_environment_ref = (
        req.environment_ref if req.environment_ref is not None else current_agent.environment_ref
    )
    validate_engine(effective_engine_kind)
    await _validate_environment_ref(
        db,
        environment_ref=effective_environment_ref,
        project_id=auth_ctx.project_id,
    )

    dependency_ref_changed = (
        model_credential_supplied and req.model_credential_id != current_agent.model_credential_id
    ) or (req.environment_ref is not None and req.environment_ref != current_agent.environment_ref)
    if dependency_ref_changed:
        active_tasks = await svc.list_active_tasks_for_agent(agent_id, project_id=auth_ctx.project_id)
        if active_tasks:
            raise ResourceConflictError(
                code="AGENT_ACTIVE_TASKS",
                message=(
                    "Agent has active tasks. Stop or wait for them before changing "
                    "model_credential_id or environment_ref."
                ),
                data={
                    "agent_id": str(agent_id),
                    "active_task_ids": [str(task.id) for task in active_tasks],
                },
                retryable=True,
                user_action="retry",
            )

    # No-op detection: compare serialized JSON minus version/updated_at
    def _agent_snapshot(agent) -> str:
        snap = svc.build_execution_snapshot(agent)
        snap.pop("version", None)
        return json.dumps(snap, sort_keys=True, default=str)

    before_snapshot = _agent_snapshot(current_agent)

    try:
        agent = await svc.update_agent(agent_id, req, project_id=auth_ctx.project_id)
    except ValueError as e:
        raise ResourceConflictError(
            code="AGENT_VERSION_CONFLICT",
            message=str(e),
            data={"agent_id": str(agent_id)},
        ) from e
    if not agent:
        raise _agent_not_found_error(agent_id)

    after_snapshot = _agent_snapshot(agent)
    if before_snapshot == after_snapshot:
        # No real change — return existing agent without bumping version
        return _agent_to_response(current_agent)

    return _agent_to_response(agent)


@router.get("/{agent_id}/delete_preview")
async def delete_agent_preview(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> dict[str, int]:
    """Counts of data that will be removed when the agent is deleted.

    Powers the frontend delete-confirmation dialog. Returns exact counts of
    sessions, active tasks, and versions tied to the agent.
    """
    svc = AgentService(db)
    counts = await svc.count_delete_preview(agent_id, project_id=auth_ctx.project_id)
    if counts is None:
        raise _agent_not_found_error(agent_id)
    sessions, tasks, versions, triggers = counts
    return {"sessions": sessions, "tasks": tasks, "versions": versions, "triggers": triggers}


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: AgentId,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)

    # Cleanup agent identity credentials (Redis cache + identity platform)
    await _cleanup_agent_identity(str(agent_id))

    if not force:
        # Check for active tasks before soft delete
        active_tasks = await svc.list_active_tasks_for_agent(agent_id, project_id=auth_ctx.project_id)
        if active_tasks:
            raise ResourceConflictError(
                code="AGENT_ACTIVE_TASKS",
                message="Agent has active tasks (pending/running). Use ?force=true to force delete.",
                data={
                    "agent_id": str(agent_id),
                    "active_task_ids": [str(task.id) for task in active_tasks],
                },
                retryable=True,
                user_action="retry",
            )
        try:
            await _destroy_sandboxes_for_agent(
                agent_id,
                db,
                reason="Agent deleted",
                project_id=auth_ctx.project_id,
            )
            ok = await svc.hard_delete_agent(agent_id, project_id=auth_ctx.project_id)
        except ValueError as e:
            raise ResourceConflictError(
                code="AGENT_ACTIVE_TASKS",
                message=str(e),
                data={"agent_id": str(agent_id)},
                retryable=True,
                user_action="retry",
            ) from e
        if not ok:
            raise _agent_not_found_error(agent_id)
        return

    # Force delete: cascade cleanup
    await _cancel_active_tasks_for_agent(agent_id, db, project_id=auth_ctx.project_id)
    await _destroy_sandboxes_for_agent(
        agent_id,
        db,
        reason="Agent force deleted",
        project_id=auth_ctx.project_id,
    )
    try:
        ok = await svc.hard_delete_agent(agent_id, project_id=auth_ctx.project_id)
    except ValueError as e:
        raise ServiceUnavailableError(
            code="AGENT_FORCE_DELETE_ACTIVE_TASKS_REMAIN",
            message=str(e),
            data={"agent_id": str(agent_id)},
            retryable=True,
            user_action="refresh",
        ) from e
    if not ok:
        raise _agent_not_found_error(agent_id)


async def _cancel_active_tasks_for_agent(agent_id: AgentId, db: AsyncSession, project_id: Optional[str] = None) -> None:
    """Cancel all active tasks through the Rust runtime boundary."""
    from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService

    svc = AgentService(db)
    cancellation = TaskCancellationService(db)

    active_tasks = await svc.list_active_tasks_for_agent(agent_id, project_id=project_id)
    cancelled = 0

    for task in active_tasks:
        try:
            await cancellation.cancel(task, reason="Agent deleted")
            cancelled += 1
        except ServiceUnavailableError as exc:
            if exc.code == "TASK_CANCEL_REDIS_RELAY_FAILED":
                sandbox_id = (exc.data or {}).get("sandbox_id") or str(getattr(task, "sandbox_id", ""))
                raise ServiceUnavailableError(
                    code="AGENT_REDIS_CANCEL_RELAY_FAILED",
                    message="Failed to cancel agent task in sandbox runtime.",
                    data={
                        "agent_id": str(agent_id),
                        "task_id": str(task.id),
                        "sandbox_id": str(sandbox_id),
                    },
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                ) from exc
            logger.debug("Failed to cancel task %s during agent force delete", task.id, exc_info=True)
        except Exception:
            logger.debug("Failed to cancel task %s during agent force delete", task.id, exc_info=True)

    remaining_active = await svc.list_active_tasks_for_agent(agent_id, project_id=project_id)
    if remaining_active:
        logger.warning(
            "Could not cancel all active tasks for agent %s: remaining=%s",
            agent_id,
            [str(task.id) for task in remaining_active],
        )
        raise ServiceUnavailableError(
            code="AGENT_FORCE_CANCEL_ACTIVE_TASKS_FAILED",
            message="Failed to cancel all active tasks for agent",
            data={
                "agent_id": str(agent_id),
                "active_task_ids": [str(task.id) for task in remaining_active],
            },
            source="runtime",
            retryable=True,
            user_action="retry",
        )

    try:
        await svc.archive_sessions_for_agent(agent_id, project_id=project_id)
    except Exception as exc:
        log_boundary_failure(
            logger,
            boundary="agent_api",
            code="AGENT_SESSION_ARCHIVE_FAILED",
            message="Failed to archive sessions during agent cleanup",
            operation="archive_agent_sessions",
            error=exc,
            data={"agent_id": str(agent_id)},
        )
        raise ServiceUnavailableError(
            code="AGENT_SESSION_ARCHIVE_FAILED",
            message="Failed to archive sessions during agent cleanup.",
            data={"agent_id": str(agent_id)},
            source="api",
            retryable=True,
            user_action="retry",
        ) from None

    if cancelled > 0:
        logger.info(
            "Cancelled %d active tasks for agent %s",
            cancelled,
            agent_id,
        )


async def _destroy_sandboxes_for_agent(
    agent_id: AgentId,
    db: AsyncSession,
    *,
    reason: str,
    project_id: Optional[str] = None,
) -> None:
    from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService

    sandbox_svc = SandboxService(db)
    sandboxes = await sandbox_svc.list_active_for_agent(agent_id, project_id=project_id)
    if not sandboxes:
        return

    for sandbox in sandboxes:
        expected_external_id = str(sandbox.external_id or "") or None
        relayed = await relay_sandbox_destroy_via_redis(
            sandbox.id,
            boundary="agent_api",
            operation="delete_agent_destroy_sandbox",
            failure_code="AGENT_SANDBOX_DESTROY_FAILED",
            failure_message="Redis sandbox destroy relay failed during agent delete",
            reason=reason,
            external_id=expected_external_id,
            data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
        )
        if not relayed:
            raise ServiceUnavailableError(
                code="AGENT_SANDBOX_DESTROY_FAILED",
                message="Agent could not be deleted because sandbox cleanup failed.",
                data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                source="runtime",
                retryable=True,
                user_action="retry",
            )
        try:
            destroyed = await sandbox_svc.mark_destroyed_after_runtime_ack(
                sandbox.id,
                sandbox.status,
                expected_external_id,
            )
        except Exception as exc:
            log_boundary_failure(
                logger,
                boundary="agent_api",
                code="AGENT_SANDBOX_STATE_SYNC_FAILED",
                message="Failed to mark sandbox destroyed during agent cleanup",
                operation="delete_agent_mark_sandbox_destroyed",
                error=exc,
                data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
            )
            raise ServiceUnavailableError(
                code="AGENT_SANDBOX_STATE_SYNC_FAILED",
                message="Agent could not be deleted because sandbox state sync failed.",
                data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                source="api",
                retryable=True,
                user_action="retry",
            ) from None
        if not destroyed:
            raise ServiceUnavailableError(
                code="AGENT_SANDBOX_STATE_SYNC_FAILED",
                message="Agent could not be deleted because sandbox state sync failed.",
                data={"agent_id": str(agent_id), "sandbox_id": str(sandbox.id)},
                source="api",
                retryable=True,
                user_action="retry",
            )


async def _cleanup_agent_identity(agent_id: AgentId) -> None:
    """Clear cached agent identity tokens from Redis on agent deletion.

    Only removes the cache entries. Any real revocation on the identity
    platform is handled by the orchestrator's identity provider; cached
    credentials also carry a TTL and expire naturally.

    The cache key prefix is provider-defined and supplied via
    ``AGENT_IDENTITY_CACHE_PREFIX``; when unset, cleanup is skipped.
    Non-fatal: errors are logged but don't block agent deletion.
    """
    import os

    cache_prefix = os.environ.get("AGENT_IDENTITY_CACHE_PREFIX", "").strip()
    if not cache_prefix:
        return  # No cache-key convention configured — nothing to clear

    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        redis_host = os.environ.get("REDIS_HOST", "")
        if not redis_host:
            return
        redis_port = os.environ.get("REDIS_PORT", "6379")
        redis_password = os.environ.get("REDIS_PASSWORD", "")
        if redis_password:
            redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
        else:
            redis_url = f"redis://{redis_host}:{redis_port}/0"

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url)
        pattern = f"{cache_prefix}:*:{agent_id}:*"
        deleted = 0
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
            deleted += 1
        await client.aclose()
        if deleted:
            logger.info(
                f"Cleared {deleted} agent identity cache entries for agent {agent_id}"
            )
    except Exception as e:
        logger.warning(
            f"Agent identity cache cleanup failed for {agent_id} (non-fatal): {e}"
        )


@router.post("/{agent_id}/archive", status_code=200)
async def archive_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    try:
        archived, archived_session_ids = await svc.archive_agent_with_sessions(agent_id, project_id=auth_ctx.project_id)
    except ValueError as e:
        raise ResourceConflictError(
            code="AGENT_ACTIVE_TASKS",
            message=str(e),
            data={"agent_id": str(agent_id)},
            retryable=True,
            user_action="retry",
        ) from e
    if not archived:
        raise _agent_not_found_error(agent_id)
    return {
        "status": "archived",
        "archived_sessions": len(archived_session_ids),
    }


@router.post("/{agent_id}/unarchive", status_code=200)
async def unarchive_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = AgentService(db)
    restored = await svc.restore_agent(agent_id, project_id=auth_ctx.project_id)
    if not restored:
        raise _agent_not_found_error(agent_id)
    return {"status": "active"}


@router.get("/{agent_id}/tasks")
async def list_agent_tasks(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[TaskResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    tasks = await svc.list_active_tasks_for_agent(agent_id, project_id=auth_ctx.project_id)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("/{agent_id}/sessions")
async def list_agent_sessions(
    agent_id: AgentId,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[SessionId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
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
    agent_id: AgentId,
    limit: int = Query(20, ge=1, le=100),
    before_version: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentVersionResponse]:
    svc = AgentService(db)
    agent = await svc.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    versions, has_more = await svc.list_versions(agent_id, limit, before_version, project_id=auth_ctx.project_id)
    data = [AgentVersionResponse.model_validate(v) for v in versions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )
