import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conductor-health"])


@router.get("")
@router.get("/ready")
async def health_ready():
    postgres_ok = True
    redis_ok = True

    # Probe PostgreSQL — equivalent to Rust PgStore.health_check()
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("Health check: postgres down: %s", e)
        postgres_ok = False

    # Probe Redis via RedisCoordinator.is_healthy() if available
    try:
        from app.conductor.lifespan import get_redis_coordinator

        coordinator = get_redis_coordinator()
        if coordinator:
            redis_ok = await coordinator.is_healthy()
        else:
            # No coordinator — fall back to direct ping
            from app.core.redis import RedisClient

            client = RedisClient.get_client()
            if client:
                await client.ping()
            else:
                # Redis not configured — treat as healthy (optional dependency)
                redis_ok = True
    except Exception as e:
        logger.warning("Health check: redis down: %s", e)
        redis_ok = False

    healthy = postgres_ok and redis_ok
    status = "ok" if healthy else "degraded"
    code = 200 if postgres_ok else 503
    return JSONResponse(
        status_code=code,
        content={
            "status": status,
            "checks": {
                "postgres": "up" if postgres_ok else "down",
                "redis": "up" if redis_ok else "down",
            },
        },
    )


@router.get("/live")
async def health_live() -> dict:
    return {"status": "ok"}


@router.get("/diagnostics")
async def health_diagnostics() -> dict:
    """Debug endpoint: expose scheduler/queue/background-task state."""
    import asyncio

    from app.conductor.lifespan import (
        get_scheduler,
        get_bridge_registry,
        get_sandbox_resolver,
        _background_tasks,
    )

    scheduler = get_scheduler()
    sched_info: dict = {"initialized": scheduler is not None}
    if scheduler:
        sched_info["running"] = scheduler._running
        sched_info["execution_semaphore_value"] = scheduler._semaphore._value
        sched_info["scheduling_semaphore_value"] = scheduler._scheduling_semaphore._value
        sched_info["inflight_tasks_count"] = len(scheduler._inflight_tasks)
        queue = scheduler._queue
        sched_info["queue_has_redis_coord"] = queue._redis_coord is not None
        sched_info["local_global_queue_size"] = len(queue._global_queue._inner)
        sched_info["sandbox_queues_count"] = len(queue._sandbox_queues)
        sandbox_queue_sizes = {
            str(k): len(v._inner) for k, v in queue._sandbox_queues.items()
        }
        sched_info["sandbox_queue_sizes"] = sandbox_queue_sizes

    bg_tasks_info = []
    for t in _background_tasks:
        bg_tasks_info.append({
            "name": t.get_name(),
            "done": t.done(),
            "cancelled": t.cancelled(),
            "exception": str(t.exception()) if t.done() and not t.cancelled() else None,
        })

    bridge_registry = get_bridge_registry()
    bridge_info = {"count": bridge_registry.count() if bridge_registry else 0}

    return {
        "scheduler": sched_info,
        "background_tasks": bg_tasks_info,
        "bridges": bridge_info,
    }
