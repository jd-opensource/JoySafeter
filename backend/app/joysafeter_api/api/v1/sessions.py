import asyncio
import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.model_connection_summary import (
    load_model_connection_summaries,
    maybe_credential_id,
    normalize_agent_model,
)
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_domain.credentials.references import snapshot_model_credential_id
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog
from app.joysafeter_domain.models.joysafeter_storage_mount import JoySafeterSessionStorageMount
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_session import (
    MAX_MEMORY_STORE_RESOURCES,
    MAX_STORAGE_MOUNT_RESOURCES,
    CreateSessionRequest,
    SendEventRequest,
    SessionAgent,
    SessionEventResponse,
    SessionFileResourceRequest,
    SessionRepoResourceRequest,
    SessionRepoResourceResponse,
    SessionResourceResponse,
    SessionResponse,
    SessionStorageMountResponse,
    SessionUsage,
    SingleEventRequest,
    UpdateRepoResourceRequest,
)
from app.joysafeter_domain.schemas.joysafeter_credential import ModelCredentialSummary
from app.joysafeter_domain.schemas.joysafeter_skill import SkillUsageResponse as SessionSkillUsageResponse
from app.joysafeter_domain.schemas.joysafeter_task import MAX_PROMPT_CHARS
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService as AgentService
from app.joysafeter_domain.services.joysafeter_session_resource_service import SessionResourceService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_storage_mount_service import StorageMountService
from app.joysafeter_shared.common.app_errors import (
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
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialId,
    EnvironmentId,
    EventId,
    MemoryStoreId,
    SandboxId,
    SessionId,
    SessionResourceId,
    TaskId,
    registered_entity_id_prefix,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-sessions"])


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SANDBOX_FILE_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
_SANDBOX_ARCHIVE_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
_SANDBOX_FILE_MAX_PREVIEW_CHARS = 2 * 1024 * 1024


def _slugify_mount_name(name: str) -> str:
    """Slugify a store name: lowercase, replace non-alphanumeric runs with '-'."""
    return _NON_ALNUM_RE.sub("-", name.lower()).strip("-")


def _canonical_environment_ref(raw: str | None) -> str:
    ref = (raw or "").strip()
    if not ref:
        return ""
    prefix = registered_entity_id_prefix(ref)
    if prefix is not None:
        if prefix != EnvironmentId.prefix:
            raise InvalidRequestError(
                code="ENVIRONMENT_ID_INVALID",
                message="Invalid environment_id",
                data={"environment_id": ref},
                user_action="fix_input",
            )
        try:
            return str(EnvironmentId.from_public(ref))
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(
                code="ENVIRONMENT_ID_INVALID",
                message="Invalid environment_id",
                data={"environment_id": ref},
                user_action="fix_input",
            ) from exc
    try:
        uuid.UUID(ref)
    except ValueError:
        return ref
    raise InvalidRequestError(
        code="ENVIRONMENT_ID_INVALID",
        message="Invalid environment_id",
        data={"environment_id": ref},
        user_action="fix_input",
    )


def _safe_content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii")
    for ch in ('"', "\\", "\r", "\n"):
        ascii_fallback = ascii_fallback.replace(ch, "")
    ascii_fallback = ascii_fallback.strip() or "download"
    utf8_encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_encoded}"


def _validate_sandbox_file_path(path: str | None) -> str:
    value = (path or "/workspace").strip() or "/workspace"
    if len(value) > 4096 or "\x00" in value:
        raise InvalidRequestError(
            code="SANDBOX_FILE_PATH_INVALID",
            message="Invalid sandbox file path",
            data={"path": path or ""},
            user_action="fix_input",
        )
    parts = [part for part in value.split("/") if part]
    if any(part == ".." for part in parts):
        raise InvalidRequestError(
            code="SANDBOX_FILE_PATH_TRAVERSAL",
            message="Sandbox file path cannot contain '..'",
            data={"path": value},
            user_action="fix_input",
        )
    hidden_parts = [part for part in parts if part.startswith(".")]
    if hidden_parts:
        raise InvalidRequestError(
            code="SANDBOX_FILE_PATH_HIDDEN",
            message="Sandbox hidden files are not accessible",
            data={"path": value},
            user_action="fix_input",
        )
    if value.startswith("/") and value != "/workspace" and not value.startswith("/workspace/"):
        raise InvalidRequestError(
            code="SANDBOX_FILE_PATH_OUTSIDE_WORKSPACE",
            message="Sandbox file path must be under /workspace",
            data={"path": value},
            user_action="fix_input",
        )
    return value if value.startswith("/") else f"/workspace/{value}"


def _extract_host(url: str) -> str | None:
    try:
        from urllib.parse import urlparse

        return urlparse(url).hostname
    except Exception:
        return None


def _networking_with_agent_mcp_hosts(networking: dict, mcp_servers: list[dict] | None) -> dict:
    if networking.get("type") != "limited":
        return networking

    allowed = list(networking.get("allowed_hosts", []))
    for mcp in mcp_servers or []:
        if isinstance(mcp, dict) and mcp.get("url"):
            host = _extract_host(str(mcp["url"]))
            if host and host not in allowed:
                allowed.append(host)
    return {**networking, "allowed_hosts": allowed}


async def _load_session_repos(db: AsyncSession, session_id: SessionId, project_id: Optional[str]) -> list:
    """Load a session's repo resources (without decrypting tokens)."""
    return await SessionResourceService(db).list_repo_records(session_id, project_id=project_id)


async def _load_session_storage_mounts(db: AsyncSession, session_id: SessionId, project_id: Optional[str]) -> list:
    query = select(JoySafeterSessionStorageMount).where(
        JoySafeterSessionStorageMount.session_id == session_id,
        JoySafeterSessionStorageMount.detached_at.is_(None),
    )
    if project_id is not None:
        query = query.where(JoySafeterSessionStorageMount.project_id == project_id)
    result = await db.execute(query.order_by(JoySafeterSessionStorageMount.created_at.asc()))
    return list(result.scalars().all())


def _public_session_metadata(metadata) -> dict:
    """Strip internal-only keys before returning session metadata to clients.

    ``agent_identity_context`` is a reserved legacy key. Identity credentials
    are task-scoped and must never be stored in or returned from session metadata.
    """
    if not isinstance(metadata, dict):
        return {}
    return {k: v for k, v in metadata.items() if k != "agent_identity_context"}


def _session_model_credential_id(session, agent=None) -> CredentialId | None:
    if agent is not None and agent.model_credential_id:
        return agent.model_credential_id
    snapshot = session.agent_snapshot or {}
    if not isinstance(snapshot, dict):
        return None
    return maybe_credential_id(snapshot_model_credential_id(snapshot))


