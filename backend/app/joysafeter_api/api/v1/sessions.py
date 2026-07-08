import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.id_helpers import parse_session_id as _parse_session_id
from app.joysafeter_api.services import JoySafeterAgentService as AgentService
from app.joysafeter_api.services import SessionService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_session import (
    MAX_MEMORY_STORE_RESOURCES,
    AgentRef,
    CreateSessionRequest,
    SendEventRequest,
    SessionAgent,
    SessionEventResponse,
    SessionRepoResourceResponse,
    SessionResourceResponse,
    SessionResponse,
    SessionUsage,
    SingleEventRequest,
)
from app.joysafeter_shared.common.app_errors import (
    AppError,
    InvalidRequestError,
    NotFoundError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-sessions"])


def _validate_mount_path(path: str) -> str:
    """Validate mount_path: must be under /workspace/, no '..' traversal."""
    import posixpath

    normalized = posixpath.normpath(path)
    if not normalized.startswith("/workspace/"):
        raise InvalidRequestError(
            code="SESSION_RESOURCE_MOUNT_PATH_INVALID",
            message="mount_path must be under /workspace/",
            data={"mount_path": path},
            user_action="fix_input",
        )
    if ".." in normalized.split("/"):
        raise InvalidRequestError(
            code="SESSION_RESOURCE_MOUNT_PATH_INVALID",
            message="mount_path must not contain '..' components",
            data={"mount_path": path},
            user_action="fix_input",
        )
    return normalized


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify_mount_name(name: str) -> str:
    """Slugify a store name: lowercase, replace non-alphanumeric runs with '-'."""
    return _NON_ALNUM_RE.sub("-", name.lower()).strip("-")


def _canonical_environment_ref(raw: str | None) -> str:
    ref = (raw or "").strip()
    if not ref:
        return ""
    try:
        env_id = uuid.UUID(ref.removeprefix("env_"))
        return f"env_{env_id}"
    except ValueError:
        return ref


def _extract_host(url: str) -> str | None:
    try:
        from urllib.parse import urlparse

        return urlparse(url).hostname
    except Exception:
        return None


def _networking_with_agent_mcp_hosts(networking: dict, mcp_configs: list[dict] | None) -> dict:
    if networking.get("type") != "limited":
        return networking

    allowed = list(networking.get("allowed_hosts", []))
    for mcp in mcp_configs or []:
        if isinstance(mcp, dict) and mcp.get("url"):
            host = _extract_host(str(mcp["url"]))
            if host and host not in allowed:
                allowed.append(host)
    return {**networking, "allowed_hosts": allowed}


def _session_task_enqueue_failed_stop_reason(
    *, session_id: uuid.UUID, task_id: uuid.UUID | None = None
) -> dict[str, object]:
    data: dict[str, object] = {"session_id": str(session_id)}
    if task_id is not None:
        data["task_id"] = str(task_id)
    return async_error_payload(
        code="TASK_ENQUEUE_FAILED",
        message="Failed to enqueue task",
        data=data,
        source="runtime",
        retryable=True,
        user_action="retry",
    )


async def _load_session_repos(db: AsyncSession, session_id: uuid.UUID) -> list:
    """Load a session's repo resources (without decrypting tokens)."""
    from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo

    result = await db.execute(
        select(JoySafeterSessionRepo)
        .where(JoySafeterSessionRepo.session_id == session_id)
        .order_by(JoySafeterSessionRepo.created_at)
    )
    return list(result.scalars().all())


def _session_to_response(session, agent=None, resources=None, repo_resources=None) -> SessionResponse:
    agent_snapshot = session.agent_snapshot or {}
    agent_data = SessionAgent(
        id=session.agent_id,
        version=session.agent_version or 1,
        name=agent.name if agent else agent_snapshot.get("name", ""),
        engine_kind=agent.engine_kind if agent else agent_snapshot.get("engine_kind"),
        description=agent.description if agent else agent_snapshot.get("description"),
        model=agent.model if agent else agent_snapshot.get("model"),
        system=agent.system_prompt if agent else agent_snapshot.get("system"),
        tools=agent.tools if agent else agent_snapshot.get("tools") or [],
        skills=agent.skills if agent else agent_snapshot.get("skills") or [],
        mcp_servers=agent.mcp_configs if agent else agent_snapshot.get("mcp_servers") or [],
    )
    usage_data = session.usage or {}
    resource_responses = []
    for r in resources or []:
        resource_responses.append(
            SessionResourceResponse(
                memory_store_id=r.store_id,
                access=r.access,
                instructions=r.instructions,
                mount_name=r.mount_name,
            )
        )
    repo_responses = []
    for rr in repo_resources or []:
        repo_responses.append(
            SessionRepoResourceResponse(
                id=rr.id,
                url=rr.url,
                branch=rr.branch or "",
                mount_path=rr.mount_path or "",
                mount_name=rr.mount_name or "",
            )
        )
    return SessionResponse(
        id=session.id,
        agent=agent_data,
        environment_id=session.environment_ref,
        status=session.status,
        stop_reason=session.stop_reason,
        title=session.title,
        metadata=session.metadata_,
        vault_ids=session.vault_ids or [],
        resources=resource_responses,
        repo_resources=repo_responses,
        usage=SessionUsage(**usage_data) if isinstance(usage_data, dict) else SessionUsage(),
        created_at=session.created_at,
        updated_at=session.updated_at,
        archived_at=session.archived_at,
    )


@router.post("", status_code=201)
async def create_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SessionResponse:
    # --- Validate memory_store resources limit ---
    if len(req.resources) > MAX_MEMORY_STORE_RESOURCES:
        raise InvalidRequestError(
            code="SESSION_MEMORY_STORE_RESOURCE_LIMIT_EXCEEDED",
            message=f"Too many memory_store resources (max {MAX_MEMORY_STORE_RESOURCES})",
            data={"max": MAX_MEMORY_STORE_RESOURCES, "actual": len(req.resources)},
            user_action="fix_input",
        )

    # --- Parse environment_id: canonicalize UUID refs, preserve name refs ---
    environment_ref = _canonical_environment_ref(req.environment_id)

    # --- Resolve agent ---
    agent_svc = AgentService(db)
    agent = None
    pinned_version: Optional[int] = None
    if req.agent:
        if isinstance(req.agent, AgentRef):
            agent = await agent_svc.get_agent(req.agent.id, project_id=auth_ctx.project_id)
            pinned_version = req.agent.version
        else:
            try:
                agent_uuid = uuid.UUID(req.agent.removeprefix("agent_"))
            except ValueError:
                raise InvalidRequestError(
                    code="SESSION_AGENT_ID_INVALID",
                    message=f"Invalid agent id: {req.agent}",
                    data={"agent_id": str(req.agent)},
                    user_action="fix_input",
                )
            agent = await agent_svc.get_agent(agent_uuid, project_id=auth_ctx.project_id)
    elif req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id, project_id=auth_ctx.project_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name, project_id=auth_ctx.project_id)
    if not agent:
        raise NotFoundError(
            code="SESSION_AGENT_NOT_FOUND",
            message="Agent not found",
            data={
                "agent_id": str(req.agent_id or (req.agent.id if isinstance(req.agent, AgentRef) else req.agent)),
                "agent_name": req.agent_name,
            },
            user_action="refresh",
        )

    # --- Build agent_snapshot ---
    agent_version = agent.version
    agent_snapshot: dict = {
        "name": agent.name,
        "engine_kind": agent.engine_kind,
        "model": agent.model,
    }
    if pinned_version is not None:
        snapshot = await agent_svc.get_agent_version_snapshot(agent.id, pinned_version)
        if snapshot is None:
            raise NotFoundError(
                code="SESSION_AGENT_VERSION_NOT_FOUND",
                message=f"Agent version {pinned_version} not found",
                data={"agent_id": str(agent.id), "version": pinned_version},
                user_action="refresh",
            )
        agent_version = pinned_version
        agent_snapshot = snapshot

    # --- Compute mount_name for each resource ---
    from app.joysafeter_api.services import JoySafeterMemoryService as MemoryService

    mem_svc = MemoryService(db)
    resource_dicts = []
    for r in req.resources:
        dump = r.model_dump()
        store = await mem_svc.get_store(r.memory_store_id, project_id=auth_ctx.project_id)
        if not store:
            raise NotFoundError(
                code="SESSION_MEMORY_STORE_NOT_FOUND",
                message=f"Memory store not found: {r.memory_store_id}",
                data={"memory_store_id": str(r.memory_store_id)},
                user_action="refresh",
            )
        if not dump.get("mount_name"):
            dump["mount_name"] = _slugify_mount_name(store.name)
        resource_dicts.append(dump)

    # --- Validate vault_ids belong to this project ---
    if req.vault_ids:
        from app.joysafeter_api.services import VaultService

        vault_svc = VaultService(db)
        for vid_raw in req.vault_ids:
            vid_str = vid_raw.removeprefix("vlt_").removeprefix("vault_")
            try:
                vid_uuid = uuid.UUID(vid_str)
            except ValueError:
                raise InvalidRequestError(
                    code="SESSION_VAULT_ID_INVALID",
                    message=f"Invalid vault_id: {vid_raw}",
                    data={"vault_id": vid_raw},
                    user_action="fix_input",
                )
            vault = await vault_svc.get_vault(vid_uuid)
            if not vault or vault.project_id != auth_ctx.project_id:
                raise NotFoundError(
                    code="SESSION_VAULT_NOT_FOUND",
                    message=f"Vault not found: {vid_raw}",
                    data={"vault_id": vid_raw},
                    user_action="refresh",
                )

    # --- Validate file resources before creating the session ---
    from app.joysafeter_domain.schemas.joysafeter_session import MAX_FILE_RESOURCES, MAX_REPO_RESOURCES

    file_resource_records = []
    if len(req.file_resources) > MAX_FILE_RESOURCES:
        raise InvalidRequestError(
            code="SESSION_FILE_RESOURCE_LIMIT_EXCEEDED",
            message=f"Too many file resources (max {MAX_FILE_RESOURCES})",
            data={"max": MAX_FILE_RESOURCES, "actual": len(req.file_resources)},
            user_action="fix_input",
        )
    if req.file_resources:
        from app.joysafeter_api.services import FileService
        from app.joysafeter_shared.storage import get_storage

        file_svc = FileService(get_storage())
        for fr in req.file_resources:
            file_id_str = fr.file_id.removeprefix("file_")
            try:
                fid = uuid.UUID(file_id_str)
            except ValueError:
                raise InvalidRequestError(
                    code="SESSION_FILE_ID_INVALID",
                    message=f"Invalid file_id: {fr.file_id}",
                    data={"file_id": fr.file_id},
                    user_action="fix_input",
                )
            record = await file_svc.get_metadata(db, fid, auth_ctx.project_id)
            if not record:
                raise NotFoundError(
                    code="SESSION_FILE_NOT_FOUND",
                    message=f"File not found: {fr.file_id}",
                    data={"file_id": fr.file_id},
                    user_action="refresh",
                )
            mount_path = _validate_mount_path(fr.mount_path or f"/workspace/{record.filename}")
            file_resource_records.append((record.id, mount_path))

    # --- Validate repo resources before creating the session ---
    repo_resource_records = []
    if len(req.repo_resources) > MAX_REPO_RESOURCES:
        raise InvalidRequestError(
            code="SESSION_REPO_RESOURCE_LIMIT_EXCEEDED",
            message=f"Too many repo resources (max {MAX_REPO_RESOURCES})",
            data={"max": MAX_REPO_RESOURCES, "actual": len(req.repo_resources)},
            user_action="fix_input",
        )
    for rr in req.repo_resources:
        if not rr.url or not rr.url.strip():
            raise InvalidRequestError(
                code="SESSION_REPO_URL_REQUIRED",
                message="repo resource url is required",
                data={"resource_type": "github_repository"},
                user_action="fix_input",
            )
        mount_path = _validate_mount_path(rr.mount_path) if rr.mount_path else ""
        mount_name = rr.mount_name or _slugify_mount_name(rr.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
        repo_resource_records.append((rr, mount_path, mount_name))

    svc = SessionService(db)
    session = await svc.create_session(
        agent_id=agent.id,
        title=req.title,
        metadata=req.metadata,
        vault_ids=req.vault_ids,
        environment_ref=environment_ref,
        agent_version=agent_version,
        agent_snapshot=agent_snapshot,
        project_id=auth_ctx.project_id,
    )

    resources = []
    if resource_dicts:
        resources = await svc.attach_memory_stores(session.id, resource_dicts)

    # --- Attach file resources ---
    if file_resource_records:
        from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile

        for file_id, mount_path in file_resource_records:
            session_file = JoySafeterSessionFile(
                session_id=session.id,
                file_id=file_id,
                mount_path=mount_path,
                access="read_only",
            )
            db.add(session_file)
        await db.commit()

    # --- Attach repo resources (github_repository) ---
    if repo_resource_records:
        from app.joysafeter_api.services import SecretService
        from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo

        repo_secret_svc = SecretService(db)
        for rr, mount_path, mount_name in repo_resource_records:
            # Encrypt the clone token at rest; never store or echo it in plaintext.
            encrypted_token = ""
            if rr.authorization_token:
                encrypted_token = repo_secret_svc.encrypt_data_for_storage({"token": rr.authorization_token})["token"]
            db.add(
                JoySafeterSessionRepo(
                    session_id=session.id,
                    url=rr.url.strip(),
                    branch=rr.branch or "",
                    mount_path=mount_path,
                    mount_name=mount_name,
                    encrypted_token=encrypted_token,
                )
            )
        await db.commit()

    # Provision sandbox at session creation time (per API spec)
    try:
        from app.joysafeter_shared.orchestrator_bridge import get_sandbox_resolver

        resolver = get_sandbox_resolver()
        if resolver:
            env_ref = environment_ref or agent.environment_ref
            agent_env: dict[str, str] = {}
            resolved_image = None
            networking = None
            environment_config = {}
            if env_ref:
                from app.joysafeter_api.services import JoySafeterEnvironmentService as EnvironmentService

                env_svc = EnvironmentService(db)
                environment = await env_svc.get_environment_by_ref(env_ref, project_id=auth_ctx.project_id)
                if environment:
                    resolved_image = getattr(environment, "image_tag", None)
                    config = environment.config or {}
                    environment_config = config if isinstance(config, dict) else {}
                    net_cfg = environment_config.get("networking")
                    if net_cfg and isinstance(net_cfg, dict):
                        networking = _networking_with_agent_mcp_hosts(net_cfg, agent.mcp_configs or [])
            from app.joysafeter_api.services import SecretService

            secret_svc = SecretService(db)
            env_vars = environment_config.get("env_vars")
            if isinstance(env_vars, dict):
                agent_env.update({str(k): str(v) for k, v in env_vars.items()})
            secret_refs = environment_config.get("secret_refs")
            if isinstance(secret_refs, list):
                agent_env = await secret_svc.merge_secret_refs_into_env(
                    agent_env,
                    [str(ref) for ref in secret_refs if ref is not None],
                    project_id=auth_ctx.project_id,
                )
            if getattr(agent, "secret_ref", None):
                agent_env = await secret_svc.merge_secret_refs_into_env(
                    agent_env, [str(agent.secret_ref)], project_id=auth_ctx.project_id, override=True
                )
            agent_env.update({str(k): str(v) for k, v in (agent.env or {}).items()})
            secret_svc.apply_provider_aliases(agent_env)
            resolved = await resolver.resolve(
                session.id,
                agent_env,
                image=resolved_image,
                networking=networking,
                engine_kind=getattr(agent, "engine_kind", None),
            )
            if resolved.get("sandbox_id"):
                await svc.update_session_sandbox(session.id, resolved["sandbox_id"])
    except Exception as exc:
        log_boundary_failure(
            logger,
            boundary="session_api",
            code="SESSION_SANDBOX_PROVISION_FAILED",
            message="Failed to provision sandbox at session creation; sandbox will be lazy-created",
            operation="provision_session_sandbox",
            error=exc,
            data={"session_id": str(session.id), "agent_id": str(agent.id) if agent else None},
        )

    repo_records = await _load_session_repos(db, session.id)
    return _session_to_response(session, agent, resources=resources, repo_resources=repo_records)


@router.get("")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    agent_id: Optional[uuid.UUID] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionResponse]:
    svc = SessionService(db)
    if agent_id:
        agent_svc = AgentService(db)
        agent = await agent_svc.get_agent(agent_id, project_id=auth_ctx.project_id)
        if not agent:
            raise NotFoundError(
                code="SESSION_AGENT_NOT_FOUND",
                message="Agent not found",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )
        sessions, has_more = await svc.list_sessions_by_agent(
            agent_id, limit, after_id, project_id=auth_ctx.project_id, include_archived=include_archived
        )
    else:
        sessions, has_more = await svc.list_sessions(
            limit, after_id, include_archived=include_archived, project_id=auth_ctx.project_id
        )
    agent_ids = {s.agent_id for s in sessions if s.agent_id}
    agents_by_id = {}
    if agent_ids:
        agent_query = select(JoySafeterAgent).where(
            JoySafeterAgent.id.in_(agent_ids),
            JoySafeterAgent.deleted_at.is_(None),
        )
        if auth_ctx.project_id is not None:
            agent_query = agent_query.where(JoySafeterAgent.project_id == auth_ctx.project_id)
        result = await db.execute(agent_query)
        agents_by_id = {agent.id: agent for agent in result.scalars().all()}
    data = [_session_to_response(s, agents_by_id.get(s.agent_id)) for s in sessions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SessionResponse:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    resources = await svc.list_session_memory_stores(session_id)
    repo_records = await _load_session_repos(db, session_id)
    agent = None
    if session.agent_id:
        agent_svc = AgentService(db)
        agent = await agent_svc.get_agent(session.agent_id, project_id=auth_ctx.project_id)
    return _session_to_response(session, agent=agent, resources=resources, repo_resources=repo_records)


@router.delete("/{session_id}", status_code=200)
async def delete_session(
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.status == "running":
        raise ResourceConflictError(
            code="SESSION_ALREADY_RUNNING",
            message="Running session cannot be deleted. Send user.interrupt first.",
            data={"session_id": str(session_id), "session_status": session.status},
            retryable=True,
            user_action="interrupt",
        )
    from app.joysafeter_api.services import JoySafeterTaskService as TaskService

    active_tasks = await TaskService(db).list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)
    if active_tasks:
        raise ResourceConflictError(
            code="SESSION_ACTIVE_TASK",
            message="Session has an active task; stop it before deleting session",
            data={"session_id": str(session_id), "active_task_ids": [str(task.id) for task in active_tasks]},
            retryable=True,
            user_action=("retry" if True else "fix_input"),
        )

    from app.joysafeter_shared.orchestrator_bridge import (
        get_bridge_registry,
        get_envoy_manager,
        get_sandbox_provider,
        get_session_broadcaster,
    )

    broadcaster = get_session_broadcaster()

    # Clean up sandbox container linked to this session
    from app.joysafeter_api.services import SandboxService

    sandbox_svc = SandboxService(db)
    sandbox = await sandbox_svc.find_by_session(session_id)
    if sandbox:
        # Send gRPC Shutdown to runner via bridge (not cancel)
        bridge_registry = get_bridge_registry()
        if bridge_registry:
            bridge = await bridge_registry.get(sandbox.id)
            if bridge:
                from app.joysafeter_shared.orchestrator_bridge.proto import joysafeter_pb2

                shutdown_msg = joysafeter_pb2.OrchestratorMessage(
                    shutdown=joysafeter_pb2.Shutdown(reason="session deleted")
                )
                try:
                    await bridge.write_to_runner(shutdown_msg)
                except Exception as exc:
                    log_boundary_failure(
                        logger,
                        boundary="session_api",
                        code="SESSION_DELETE_GRPC_SHUTDOWN_FAILED",
                        message="Failed to send gRPC Shutdown during session delete",
                        operation="delete_session_shutdown_runner",
                        error=exc,
                        data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    )
            await bridge_registry.remove(sandbox.id)

        # Stop and destroy container
        provider = get_sandbox_provider()
        if provider and sandbox.external_id:
            try:
                await provider.stop(sandbox.external_id)
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="session_api",
                    code="SESSION_DELETE_SANDBOX_STOP_FAILED",
                    message="Failed to stop sandbox before session delete",
                    operation="delete_session_stop_sandbox",
                    error=exc,
                    data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                )
            try:
                await provider.destroy(sandbox.external_id)
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="session_api",
                    code="SESSION_SANDBOX_DESTROY_FAILED",
                    message="Session sandbox destroy failed during delete",
                    operation="delete_session_destroy_sandbox",
                    error=exc,
                    data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                )
                raise ServiceUnavailableError(
                    code="SESSION_SANDBOX_DESTROY_FAILED",
                    message="Session could not be deleted because its sandbox cleanup failed.",
                    data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                ) from None

        # Mark as destroyed in DB
        await sandbox_svc.update_status_cas(sandbox.id, sandbox.status, "destroyed")

        # Envoy teardown
        envoy = get_envoy_manager()
        if envoy:
            try:
                await envoy.remove_sandbox(sandbox.id)
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="session_api",
                    code="SESSION_DELETE_ENVOY_REMOVE_FAILED",
                    message="Failed to remove sandbox from Envoy during session delete",
                    operation="delete_session_remove_envoy",
                    error=exc,
                    data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                )

    # Hard delete the session
    ok = await svc.delete_session(session_id)
    if not ok:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    # Emit session.deleted only after cleanup and durable deletion succeeded.
    if broadcaster:
        await broadcaster.send(
            session_id,
            {
                "type": "session.deleted",
                "session_id": str(session_id),
            },
        )

    # Cleanup broadcaster subscriptions for this session
    if broadcaster:
        # Remove all subscriber queues for this session
        if session_id in broadcaster._channels:
            del broadcaster._channels[session_id]

    session_id_str = f"sess_{session_id}"
    return {"id": session_id_str, "object": "session", "deleted": True}


