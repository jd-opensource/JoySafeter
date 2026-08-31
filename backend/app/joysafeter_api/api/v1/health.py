import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-health"])


@router.get("")
@router.get("/ready")
async def health_ready():
    postgres_ok = True
    redis_ok = True

    # Readiness owns only dependencies used directly by the API process.
    # Orchestrator health is checked through its own transport/metrics surface
    # by deployment probes; PostgreSQL is not an ephemeral membership mirror.
    try:
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        log_boundary_failure(
            logger,
            boundary="health_api",
            code="HEALTH_POSTGRES_CHECK_FAILED",
            message="Health check postgres probe failed",
            operation="check_postgres",
            error=e,
            retryable=True,
            user_action="check_status",
        )
        postgres_ok = False

    # Probe Redis directly from the API process. Runtime coordination is owned
    # by the Rust orchestrator and should not be reached through Python globals.
    try:
        from app.joysafeter_shared.cache.redis import RedisClient

        client = RedisClient.get_client()
        if client:
            await client.ping()
        else:
            # Redis not configured — treat as healthy (optional dependency)
            redis_ok = True
    except Exception as e:
        log_boundary_failure(
            logger,
            boundary="health_api",
            code="HEALTH_REDIS_CHECK_FAILED",
            message="Health check Redis probe failed",
            operation="check_redis",
            error=e,
            retryable=True,
            user_action="check_status",
        )
        redis_ok = False

    healthy = postgres_ok and redis_ok
    status = "ok" if healthy else "degraded"
    code = 200 if healthy else 503
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