def _session_to_response(
    session,
    agent=None,
    resources=None,
    repo_resources=None,
    storage_mounts=None,
    credential_group_ids=None,
    model_connection: ModelCredentialSummary | None = None,
) -> SessionResponse:
    agent_snapshot = session.agent_snapshot or {}
    model_credential_id = _session_model_credential_id(session, agent)
    agent_data = SessionAgent(
        id=session.agent_id,
        version=session.agent_version or 1,
        name=agent.name if agent else agent_snapshot.get("name", ""),
        engine_kind=agent.engine_kind if agent else agent_snapshot.get("engine_kind"),
        description=agent.description if agent else agent_snapshot.get("description"),
        model=normalize_agent_model(agent.model if agent else agent_snapshot.get("model")),
        system=agent.system_prompt if agent else agent_snapshot.get("system"),
        tools=agent.tools if agent else agent_snapshot.get("tools") or [],
        skills=agent.skills if agent else agent_snapshot.get("skills") or [],
        mcp_servers=agent.mcp_servers if agent else agent_snapshot.get("mcp_servers") or [],
        model_credential_id=model_credential_id,
        model_connection=model_connection,
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
    storage_mount_responses = []
    for mount in storage_mounts or []:
        config = mount.config or {}
        storage_mount_responses.append(
            SessionStorageMountResponse(
                id=mount.id,
                name=mount.name,
                volume_ref=str(config.get("volume_ref") or ""),
                volume_id=mount.volume_id,
                sub_path=mount.sub_path or "",
                mount_path=mount.mount_path,
                access=mount.access,
                required=mount.required,
                created_at=mount.created_at,
            )
        )
    return SessionResponse(
        id=session.id,
        agent=agent_data,
        environment_id=session.environment_ref,
        status=session.status,
        stop_reason=session.stop_reason,
        title=session.title,
        metadata=_public_session_metadata(session.metadata_),
        credential_group_ids=credential_group_ids or [],
        resources=resource_responses,
        repo_resources=repo_responses,
        storage_mounts=storage_mount_responses,
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
    if len(req.storage_mounts) > MAX_STORAGE_MOUNT_RESOURCES:
        raise InvalidRequestError(
            code="SESSION_STORAGE_MOUNT_LIMIT_EXCEEDED",
            message=f"Too many storage mounts (max {MAX_STORAGE_MOUNT_RESOURCES})",
            data={"max": MAX_STORAGE_MOUNT_RESOURCES, "actual": len(req.storage_mounts)},
            user_action="fix_input",
        )

    # --- Parse environment_id: validate canonical ID refs, preserve name refs ---
    environment_ref = _canonical_environment_ref(req.environment_id)

    # --- Resolve agent ---
    agent_svc = AgentService(db)
    agent = None
    pinned_version: Optional[int] = None
    if req.agent:
        agent = await agent_svc.get_agent(req.agent.id, project_id=auth_ctx.project_id)
        pinned_version = req.agent.version
    elif req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id, project_id=auth_ctx.project_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name, project_id=auth_ctx.project_id)
    if not agent:
        raise NotFoundError(
            code="SESSION_AGENT_NOT_FOUND",
            message="Agent not found",
            data={
                "agent_id": str(req.agent.id if req.agent else req.agent_id),
                "agent_name": req.agent_name,
            },
            user_action="refresh",
        )
    if agent.archived_at is not None:
        raise ResourceConflictError(
            code="AGENT_ARCHIVED",
            message="Agent is archived and cannot create new sessions.",
            data={"agent_id": str(agent.id)},
            user_action="refresh",
        )

    storage_svc = StorageMountService(db)
    await storage_svc.validate_mount_resources(req.storage_mounts, auth_ctx.project_id)

    # --- Compute mount_name for each resource ---
    from app.joysafeter_domain.services.joysafeter_memory_service import MemoryService

    mem_svc = MemoryService(db)
    resource_dicts = []
    seen_memory_store_ids: set[MemoryStoreId] = set()
    for r in req.resources:
        dump = r.model_dump()
        if r.memory_store_id in seen_memory_store_ids:
            raise ResourceConflictError(
                code="SESSION_MEMORY_STORE_ALREADY_ATTACHED",
                message=f"Memory store is already attached to session: {r.memory_store_id}",
                data={"memory_store_id": str(r.memory_store_id)},
                user_action="fix_input",
            )
        seen_memory_store_ids.add(r.memory_store_id)
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

    # Credential-group binding (existence / project / archived / cross-group url
    # conflict) is validated inside ``SessionService.create_session`` so the check
    # and the association-row write commit together.

    resource_svc = SessionResourceService(db)
    file_resource_records = await resource_svc.prepare_file_resources(
        req.file_resources,
        project_id=auth_ctx.project_id,
    )
    repo_resource_records = await resource_svc.prepare_repo_resources(
        req.repo_resources,
        existing_reserved_mount_paths={resource.mount_path for resource in file_resource_records},
    )

    svc = SessionService(db)
    session = await svc.create_session_from_source(
        CreateCredentialAwareSession(
            project_id=auth_ctx.project_id,
            agent_id=agent.id,
            pinned_agent_version=pinned_version,
            environment_ref=environment_ref or None,
            credential_group_ids=tuple(req.credential_group_ids),
            title=req.title,
            metadata=req.metadata,
            caller="session_api",
            environment_mount_resources=tuple(mount.model_dump() for mount in req.storage_mounts),
        )
    )

    resources = []
    if resource_dicts:
        resources = await svc.attach_memory_stores(session.id, resource_dicts, project_id=auth_ctx.project_id)

    storage_mount_records = []
    if req.storage_mounts:
        authorized = {item["volume_ref"]: item for item in await storage_svc.catalog_for_project(auth_ctx.project_id)}
        for mount in req.storage_mounts:
            volume = await storage_svc.get_volume_by_ref(mount.volume_ref)
            if not volume:
                continue
            record = JoySafeterSessionStorageMount(
                session_id=session.id,
                volume_id=volume.id,
                project_id=auth_ctx.project_id,
                name=mount.name,
                sub_path=mount.sub_path,
                mount_path=mount.mount_path,
                access=mount.access,
                required=mount.required,
                config={"volume_ref": mount.volume_ref, "catalog": authorized.get(mount.volume_ref, {})},
            )
            db.add(record)
            storage_mount_records.append(record)
        await db.flush()
        for record in storage_mount_records:
            await storage_svc.record_audit(
                action="session.mount.attach",
                volume_id=record.volume_id,
                volume_ref=(record.config or {}).get("volume_ref"),
                project_id=auth_ctx.project_id,
                session_id=session.id,
                user_id=auth_ctx.user_id,
                mount_path=record.mount_path,
                sub_path=record.sub_path,
                access=record.access,
                commit=False,
            )
        await db.commit()
        for record in storage_mount_records:
            await db.refresh(record)

    await resource_svc.attach_prepared_resources(
        session.id,
        files=file_resource_records,
        repos=repo_resource_records,
    )

    repo_records = await resource_svc.list_repo_records(session.id, project_id=auth_ctx.project_id)
    storage_mount_records = await _load_session_storage_mounts(db, session.id, auth_ctx.project_id)
    model_connections = await load_model_connection_summaries(
        db,
        [agent.model_credential_id],
        project_id=auth_ctx.project_id,
    )
    return _session_to_response(
        session,
        agent,
        resources=resources,
        repo_resources=repo_records,
        storage_mounts=storage_mount_records,
        credential_group_ids=req.credential_group_ids,
        model_connection=model_connections.get(agent.model_credential_id),
    )


@router.get("")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[SessionId] = Query(None),
    agent_id: Optional[AgentId] = Query(None),
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
    storage_mounts_by_session: dict[SessionId, list[JoySafeterSessionStorageMount]] = {}
    if sessions:
        mount_query = select(JoySafeterSessionStorageMount).where(
            JoySafeterSessionStorageMount.session_id.in_([s.id for s in sessions])
        )
        if auth_ctx.project_id is not None:
            mount_query = mount_query.where(JoySafeterSessionStorageMount.project_id == auth_ctx.project_id)
        mount_result = await db.execute(mount_query)
        for mount in mount_result.scalars().all():
            storage_mounts_by_session.setdefault(mount.session_id, []).append(mount)
    group_ids_by_session = await svc.credential_group_ids_map([s.id for s in sessions])
    model_connections = await load_model_connection_summaries(
        db,
        (_session_model_credential_id(s, agents_by_id.get(s.agent_id)) for s in sessions),
        project_id=auth_ctx.project_id,
    )
    data = [
        _session_to_response(
            s,
            agents_by_id.get(s.agent_id),
            storage_mounts=storage_mounts_by_session.get(s.id, []),
            credential_group_ids=group_ids_by_session.get(s.id, []),
            model_connection=model_connections.get(_session_model_credential_id(s, agents_by_id.get(s.agent_id))),
        )
        for s in sessions
    ]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{session_id}")
async def get_session(
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SessionResponse:
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    resources = await svc.list_session_memory_stores(session_id)
    repo_records = await _load_session_repos(db, session_id, auth_ctx.project_id)
    storage_mount_records = await _load_session_storage_mounts(db, session_id, auth_ctx.project_id)
    agent = None
    if session.agent_id:
        agent_svc = AgentService(db)
        agent = await agent_svc.get_agent(session.agent_id, project_id=auth_ctx.project_id)
    model_connections = await load_model_connection_summaries(
        db,
        [_session_model_credential_id(session, agent)],
        project_id=auth_ctx.project_id,
    )
    model_credential_id = _session_model_credential_id(session, agent)
    return _session_to_response(
        session,
        agent=agent,
        resources=resources,
        repo_resources=repo_records,
        storage_mounts=storage_mount_records,
        credential_group_ids=await svc.get_credential_group_ids(session_id),
        model_connection=model_connections.get(model_credential_id),
    )


@router.get("/{session_id}/skill-usage")
async def list_session_skill_usage(
    session_id: SessionId,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionSkillUsageResponse]:
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )

    stmt = (
        select(JoySafeterSkillUsageLog)
        .where(JoySafeterSkillUsageLog.session_id == session_id)
        .order_by(JoySafeterSkillUsageLog.created_at.desc(), JoySafeterSkillUsageLog.id.desc())
        .limit(limit + 1)
    )
    if auth_ctx.project_id is not None:
        stmt = stmt.where(JoySafeterSkillUsageLog.project_id == auth_ctx.project_id)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    data = [SessionSkillUsageResponse.model_validate(row) for row in rows[:limit]]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.delete("/{session_id}", status_code=200)
async def delete_session(
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
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
    from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService

    active_tasks = await TaskService(db).list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)
    if active_tasks:
        raise ResourceConflictError(
            code="SESSION_ACTIVE_TASK",
            message="Session has an active task; stop it before deleting session",
            data={
                "session_id": str(session_id),
                "active_task_ids": [str(task.id) for task in active_tasks],
            },
            retryable=True,
            user_action=("retry" if True else "fix_input"),
        )

    from app.joysafeter_shared.orchestrator_bridge import get_session_broadcaster

    broadcaster = get_session_broadcaster()

    # Clean up sandbox container linked to this session
    from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService

    sandbox_svc = SandboxService(db)
    sandbox = await sandbox_svc.find_by_session(session_id, project_id=auth_ctx.project_id)
    if sandbox:
        expected_external_id = str(getattr(sandbox, "external_id", "") or "") or None
        if not await _relay_sandbox_destroy_via_redis(
            sandbox,
            session_id=session_id,
            expected_external_id=expected_external_id,
        ):
            raise ServiceUnavailableError(
                code="SESSION_SANDBOX_DESTROY_FAILED",
                message="Session could not be deleted because its sandbox cleanup failed.",
                data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="runtime",
                retryable=True,
                user_action="retry",
            )
        # The Rust owner updates this row before ACK. This CAS is idempotent
        # for unit tests and for API DB sessions that have not observed the
        # Rust-side write yet.
        destroyed = await sandbox_svc.mark_destroyed_after_runtime_ack(
            sandbox.id,
            sandbox.status,
            expected_external_id,
        )
        if not destroyed:
            log_boundary_failure(
                logger,
                boundary="session_api",
                code="SESSION_SANDBOX_DESTROY_FAILED",
                message="Failed to mark sandbox destroyed after runtime ACK",
                operation="delete_session_mark_sandbox_destroyed",
                data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
            )
            raise ServiceUnavailableError(
                code="SESSION_SANDBOX_DESTROY_FAILED",
                message="Session could not be deleted because sandbox state sync failed.",
                data={"session_id": str(session_id), "sandbox_id": str(sandbox.id)},
                source="api",
                retryable=True,
                user_action="retry",
            )

    # Hard delete the session
    ok = await svc.delete_session(session_id, project_id=auth_ctx.project_id)
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

    # Cleanup broadcaster subscriptions for this session. Use remove() so the
    # per-subscriber Redis listener tasks are cancelled; a raw del of _channels
    # drops the queues but leaks their _redis_subscriber tasks + pubsub conns.
    if broadcaster:
        broadcaster.remove(session_id)

    session_id_str = str(session_id)
    return {"id": session_id_str, "object": "session", "deleted": True}


@router.post("/{session_id}/archive")
async def archive_session(
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    ok = await svc.archive_session(session_id, project_id=auth_ctx.project_id)
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
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
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

    from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService
    from app.joysafeter_domain.services.task_cancellation_service import TaskCancellationService
    from app.joysafeter_shared.orchestrator_bridge import get_session_broadcaster

    stop_reason = {"type": "cancelled"}
    task_svc = TaskService(db)
    active_tasks = await task_svc.list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)

    # Cancel each active task through the shared cancellation service. It relays
    # the real cancel to the running sandbox and FAILS CLOSED — raising
    # TASK_CANCEL_REDIS_RELAY_FAILED — when the runtime never confirmed the stop,
    # rather than flipping the DB row and reporting success while the tooling keeps
    # running against a live target. This is the same primitive that
    # POST /tasks/{id}/cancel uses, so the two cancel paths cannot drift; cancel()
    # also transitions the linked session to idle for each cancelled task.
    cancellation = TaskCancellationService(db)
    cancelled_count = 0
    for task in active_tasks:
        try:
            await cancellation.cancel(task, reason="Cancelled via session stop")
            cancelled_count += 1
        except ValueError as exc:
            # The task reached a terminal state between our active-task snapshot
            # and this cancel (it finished on its own, or a prior/retried stop
            # already cancelled it). The state machine raises ValueError for an
            # already-terminal task; stopping a session is idempotent, so that is
            # the desired end state — treat it as already-stopped and let the
            # remaining-active re-check below fail closed if the task is somehow
            # still live. Without this, the ValueError escapes as a 500.
            if not str(exc).startswith("Task already in terminal state: "):
                raise
            logger.debug(
                "Task %s already terminal during session stop; treating as stopped",
                task.id,
                exc_info=True,
            )

    # Defence in depth: cancel() relays before touching the DB and raises on an
    # unconfirmed relay, but re-verify that every task actually reached a terminal
    # state. If a DB transition silently no-op'd, fail closed rather than reporting
    # the session stopped while a task is still active.
    remaining_active = await task_svc.list_active_tasks_by_session(session_id, project_id=auth_ctx.project_id)
    if remaining_active:
        raise ServiceUnavailableError(
            code="SESSION_STOP_CANCEL_TASKS_FAILED",
            message="Failed to cancel all active tasks",
            data={
                "session_id": str(session_id),
                "active_task_ids": [str(task.id) for task in remaining_active],
            },
            source="runtime",
            retryable=True,
            user_action="retry",
        )

    # cancel() idles the session per cancelled task; make sure the session ends up
    # idle even when there were no active tasks, and emit exactly one idle event
    # (skip when a cancel already transitioned it to idle).
    refreshed = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if refreshed is not None and refreshed.status != "idle":
        try:
            idle_updated = await svc.update_session_status(
                session_id,
                "idle",
                stop_reason=stop_reason,
                project_id=auth_ctx.project_id,
                require_no_active_tasks=True,
            )
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

        if not idle_updated:
            remaining_active = await task_svc.list_active_tasks_by_session(
                session_id,
                project_id=auth_ctx.project_id,
            )
            if remaining_active:
                raise ServiceUnavailableError(
                    code="SESSION_STOP_CANCEL_TASKS_FAILED",
                    message="Failed to cancel all active tasks",
                    data={
                        "session_id": str(session_id),
                        "active_task_ids": [str(task.id) for task in remaining_active],
                    },
                    source="runtime",
                    retryable=True,
                    user_action="retry",
                )
            raise ServiceUnavailableError(
                code="SESSION_STOP_IDLE_SYNC_FAILED",
                message="Failed to mark session idle",
                data={"session_id": str(session_id)},
                source="runtime",
                retryable=True,
                user_action="retry",
            )

        try:
            await svc.send_event(session_id, "session.status_idle", {"stop_reason": stop_reason})
        except Exception:
            logger.debug(
                "Could not persist idle event for stopped session %s",
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
        "id": str(session_id),
        "status": "idle",
        "cancelled_tasks": cancelled_count,
    }


CONTROL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result", "user.interrupt"}
CONTROL_TOOL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result"}
LIVE_INPUT_PREFIX = "__joysafeter_input_v1__:"


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


async def _normalize_control_event_for_runtime(
    svc: SessionService,
    session_id: SessionId,
    event: SingleEventRequest,
) -> tuple[SingleEventRequest, Optional[str]]:
    raw_tool_use_id = event.resolved_tool_use_id()
    if event.type not in CONTROL_TOOL_EVENT_TYPES or not raw_tool_use_id:
        return event, None

    call_id = await svc.resolve_control_tool_use_call_id(session_id, raw_tool_use_id)
    if call_id == raw_tool_use_id:
        return event, None

    return (
        event.model_copy(
            update={
                "tool_use_id": call_id,
                "custom_tool_use_id": None,
                "tool_use_event_id": None,
            }
        ),
        raw_tool_use_id,
    )


async def _relay_control_via_redis(
    event: SingleEventRequest,
    *,
    session,
    event_id: EventId,
) -> bool:
    """Relay a control event (tool_confirmation / custom_tool_result / interrupt) to
    the sandbox owner instance via Redis pub/sub.

    Used by the Python API to reach the Rust orchestrator process that owns
    the active sandbox.
    The Rust orchestrator's command_listener subscribes to
    ``joysafeter:cmd:{instance_id}`` and dispatches ``input`` commands to its
    sandbox bridge -> SendInput gRPC -> runner stdin -> claude control_response.

    Returns True only after the owning command listener acknowledges that it
    delivered the input to the sandbox bridge. This still does not guarantee the
    runner completed the user-visible action; that arrives later as events.
    """
    if not getattr(session, "last_sandbox_id", None):
        return False

    live_input = _encode_live_input(event, source_event_id=str(event_id))
    if not live_input:
        return False

    try:
        from app.joysafeter_shared.orchestrator_bridge.runtime_commands import publish_to_sandbox_owner_via_redis

        return await publish_to_sandbox_owner_via_redis(
            session.last_sandbox_id,
            command={"type": "input", "content": live_input},
            require_ack=True,
            boundary="session_api",
            operation="relay_input_command",
            failure_code="SESSION_REDIS_INPUT_RELAY_FAILED",
            failure_message="Redis input relay command failed",
            data={
                "session_id": str(getattr(session, "id", "?")),
                "event_type": event.type,
            },
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
                        "sandbox_id": str(session.last_sandbox_id),
                        "event_type": event.type,
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False


async def _publish_command_and_wait_for_ack(
    redis_client,
    channel: str,
    command: dict[str, Any],
    *,
    command_id: str,
    ack_key: str,
    ack_timeout_seconds: int = 2,
) -> bool:
    from app.joysafeter_shared.orchestrator_bridge.runtime_commands import publish_command_and_wait_for_ack

    return await publish_command_and_wait_for_ack(
        redis_client,
        channel,
        command,
        command_id=command_id,
        ack_key=ack_key,
        ack_timeout_seconds=ack_timeout_seconds,
        boundary="session_api",
        failure_code="SESSION_REDIS_COMMAND_ACK_WAIT_FAILED",
        failure_message="Redis command ACK wait failed",
    )


async def _relay_cancel_via_redis(session, *, reason: str, sandbox_id: SandboxId | None = None) -> bool:
    """Send a `cancel` command for this session's active sandbox via Redis.

    Used by user.interrupt to force the task to terminate after the LLM has
    been aborted (claude's stdio `interrupt` only aborts the current turn but
    leaves the claude CLI waiting for the next user message — the task never
    completes). Pairing interrupt with cancel ensures the task transitions
    to a terminal status so the session can be sent a fresh user.message.
    """
    sandbox_id = sandbox_id or getattr(session, "last_sandbox_id", None)
    if not sandbox_id:
        return False
    try:
        from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_command_via_redis

        return await relay_sandbox_command_via_redis(
            sandbox_id,
            command_type="cancel",
            reason=reason,
            boundary="session_api",
            operation="relay_cancel_command",
            failure_code="SESSION_REDIS_CANCEL_RELAY_FAILED",
            failure_message="Redis cancel relay command failed",
            data={"session_id": str(getattr(session, "id", "?"))},
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
                        "sandbox_id": str(sandbox_id),
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False


async def _relay_sandbox_destroy_via_redis(
    sandbox,
    *,
    session_id: SessionId,
    expected_external_id: str | None = None,
) -> bool:
    from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_destroy_via_redis

    return await relay_sandbox_destroy_via_redis(
        getattr(sandbox, "id"),
        boundary="session_api",
        operation="delete_session_destroy_sandbox",
        failure_code="SESSION_REDIS_DESTROY_RELAY_FAILED",
        failure_message="Redis sandbox destroy relay command failed",
        reason="session deleted",
        external_id=expected_external_id,
        data={"session_id": str(session_id), "sandbox_id": str(getattr(sandbox, "id"))},
    )


def _build_resume_prompt(event: SingleEventRequest, event_id: EventId) -> Optional[str]:
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


def _ensure_message_within_limit(text: str) -> str:
    """Bound user.message text like the task-prompt schema cap.

    The concatenated message becomes an agent prompt via the internal service
    path, bypassing JoySafeterCreateTaskRequest's schema cap — so it needs its
    own bound to keep one message from bloating a DB row / the Redis SSE fan-out.
    """
    if len(text) > MAX_PROMPT_CHARS:
        raise RequestValidationAppError(
            code="SESSION_CONTENT_TOO_LARGE",
            message="Message content is too large",
            data={"field": "content", "max_chars": MAX_PROMPT_CHARS, "actual_chars": len(text)},
            user_action="fix_input",
        )
    return text


def _validate_message_content(content: Any) -> str:
    """Validate user.message content.

    Accepts either a plain string or a list of ``{type: "text", text: "..."}``
    content blocks (matching the Rust joysafeter spec).  Returns the concatenated
    text for task creation.
    """
    if isinstance(content, str):
        return _ensure_message_within_limit(content)
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
        return _ensure_message_within_limit("\n".join(parts))
    raise RequestValidationAppError(
        code="SESSION_CONTENT_INVALID",
        message="content must be a string or array of content blocks",
        data={"field": "content", "content_type": type(content).__name__},
        user_action="fix_input",
    )


async def _find_idempotent_user_message_event(
    db: AsyncSession,
    session_id: SessionId,
    idempotency_key: str,
    project_id: Optional[str] = None,
):
    return await SessionService(db).find_user_message_event_by_idempotency_key(
        session_id,
        idempotency_key,
        project_id=project_id,
    )


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
    session_id: SessionId,
    idempotency_key: str,
    project_id: Optional[str],
    expected_prompt: Optional[str] = None,
) -> SessionEventResponse | None:
    from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService

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

    existing_event = await _find_idempotent_user_message_event(
        db,
        session_id,
        idempotency_key,
        project_id=project_id,
    )
    if existing_event is not None and existing_task is not None:
        return _session_event_response(existing_event)
    return None


async def _create_and_enqueue_resume_task(
    *,
    svc: SessionService,
    session_id: SessionId,
    agent_id: AgentId,
    project_id: Optional[str],
    user_id: Optional[str],
    org_id: Optional[str],
    prompt: str,
    failure_context: str,
    source_event_id: EventId,
    enforce_user_quota: bool,
) -> TaskId:
    from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService

    task, _created = await TaskSubmissionService(svc.db).create_and_dispatch(
        agent_id=agent_id,
        prompt=prompt,
        system_prompt=None,
        chat_session_id=session_id,
        session_svc=svc,
        timeout_sec=7200,
        max_retries=2,
        project_id=project_id,
        user_id=user_id,
        org_id=org_id,
        idempotency_key=f"session-control:{source_event_id}:{failure_context}",
        enforce_user_quota=enforce_user_quota,
        emit_user_message=False,  # caller already emitted via POST /sessions/{id}/events
    )
    return task.id


async def _mark_session_running_for_active_task(
    *,
    svc: SessionService,
    session_id: SessionId,
    task_id: TaskId | None = None,
    project_id: Optional[str] = None,
    broadcaster=None,
) -> bool:
    if task_id is None:
        from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService

        active_tasks = await TaskService(svc.db).list_active_tasks_by_session(session_id, project_id=project_id)
        if len(active_tasks) != 1:
            return False
        task_id = active_tasks[0].id

    running_accepted = await svc.update_session_status_for_task_event(session_id, "running", task_id)
    if not running_accepted:
        return False

    running_event = await svc.send_event(
        session_id,
        "session.status_running",
        {"task_id": str(task_id)},
    )
    if broadcaster:
        running_broadcast = {
            "id": str(running_event.id),
            "type": running_event.event_type,
            "seq": running_event.seq,
        }
        if isinstance(running_event.payload, dict):
            running_broadcast.update(running_event.payload)
        await broadcaster.send(session_id, running_broadcast)
    return True


async def _replay_pending_control_inputs(
    session_id: SessionId,
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
                tool_use_id=evt.payload.get("call_id")
                or evt.payload.get("tool_use_call_id")
                or evt.payload.get("tool_use_id"),
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
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    request: Request = None,
) -> dict:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        idempotency_key = None
    else:
        idempotency_key = idempotency_key.strip()

    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
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

    from app.joysafeter_shared.orchestrator_bridge import get_session_broadcaster

    broadcaster = get_session_broadcaster()

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
            from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService as TaskService

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

        runtime_single, source_tool_use_event_id = await _normalize_control_event_for_runtime(
            svc,
            session_id,
            single,
        )

        # Build payload for persistence
        payload = dict(single.payload)
        if single.content and "content" not in payload:
            payload["content"] = single.content
        if source_tool_use_event_id and "tool_use_event_id" not in payload:
            payload["tool_use_event_id"] = source_tool_use_event_id
        if runtime_single.resolved_tool_use_id() and "call_id" not in payload:
            payload["call_id"] = runtime_single.resolved_tool_use_id()
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
                "id": str(event.id),
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
            from app.joysafeter_api.api.v1.agent_identity_capture import (
                prepare_agent_identity_capture,
            )
            from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService

            agent_obj = await AgentService(db).get_agent(session.agent_id, project_id=auth_ctx.project_id)
            identity_hook = None
            if agent_obj is not None:
                identity_hook = await prepare_agent_identity_capture(
                    db,
                    request,
                    auth_ctx,
                    agent_obj,
                )
            task, _created = await TaskSubmissionService(db).create_and_dispatch(
                agent_id=session.agent_id,
                prompt=message_text,
                system_prompt=None,
                chat_session_id=session_id,
                session_svc=svc,
                timeout_sec=7200,
                max_retries=2,
                project_id=auth_ctx.project_id,
                user_id=auth_ctx.user_id,
                org_id=auth_ctx.org_id,
                idempotency_key=idempotency_key,
                enforce_user_quota=auth_ctx.principal_type == "user",
                emit_user_message=False,  # event already persisted by this endpoint
                before_enqueue=identity_hook,
            )
            if broadcaster:
                running_event = await svc.find_status_running_event_for_task(
                    session_id,
                    task.id,
                    project_id=auth_ctx.project_id,
                )
                if running_event is not None:
                    running_broadcast = {
                        "id": str(running_event.id),
                        "type": running_event.event_type,
                        "seq": running_event.seq,
                    }
                    if isinstance(running_event.payload, dict):
                        running_broadcast.update(running_event.payload)
                    await broadcaster.send(session_id, running_broadcast)

        elif single.type == "user.custom_tool_result":
            injected = False
            # Cross-process relay: route via Redis to the sandbox owner instance.
            if not injected and await _relay_control_via_redis(runtime_single, session=session, event_id=event.id):
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
                resume_prompt = _build_resume_prompt(runtime_single, event.id)
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            svc=svc,
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            user_id=auth_ctx.user_id,
                            org_id=auth_ctx.org_id,
                            prompt=resume_prompt,
                            failure_context="custom_tool_result",
                            source_event_id=event.id,
                            enforce_user_quota=auth_ctx.principal_type == "user",
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
            # Cross-process relay: route via Redis to the Rust orchestrator
            # instance that owns the sandbox.
            if not injected and await _relay_control_via_redis(runtime_single, session=session, event_id=event.id):
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
                resume_prompt = _build_resume_prompt(runtime_single, event.id)
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            svc=svc,
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            user_id=auth_ctx.user_id,
                            org_id=auth_ctx.org_id,
                            prompt=resume_prompt,
                            failure_context="tool_confirmation",
                            source_event_id=event.id,
                            enforce_user_quota=auth_ctx.principal_type == "user",
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
            # Cross-process relay: route via Redis to the sandbox owner instance.
            if not injected and await _relay_control_via_redis(runtime_single, session=session, event_id=event.id):
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
                resume_prompt = _build_resume_prompt(runtime_single, event.id)
                if resume_prompt and session.status != "running":
                    try:
                        await _create_and_enqueue_resume_task(
                            svc=svc,
                            session_id=session_id,
                            agent_id=session.agent_id,
                            project_id=auth_ctx.project_id,
                            user_id=auth_ctx.user_id,
                            org_id=auth_ctx.org_id,
                            prompt=resume_prompt,
                            failure_context="interrupt",
                            source_event_id=event.id,
                            enforce_user_quota=auth_ctx.principal_type == "user",
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

    return {"events": [r.model_dump() for r in results]}


@router.get("/{session_id}/events")
async def list_events(
    session_id: SessionId,
    limit: int = Query(50, ge=1, le=200),
    after_seq: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    before_seq: Optional[int] = Query(None),
    order: Literal["asc", "desc"] = Query("asc"),
) -> PaginatedResponse[SessionEventResponse]:
    if after_seq is not None and before_seq is not None:
        raise InvalidRequestError(
            code="SESSION_EVENT_CURSOR_CONFLICT",
            message="Use either after_seq or before_seq, not both",
            data={"after_seq": after_seq, "before_seq": before_seq},
            user_action="fix_input",
        )

    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    events, has_more = await svc.list_events(
        session_id,
        limit,
        after_seq=after_seq,
        before_seq=before_seq,
        order=order,
        project_id=auth_ctx.project_id,
    )
    data = [SessionEventResponse.model_validate(e) for e in events]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


async def _iter_events_after(svc, session_id, start_seq, project_id, page_size: int = 1000):
    """Yield every event with seq > start_seq, in order, paginating past the
    per-call page limit.

    ``list_events`` caps each call at ``page_size`` and reports ``has_more``. The
    SSE replay/poll paths previously issued a single call and discarded
    ``has_more``, so a session with more than one page of events after the cursor
    (a reconnect to a long session, or a fast producer) had its tail silently
    dropped — a permanent gap for an active session whose live traffic keeps the
    30s catch-up timeout from firing. Draining until ``has_more`` is False closes
    that gap; the caller's seq<=last_seq dedup makes over-fetching harmless.
    """
    cursor = start_seq
    while True:
        events, has_more = await svc.list_events(session_id, page_size, cursor, project_id=project_id)
        if not events:
            return
        for ev in events:
            yield ev
            cursor = ev.seq
        if not has_more:
            return


@router.get("/{session_id}/events/stream")
async def session_event_stream(
    request: Request,
    session_id: SessionId,
    after_seq: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """SSE endpoint for real-time session event streaming."""
    svc = SessionService(db)
    session = await svc.get_session(session_id, project_id=auth_ctx.project_id)
    if not session:
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

        # Subscribe to live events BEFORE replaying from the DB. Any event
        # published during the replay window is buffered in the queue and
        # delivered right after replay; the seq<=last_seq dedup in the consume
        # loop drops anything already replayed. Subscribing after replay (the
        # old order) left a handoff gap where such an event surfaced only via
        # the 30s DB catch-up.
        q = broadcaster.subscribe(session_id) if broadcaster else None
        try:
            # First, replay existing events after the cursor
            if after_seq is not None:
                from app.joysafeter_shared.database import AsyncSessionLocal

                async with AsyncSessionLocal() as replay_db:
                    replay_svc = SessionService(replay_db)
                    replayed = 0
                    async for ev in _iter_events_after(replay_svc, session_id, after_seq, auth_ctx.project_id):
                        last_seq = max(last_seq, ev.seq)
                        replayed += 1
                        data_dict = {
                            "id": str(ev.id),
                            "type": ev.event_type,
                            "seq": ev.seq,
                        }
                        if isinstance(ev.payload, dict):
                            data_dict.update(ev.payload)
                        data_dict["_sse_source"] = "db_replay"
                        data = json.dumps(data_dict)
                        yield f"id: evt_{ev.id}\ndata: {data}\n\n"
                    if replayed:
                        logger.info(
                            "SSE db_replay session=%s count=%s from_seq=%s to_seq=%s",
                            session_id,
                            replayed,
                            after_seq,
                            last_seq,
                        )

            # No broadcaster available: fall back to DB polling
            if not broadcaster:
                while True:
                    if await request.is_disconnected():
                        break
                    from app.joysafeter_shared.database import AsyncSessionLocal

                    async with AsyncSessionLocal() as poll_db:
                        poll_svc = SessionService(poll_db)
                        polled = 0
                        async for ev in _iter_events_after(poll_svc, session_id, last_seq, auth_ctx.project_id):
                            last_seq = max(last_seq, ev.seq)
                            polled += 1
                            data_dict = {
                                "id": str(ev.id),
                                "type": ev.event_type,
                                "seq": ev.seq,
                            }
                            if isinstance(ev.payload, dict):
                                data_dict.update(ev.payload)
                            data_dict["_sse_source"] = "db_fallback_no_broadcaster"
                            yield f"id: evt_{ev.id}\ndata: {json.dumps(data_dict)}\n\n"
                        if polled:
                            logger.warning(
                                "SSE db_fallback_no_broadcaster session=%s count=%s to_seq=%s",
                                session_id,
                                polled,
                                last_seq,
                            )

                    await asyncio.sleep(2)
                return

            # Consume live events from the subscription opened above
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
                        polled = 0
                        async for ev in _iter_events_after(poll_svc, session_id, last_seq, auth_ctx.project_id):
                            last_seq = max(last_seq, ev.seq)
                            polled += 1
                            data_dict = {
                                "id": str(ev.id),
                                "type": ev.event_type,
                                "seq": ev.seq,
                            }
                            if isinstance(ev.payload, dict):
                                data_dict.update(ev.payload)
                            data_dict["_sse_source"] = "db_fallback_timeout"
                            yield f"id: {ev.id}\ndata: {json.dumps(data_dict)}\n\n"
                        if polled:
                            log_boundary_failure(
                                logger,
                                boundary="session_stream",
                                code="SESSION_STREAM_DB_FALLBACK_TIMEOUT",
                                message="SSE DB fallback timeout",
                                operation="stream_session_events_db_fallback",
                                data={"session_id": str(session_id), "count": polled, "to_seq": last_seq},
                                retryable=True,
                                user_action="retry",
                            )
                    yield ": heartbeat\n\n"
        finally:
            if broadcaster and q is not None:
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


@router.get("/{session_id}/resources")
async def list_session_resources(
    session_id: SessionId,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    resource_svc = SessionResourceService(db)
    await resource_svc.get_project_session_or_raise(session_id, auth_ctx.project_id)
    return {"data": await resource_svc.list_resource_payloads(session_id, project_id=auth_ctx.project_id)}


async def _relay_sandbox_file_command(
    *,
    db: AsyncSession,
    session_id: SessionId,
    project_id: Optional[str],
    op: str,
    path: str,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    session = await SessionService(db).get_session(session_id, project_id=project_id)
    if not session:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message="Session not found",
            data={"session_id": str(session_id)},
            user_action="refresh",
        )
    sandbox_id = getattr(session, "last_sandbox_id", None)
    if not sandbox_id:
        raise ServiceUnavailableError(
            code="SESSION_SANDBOX_NOT_AVAILABLE",
            message="Session sandbox is not available",
            data={"session_id": str(session_id)},
            retryable=False,
            user_action="refresh",
        )

    try:
        from app.joysafeter_shared.orchestrator_bridge.runtime_commands import relay_sandbox_command_payload_via_redis

        payload = await relay_sandbox_command_payload_via_redis(
            sandbox_id,
            command_type="sandbox_file",
            extra_command={
                "op": op,
                "path": path,
                **({"max_bytes": max_bytes} if max_bytes is not None else {}),
            },
            boundary="session_api",
            operation="relay_sandbox_file_command",
            failure_code="SESSION_REDIS_SANDBOX_FILE_RELAY_FAILED",
            failure_message="Redis sandbox file relay command failed",
            data={"session_id": str(session_id), "op": op},
            ack_timeout_seconds=15,
        )
    except Exception as exc:
        log_boundary_failure(
            logger,
            boundary="session_api",
            code="SESSION_SANDBOX_FILE_RELAY_FAILED",
            message="Sandbox file relay failed",
            operation="relay_sandbox_file_command",
            error=exc,
            data={"session_id": str(session_id), "op": op},
        )
        payload = None

    if not payload:
        raise ServiceUnavailableError(
            code="SESSION_SANDBOX_FILE_RELAY_UNAVAILABLE",
            message="Sandbox file service is not available",
            data={"session_id": str(session_id)},
            retryable=True,
            user_action="retry",
        )
    if not payload.get("ok"):
        code = str(payload.get("code") or "SANDBOX_FILE_ERROR")
        if code == "NOT_FOUND":
            raise NotFoundError(
                code="SANDBOX_FILE_NOT_FOUND",
                message="Sandbox file path not found",
                data={"path": path},
                user_action="refresh",
            )
        raise InvalidRequestError(
            code=code,
            message=str(payload.get("error") or "Sandbox file command failed"),
            data={"path": path, "op": op},
            user_action="fix_input",
        )
    return payload


def _decode_sandbox_file_payload(payload: dict[str, Any], *, max_bytes: int) -> bytes:
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str):
        raise ServiceUnavailableError(
            code="SANDBOX_FILE_PAYLOAD_INVALID",
            message="Sandbox file payload is invalid",
            data={},
            retryable=True,
            user_action="retry",
        )
    if len(encoded) > ((max_bytes + 2) // 3) * 4 + 16:
        raise InvalidRequestError(
            code="SANDBOX_FILE_TOO_LARGE",
            message="Sandbox file exceeds download size limit",
            data={"max_bytes": max_bytes},
            user_action="fix_input",
        )
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ServiceUnavailableError(
            code="SANDBOX_FILE_PAYLOAD_INVALID",
            message="Sandbox file payload is invalid",
            data={},
            retryable=True,
            user_action="retry",
        ) from exc
    if len(data) > max_bytes:
        raise InvalidRequestError(
            code="SANDBOX_FILE_TOO_LARGE",
            message="Sandbox file exceeds download size limit",
            data={"max_bytes": max_bytes},
            user_action="fix_input",
        )
    return data


@router.get("/{session_id}/sandbox/files")
async def list_sandbox_files(
    session_id: SessionId,
    path: Optional[str] = Query(default="/workspace"),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    safe_path = _validate_sandbox_file_path(path)
    return await _relay_sandbox_file_command(
        db=db,
        session_id=session_id,
        project_id=auth_ctx.project_id,
        op="list",
        path=safe_path,
    )


@router.get("/{session_id}/sandbox/files/content")
async def read_sandbox_file_content(
    session_id: SessionId,
    path: str = Query(...),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    safe_path = _validate_sandbox_file_path(path)
    payload = await _relay_sandbox_file_command(
        db=db,
        session_id=session_id,
        project_id=auth_ctx.project_id,
        op="content",
        path=safe_path,
    )
    content = payload.get("content")
    if isinstance(content, str) and len(content) > _SANDBOX_FILE_MAX_PREVIEW_CHARS:
        raise InvalidRequestError(
            code="SANDBOX_FILE_TOO_LARGE",
            message="Sandbox file exceeds preview size limit",
            data={"max_chars": _SANDBOX_FILE_MAX_PREVIEW_CHARS},
            user_action="fix_input",
        )
    return payload


@router.get("/{session_id}/sandbox/files/raw")
async def download_sandbox_file_raw(
    session_id: SessionId,
    path: str = Query(...),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    safe_path = _validate_sandbox_file_path(path)
    payload = await _relay_sandbox_file_command(
        db=db,
        session_id=session_id,
        project_id=auth_ctx.project_id,
        op="raw",
        path=safe_path,
        max_bytes=_SANDBOX_FILE_MAX_DOWNLOAD_BYTES,
    )
    data = _decode_sandbox_file_payload(payload, max_bytes=_SANDBOX_FILE_MAX_DOWNLOAD_BYTES)
    filename = str(payload.get("filename") or safe_path.rstrip("/").rsplit("/", 1)[-1] or "download")
    media_type = str(payload.get("content_type") or "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": _safe_content_disposition(filename)},
    )


@router.get("/{session_id}/sandbox/files/archive")
async def download_sandbox_file_archive(
    session_id: SessionId,
    path: str = Query(default="/workspace"),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    safe_path = _validate_sandbox_file_path(path)
    payload = await _relay_sandbox_file_command(
        db=db,
        session_id=session_id,
        project_id=auth_ctx.project_id,
        op="archive",
        path=safe_path,
        max_bytes=_SANDBOX_ARCHIVE_MAX_DOWNLOAD_BYTES,
    )
    data = _decode_sandbox_file_payload(payload, max_bytes=_SANDBOX_ARCHIVE_MAX_DOWNLOAD_BYTES)
    filename = str(payload.get("filename") or "workspace.zip")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": _safe_content_disposition(filename)},
    )


@router.post("/{session_id}/resources", status_code=201)
async def add_session_resource(
    session_id: SessionId,
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

    resource_svc = SessionResourceService(db)
    session = await resource_svc.get_project_session_or_raise(session_id, auth_ctx.project_id)
    resource_svc.ensure_mutable(session, session_id)

    if rtype == "file":
        try:
            file_req = SessionFileResourceRequest.model_validate(req)
        except Exception as e:
            raise InvalidRequestError(
                code="SESSION_FILE_RESOURCE_INVALID",
                message="Invalid file resource",
                data={"resource_type": "file"},
                detail=str(e),
                user_action="fix_input",
            ) from e
        return await resource_svc.add_file_resource(session_id, file_req, project_id=auth_ctx.project_id)

    if rtype == "github_repository":
        try:
            repo_req = SessionRepoResourceRequest.model_validate(req)
        except Exception as e:
            raise InvalidRequestError(
                code="SESSION_REPO_RESOURCE_INVALID",
                message="Invalid repo resource",
                data={"resource_type": "github_repository"},
                detail=str(e),
                user_action="fix_input",
            ) from e
        return await resource_svc.add_repo_resource(session_id, repo_req, project_id=auth_ctx.project_id)

    raise InvalidRequestError(
        code="SESSION_RESOURCE_TYPE_UNSUPPORTED",
        message=f"Unsupported resource type: {rtype}",
        data={"resource_type": str(rtype)},
        user_action="fix_input",
    )


@router.delete("/{session_id}/resources/{resource_id}")
async def delete_session_resource(
    session_id: SessionId,
    resource_id: SessionResourceId,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
):
    resource_svc = SessionResourceService(db)
    session = await resource_svc.get_project_session_or_raise(session_id, auth_ctx.project_id)
    resource_svc.ensure_mutable(session, session_id)
    return await resource_svc.delete_resource(session_id, resource_id, project_id=auth_ctx.project_id)


@router.patch("/{session_id}/resources/{resource_id}")
async def update_repo_resource_token(
    session_id: SessionId,
    resource_id: SessionResourceId,
    req: UpdateRepoResourceRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> SessionRepoResourceResponse:
    """Rotate the clone credential on a github_repository resource.

    The new token is re-encrypted at rest; the response never echoes it.
    """
    resource_svc = SessionResourceService(db)
    session = await resource_svc.get_project_session_or_raise(session_id, auth_ctx.project_id)
    resource_svc.ensure_mutable(session, session_id)
    return await resource_svc.rotate_repo_token(
        session_id,
        resource_id,
        req.authorization_token,
        project_id=auth_ctx.project_id,
    )
