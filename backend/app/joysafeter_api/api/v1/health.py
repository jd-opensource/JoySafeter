import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-health"])


@router.get("")
@router.get("/ready")
async def health_ready():
    postgres_ok = True
    redis_ok = True

    # Probe PostgreSQL — equivalent to Rust PgStore.health_check()
    try:
        from sqlalchemy import text

        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("Health check: postgres down: %s", e)
        postgres_ok = False

    # Probe Redis via RedisCoordinator.is_healthy() if available
    try:
        from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

        coordinator = get_redis_coordinator()
        if coordinator:
            redis_ok = await coordinator.is_healthy()
        else:
            # No coordinator — fall back to direct ping
            from app.joysafeter_shared.cache.redis import RedisClient

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
