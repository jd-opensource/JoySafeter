import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.session import (
    CreateSessionRequest,
    EventListParams,
    SendEventRequest,
    SingleEventRequest,
    SessionEventResponse,
    SessionResourceResponse,
    SessionResponse,
    SessionAgent,
    SessionUsage,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.agent_service import AgentService
from app.conductor.services.session_service import SessionService

router = APIRouter(tags=["conductor-sessions"])


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
    agent_svc = AgentService(db)
    agent = None
    if req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name)
    if not agent:
        raise HTTPException(404, "Agent not found")

    svc = SessionService(db)
    session = await svc.create_session(
        agent_id=agent.id,
        title=req.title,
        metadata=req.metadata,
        vault_ids=req.vault_ids,
        environment_ref=req.environment_ref,
        agent_version=agent.version,
        agent_snapshot={"name": agent.name, "model": agent.model},
    )

    resources = []
    if req.resources:
        resources = await svc.attach_memory_stores(
            session.id,
            [r.model_dump() for r in req.resources],
        )

    # Provision sandbox at session creation time (per API spec)
    try:
        from app.conductor.lifespan import get_sandbox_resolver
        resolver = get_sandbox_resolver()
        if resolver:
            agent_env = dict(agent.env or {})
            if getattr(agent, "secret_ref", None):
                from app.conductor.services.secret_service import SecretService
                secret_svc = SecretService(db)
                secret = await secret_svc.get_secret_by_name(agent.secret_ref)
                if secret and secret.data:
                    for k, v in secret.data.items():
                        agent_env.setdefault(k, str(v))
                    if "ANTHROPIC_AUTH_TOKEN" in agent_env and "ANTHROPIC_API_KEY" not in agent_env:
                        agent_env["ANTHROPIC_API_KEY"] = agent_env["ANTHROPIC_AUTH_TOKEN"]
            env_ref = req.environment_ref or agent.environment_ref
            resolved_image = None
            networking = None
            if env_ref:
                from app.conductor.services.environment_service import EnvironmentService
                env_svc = EnvironmentService(db)
                environment = await env_svc.get_environment_by_ref(env_ref)
                if environment:
                    resolved_image = getattr(environment, "image_tag", None)
                    config = environment.config or {}
                    net_cfg = config.get("networking")
                    if net_cfg and isinstance(net_cfg, dict):
                        networking = net_cfg
            resolved = await resolver.resolve(
                session.id, agent_env, image=resolved_image, networking=networking
            )
            if resolved.get("sandbox_id"):
                await svc.update_session_sandbox(session.id, resolved["sandbox_id"])
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
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
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    resources = await svc.list_session_memory_stores(session_id)
    return _session_to_response(session, resources=resources)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    svc = SessionService(db)
    ok = await svc.delete_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")


@router.post("/{session_id}/archive")
async def archive_session(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = SessionService(db)
    ok = await svc.archive_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
    return {"status": "archived"}


CONTROL_EVENT_TYPES = {"user.tool_confirmation", "user.custom_tool_result", "user.interrupt"}
LIVE_INPUT_PREFIX = "__conductor_input_v1__:"


def _encode_live_input(event: SingleEventRequest) -> Optional[str]:
    event_type = event.type
    if event_type == "user.tool_confirmation":
        call_id = event.resolved_tool_use_id()
        if not call_id:
            return None
        payload = {
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
        return event.content
    return None


@router.post("/{session_id}/events", status_code=201)
async def send_event(
    session_id: uuid.UUID,
    req: SendEventRequest,
    db: AsyncSession = Depends(get_db),
) -> list[SessionEventResponse]:
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.archived_at:
        raise HTTPException(400, "Session is archived")

    single_events = req.to_single_events()
    if not single_events:
        raise HTTPException(400, "No events provided")

    from app.conductor.lifespan import get_session_broadcaster, get_bridge_registry

    broadcaster = get_session_broadcaster()
    bridge_registry = get_bridge_registry()

    results = []
    for single in single_events:
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

        if broadcaster:
            await broadcaster.broadcast(session_id, {
                "id": str(event.id),
                "type": event.event_type,
                "payload": event.payload,
                "seq": event.seq,
            })

        injected = False
        if single.type in CONTROL_EVENT_TYPES and bridge_registry and session.last_sandbox_id:
            bridge = await bridge_registry.get(session.last_sandbox_id)
            if bridge:
                resolved_event = single
                raw_id = single.resolved_tool_use_id()
                if raw_id and raw_id in bridge.pending_control_request_ids:
                    actual_call_id = bridge.pending_control_request_ids.pop(raw_id)
                    resolved_event = single.model_copy(update={"tool_use_id": actual_call_id})
                live_input = _encode_live_input(resolved_event)
                if live_input:
                    try:
                        await bridge.send_control_input(live_input)
                        injected = True
                        bridge._requires_action_pending = False
                        await svc.mark_event_processed(event.id)
                        await svc.update_session_status(session_id, "running")
                    except Exception:
                        pass

        if not injected and single.type in CONTROL_EVENT_TYPES:
            resume_prompt = _build_resume_prompt(single, str(event.id))
            if resume_prompt and session.status != "running":
                try:
                    from app.conductor.lifespan import get_scheduler
                    scheduler = get_scheduler()
                    if scheduler:
                        from app.conductor.services.task_service import TaskService
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
                    pass

        if single.type == "user.message" and single.content and session.status != "running":
            try:
                from app.conductor.lifespan import get_scheduler
                scheduler = get_scheduler()
                if scheduler:
                    from app.conductor.services.task_service import TaskService
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as task_db:
                        task_svc = TaskService(task_db)
                        task = await task_svc.create_task(
                            agent_id=session.agent_id,
                            prompt=single.content,
                            chat_session_id=session_id,
                        )
                        await scheduler.push_to_global(task.id)
            except Exception:
                pass

        results.append(SessionEventResponse.model_validate(event))

    return results


@router.get("/{session_id}/events")
async def list_events(
    session_id: uuid.UUID,
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
    session_id: uuid.UUID,
    request: Request,
    after_seq: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for real-time session event streaming."""
    svc = SessionService(db)
    session = await svc.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from app.conductor.lifespan import get_session_broadcaster
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
                    data = json.dumps({
                        "id": f"evt_{ev.id}",
                        "type": ev.event_type,
                        "payload": ev.payload,
                        "seq": ev.seq,
                    })
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
