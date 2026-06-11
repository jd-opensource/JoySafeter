import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v2.id_helpers import parse_session_id as _parse_session_id
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas.session import (
    CreateSessionRequest,
    EventListParams,
    MAX_MEMORY_STORE_RESOURCES,
    SendEventRequest,
    SingleEventRequest,
    SessionEventResponse,
    SessionResourceResponse,
    SessionResponse,
    SessionAgent,
    SessionUsage,
)
from app.joysafeter_domain.schemas.common import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_api.services import JoySafeterAgentService as AgentService
from app.joysafeter_api.services import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-sessions"])


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify_mount_name(name: str) -> str:
    """Slugify a store name: lowercase, replace non-alphanumeric runs with '-'."""
    return _NON_ALNUM_RE.sub("-", name.lower()).strip("-")


def _session_to_response(session, agent=None, resources=None) -> SessionResponse:
    agent_data = SessionAgent(
        id=session.agent_id,
        version=session.agent_version or 1,
        name=agent.name if agent else "",
        description=agent.description if agent else None,
        model=agent.model if agent else None,
        system=agent.system_prompt if agent else None,
        tools=agent.tools if agent else [],
        skills=agent.skills if agent else [],
        mcp_servers=agent.mcp_configs if agent else [],
    )
    usage_data = session.usage or {}
    resource_responses = []
    for r in (resources or []):
        resource_responses.append(SessionResourceResponse(
            memory_store_id=r.store_id,
            access=r.access,
            instructions=r.instructions,
            mount_name=r.mount_name,
        ))
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
        raise HTTPException(
            400,
            f"Too many memory_store resources (max {MAX_MEMORY_STORE_RESOURCES})",
        )

    # --- Parse environment_id: strip env_ prefix and store raw ref ---
    env_id_raw = req.environment_id or ""
    environment_ref = env_id_raw
    if env_id_raw.startswith("env_"):
        environment_ref = env_id_raw[len("env_"):]

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
        raise HTTPException(404, "Agent not found")

    # --- Build agent_snapshot ---
    agent_version = agent.version
    agent_snapshot: dict = {"name": agent.name, "model": agent.model}
    if pinned_version is not None:
        snapshot = await agent_svc.get_agent_version_snapshot(agent.id, pinned_version)
        if snapshot is None:
            raise HTTPException(404, f"Agent version {pinned_version} not found")
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
            raise HTTPException(404, f"Memory store not found: {r.memory_store_id}")
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
                raise HTTPException(400, f"Invalid vault_id: {vid_raw}")
            vault = await vault_svc.get_vault(vid_uuid)
            if not vault or vault.project_id != auth_ctx.project_id:
                raise HTTPException(404, f"Vault not found: {vid_raw}")

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
    from app.joysafeter_domain.schemas.thread import MAX_FILE_RESOURCES
    if len(req.file_resources) > MAX_FILE_RESOURCES:
        raise HTTPException(400, f"Too many file resources (max {MAX_FILE_RESOURCES})")
    if req.file_resources:
        from app.joysafeter_api.services import FileService
        from app.joysafeter_shared.storage import get_storage
        from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
        from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile

        file_svc = FileService(get_storage())
        for fr in req.file_resources:
            file_id_str = fr.file_id.removeprefix("file_")
            try:
                fid = uuid.UUID(file_id_str)
            except ValueError:
                raise HTTPException(400, f"Invalid file_id: {fr.file_id}")
            record = await file_svc.get_metadata(db, fid, auth_ctx.project_id)
            if not record:
                raise HTTPException(404, f"File not found: {fr.file_id}")
            mount_path = fr.mount_path or f"/workspace/{record.filename}"
            session_file = JoySafeterSessionFile(
                session_id=session.id,
                file_id=record.id,
                mount_path=mount_path,
                access="read_only",
            )
            db.add(session_file)
        await db.commit()

    # Provision sandbox at session creation time (per API spec)
    try:
        from app.joysafeter_orchestrator.lifespan import get_sandbox_resolver
        resolver = get_sandbox_resolver()
        if resolver:
            agent_env = dict(agent.env or {})
            if getattr(agent, "secret_ref", None):
                from app.joysafeter_api.services import SecretService
                secret_svc = SecretService(db)
                secret = await secret_svc.get_secret_by_name(
                    agent.secret_ref, project_id=auth_ctx.project_id
                )
                if secret and secret.data:
                    for k, v in secret.data.items():
                        agent_env.setdefault(k, str(v))
                    if "ANTHROPIC_AUTH_TOKEN" in agent_env and "ANTHROPIC_API_KEY" not in agent_env:
                        agent_env["ANTHROPIC_API_KEY"] = agent_env["ANTHROPIC_AUTH_TOKEN"]
            env_ref = environment_ref or agent.environment_ref
            resolved_image = None
            networking = None
            if env_ref:
                from app.joysafeter_api.services import JoySafeterEnvironmentService as EnvironmentService
                env_svc = EnvironmentService(db)
                environment = await env_svc.get_environment_by_ref(env_ref, project_id=auth_ctx.project_id)
                if environment:
                    resolved_image = getattr(environment, "image_tag", None)
                    config = environment.config or {}
                    net_cfg = config.get("networking")
                    if net_cfg and isinstance(net_cfg, dict):
                        networking = net_cfg
            resolved = await resolver.resolve(
                session.id, agent_env, image=resolved_image, networking=networking,
                engine_kind=getattr(agent, "engine_kind", None),
            )
            if resolved.get("sandbox_id"):
                await svc.update_session_sandbox(session.id, resolved["sandbox_id"])
    except Exception:
        logger.warning(
            "Failed to provision sandbox at session creation (will be lazy-created)",
            exc_info=True,
        )

    return _session_to_response(session, agent, resources=resources)


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
            raise HTTPException(404, "Agent not found")
        sessions, has_more = await svc.list_sessions_by_agent(
            agent_id, limit, after_id, project_id=auth_ctx.project_id
        )
    else:
        sessions, has_more = await svc.list_sessions(limit, after_id, include_archived=include_archived, project_id=auth_ctx.project_id)
    data = [_session_to_response(s) for s in sessions]
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
        raise HTTPException(404, "Session not found")
    if session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")
    resources = await svc.list_session_memory_stores(session_id)
    agent = None
    if session.agent_id:
        agent_svc = AgentService(db)
        agent = await agent_svc.get_agent(session.agent_id, project_id=auth_ctx.project_id)
    return _session_to_response(session, agent=agent, resources=resources)