@router.post("/{session_id}/archive")
async def archive_session(
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    ok = await svc.archive_session(session_id)
    if not ok:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    return {"status": "archived"}


@router.post("/{session_id}/stop")
async def stop_session(
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.archived_at:
        raise ResourceConflictError(
            code="SESSION_ARCHIVED",
            message="Session is archived",
            data={"session_id": str(session_id)},
            retryable=False,
            user_action="fix_input",
        )
    if session.status == "terminated":
        raise ResourceConflictError(
            code="SESSION_TERMINATED",
            message="Session is terminated",
            data={"session_id": str(session_id), "session_status": session.status},
            retryable=False,
            user_action="fix_input",
        )

    from app.joysafeter_api.services import JoySafeterTaskService as TaskService
    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus
    from app.joysafeter_shared.orchestrator_bridge.proto import joysafeter_pb2
    from app.joysafeter_shared.orchestrator_bridge import (
        get_bridge_registry,
        get_redis_coordinator,
        get_session_broadcaster,
    )

    stop_reason = {"type": "cancelled"}
    task_svc = TaskService(db)
    active_tasks = await task_svc.list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)
    cancelled_task_ids: set[uuid.UUID] = set()
    for task in active_tasks:
        try:
            cancelled = await task_svc.update_task_error(
                task.id,
                "Cancelled via session stop",
                JoySafeterTaskStatus.CANCELLED,
            )
            if cancelled:
                cancelled_task_ids.add(task.id)
        except Exception:
            logger.debug("Failed to cancel task %s during session stop", task.id)

    registry = get_bridge_registry()
    locally_cancelled: set[uuid.UUID] = set()
    if registry:
        for task in active_tasks:
            if task.id not in cancelled_task_ids:
                continue
            bridge = registry.get_by_task(task.id)
            if bridge:
                bridge.request_cancel()
                if bridge.runner_stream:
                    try:
                        await bridge.write_to_runner(
                            joysafeter_pb2.OrchestratorMessage(
                                cancel=joysafeter_pb2.CancelTask(reason="Cancelled via session stop")
                            )
                        )
                        locally_cancelled.add(task.id)
                    except Exception as exc:
                        log_boundary_failure(
                            logger,
                            boundary="session_api",
                            code="SESSION_STOP_GRPC_CANCEL_FAILED",
                            message="Failed to send CancelTask during session stop",
                            operation="stop_session_cancel_runner",
                            error=exc,
                            data={"session_id": str(session_id), "task_id": str(task.id)},
                        )

    coordinator = get_redis_coordinator()
    if coordinator:
        for task in active_tasks:
            if task.id not in cancelled_task_ids:
                continue
            if task.id not in locally_cancelled:
                sandbox_id = await coordinator.get_task_sandbox(task.id)
                if sandbox_id:
                    owner = await coordinator.get_sandbox_owner(sandbox_id)
                    if owner:
                        if isinstance(owner, bytes):
                            owner = owner.decode()
                        await coordinator.send_instance_command(
                            owner,
                            {"type": "cancel", "sandbox_id": str(sandbox_id)},
                        )
            await coordinator.publish_event(
                task.id,
                json.dumps(
                    {
                        "type": "complete",
                        "output": "",
                        "error": "Cancelled via session stop",
                        "status": "cancelled",
                    }
                ),
            )

    remaining_active = await task_svc.list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)
    if remaining_active:
        logger.warning(
            "Session stop could not cancel all active tasks for session %s: remaining=%s",
            session_id,
            [str(task.id) for task in remaining_active],
        )
        raise ServiceUnavailableError(
            code="SESSION_STOP_CANCEL_TASKS_FAILED",
            message="Failed to cancel all active tasks",
            data={"session_id": str(session_id), "active_task_ids": [str(task.id) for task in remaining_active]},
            source="runtime",
            retryable=True,
            user_action="retry",
        )

    try:
        await svc.update_session_status(session_id, "idle", stop_reason=stop_reason)
        await svc.send_event(session_id, "session.status_idle", {"stop_reason": stop_reason})
    except Exception:
        logger.debug(
            "Could not transition session %s to idle during stop",
            session_id,
            exc_info=True,
        )
        raise ServiceUnavailableError(
            code="SESSION_STOP_IDLE_SYNC_FAILED",
            message="Failed to mark session idle",
            data={"session_id": str(session_id)},
            source="runtime",
            retryable=True,
            user_action="retry",
        ) from None

    broadcaster = get_session_broadcaster()
    if broadcaster:
        await broadcaster.send(
            session_id,
            {"type": "session.status_idle", "stop_reason": stop_reason},
        )

    return {
        "id": f"sess_{session_id}",
        "status": "idle",
        "cancelled_tasks": len(cancelled_task_ids),
    }


