import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.task import CreateTaskRequest, CreateTaskResponse, TaskResponse
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.agent_service import AgentService
from app.conductor.services.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conductor-tasks"])


@router.post("", status_code=202)
async def create_task(
    req: CreateTaskRequest, db: AsyncSession = Depends(get_db)
) -> CreateTaskResponse:
    agent_svc = AgentService(db)
    agent = None
    if req.agent_id:
        agent = await agent_svc.get_agent(req.agent_id)
    elif req.agent_name:
        agent = await agent_svc.get_agent_by_name(req.agent_name)
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Resolve environment_ref: prefer request field, fall back to agent default
    environment_ref = req.environment_ref or getattr(agent, "environment_ref", None)

    # Validate environment_ref if provided
    if environment_ref:
        from app.conductor.services.environment_service import EnvironmentService
        env_svc = EnvironmentService(db)
        env = await env_svc.get_environment_by_ref(environment_ref)
        if not env:
            raise HTTPException(422, f"Environment not found: {environment_ref}")

    # Auto-create a ChatSession for the task if none provided
    chat_session_id = req.chat_session_id
    if not chat_session_id:
        from app.conductor.services.session_service import SessionService
        session_svc = SessionService(db)
        session = await session_svc.create_session(
            agent_id=agent.id,
            title=f"Task: {req.prompt[:80]}",
            environment_ref=environment_ref,
            agent_version=getattr(agent, "version", None),
            agent_snapshot={"name": agent.name, "model": getattr(agent, "model", None)},
        )
        chat_session_id = session.id

    svc = TaskService(db)
    task = await svc.create_task(
        agent_id=agent.id,
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        chat_session_id=chat_session_id,
        timeout_sec=req.timeout_sec,
        max_retries=req.max_retries,
    )

    # Push to scheduler queue
    from app.conductor.lifespan import get_scheduler
    scheduler = get_scheduler()
    if scheduler:
        await scheduler.push_to_global(task.id)

    return CreateTaskResponse(id=task.id, status=task.status)


@router.get("")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    agent_id: Optional[uuid.UUID] = Query(None),
    session_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TaskResponse]:
    svc = TaskService(db)
    tasks, has_more = await svc.list_tasks(
        limit=limit, after_id=after_id, agent_id=agent_id,
        session_id=session_id, status=status,
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
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    svc = TaskService(db)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    svc = TaskService(db)

    # Fetch task first (we need chat_session_id for post-cancel work)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    try:
        task = await svc.cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    # cancel_task returns None only if the task doesn't exist, which we
    # already checked above.
    assert task is not None

    from app.conductor.lifespan import get_bridge_registry, get_redis_coordinator, get_session_broadcaster
    from app.conductor.proto import conductor_pb2

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
                    cancel_msg = conductor_pb2.OrchestratorMessage(
                        cancel=conductor_pb2.CancelTask(reason="Cancelled via API")
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
                        {"action": "cancel", "sandbox_id": str(sandbox_id)},
                    )

    # Transition the linked ChatSession to idle with cancellation stop_reason
    session_id = task.chat_session_id
    if session_id:
        from app.conductor.services.session_service import SessionService
        from app.conductor.models.session import SessionStatus
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
            await broadcaster.broadcast(
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

    return TaskResponse.model_validate(task)


@router.websocket("/{task_id}/stream")
async def task_stream(websocket: WebSocket, task_id: uuid.UUID):
    """WebSocket endpoint for real-time task output streaming."""
    from app.conductor.lifespan import get_bridge_registry

    registry = get_bridge_registry()
    if not registry:
        await websocket.close(code=1011, reason="Conductor kernel not running")
        return

    bridge = registry.get_by_task(task_id)
    if not bridge:
        # Task might not be running yet — accept and send current status
        await websocket.accept()
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if not task:
                await websocket.send_json({"type": "error", "error": "Task not found"})
                await websocket.close()
                return
            await websocket.send_json({"type": "status", "status": task.status})
            from app.conductor.models.task import TaskStatus
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
            from app.conductor.lifespan import get_redis_coordinator
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
    channel = f"conductor:events:{task_id}"
    pubsub = coordinator._redis.pubsub()
    try:
        await pubsub.subscribe(channel)

        # After subscribing, check if task already reached a terminal state.
        # Any completion event published concurrently will be caught by the
        # subscription, so there is no missed-message window.
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            svc = TaskService(db)
            task = await svc.get_task(task_id)
            if task:
                from app.conductor.models.task import TaskStatus
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