@router.delete("/{session_id}", status_code=200)
async def delete_session(
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")
    if session.status == "running":
        raise HTTPException(409, "Running session cannot be deleted. Send user.interrupt first.")

    # Emit session.deleted event via broadcaster before deleting
    from app.joysafeter_orchestrator.lifespan import (
        get_session_broadcaster,
        get_bridge_registry,
        get_sandbox_provider,
        get_envoy_manager,
    )
    broadcaster = get_session_broadcaster()
    if broadcaster:
        await broadcaster.send(session_id, {
            "type": "session.deleted",
            "session_id": str(session_id),
        })

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
                from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
                shutdown_msg = joysafeter_pb2.OrchestratorMessage(
                    shutdown=joysafeter_pb2.Shutdown(reason="session deleted")
                )
                try:
                    await bridge.runner_tx.put(shutdown_msg)
                except Exception:
                    pass
            await bridge_registry.remove(sandbox.id)

        # Stop and destroy container
        provider = get_sandbox_provider()
        if provider and sandbox.external_id:
            try:
                await provider.stop(sandbox.external_id)
            except Exception:
                pass
            try:
                await provider.destroy(sandbox.external_id)
            except Exception:
                pass

        # Mark as destroyed in DB
        await sandbox_svc.update_status_cas(sandbox.id, sandbox.status, "destroyed")

        # Envoy teardown
        envoy = get_envoy_manager()
        if envoy:
            try:
                await envoy.remove_sandbox(sandbox.id)
            except Exception:
                pass

    # Hard delete the session
    ok = await svc.delete_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")

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
        raise HTTPException(404, "Session not found")
    ok = await svc.archive_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
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
        raise HTTPException(404, "Session not found")
    if session.archived_at:
        raise HTTPException(409, "Session is archived")
    if session.status == "terminated":
        raise HTTPException(409, "Session is terminated")

    from app.joysafeter_orchestrator.lifespan import (
        get_bridge_registry,
        get_redis_coordinator,
        get_session_broadcaster,
    )
    from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
    from app.joysafeter_domain.models.task import JoySafeterTaskStatus
    from app.joysafeter_api.services import JoySafeterSessionLifecycleService
    from app.joysafeter_api.services import JoySafeterTaskService as TaskService

    stop_reason = {"type": "cancelled"}
    lifecycle = JoySafeterSessionLifecycleService(db)
    try:
        await lifecycle.transition_and_emit(
            session_id,
            "idle",
            "session.status_idle",
            {"stop_reason": stop_reason},
            stop_reason=stop_reason,
        )
    except Exception:
        logger.debug(
            "Could not transition session %s to idle during stop",
            session_id,
            exc_info=True,
        )

    task_svc = TaskService(db)
    active_tasks = await task_svc.list_active_tasks_by_session(
        session_id, project_id=auth_ctx.project_id
    )
    for task in active_tasks:
        try:
            await task_svc.update_task_error(
                task.id,
                "Cancelled via session stop",
                JoySafeterTaskStatus.CANCELLED,
            )
        except Exception:
            logger.debug("Failed to cancel task %s during session stop", task.id)

    registry = get_bridge_registry()
    locally_cancelled: set[uuid.UUID] = set()
    if registry:
        for task in active_tasks:
            bridge = registry.get_by_task(task.id)
            if bridge:
                bridge.request_cancel()
                if bridge.runner_stream:
                    try:
                        await bridge.runner_stream.write(
                            joysafeter_pb2.OrchestratorMessage(
                                cancel=joysafeter_pb2.CancelTask(
                                    reason="Cancelled via session stop"
                                )
                            )
                        )
                        locally_cancelled.add(task.id)
                    except Exception:
                        logger.warning("Failed to send CancelTask for task %s", task.id)

    coordinator = get_redis_coordinator()
    if coordinator:
        for task in active_tasks:
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
                json.dumps({
                    "type": "complete",
                    "output": "",
                    "error": "Cancelled via session stop",
                    "status": "cancelled",
                }),
            )

    broadcaster = get_session_broadcaster()
    if broadcaster:
        await broadcaster.send(
            session_id,
            {"type": "session.status_idle", "stop_reason": stop_reason},
        )

    return {
        "id": f"sess_{session_id}",
        "status": "idle",
        "cancelled_tasks": len(active_tasks),
    }