CONTROL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result", "user.interrupt"}
LIVE_INPUT_PREFIX = "__joysafeter_input_v1__:"
COMMAND_ACK_TIMEOUT_SECONDS = 2


def _encode_live_input(event: SingleEventRequest, source_event_id: Optional[str] = None) -> Optional[str]:
    event_type = event.type
    if event_type == "user.tool_confirmation":
        call_id = event.resolved_tool_use_id()
        if not call_id:
            return None
        payload: dict[str, Any] = {
            "type": "tool_confirmation",
            "tool_use_call_id": call_id,
            "approved": event.resolved_approved() or False,
        }
        if event.deny_message:
            payload["deny_message"] = event.deny_message
        return f"{LIVE_INPUT_PREFIX}{json.dumps(payload)}"
    elif event_type == "user.custom_tool_result":
        call_id = event.resolved_tool_use_id()
        if not call_id:
            return None
        payload = {
            "type": "custom_tool_result",
            "tool_use_call_id": call_id,
            "content": event.content or "",
        }
        return f"{LIVE_INPUT_PREFIX}{json.dumps(payload)}"
    elif event_type == "user.interrupt":
        payload = {"type": "interrupt"}
        if source_event_id:
            payload["source_event_id"] = source_event_id
        return f"{LIVE_INPUT_PREFIX}{json.dumps(payload)}"
    return None


