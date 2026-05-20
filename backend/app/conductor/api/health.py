import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conductor-health"])


@router.get("")
@router.get("/ready")
async def health_ready():
    checks: dict[str, str] = {}
    healthy = True

    # Probe PostgreSQL
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = "up"
    except Exception as e:
        logger.warning("Health check: postgres down: %s", e)
        checks["postgres"] = "down"
        healthy = False

    # Probe Redis
    try:
        from app.core.redis import RedisClient

        client = RedisClient.get_client()
        if client:
            await client.ping()
            checks["redis"] = "up"
        else:
            checks["redis"] = "not_configured"
    except Exception as e:
        logger.warning("Health check: redis down: %s", e)
        checks["redis"] = "down"
        healthy = False

    status = "ok" if healthy else "degraded"
    code = 200 if healthy else 503
    return JSONResponse(
        status_code=code,
        content={"status": status, "checks": checks},
    )


@router.get("/live")
async def health_live() -> dict:
    return {"status": "ok"}