CONTROL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result", "user.interrupt"}
LIVE_INPUT_PREFIX = "__joysafeter_input_v1__:"


def _encode_live_input(
    event: SingleEventRequest, source_event_id: Optional[str] = None
) -> Optional[str]:
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
            return " ".join(
                b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
            )
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
        for block in content:
            if not isinstance(block, dict):
                raise HTTPException(
                    422,
                    "Each content block must be an object with {type, text}",
                )
            if block.get("type") != "text" or not isinstance(block.get("text"), str):
                raise HTTPException(
                    422,
                    "Content blocks must have type 'text' and a string 'text' field",
                )
            parts.append(block["text"])
        if not parts:
            raise HTTPException(422, "Content blocks array must not be empty")
        return "\n".join(parts)
    raise HTTPException(422, "content must be a string or array of content blocks")


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
                        evt.id, session_id,
                    )
    except Exception:
        logger.debug("Error replaying pending controls for session %s", session_id, exc_info=True)


@router.post("/{session_id}/events", status_code=201)
async def send_event(
    req: SendEventRequest,
    session_id: uuid.UUID = Depends(_parse_session_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")

    # --- gate: reject events on archived / terminated / rescheduling sessions ---
    if session.archived_at:
        raise HTTPException(409, "Session is archived")
    if session.status == "terminated":
        raise HTTPException(409, "Session is terminated")
    if session.status == "rescheduling":
        raise HTTPException(409, "Session is rescheduling, try again later")

    single_events = req.to_single_events()
    if not single_events:
        raise HTTPException(400, "No events provided")

    from app.joysafeter_orchestrator.lifespan import get_session_broadcaster, get_bridge_registry

    broadcaster = get_session_broadcaster()
    bridge_registry = get_bridge_registry()

    results: list[SessionEventResponse] = []
    for single in single_events:
        # --- user.message: reject if session is already running (409) ---
        if single.type == "user.message":
            if session.status == "running":
                raise HTTPException(
                    409,
                    "Session is already running; wait for completion before sending a new message",
                )
            # Validate content
            raw_content = single.content
            if raw_content is None:
                raw_content = single.payload.get("content")
            if raw_content is None:
                raise HTTPException(422, "user.message requires content")
            message_text = _validate_message_content(raw_content)

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

        event = await svc.send_event(session_id, single.type, payload)

        event_response = SessionEventResponse(
            id=event.id,
            event_type=event.event_type,
            payload=event.payload,
            seq=event.seq,
            processed_at=event.processed_at,
            created_at=event.created_at,
        )

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
            try:
                from app.joysafeter_orchestrator.lifespan import get_scheduler
                scheduler = get_scheduler()
                from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                from app.joysafeter_shared.database import AsyncSessionLocal
                async with AsyncSessionLocal() as task_db:
                    task_svc = TaskService(task_db)
                    task = await task_svc.create_task(
                        agent_id=session.agent_id,
                        prompt=message_text,
                        chat_session_id=session_id,
                        project_id=auth_ctx.project_id,
                    )
                # Insert session.status_running event
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
                # Transition session to running
                try:
                    await svc.update_session_status(session_id, "running")
                except Exception:
                    logger.debug(
                        "Could not transition session %s to running (may already be running)",
                        session_id,
                    )
                # Push task to runner queue. In split-service mode the API
                # process does not own an in-memory scheduler, so publish
                # directly to the Redis-backed global queue.
                if scheduler:
                    await scheduler.push_to_global(task.id)
                else:
                    from app.joysafeter_shared.cache.redis import RedisClient
                    redis = await RedisClient.get_client()
                    await redis.rpush("joysafeter:global_queue", str(task.id))
            except HTTPException:
                raise
            except Exception:
                logger.exception("Failed to dispatch user.message for session %s", session_id)

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
                            await svc.update_session_status(session_id, "running")
                        except Exception:
                            logger.debug(
                                "Bridge injection failed for custom_tool_result, falling back to task",
                            )
            # Fallback: create a retry task when bridge injection was not possible
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        from app.joysafeter_orchestrator.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                            from app.joysafeter_shared.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
                                    project_id=auth_ctx.project_id,
                                )
                                await scheduler.push_to_global(task.id)
                    except Exception:
                        logger.debug(
                            "Failed to create fallback task for custom_tool_result on session %s",
                            session_id,
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
                            await svc.update_session_status(session_id, "running")
                        except Exception:
                            logger.debug(
                                "Bridge injection failed for tool_confirmation on session %s",
                                session_id,
                            )
            # Fallback: create a retry task
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        from app.joysafeter_orchestrator.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                            from app.joysafeter_shared.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
                                    project_id=auth_ctx.project_id,
                                )
                                await scheduler.push_to_global(task.id)
                    except Exception:
                        logger.debug(
                            "Failed to create fallback task for tool_confirmation on session %s",
                            session_id,
                        )

        elif single.type == "user.interrupt":
            # Encode interrupt as a live-input with source_event_id
            injected = False
            if bridge_registry and session.last_sandbox_id:
                bridge = await bridge_registry.get(session.last_sandbox_id)
                if bridge:
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
            # Fallback: create a retry task when bridge injection was not possible
            if not injected:
                resume_prompt = _build_resume_prompt(single, str(event.id))
                if resume_prompt and session.status != "running":
                    try:
                        from app.joysafeter_orchestrator.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.joysafeter_api.services import JoySafeterTaskService as TaskService
                            from app.joysafeter_shared.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
                                    project_id=auth_ctx.project_id,
                                )
                                await scheduler.push_to_global(task.id)
                    except Exception:
                        logger.debug(
                            "Failed to create fallback task for interrupt on session %s",
                            session_id,
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
        raise HTTPException(404, "Session not found")
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
        raise HTTPException(404, "Session not found")
    if session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")

    from app.joysafeter_orchestrator.lifespan import (
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

                await asyncio.sleep(15)
            return

        q = broadcaster.subscribe(session_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    event_seq = event.get("seq", 0)
                    if event_seq <= last_seq:
                        continue
                    last_seq = event_seq
                    event_id = event.get("id", "")
                    if not event_id.startswith("evt_"):
                        event_id = f"evt_{event_id}"
                    logger.debug(
                        "SSE live_push session=%s source=%s seq=%s type=%s",
                        session_id,
                        event.get("_sse_source") or "unknown_live",
                        event_seq,
                        event.get("type"),
                    )
                    yield f"id: {event_id}\ndata: {json.dumps(event)}\n\n"
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
                            logger.warning(
                                "SSE db_fallback_timeout session=%s count=%s to_seq=%s",
                                session_id,
                                len(events),
                                last_seq,
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

from datetime import datetime
from pydantic import BaseModel as PydanticBaseModel


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


@router.get("/{session_id}/resources")
async def list_session_resources(
    session_id: uuid.UUID,
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from sqlalchemy import select as sa_select
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")

    result = await db.execute(
        sa_select(JoySafeterSessionFile).where(JoySafeterSessionFile.session_id == session_id)
    )
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
    return {"data": data}


@router.post("/{session_id}/resources", status_code=201)
async def add_session_resource(
    session_id: uuid.UUID,
    req: AddSessionFileRequest,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
) -> SessionFileResourceResponse:
    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from app.joysafeter_api.services import FileService
    from app.joysafeter_shared.storage import get_storage
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")

    file_id_str = req.file_id.removeprefix("file_")
    try:
        fid = uuid.UUID(file_id_str)
    except ValueError:
        raise HTTPException(400, f"Invalid file_id: {req.file_id}")

    file_svc = FileService(get_storage())
    record = await file_svc.get_metadata(db, fid, auth_ctx.project_id)
    if not record:
        raise HTTPException(404, f"File not found: {req.file_id}")

    mount_path = req.mount_path or f"/workspace/{record.filename}"
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


@router.delete("/{session_id}/resources/{resource_id}")
async def delete_session_resource(
    session_id: uuid.UUID,
    resource_id: str,
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
    db: AsyncSession = Depends(get_db),
):
    from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
    from sqlalchemy import select as sa_select
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session or session.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Session not found")

    rid = resource_id.removeprefix("sesrsc_")
    try:
        rid_uuid = uuid.UUID(rid)
    except ValueError:
        raise HTTPException(400, "Invalid resource_id")

    result = await db.execute(
        sa_select(JoySafeterSessionFile).where(
            JoySafeterSessionFile.id == rid_uuid,
            JoySafeterSessionFile.session_id == session_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Resource not found")

    await db.delete(row)
    await db.commit()
    return {"id": resource_id, "deleted": True}