async def _relay_control_via_redis(
    event: SingleEventRequest,
    *,
    session,
    event_id: str,
) -> bool:
    """Relay a control event (tool_confirmation / custom_tool_result / interrupt) to
    the sandbox owner instance via Redis pub/sub.

    Used when the in-process Python bridge isn't available (e.g. the active
    orchestrator is the Rust binary, or the bridge runs in another worker).
    The Rust orchestrator's command_listener subscribes to
    ``joysafeter:cmd:{instance_id}`` and dispatches ``input`` commands to its
    local bridge → SendInput gRPC → runner stdin → claude control_response.

    Returns True only after the owning command listener acknowledges that it
    delivered the input to the local bridge. This still does not guarantee the
    runner completed the user-visible action; that arrives later as events.
    """
    if not getattr(session, "last_sandbox_id", None):
        return False

    # In the API process the orchestrator's RedisCoordinator may not be
    # initialized (it lives in the orchestrator process). Use the shared
    # RedisClient directly — we only need GET + PUBLISH, both stateless.
    try:
        from app.joysafeter_shared.cache.redis import RedisClient
    except Exception:
        return False
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return False

    sandbox_id = str(session.last_sandbox_id)
    try:
        owner = await redis_client.get(f"joysafeter:sandbox_owner:{sandbox_id}")
    except Exception:
        return False
    if not owner:
        return False
    if isinstance(owner, bytes):
        owner = owner.decode()

    live_input = _encode_live_input(event, source_event_id=event_id)
    if not live_input:
        return False

    command_id = uuid.uuid4().hex
    ack_key = f"joysafeter:cmd_ack:{command_id}"
    channel = f"joysafeter:cmd:{owner}"
    command = {
        "type": "input",
        "sandbox_id": sandbox_id,
        "content": live_input,
        "command_id": command_id,
        "ack_key": ack_key,
    }
    try:
        delivered = await _publish_command_and_wait_for_ack(
            redis_client,
            channel,
            command,
            command_id=command_id,
            ack_key=ack_key,
        )
    except Exception as exc:
        logger.debug(
            "Redis relay command failed for %s on session %s",
            event.type,
            getattr(session, "id", "?"),
            extra={
                "error": async_boundary_error_payload(
                    code="SESSION_REDIS_INPUT_RELAY_FAILED",
                    message="Redis input relay command failed",
                    boundary="session_api",
                    operation="relay_input_command",
                    data={
                        "session_id": str(getattr(session, "id", "?")),
                        "sandbox_id": sandbox_id,
                        "event_type": event.type,
                        "command_id": command_id,
                        "channel": channel,
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False
    return delivered


async def _relay_cancel_via_redis(session, *, reason: str) -> bool:
    """Send a `cancel` command for this session's active sandbox via Redis.

    Used by user.interrupt to force the task to terminate after the LLM has
    been aborted (claude's stdio `interrupt` only aborts the current turn but
    leaves the claude CLI waiting for the next user message — the task never
    completes). Pairing interrupt with cancel ensures the task transitions
    to a terminal status so the session can be sent a fresh user.message.
    """
    if not getattr(session, "last_sandbox_id", None):
        return False
    try:
        from app.joysafeter_shared.cache.redis import RedisClient
    except Exception:
        return False
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return False
    sandbox_id = str(session.last_sandbox_id)
    try:
        owner = await redis_client.get(f"joysafeter:sandbox_owner:{sandbox_id}")
    except Exception:
        return False
    if not owner:
        return False
    if isinstance(owner, bytes):
        owner = owner.decode()
    command_id = uuid.uuid4().hex
    ack_key = f"joysafeter:cmd_ack:{command_id}"
    command = {
        "type": "cancel",
        "sandbox_id": sandbox_id,
        "reason": reason,
        "command_id": command_id,
        "ack_key": ack_key,
    }
    try:
        delivered = await _publish_command_and_wait_for_ack(
            redis_client,
            f"joysafeter:cmd:{owner}",
            command,
            command_id=command_id,
            ack_key=ack_key,
        )
    except Exception as exc:
        logger.debug(
            "Redis relay cancel command failed for session %s",
            getattr(session, "id", "?"),
            extra={
                "error": async_boundary_error_payload(
                    code="SESSION_REDIS_CANCEL_RELAY_FAILED",
                    message="Redis cancel relay command failed",
                    boundary="session_api",
                    operation="relay_cancel_command",
                    data={
                        "session_id": str(getattr(session, "id", "?")),
                        "sandbox_id": sandbox_id,
                        "command_id": command_id,
                        "channel": f"joysafeter:cmd:{owner}",
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False
    return delivered


async def _publish_command_and_wait_for_ack(
    redis_client,
    channel: str,
    command: dict[str, Any],
    *,
    command_id: str,
    ack_key: str,
) -> bool:
    receivers = await redis_client.publish(channel, json.dumps(command))
    if receivers is None or int(receivers) == 0:
        return False

    try:
        ack = await redis_client.blpop(ack_key, timeout=COMMAND_ACK_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.debug(
            "Redis command ACK wait failed for %s",
            command_id,
            extra={
                "error": async_boundary_error_payload(
                    code="SESSION_REDIS_COMMAND_ACK_WAIT_FAILED",
                    message="Redis command ACK wait failed",
                    boundary="session_api",
                    operation="wait_command_ack",
                    data={"command_id": command_id, "ack_key": ack_key, "channel": channel},
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False
    if not ack:
        logger.debug("Redis command ACK timed out for %s", command_id)
        return False

    _key, raw_payload = ack
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode()
    try:
        payload = json.loads(raw_payload)
    except Exception:
        logger.debug("Redis command ACK payload is invalid for %s: %r", command_id, raw_payload)
        return False
    if str(payload.get("command_id") or "") != command_id:
        logger.debug("Redis command ACK command_id mismatch for %s: %s", command_id, payload)
        return False
    return bool(payload.get("ok"))


def _build_resume_prompt(event: SingleEventRequest, event_id: str) -> Optional[str]:
    event_type = event.type
    if event_type == "user.custom_tool_result":
        content = event.content or ""
        return f"Tool result received for tool call event {event_id}:\n{content}\nContinue the task using this tool result."
    elif event_type == "user.tool_confirmation":
        if event.resolved_approved():
            return f"User approved tool call event {event_id}. Continue execution."
        else:
            reason = event.deny_message or "No reason given"
            return f"User denied tool call event {event_id}. Reason: {reason} Do not run that tool; choose an alternative path."
    elif event_type == "user.interrupt":
        return "User requested interruption. Stop the current operation."
    elif event_type == "user.message":
        c = event.content
        if isinstance(c, list):
            return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        return c
    return None


def _validate_message_content(content: Any) -> str:
    """Validate user.message content.

    Accepts either a plain string or a list of ``{type: "text", text: "..."}``
    content blocks (matching the Rust joysafeter spec).  Returns the concatenated
    text for task creation.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                raise RequestValidationAppError(
                    code="SESSION_CONTENT_BLOCK_INVALID",
                    message="Each content block must be an object with {type, text}",
                    data={"field": "content", "index": index},
                    user_action="fix_input",
                )
            if block.get("type") != "text" or not isinstance(block.get("text"), str):
                raise RequestValidationAppError(
                    code="SESSION_CONTENT_BLOCK_INVALID",
                    message="Content blocks must have type 'text' and a string 'text' field",
                    data={
                        "field": "content",
                        "index": index,
                        "block_type": str(block.get("type")) if block.get("type") is not None else None,
                    },
                    user_action="fix_input",
                )
            parts.append(block["text"])
        if not parts:
            raise RequestValidationAppError(
                code="SESSION_CONTENT_EMPTY",
                message="Content blocks array must not be empty",
                data={"field": "content"},
                user_action="fix_input",
            )
        return "\n".join(parts)
    raise RequestValidationAppError(
        code="SESSION_CONTENT_INVALID",
        message="content must be a string or array of content blocks",
        data={"field": "content", "content_type": type(content).__name__},
        user_action="fix_input",
    )


async def _find_idempotent_user_message_event(
    db: AsyncSession,
    session_id: uuid.UUID,
    idempotency_key: str,
):
    from app.joysafeter_domain.models.joysafeter_session import JoySafeterSessionEvent

    result = await db.execute(
        select(JoySafeterSessionEvent)
        .where(
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "user.message",
            text("payload->>'_idempotency_key' = :idempotency_key"),
        )
        .params(idempotency_key=idempotency_key)
        .order_by(JoySafeterSessionEvent.seq.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _session_event_response(event) -> SessionEventResponse:
    return SessionEventResponse(
        id=event.id,
        event_type=event.event_type,
        payload=event.payload,
        seq=event.seq,
        processed_at=event.processed_at,
        created_at=event.created_at,
    )


async def _idempotent_user_message_replay_response(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    idempotency_key: str,
    project_id: Optional[str],
    expected_prompt: Optional[str] = None,
) -> SessionEventResponse | None:
    from app.joysafeter_api.services import JoySafeterTaskService as TaskService

    existing_task = await TaskService(db).get_by_idempotency_key(
        idempotency_key,
        project_id=project_id,
    )
    if existing_task is not None:
        if existing_task.chat_session_id != session_id:
            raise ResourceConflictError(
                code="SESSION_IDEMPOTENCY_KEY_MISMATCH",
                message="Idempotency-Key was already used for a different session",
                data={
                    "session_id": str(session_id),
                    "task_id": str(existing_task.id),
                    "conflict_field": "chat_session_id",
                    "requested_value": str(session_id),
                    "existing_value": str(existing_task.chat_session_id),
                },
                user_action="fix_input",
            )
        if expected_prompt is not None and existing_task.prompt != expected_prompt:
            raise ResourceConflictError(
                code="SESSION_IDEMPOTENCY_KEY_MISMATCH",
                message="Idempotency-Key was already used for a different message",
                data={
                    "session_id": str(session_id),
                    "task_id": str(existing_task.id),
                    "conflict_field": "message",
                    "requested_value": str(expected_prompt),
                    "existing_value": str(existing_task.prompt),
                },
                user_action="fix_input",
            )
        if existing_task.status == "failed" and "Failed to enqueue task" in (existing_task.error or ""):
            raise ServiceUnavailableError(
                code="TASK_ENQUEUE_FAILED",
                message="Failed to enqueue task",
                data={"session_id": str(session_id), "task_id": str(existing_task.id)},
                source="runtime",
                retryable=True,
                user_action="retry",
            )

    existing_event = await _find_idempotent_user_message_event(db, session_id, idempotency_key)
    if existing_event is not None and existing_task is not None:
        return _session_event_response(existing_event)
    return None


async def _push_task_to_global_queue(task_id: uuid.UUID) -> None:
    from app.joysafeter_api.services import enqueue_joysafeter_task

    await enqueue_joysafeter_task(task_id)


async def _create_and_enqueue_resume_task(
    *,
    session_id: uuid.UUID,
    agent_id: uuid.UUID,
    project_id: Optional[str],
    prompt: str,
    failure_context: str,
) -> uuid.UUID:
    from app.joysafeter_api.services import JoySafeterTaskService as TaskService
    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus
    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as task_db:
        task_svc = TaskService(task_db)
        task = await task_svc.create_task(
            agent_id=agent_id,
            prompt=prompt,
            chat_session_id=session_id,
            project_id=project_id,
        )

    try:
        await _push_task_to_global_queue(task.id)
    except Exception as exc:
        async with AsyncSessionLocal() as task_db:
            await TaskService(task_db).update_task_error(
                task.id,
                f"Failed to enqueue fallback task for {failure_context}: {exc}",
                JoySafeterTaskStatus.FAILED,
            )
        raise
    return task.id


async def _mark_session_running_for_active_task(
    *,
    svc: SessionService,
    session_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    project_id: Optional[str] = None,
    broadcaster=None,
) -> bool:
    if task_id is None:
        from app.joysafeter_api.services import JoySafeterTaskService as TaskService

        active_tasks = await TaskService(svc.db).list_active_tasks_by_session(session_id, project_id=project_id)
        if len(active_tasks) != 1:
            return False
        task_id = active_tasks[0].id

    running_accepted = await svc.update_session_status_for_task_event(session_id, "running", task_id)
    if not running_accepted:
        return False

    running_event = await svc.send_event(session_id, "session.status_running", {"task_id": str(task_id)})
    if broadcaster:
        running_broadcast = {
            "id": f"evt_{running_event.id}",
            "type": running_event.event_type,
            "seq": running_event.seq,
        }
        if isinstance(running_event.payload, dict):
            running_broadcast.update(running_event.payload)
        await broadcaster.send(session_id, running_broadcast)
    return True


async def _replay_pending_control_inputs(
    session_id: uuid.UUID,
    bridge,
    svc: SessionService,
) -> None:
    """Replay any unprocessed control events for the session via the bridge.

    This mirrors the Rust JoySafeter runner's ``replay_pending_control_inputs`` which
    re-sends control events that arrived while the bridge was unavailable.
    """
    try:
        unprocessed = await svc.list_unprocessed_events(
            session_id,
            list(CONTROL_EVENT_TYPES),
        )
        for evt in unprocessed:
            single = SingleEventRequest(
                type=evt.event_type,
                content=evt.payload.get("content"),
                tool_use_id=evt.payload.get("call_id") or evt.payload.get("tool_use_id"),
                approved=evt.payload.get("approved"),
                deny_message=evt.payload.get("deny_message"),
                payload=evt.payload,
            )
            raw_id = single.resolved_tool_use_id()
            resolved_event = single
            if raw_id and raw_id in bridge.pending_control_request_ids:
                actual_call_id = bridge.pending_control_request_ids.pop(raw_id)
                resolved_event = single.model_copy(update={"tool_use_id": actual_call_id})
            live_input = _encode_live_input(resolved_event, source_event_id=str(evt.id))
            if live_input:
                try:
                    await bridge.send_control_input(live_input)
                    await svc.mark_event_processed(evt.id)
                except Exception:
                    logger.debug(
                        "Failed to replay control event %s for session %s",
                        evt.id,
                        session_id,
                    )
    except Exception:
        logger.debug("Error replaying pending controls for session %s", session_id, exc_info=True)


@router.post("/{session_id}/events", status_code=201)
async def send_event(
    req: SendEventRequest,
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        idempotency_key = None
    else:
        idempotency_key = idempotency_key.strip()

    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    # --- gate: reject events on archived / terminated / rescheduling sessions ---
    if session.archived_at:
        raise ResourceConflictError(
            code="SESSION_ARCHIVED",
            message="Session is archived",
            data={"session_id": str(session_id)},
        )
    if session.status == "terminated":
        raise ResourceConflictError(
            code="SESSION_TERMINATED",
            message="Session is terminated",
            data={"session_id": str(session_id), "session_status": session.status},
        )
    if session.status == "rescheduling":
        raise ResourceConflictError(
            code="SESSION_RESCHEDULING",
            message="Session is rescheduling, try again later",
            data={"session_id": str(session_id), "session_status": session.status},
            retryable=True,
            user_action="retry",
        )

    single_events = req.to_single_events()
    if not single_events:
        raise InvalidRequestError(
            code="SESSION_EVENTS_EMPTY", message="No events provided", data={"field": "events"}, user_action="fix_input"
        )

    from app.joysafeter_shared.orchestrator_bridge import get_bridge_registry, get_session_broadcaster

    broadcaster = get_session_broadcaster()
    bridge_registry = get_bridge_registry()

    results: list[SessionEventResponse] = []
    for single in single_events:
        # --- user.message: reject if session is already running (409) ---
        if single.type == "user.message":
            # Validate content before idempotent replay so a reused key cannot
            # silently map different message text to the original task/event.
            raw_content = single.content
            if raw_content is None:
                raw_content = single.payload.get("content")
            if raw_content is None:
                raise RequestValidationAppError(
                    code="SESSION_USER_MESSAGE_CONTENT_REQUIRED",
                    message="user.message requires content",
                    data={"field": "content", "event_type": single.type},
                    user_action="fix_input",
                )
            message_text = _validate_message_content(raw_content)

            if idempotency_key:
                replay = await _idempotent_user_message_replay_response(
                    db,
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                    project_id=auth_ctx.project_id,
                    expected_prompt=message_text,
                )
                if replay is not None:
                    results.append(replay)
                    continue

            if session.status == "running":
                raise ResourceConflictError(
                    code="SESSION_ALREADY_RUNNING",
                    message="Session is already running; wait for completion before sending a new message",
                    data={"session_id": str(session_id), "session_status": session.status},
                    retryable=True,
                    user_action="retry",
                )
            from app.joysafeter_api.services import JoySafeterTaskService as TaskService

            active_tasks = await TaskService(db).list_active_tasks_by_session(
                session_id,
                project_id=auth_ctx.project_id,
            )
            if active_tasks:
                raise ResourceConflictError(
                    code="SESSION_ACTIVE_TASK",
                    message="Session has an active task; wait for completion before sending a new message",
                    data={
                        "session_id": str(session_id),
                        "active_task_ids": [str(task.id) for task in active_tasks],
                    },
                    retryable=True,
                    user_action="retry",
                )

        # Build payload for persistence
        payload = dict(single.payload)
        if single.content and "content" not in payload:
            payload["content"] = single.content
        if single.resolved_tool_use_id() and "call_id" not in payload:
            payload["call_id"] = single.resolved_tool_use_id()
        if single.deny_message and "deny_message" not in payload:
            payload["deny_message"] = single.deny_message
        if single.resolved_approved() is not None and "approved" not in payload:
            payload["approved"] = single.resolved_approved()
        if single.type == "user.message" and idempotency_key:
            payload["_idempotency_key"] = idempotency_key

        try:
            event = await svc.send_event(session_id, single.type, payload)
        except IntegrityError:
            if single.type != "user.message" or not idempotency_key:
                raise
            try:
                await db.rollback()
            except Exception:
                logger.debug("Failed to rollback after idempotent user.message collision", exc_info=True)
            for _attempt in range(10):
                replay = await _idempotent_user_message_replay_response(
                    db,
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                    project_id=auth_ctx.project_id,
                    expected_prompt=message_text,
                )
                if replay is not None:
                    results.append(replay)
                    break
                await asyncio.sleep(0.05)
            else:
                raise ResourceConflictError(
                    code="IDEMPOTENCY_KEY_IN_PROGRESS",
                    message="Idempotency-Key is already in progress",
                    data={"session_id": str(session_id)},
                    retryable=True,
                    user_action="retry",
                )
            continue

        event_response = _session_event_response(event)

        if broadcaster:
            broadcast_data = {
                "id": f"evt_{event.id}",
                "type": event.event_type,
                "seq": event.seq,
            }
            if isinstance(event.payload, dict):
                broadcast_data.update(event.payload)
            await broadcaster.send(session_id, broadcast_data)

        # ----------------------------------------------------------------
        # Dispatch by event type
        # ----------------------------------------------------------------
        if single.type == "user.message":
            # Create task, mark session running, push to scheduler
            task = None
            try:
                from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                from app.joysafeter_shared.database import AsyncSessionLocal

                async with AsyncSessionLocal() as task_db:
                    task_svc = TaskService(task_db)
                    task = await task_svc.create_task(
                        agent_id=session.agent_id,
                        prompt=message_text,
                        chat_session_id=session_id,
                        project_id=auth_ctx.project_id,
                        idempotency_key=idempotency_key,
                    )
                # Transition session to running before writing the event anchor.
                # If a concurrent active task already owns the session context,
                # do not leave a misleading session.status_running event behind.
                running_accepted = await svc.update_session_status_for_task_event(session_id, "running", task.id)
                if not running_accepted:
                    raise RuntimeError("Session already has another active task")

                running_event = await svc.send_event(
                    session_id,
                    "session.status_running",
                    {"task_id": str(task.id)},
                )
                if broadcaster:
                    running_broadcast = {
                        "id": f"evt_{running_event.id}",
                        "type": running_event.event_type,
                        "seq": running_event.seq,
                    }
                    if isinstance(running_event.payload, dict):
                        running_broadcast.update(running_event.payload)
                    await broadcaster.send(session_id, running_broadcast)
                # Push task to runner queue. In split-service mode the API
                # process does not own an in-memory scheduler, so publish
                # directly to the Redis-backed global queue.
                await _push_task_to_global_queue(task.id)
            except AppError:
                raise
            except Exception as exc:
                log_boundary_failure(
                    logger,
                    boundary="session_api",
                    code="SESSION_USER_MESSAGE_DISPATCH_FAILED",
                    message="Failed to dispatch user.message for session",
                    operation="dispatch_user_message",
                    error=exc,
                    data={"session_id": str(session_id), "task_id": str(task.id) if task is not None else ""},
                )
                try:
                    if db.in_transaction():
                        await db.rollback()
                except Exception:
                    logger.debug("Failed to rollback session DB after dispatch failure", exc_info=True)

                from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus

                if task is not None:
                    try:
                        from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                        from app.joysafeter_shared.database import AsyncSessionLocal

                        async with AsyncSessionLocal() as task_db:
                            await TaskService(task_db).update_task_error(
                                task.id,
                                f"Failed to enqueue task: {exc}",
                                JoySafeterTaskStatus.FAILED,
                            )
                    except Exception as mark_exc:
                        log_boundary_failure(
                            logger,
                            boundary="session_api",
                            code="SESSION_UNQUEUED_TASK_MARK_FAILED",
                            message="Failed to mark unqueued task as failed",
                            operation="mark_unqueued_task_failed",
                            error=mark_exc,
                            data={
                                "session_id": str(session_id),
                                "task_id": str(getattr(task, "id", "")),
                            },
                        )

                stop_reason = _session_task_enqueue_failed_stop_reason(
                    session_id=session_id,
                    task_id=task.id if task is not None else None,
                )
                idle_accepted = False
                try:
                    if task is not None:
                        idle_accepted = await svc.update_session_status_for_task_event(
                            session_id,
                            "idle",
                            task.id,
                            stop_reason=stop_reason,
                        )
                    else:
                        idle_accepted = await svc.update_session_status(session_id, "idle", stop_reason=stop_reason)
                except Exception:
                    logger.debug(
                        "Could not compensate session %s to idle after dispatch failure",
                        session_id,
                        exc_info=True,
                    )

                try:
                    if idle_accepted:
                        idle_event = await svc.send_event(
                            session_id,
                            "session.status_idle",
                            {
                                **({"task_id": str(task.id)} if task is not None else {}),
                                "stop_reason": stop_reason,
                            },
                        )
                        if broadcaster:
                            idle_broadcast = {
                                "id": f"evt_{idle_event.id}",
                                "type": idle_event.event_type,
                                "seq": idle_event.seq,
                            }
                            if isinstance(idle_event.payload, dict):
                                idle_broadcast.update(idle_event.payload)
                            await broadcaster.send(session_id, idle_broadcast)
                except Exception:
                    logger.debug(
                        "Failed to emit idle compensation event for session %s",
                        session_id,
                        exc_info=True,
                    )

                raise ServiceUnavailableError(
                    code="TASK_ENQUEUE_FAILED",
                    message="Failed to enqueue task",
                    data={"session_id": str(session_id), "task_id": str(task.id if task is not None else None)},
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                ) from exc

        elif single.type == "user.custom_tool_result":
            injected = False
            if bridge_registry and session.last_sandbox_id:
                bridge = await bridge_registry.get(session.last_sandbox_id)
                if bridge:
                    resolved_event = single
                    raw_id = single.resolved_tool_use_id()
                    if raw_id and raw_id in bridge.pending_control_request_ids:
                        actual_call_id = bridge.pending_control_request_ids.pop(raw_id)
                        resolved_event = single.model_copy(update={"tool_use_id": actual_call_id})
                    live_input = _encode_live_input(resolved_event, source_event_id=str(event.id))
                    if live_input:
                        try:
                            await bridge.send_control_input(live_input)
                            injected = True
                            bridge._requires_action_pending = False
                            await svc.mark_event_processed(event.id)
                            await _mark_session_running_for_active_task(
                                svc=svc,
                                session_id=session_id,
                                task_id=bridge.current_task_id,
                                project_id=auth_ctx.project_id,
                                broadcaster=broadcaster,
                            )
                        except Exception:
                            logger.debug(
                                "Bridge injection failed for custom_tool_result, falling back to task",
                            )
            # Cross-process relay: route via Redis to the sandbox owner instance.
            if not injected and await _relay_control_via_redis(single, session=session, event_id=str(event.id)):
                injected = True
                await svc.mark_event_processed(event.id)
                await _mark_session_running_for_active_task(
                    svc=svc,
                    session_id=session_id,
                    project_id=auth_ctx.project_id,
                    broadcaster=broadcaster,
                )
            # Fallback: create a retry task when bridge injection was not possible
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            prompt=resume_prompt,
                            failure_context="custom_tool_result",
                        )
                    except Exception as exc:
                        logger.debug(
                            "Failed to create fallback task for custom_tool_result on session %s",
                            session_id,
                            exc_info=True,
                        )
                        raise ServiceUnavailableError(
                            code="SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED",
                            message="Failed to deliver custom tool result",
                            data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                            source="runtime",
                            retryable=True,
                            user_action="retry",
                        ) from exc
                else:
                    raise ServiceUnavailableError(
                        code="SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED",
                        message="Failed to deliver custom tool result",
                        data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                        source="runtime",
                        retryable=True,
                        user_action="retry",
                    )

        elif single.type == "user.tool_confirmation":
            injected = False
            if bridge_registry and session.last_sandbox_id:
                bridge = await bridge_registry.get(session.last_sandbox_id)
                if bridge:
                    resolved_event = single
                    raw_id = single.resolved_tool_use_id()
                    if raw_id and raw_id in bridge.pending_control_request_ids:
                        actual_call_id = bridge.pending_control_request_ids.pop(raw_id)
                        resolved_event = single.model_copy(update={"tool_use_id": actual_call_id})
                    live_input = _encode_live_input(resolved_event, source_event_id=str(event.id))
                    if live_input:
                        try:
                            await bridge.send_control_input(live_input)
                            injected = True
                            bridge._requires_action_pending = False
                            await svc.mark_event_processed(event.id)
                            await _mark_session_running_for_active_task(
                                svc=svc,
                                session_id=session_id,
                                task_id=bridge.current_task_id,
                                project_id=auth_ctx.project_id,
                                broadcaster=broadcaster,
                            )
                        except Exception:
                            logger.debug(
                                "Bridge injection failed for tool_confirmation on session %s",
                                session_id,
                            )
            # Cross-process relay: route via Redis to the sandbox owner instance
            # (Rust orchestrator or another API worker) when no local bridge.
            if not injected and await _relay_control_via_redis(single, session=session, event_id=str(event.id)):
                injected = True
                await svc.mark_event_processed(event.id)
                await _mark_session_running_for_active_task(
                    svc=svc,
                    session_id=session_id,
                    project_id=auth_ctx.project_id,
                    broadcaster=broadcaster,
                )
            # Fallback: create a retry task
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            prompt=resume_prompt,
                            failure_context="tool_confirmation",
                        )
                    except Exception as exc:
                        logger.debug(
                            "Failed to create fallback task for tool_confirmation on session %s",
                            session_id,
                            exc_info=True,
                        )
                        raise ServiceUnavailableError(
                            code="SESSION_TOOL_CONFIRMATION_DELIVERY_FAILED",
                            message="Failed to deliver tool confirmation",
                            data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                            source="runtime",
                            retryable=True,
                            user_action="retry",
                        ) from exc
                else:
                    raise ServiceUnavailableError(
                        code="SESSION_TOOL_CONFIRMATION_DELIVERY_FAILED",
                        message="Failed to deliver tool confirmation",
                        data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                        source="runtime",
                        retryable=True,
                        user_action="retry",
                    )

        elif single.type == "user.interrupt":
            # Encode interrupt as a live-input with source_event_id
            injected = False
            cancel_requested = False
            if bridge_registry and session.last_sandbox_id:
                bridge = await bridge_registry.get(session.last_sandbox_id)
                if bridge:
                    bridge.request_cancel()
                    cancel_requested = True
                    live_input = _encode_live_input(single, source_event_id=str(event.id))
                    if live_input:
                        try:
                            await bridge.send_control_input(live_input)
                            injected = True
                            await svc.mark_event_processed(event.id)
                        except Exception:
                            logger.debug(
                                "Bridge injection failed for interrupt on session %s",
                                session_id,
                            )
            # Cross-process relay: route via Redis to the sandbox owner instance.
            if not injected and await _relay_control_via_redis(single, session=session, event_id=str(event.id)):
                injected = True
                await svc.mark_event_processed(event.id)
            # interrupt 单独 abort 当前 LLM turn,但 claude headless 不会因此
            # emit `result` 让 task 结束(它认为后面会有新的 user.message)。
            # 为了产品语义"中断 = task 终结,session 可续聊",额外发一次 cancel
            # 强制结束 task;下一条 user.message 会重新起 claude 进程。
            if not cancel_requested and await _relay_cancel_via_redis(session, reason="user requested interrupt"):
                cancel_requested = True
            if session.status == "running" and not cancel_requested:
                raise ServiceUnavailableError(
                    code="SESSION_INTERRUPT_DELIVERY_FAILED",
                    message="Failed to deliver interrupt",
                    data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )
            # Fallback: create a retry task when bridge injection was not possible
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            prompt=resume_prompt,
                            failure_context="interrupt",
                        )
                    except Exception as exc:
                        logger.debug(
                            "Failed to create fallback task for interrupt on session %s",
                            session_id,
                            exc_info=True,
                        )
                        raise ServiceUnavailableError(
                            code="SESSION_INTERRUPT_DELIVERY_FAILED",
                            message="Failed to deliver interrupt",
                            data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                            source="runtime",
                            retryable=True,
                            user_action="retry",
                        ) from exc
                else:
                    raise ServiceUnavailableError(
                        code="SESSION_INTERRUPT_DELIVERY_FAILED",
                        message="Failed to deliver interrupt",
                        data={"session_id": str(session_id), "event_id": str(event.id), "event_type": single.type},
                        source="runtime",
                        retryable=True,
                        user_action="retry",
                    )

        results.append(event_response)

    # --- After all events: replay pending control inputs for the session ---
    if bridge_registry and session.last_sandbox_id:
        bridge = await bridge_registry.get(session.last_sandbox_id)
        if bridge:
            await _replay_pending_control_inputs(session_id, bridge, svc)

    return {"events": [r.model_dump() for r in results]}


@router.get("/{session_id}/events")
async def list_events(
    session_id: uuid.UUID = Depends(_parse_session_id),
    limit: int = Query(50, ge=1, le=200),
    after_seq: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionEventResponse]:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    events, has_more = await svc.list_events(session_id, limit, after_seq)
    data = [SessionEventResponse.model_validate(e) for e in events]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{session_id}/events/stream")
async def session_event_stream(
    request: Request,
    session_id: uuid.UUID = Depends(_parse_session_id),
    after_seq: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """SSE endpoint for real-time session event streaming."""
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    if session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    from app.joysafeter_shared.orchestrator_bridge import (
        ensure_session_broadcaster,
        get_session_broadcaster,
    )

    broadcaster = get_session_broadcaster()
    if not broadcaster:
        try:
            from app.joysafeter_shared.cache.redis import RedisClient
            from app.joysafeter_shared.config.settings import joysafeter_config

            broadcaster = ensure_session_broadcaster(
                redis_client=RedisClient.get_client(),
                instance_id=f"{joysafeter_config.instance_id}:api:{os.getpid()}",
            )
        except Exception:
            logger.debug("Failed to lazily initialize session broadcaster", exc_info=True)

    async def event_generator():
        last_seq = after_seq or 0

        # First, replay existing events after the cursor
        if after_seq is not None:
            from app.joysafeter_shared.database import AsyncSessionLocal

            async with AsyncSessionLocal() as replay_db:
                replay_svc = SessionService(replay_db)
                events, _ = await replay_svc.list_events(session_id, 1000, after_seq)
                for ev in events:
                    last_seq = max(last_seq, ev.seq)
                    data_dict = {
                        "id": f"evt_{ev.id}",
                        "type": ev.event_type,
                        "seq": ev.seq,
                    }
                    if isinstance(ev.payload, dict):
                        data_dict.update(ev.payload)
                    data_dict["_sse_source"] = "db_replay"
                    data = json.dumps(data_dict)
                    yield f"id: evt_{ev.id}\ndata: {data}\n\n"
                if events:
                    logger.info(
                        "SSE db_replay session=%s count=%s from_seq=%s to_seq=%s",
                        session_id,
                        len(events),
                        after_seq,
                        last_seq,
                    )

        # Subscribe to live events
        if not broadcaster:
            while True:
                if await request.is_disconnected():
                    break
                from app.joysafeter_shared.database import AsyncSessionLocal

                async with AsyncSessionLocal() as poll_db:
                    poll_svc = SessionService(poll_db)
                    events, _ = await poll_svc.list_events(session_id, 1000, last_seq)
                    for ev in events:
                        last_seq = max(last_seq, ev.seq)
                        data_dict = {
                            "id": f"evt_{ev.id}",
                            "type": ev.event_type,
                            "seq": ev.seq,
                        }
                        if isinstance(ev.payload, dict):
                            data_dict.update(ev.payload)
                        data_dict["_sse_source"] = "db_fallback_no_broadcaster"
                        yield f"id: evt_{ev.id}\ndata: {json.dumps(data_dict)}\n\n"
                    if events:
                        logger.warning(
                            "SSE db_fallback_no_broadcaster session=%s count=%s to_seq=%s",
                            session_id,
                            len(events),
                            last_seq,
                        )

                await asyncio.sleep(2)
            return

        q = broadcaster.subscribe(session_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    # P1: broadcaster sends {lagged: True} on queue overflow
                    if event.get("lagged"):
                        yield f"data: {json.dumps({'lagged': True})}\n\n"
                        break  # frontend will reconnect and replay from DB
                    event_seq = event.get("seq")
                    if event_seq is not None:
                        if event_seq <= last_seq:
                            continue
                        last_seq = event_seq
                    event_id = event.get("id") or ""
                    if event_id and not event_id.startswith("evt_"):
                        event_id = f"evt_{event_id}"
                    logger.debug(
                        "SSE live_push session=%s source=%s seq=%s type=%s",
                        session_id,
                        event.get("_sse_source") or "unknown_live",
                        event_seq if event_seq is not None else event.get("_runner_seq"),
                        event.get("type"),
                    )
                    id_line = f"id: {event_id}\n" if event_id else ""
                    yield f"{id_line}data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    from app.joysafeter_shared.database import AsyncSessionLocal

                    async with AsyncSessionLocal() as poll_db:
                        poll_svc = SessionService(poll_db)
                        events, _ = await poll_svc.list_events(session_id, 1000, last_seq)
                        for ev in events:
                            last_seq = max(last_seq, ev.seq)
                            data_dict = {
                                "id": f"evt_{ev.id}",
                                "type": ev.event_type,
                                "seq": ev.seq,
                            }
                            if isinstance(ev.payload, dict):
                                data_dict.update(ev.payload)
                            data_dict["_sse_source"] = "db_fallback_timeout"
                            yield f"id: evt_{ev.id}\ndata: {json.dumps(data_dict)}\n\n"
                        if events:
                            log_boundary_failure(
                                logger,
                                boundary="session_stream",
                                code="SESSION_STREAM_DB_FALLBACK_TIMEOUT",
                                message="SSE DB fallback timeout",
                                operation="stream_session_events_db_fallback",
                                data={"session_id": str(session_id), "count": len(events), "to_seq": last_seq},
                                retryable=True,
                                user_action="retry",
                            )
                    yield ": heartbeat\n\n"
        finally:
            broadcaster.unsubscribe(session_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════════════════════
# Session File Resources
# ══════════════════════════════════════════════════════════════════════

from datetime import datetime  # noqa: E402

from pydantic import BaseModel as PydanticBaseModel  # noqa: E402


class SessionFileResourceResponse(PydanticBaseModel):
    id: str
    type: str = "file"
    file_id: str
    mount_path: str
    access: str
    created_at: datetime


class AddSessionFileRequest(PydanticBaseModel):
    type: str = "file"
    file_id: str
    mount_path: Optional[str] = None


class AddSessionRepoRequest(PydanticBaseModel):
    """Mount a github_repository on an already-running session.

    Mirrors the official ``resources.add`` semantics: the unified endpoint
    accepts either a file or a github_repository, discriminated by ``type``.
    """

    type: str = "github_repository"
    url: str
    branch: Optional[str] = None
    mount_path: Optional[str] = None
    mount_name: Optional[str] = None
    authorization_token: Optional[str] = None


class UpdateRepoResourceRequest(PydanticBaseModel):
    """Rotate the clone credential on a github_repository resource."""

    authorization_token: str


@router.get("/{session_id}/resources")
async def list_session_resources(
    session_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import select as sa_select

    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile

    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    result = await db.execute(sa_select(JoySafeterSessionFile).where(JoySafeterSessionFile.session_id == session_id))
    rows = result.scalars().all()
    data = [
        SessionFileResourceResponse(
            id=f"sesrsc_{r.id}",
            file_id=f"file_{r.file_id}",
            mount_path=r.mount_path,
            access=r.access,
            created_at=r.created_at,
        ).model_dump(mode="json")
        for r in rows
    ]

    # Repo resources — never include the clone token.
    repo_records = await _load_session_repos(db, session_id)
    data.extend(
        SessionRepoResourceResponse(
            id=rr.id,
            url=rr.url,
            branch=rr.branch or "",
            mount_path=rr.mount_path or "",
            mount_name=rr.mount_name or "",
        ).model_dump(mode="json")
        for rr in repo_records
    )
    return {"data": data}


@router.post("/{session_id}/resources", status_code=201)
async def add_session_resource(
    session_id: uuid.UUID,
    req: dict,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
):
    """Add a resource to a running session.

    Discriminated by ``type``:
    - ``file`` (default for back-compat): mounts an uploaded file
    - ``github_repository``: clones a repo on the next task

    Matches the official Managed Agents unified ``resources.add`` endpoint.
    """
    if not isinstance(req, dict):
        raise InvalidRequestError(
            code="SESSION_RESOURCE_BODY_INVALID",
            message="Request body must be an object",
            data={"expected": "object"},
            user_action="fix_input",
        )
    rtype = req.get("type") or "file"

    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    if rtype == "file":
        try:
            file_req = AddSessionFileRequest.model_validate(req)
        except Exception as e:
            raise InvalidRequestError(
                code="SESSION_FILE_RESOURCE_INVALID",
                message="Invalid file resource",
                data={"resource_type": "file"},
                detail=str(e),
                user_action="fix_input",
            ) from e
        return await _add_file_resource(db, session_id, file_req, auth_ctx)

    if rtype == "github_repository":
        try:
            repo_req = AddSessionRepoRequest.model_validate(req)
        except Exception as e:
            raise InvalidRequestError(
                code="SESSION_REPO_RESOURCE_INVALID",
                message="Invalid repo resource",
                data={"resource_type": "github_repository"},
                detail=str(e),
                user_action="fix_input",
            ) from e
        return await _add_repo_resource(db, session_id, repo_req)

    raise InvalidRequestError(
        code="SESSION_RESOURCE_TYPE_UNSUPPORTED",
        message=f"Unsupported resource type: {rtype}",
        data={"resource_type": str(rtype)},
        user_action="fix_input",
    )


async def _add_file_resource(
    db: AsyncSession,
    session_id: uuid.UUID,
    req: AddSessionFileRequest,
    auth_ctx: JoySafeterAuthContext,
) -> SessionFileResourceResponse:
    from app.joysafeter_api.services import FileService
    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from app.joysafeter_shared.storage import get_storage

    file_id_str = req.file_id.removeprefix("file_")
    try:
        fid = uuid.UUID(file_id_str)
    except ValueError:
        raise InvalidRequestError(
            code="SESSION_FILE_ID_INVALID",
            message=f"Invalid file_id: {req.file_id}",
            data={"session_id": str(session_id), "file_id": req.file_id},
            user_action="fix_input",
        )

    file_svc = FileService(get_storage())
    record = await file_svc.get_metadata(db, fid, auth_ctx.project_id)
    if not record:
        raise NotFoundError(
            code="SESSION_FILE_NOT_FOUND",
            message=f"File not found: {req.file_id}",
            data={"session_id": str(session_id), "file_id": req.file_id},
            user_action="refresh",
        )

    mount_path = _validate_mount_path(req.mount_path or f"/workspace/{record.filename}")
    session_file = JoySafeterSessionFile(
        session_id=session_id,
        file_id=record.id,
        mount_path=mount_path,
        access="read_only",
    )
    db.add(session_file)
    await db.commit()
    await db.refresh(session_file)

    return SessionFileResourceResponse(
        id=f"sesrsc_{session_file.id}",
        file_id=f"file_{session_file.file_id}",
        mount_path=session_file.mount_path,
        access=session_file.access,
        created_at=session_file.created_at,
    )


async def _add_repo_resource(
    db: AsyncSession,
    session_id: uuid.UUID,
    req: AddSessionRepoRequest,
) -> SessionRepoResourceResponse:
    from app.joysafeter_api.services import SecretService
    from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo

    if not req.url or not req.url.strip():
        raise InvalidRequestError(
            code="SESSION_REPO_URL_REQUIRED",
            message="Repo url is required",
            data={"session_id": str(session_id), "resource_type": "github_repository"},
            user_action="fix_input",
        )

    # Enforce per-session repo cap (mirrors create flow).
    from app.joysafeter_domain.schemas.joysafeter_session import MAX_REPO_RESOURCES

    existing = await _load_session_repos(db, session_id)
    if len(existing) >= MAX_REPO_RESOURCES:
        raise InvalidRequestError(
            code="SESSION_REPO_RESOURCE_LIMIT_EXCEEDED",
            message=f"Too many repo resources (max {MAX_REPO_RESOURCES})",
            data={"session_id": str(session_id), "max": MAX_REPO_RESOURCES, "actual": len(existing) + 1},
            user_action="fix_input",
        )

    mount_path = _validate_mount_path(req.mount_path) if req.mount_path else ""
    mount_name = req.mount_name or _slugify_mount_name(req.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))

    encrypted_token = ""
    if req.authorization_token:
        secret_svc = SecretService(db)
        encrypted_token = secret_svc.encrypt_data_for_storage({"token": req.authorization_token})["token"]

    repo = JoySafeterSessionRepo(
        session_id=session_id,
        url=req.url.strip(),
        branch=req.branch or "",
        mount_path=mount_path,
        mount_name=mount_name,
        encrypted_token=encrypted_token,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    return SessionRepoResourceResponse(
        id=repo.id,
        url=repo.url,
        branch=repo.branch or "",
        mount_path=repo.mount_path or "",
        mount_name=repo.mount_name or "",
    )


@router.delete("/{session_id}/resources/{resource_id}")
async def delete_session_resource(
    session_id: uuid.UUID,
    resource_id: str,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as sa_select

    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo

    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    rid = resource_id.removeprefix("sesrsc_")
    try:
        rid_uuid = uuid.UUID(rid)
    except ValueError:
        raise InvalidRequestError(
            code="SESSION_RESOURCE_ID_INVALID",
            message="Invalid resource_id",
            data={"session_id": str(session_id), "resource_id": resource_id},
            user_action="fix_input",
        )

    # Resource id space is shared by files and repos — look in both tables.
    result = await db.execute(
        sa_select(JoySafeterSessionFile).where(
            JoySafeterSessionFile.id == rid_uuid,
            JoySafeterSessionFile.session_id == session_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        result = await db.execute(
            sa_select(JoySafeterSessionRepo).where(
                JoySafeterSessionRepo.id == rid_uuid,
                JoySafeterSessionRepo.session_id == session_id,
            )
        )
        row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError(
            code="SESSION_RESOURCE_NOT_FOUND",
            message="Resource not found",
            data={"session_id": str(session_id), "resource_id": resource_id},
            user_action="refresh",
        )

    await db.delete(row)
    await db.commit()
    return {"id": resource_id, "deleted": True}


@router.patch("/{session_id}/resources/{resource_id}")
async def update_repo_resource_token(
    session_id: uuid.UUID,
    resource_id: str,
    req: UpdateRepoResourceRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> SessionRepoResourceResponse:
    """Rotate the clone credential on a github_repository resource.

    The new token is re-encrypted at rest; the response never echoes it.
    """
    from sqlalchemy import select as sa_select

    from app.joysafeter_api.services import SecretService
    from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo

    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    rid = resource_id.removeprefix("sesrsc_")
    try:
        rid_uuid = uuid.UUID(rid)
    except ValueError:
        raise InvalidRequestError(
            code="SESSION_RESOURCE_ID_INVALID",
            message="Invalid resource_id",
            data={"session_id": str(session_id), "resource_id": resource_id},
            user_action="fix_input",
        )

    result = await db.execute(
        sa_select(JoySafeterSessionRepo).where(
            JoySafeterSessionRepo.id == rid_uuid,
            JoySafeterSessionRepo.session_id == session_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError(
            code="SESSION_REPO_RESOURCE_NOT_FOUND",
            message="Repo resource not found",
            data={"session_id": str(session_id), "resource_id": resource_id},
            user_action="refresh",
        )

    secret_svc = SecretService(db)
    row.encrypted_token = (
        secret_svc.encrypt_data_for_storage({"token": req.authorization_token})["token"]
        if req.authorization_token
        else ""
    )
    await db.commit()
    await db.refresh(row)

    return SessionRepoResourceResponse(
        id=row.id,
        url=row.url,
        branch=row.branch or "",
        mount_path=row.mount_path or "",
        mount_name=row.mount_name or "",
    )
