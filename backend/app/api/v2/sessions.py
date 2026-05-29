import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.id_helpers import parse_session_id as _parse_session_id
from app.core.database import get_db
from app.schemas.session import (
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
from app.schemas.common import CursorPaginatedResponse as PaginatedResponse
from app.services.agent_service import ConductorAgentService as AgentService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conductor-sessions"])


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
    req: CreateSessionRequest, db: AsyncSession = Depends(get_db)
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
        agent = await agent_svc.get_agent(req.agent.id)
        pinned_version = req.agent.version
    elif req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name)
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
    from app.services.conductor_memory_service import MemoryService
    mem_svc = MemoryService(db)
    resource_dicts = []
    for r in req.resources:
        dump = r.model_dump()
        if not dump.get("mount_name"):
            store = await mem_svc.get_store(r.memory_store_id)
            if store:
                dump["mount_name"] = _slugify_mount_name(store.name)
            else:
                dump["mount_name"] = str(r.memory_store_id)
        resource_dicts.append(dump)

    svc = SessionService(db)
    session = await svc.create_session(
        agent_id=agent.id,
        title=req.title,
        metadata=req.metadata,
        vault_ids=req.vault_ids,
        environment_ref=environment_ref,
        agent_version=agent_version,
        agent_snapshot=agent_snapshot,
    )

    resources = []
    if resource_dicts:
        resources = await svc.attach_memory_stores(session.id, resource_dicts)

    # Provision sandbox at session creation time (per API spec)
    try:
        from app.core.lifespan import get_sandbox_resolver
        resolver = get_sandbox_resolver()
        if resolver:
            agent_env = dict(agent.env or {})
            if getattr(agent, "secret_ref", None):
                from app.services.secret_service import SecretService
                secret_svc = SecretService(db)
                secret = await secret_svc.get_secret_by_name(agent.secret_ref)
                if secret and secret.data:
                    for k, v in secret.data.items():
                        agent_env.setdefault(k, str(v))
                    if "ANTHROPIC_AUTH_TOKEN" in agent_env and "ANTHROPIC_API_KEY" not in agent_env:
                        agent_env["ANTHROPIC_API_KEY"] = agent_env["ANTHROPIC_AUTH_TOKEN"]
            env_ref = environment_ref or agent.environment_ref
            resolved_image = None
            networking = None
            if env_ref:
                from app.services.conductor_environment_service import EnvironmentService
                env_svc = EnvironmentService(db)
                environment = await env_svc.get_environment_by_ref(env_ref)
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
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SessionResponse]:
    svc = SessionService(db)
    if agent_id:
        sessions, has_more = await svc.list_sessions_by_agent(agent_id, limit, after_id)
    else:
        sessions, has_more = await svc.list_sessions(limit, after_id)
    data = [_session_to_response(s) for s in sessions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID = Depends(_parse_session_id), db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    resources = await svc.list_session_memory_stores(session_id)
    return _session_to_response(session, resources=resources)


@router.delete("/{session_id}", status_code=200)
async def delete_session(
    session_id: uuid.UUID = Depends(_parse_session_id), db: AsyncSession = Depends(get_db)
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == "running":
        raise HTTPException(409, "Running session cannot be deleted. Send user.interrupt first.")

    # Emit session.deleted event via broadcaster before deleting
    from app.core.lifespan import (
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
    from app.services.sandbox_service import SandboxService
    sandbox_svc = SandboxService(db)
    sandbox = await sandbox_svc.find_by_session(session_id)
    if sandbox:
        # Send gRPC Shutdown to runner via bridge (not cancel)
        bridge_registry = get_bridge_registry()
        if bridge_registry:
            bridge = await bridge_registry.get(sandbox.id)
            if bridge:
                from app.core.grpc.proto import conductor_pb2
                shutdown_msg = conductor_pb2.OrchestratorMessage(
                    shutdown=conductor_pb2.Shutdown(reason="session deleted")
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
    session_id: uuid.UUID = Depends(_parse_session_id), db: AsyncSession = Depends(get_db)
) -> dict:
    svc = SessionService(db)
    ok = await svc.archive_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
    return {"status": "archived"}


CONTROL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result", "user.interrupt"}
LIVE_INPUT_PREFIX = "__conductor_input_v1__:"


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
    content blocks (matching the Rust conductor spec).  Returns the concatenated
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

    This mirrors the Rust conductor's ``replay_pending_control_inputs`` which
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
) -> dict:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
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

    from app.core.lifespan import get_session_broadcaster, get_bridge_registry

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
                from app.core.lifespan import get_scheduler
                scheduler = get_scheduler()
                if scheduler:
                    from app.services.task_service import ConductorTaskService as TaskService
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as task_db:
                        task_svc = TaskService(task_db)
                        task = await task_svc.create_task(
                            agent_id=session.agent_id,
                            prompt=message_text,
                            chat_session_id=session_id,
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
                    # Push task to global scheduler queue
                    await scheduler.push_to_global(task.id)
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
                        from app.core.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.services.task_service import ConductorTaskService as TaskService
                            from app.core.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
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
                        from app.core.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.services.task_service import ConductorTaskService as TaskService
                            from app.core.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
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
                        from app.core.lifespan import get_scheduler
                        scheduler = get_scheduler()
                        if scheduler:
                            from app.services.task_service import ConductorTaskService as TaskService
                            from app.core.database import AsyncSessionLocal
                            async with AsyncSessionLocal() as task_db:
                                task_svc = TaskService(task_db)
                                task = await task_svc.create_task(
                                    agent_id=session.agent_id,
                                    prompt=resume_prompt,
                                    chat_session_id=session_id,
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
) -> PaginatedResponse[SessionEventResponse]:
    svc = SessionService(db)
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
):
    """SSE endpoint for real-time session event streaming."""
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from app.core.lifespan import get_session_broadcaster
    broadcaster = get_session_broadcaster()

    async def event_generator():
        last_seq = after_seq or 0

        # First, replay existing events after the cursor
        if after_seq is not None:
            from app.core.database import AsyncSessionLocal
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
                    data = json.dumps(data_dict)
                    yield f"id: evt_{ev.id}\ndata: {data}\n\n"

        # Subscribe to live events
        if not broadcaster:
            yield "data: {\"type\": \"error\", \"message\": \"Broadcaster not available\"}\n\n"
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
                    yield f"id: {event_id}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
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
