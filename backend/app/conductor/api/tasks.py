import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.task import CreateTaskRequest, CreateTaskResponse, TaskResponse
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.agent_service import AgentService
from app.conductor.services.task_service import TaskService

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

    svc = TaskService(db)
    task = await svc.create_task(
        agent_id=agent.id,
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        chat_session_id=req.chat_session_id,
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
    try:
        task = await svc.cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not task:
        raise HTTPException(404, "Task not found")

    # Signal sandbox bridge to cancel if running
    from app.conductor.lifespan import get_bridge_registry
    registry = get_bridge_registry()
    if registry:
        bridge = registry.get_by_task(task_id)
        if bridge:
            bridge.request_cancel()

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
    """Stream task events via Redis pub/sub (cross-instance fallback)."""
    channel = f"conductor:events:{task_id}"
    pubsub = coordinator._redis.pubsub()
    try:
        await pubsub.subscribe(channel)
        while True:
            msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True, timeout=30), timeout=35)
            if msg and msg["type"] == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                event = json.loads(data)
                await websocket.send_json(event)
                if event.get("type") == "complete":
                    break
            else:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        try:
            await websocket.close()
        except Exception:
            pass
