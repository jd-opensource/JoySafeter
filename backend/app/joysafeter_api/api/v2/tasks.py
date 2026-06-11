import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.schemas.task import JoySafeterCreateTaskRequest as CreateTaskRequest, JoySafeterCreateTaskResponse as CreateTaskResponse, JoySafeterTaskResponse as TaskResponse
from app.joysafeter_domain.schemas.common import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_api.services import JoySafeterAgentService as AgentService
from app.joysafeter_api.services import JoySafeterTaskService as TaskService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-tasks"])


@router.post("", status_code=202)
async def create_task(
    req: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CreateTaskResponse:
    agent_svc = AgentService(db)
    agent = None
    if req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id, project_id=auth_ctx.project_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name, project_id=auth_ctx.project_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Resolve environment_ref: prefer request field, fall back to agent default
    environment_ref = req.environment_ref or getattr(agent, "environment_ref", None)

    # Validate environment_ref if provided
    if environment_ref:
        from app.joysafeter_api.services import JoySafeterEnvironmentService as EnvironmentService
        env_svc = EnvironmentService(db)
        env = await env_svc.get_environment_by_ref(environment_ref, project_id=auth_ctx.project_id)
        if not env:
            raise HTTPException(422, f"Environment not found: {environment_ref}")

    from app.joysafeter_orchestrator.lifespan import get_scheduler
    scheduler = get_scheduler()
    if not scheduler:
        raise HTTPException(503, "JoySafeter scheduler is not running")

    # Auto-create a ChatSession for the task if none provided
    chat_session_id = req.chat_session_id
    if not chat_session_id:
        from app.joysafeter_api.services import SessionService
        session_svc = SessionService(db)
        session = await session_svc.create_session(
            agent_id=agent.id,
            title=f"Task: {req.prompt[:80]}",
            environment_ref=environment_ref,
            agent_version=getattr(agent, "version", None),
            agent_snapshot={"name": agent.name, "model": getattr(agent, "model", None)},
            project_id=auth_ctx.project_id,
        )
        chat_session_id = session.id
    else:
        from app.joysafeter_api.services import SessionService
        session_svc = SessionService(db)
        session = await session_svc.get_session(chat_session_id)
        if not session or session.project_id != auth_ctx.project_id:
            raise HTTPException(404, "Session not found")
        if session.agent_id != agent.id:
            raise HTTPException(400, "Session does not belong to the selected agent")

    svc = TaskService(db)
    task = await svc.create_task(
        agent_id=agent.id,
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        chat_session_id=chat_session_id,
        timeout_sec=req.timeout_sec,
        max_retries=req.max_retries,
        project_id=auth_ctx.project_id,
    )

    try:
        await scheduler.push_to_global(task.id)
    except Exception as exc:
        from app.joysafeter_domain.models.task import JoySafeterTaskStatus
        await svc.update_task_error(
            task.id,
            f"Failed to enqueue task: {exc}",
            JoySafeterTaskStatus.FAILED,
        )
        raise HTTPException(503, "Failed to enqueue task")

    return CreateTaskResponse(id=task.id, status=task.status)


@router.get("")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    agent_id: Optional[uuid.UUID] = Query(None),
    session_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[TaskResponse]:
    svc = TaskService(db)
    tasks, has_more = await svc.list_tasks(
        limit=limit, after_id=after_id, agent_id=agent_id,
        session_id=session_id, status=status, project_id=auth_ctx.project_id,
    )
    data = [TaskResponse.model_validate(t) for t in tasks]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> TaskResponse:
    svc = TaskService(db)
    task = await svc.get_task(task_id, project_id=auth_ctx.project_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = TaskService(db)

    # Fetch task first (we need chat_session_id for post-cancel work)
    task = await svc.get_task(task_id, project_id=auth_ctx.project_id)
    if not task:
        raise HTTPException(404, "Task not found")

    try:
        task = await svc.cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    # cancel_task returns None only if the task doesn't exist, which we
    # already checked above.
    assert task is not None

    from app.joysafeter_orchestrator.lifespan import get_bridge_registry, get_redis_coordinator, get_session_broadcaster
    from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2

    # Send gRPC CancelTask to the sandbox bridge if the task is running locally
    registry = get_bridge_registry()
    grpc_cancel_sent = False
    if registry:
        bridge = registry.get_by_task(task_id)
        if bridge:
            bridge.request_cancel()
            # Send CancelTask message over gRPC so the runner actually stops
            if bridge.runner_stream:
                try:
                    cancel_msg = joysafeter_pb2.OrchestratorMessage(
                        cancel=joysafeter_pb2.CancelTask(reason="Cancelled via API")
                    )
                    await bridge.runner_stream.write(cancel_msg)
                    grpc_cancel_sent = True
                except Exception:
                    logger.warning("Failed to send gRPC CancelTask for task %s", task_id)

    # Cross-instance: if the task wasn't found on this instance, route via Redis
    if not grpc_cancel_sent:
        coordinator = get_redis_coordinator()
        if coordinator:
            sandbox_id = await coordinator.get_task_sandbox(task_id)
            if sandbox_id:
                owner = await coordinator.get_sandbox_owner(sandbox_id)
                if owner:
                    # Decode bytes from Redis if needed
                    if isinstance(owner, bytes):
                        owner = owner.decode()
                    await coordinator.send_instance_command(
                        owner,
                        {"type": "cancel", "sandbox_id": str(sandbox_id)},
                    )

    # Transition the linked ChatSession to idle with cancellation stop_reason
    session_id = task.chat_session_id
    if session_id:
        from app.joysafeter_api.services import SessionService
        from app.joysafeter_domain.models.session import SessionStatus
        session_svc = SessionService(db)
        stop_reason = {"type": "cancelled"}
        try:
            await session_svc.update_session_status(
                session_id, SessionStatus.IDLE.value, stop_reason=stop_reason,
            )
        except Exception:
            # Session may already be idle or terminated -- ignore transition errors
            pass

        # Emit SSE event so connected clients learn about the cancellation
        broadcaster = get_session_broadcaster()
        if broadcaster:
            await broadcaster.send(
                session_id,
                {"type": "session.status_idle", "stop_reason": stop_reason},
            )

    # Publish cancellation over Redis pub/sub for cross-instance WebSocket streams
    coordinator = get_redis_coordinator()
    if coordinator:
        await coordinator.publish_event(
            task_id,
            json.dumps({"type": "complete", "output": "", "error": "Cancelled via API", "status": "cancelled"}),
        )

    return {"id": str(task_id), "status": "cancelled"}


@router.websocket("/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: uuid.UUID):
    """WebSocket endpoint for real-time task output streaming."""
    from app.joysafeter_orchestrator.lifespan import get_bridge_registry
    from app.joysafeter_shared.common.cookie_auth import extract_token_from_cookies
    from app.joysafeter_shared.security import decode_token
    from app.joysafeter_domain.models.auth import AuthUser
    from app.joysafeter_domain.models.organization import Member
    from app.joysafeter_domain.models.project import Project
    from sqlalchemy import select

    token = None
    try:
        token = extract_token_from_cookies(websocket.cookies)
    except Exception:
        token = None
    token = token or websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if not payload or payload.type != "access" or not payload.project_id or not payload.org_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    from app.joysafeter_shared.database import AsyncSessionLocal
    async with AsyncSessionLocal() as auth_db:
        user_result = await auth_db.execute(select(AuthUser).where(AuthUser.id == str(payload.sub)))
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=4001, reason="Authentication required")
            return

        member_result = await auth_db.execute(
            select(Member).where(
                Member.user_id == str(payload.sub),
                Member.organization_id == str(payload.org_id),
            ).limit(1)
        )
        if not member_result.scalar_one_or_none():
            await websocket.close(code=4003, reason="Project access denied")
            return

        project_result = await auth_db.execute(
            select(Project).where(
                Project.id == str(payload.project_id),
                Project.org_id == str(payload.org_id),
            ).limit(1)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            await websocket.close(code=4003, reason="Project access denied")
            return

        auth_svc = TaskService(auth_db)
        auth_task = await auth_svc.get_task(task_id, project_id=payload.project_id)
        if not auth_task:
            await websocket.close(code=4004, reason="Task not found")
            return

    registry = get_bridge_registry()
    if not registry:
        await websocket.close(code=1011, reason="JoySafeter kernel not running")
        return

    bridge = registry.get_by_task(task_id)
    if not bridge:
        # Task might not be running yet — accept and send current status
        await websocket.accept()
        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id, project_id=payload.project_id)
            if not task:
                await websocket.send_json({"type": "error", "error": "Task not found"})
                await websocket.close()
                return
            await websocket.send_json({"type": "status", "status": task.status})
            from app.joysafeter_domain.models.task import JoySafeterTaskStatus as TaskStatus
            if TaskStatus(task.status).is_terminal():
                await websocket.send_json({
                    "type": "complete",
                    "output": task.output,
                    "error": task.error,
                })
                await websocket.close()
                return

        # Wait for bridge to appear (task being scheduled)
        for _ in range(60):
            await asyncio.sleep(1)
            bridge = registry.get_by_task(task_id)
            if bridge:
                break

        if not bridge:
            # Cross-instance: try Redis pub/sub for task events
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator
            coordinator = get_redis_coordinator()
            if coordinator:
                await _stream_via_redis(websocket, task_id, coordinator)
            else:
                await websocket.send_json({"type": "error", "error": "Task not scheduled"})
                await websocket.close()
            return
    else:
        await websocket.accept()

    # Subscribe to task events (local bridge)
    q = bridge.subscribe(task_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json({"type": msg.type, **msg.payload})
                if msg.type == "complete":
                    break
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                break
    finally:
        bridge.unsubscribe(task_id, q)
        try:
            await websocket.close()
        except Exception:
            pass


async def _stream_via_redis(websocket: WebSocket, task_id: uuid.UUID, coordinator):
    """Stream task events via Redis pub/sub (cross-instance fallback).

    Subscribes to the Redis channel first, then checks the DB for terminal
    state to avoid missing a completion event between the DB check in the
    caller and the subscribe call here.
    """
    channel = f"joysafeter:events:{task_id}"
    pubsub = coordinator._redis.pubsub()
    try:
        await pubsub.subscribe(channel)

        # After subscribing, check if task already reached a terminal state.
        # Any completion event published concurrently will be caught by the
        # subscription, so there is no missed-message window.
        from app.joysafeter_shared.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if task:
                from app.joysafeter_domain.models.task import JoySafeterTaskStatus as TaskStatus
                if TaskStatus(task.status).is_terminal():
                    await websocket.send_json({
                        "type": "complete",
                        "output": task.output,
                        "error": task.error,
                        "status": task.status,
                    })
                    return

        while True:
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=30
                )
            except asyncio.CancelledError:
                break

            if msg and msg["type"] == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    event = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                await websocket.send_json(event)
                if event.get("type") == "complete":
                    break
            else:
                # No message within timeout -- send keepalive ping
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
