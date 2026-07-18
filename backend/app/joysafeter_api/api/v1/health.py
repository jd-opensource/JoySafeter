import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-health"])


def _serialize_health_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


async def collect_cluster_membership_health(db: Any) -> dict[str, Any]:
    """Return API-visible health for the Rust orchestrator membership mirror."""

    result = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE role = 'orchestrator' AND expires_at > NOW()
                ) AS live_orchestrators,
                COUNT(*) FILTER (
                    WHERE role = 'orchestrator' AND expires_at <= NOW()
                ) AS stale_orchestrators,
                MAX(heartbeat_at) FILTER (
                    WHERE role = 'orchestrator'
                ) AS newest_heartbeat_at,
                MAX(expires_at) FILTER (
                    WHERE role = 'orchestrator'
                ) AS newest_expires_at
            FROM joysafeter_cluster_members
            """
        )
    )
    row = result.mappings().one()
    live_orchestrators = int(row["live_orchestrators"] or 0)
    stale_orchestrators = int(row["stale_orchestrators"] or 0)

    details: dict[str, Any] = {
        "status": "ok" if live_orchestrators > 0 else "degraded",
        "live_orchestrators": live_orchestrators,
        "stale_orchestrators": stale_orchestrators,
        "newest_heartbeat_at": _serialize_health_value(row["newest_heartbeat_at"]),
        "newest_expires_at": _serialize_health_value(row["newest_expires_at"]),
    }
    if live_orchestrators == 0:
        details["reason"] = "no_live_orchestrator"
    return details


@router.get("")
@router.get("/ready")
async def health_ready():
    postgres_ok = True
    redis_ok = True
    cluster_membership: dict[str, Any] = {
        "status": "unknown",
        "reason": "postgres_not_checked",
    }

    # Probe PostgreSQL — equivalent to Rust PgStore.health_check()
    try:
        from app.joysafeter_shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            try:
                cluster_membership = await collect_cluster_membership_health(db)
            except Exception as e:
                log_boundary_failure(
                    logger,
                    boundary="health_api",
                    code="HEALTH_CLUSTER_MEMBERSHIP_CHECK_FAILED",
                    message="Health check cluster membership probe failed",
                    operation="check_cluster_membership",
                    error=e,
                    retryable=True,
                    user_action="check_status",
                )
                cluster_membership = {
                    "status": "degraded",
                    "reason": "cluster_membership_unavailable",
                }
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
        cluster_membership = {
            "status": "unknown",
            "reason": "postgres_unavailable",
        }

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

    cluster_ok = cluster_membership.get("status") == "ok"
    healthy = postgres_ok and redis_ok and cluster_ok
    status = "ok" if healthy else "degraded"
    code = 200 if postgres_ok else 503
    return JSONResponse(
        status_code=code,
        content={
            "status": status,
            "checks": {
                "postgres": "up" if postgres_ok else "down",
                "redis": "up" if redis_ok else "down",
                # Expose only the cluster readiness status, never the fleet
                # topology (live/stale counts, heartbeat/expiry) or raw probe
                # error text — this endpoint is unauthenticated.
                "cluster_membership": cluster_membership.get("status", "unknown"),
            },
        },
    )


@router.get("/live")
async def health_live() -> dict:
    return {"status": "ok"}
