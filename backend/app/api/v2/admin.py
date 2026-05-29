from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["conductor-admin"])

TUNABLE_FIELDS = {
    "idle_timeout_sec",
    "stopped_max_age_sec",
    "heartbeat_timeout_sec",
    "sandbox_failure_threshold",
    "pool_min_size",
    "pool_max_age_sec",
    "event_batch_max_size",
    "event_batch_max_delay_ms",
}


class RuntimeConfigUpdate(BaseModel):
    idle_timeout_sec: int | None = None
    stopped_max_age_sec: int | None = None
    heartbeat_timeout_sec: int | None = None
    sandbox_failure_threshold: int | None = None
    pool_min_size: int | None = None
    pool_max_age_sec: int | None = None
    event_batch_max_size: int | None = None
    event_batch_max_delay_ms: int | None = None


@router.get("/runtime_config")
async def get_runtime_config_endpoint() -> dict[str, Any]:
    from app.core.lifespan import get_runtime_config

    rc = get_runtime_config()
    if not rc:
        raise HTTPException(503, "RuntimeConfig not initialized")
    return {field: getattr(rc, field) for field in TUNABLE_FIELDS}


@router.post("/runtime_config")
async def update_runtime_config(req: RuntimeConfigUpdate) -> dict[str, Any]:
    from app.core.lifespan import get_runtime_config

    rc = get_runtime_config()
    if not rc:
        raise HTTPException(503, "RuntimeConfig not initialized")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if updates:
        rc.update(**updates)
    return {field: getattr(rc, field) for field in TUNABLE_FIELDS}
