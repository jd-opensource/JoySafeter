"""OME trigger route — manually invoke a registered strategy."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.everos.core.errors import NotFoundError
from app.everos.core.observability.logging import get_logger
from app.everos.infra.ome.events import ScopedManualTick
from app.everos.infra.ome.records import RunRecord

router = APIRouter(prefix="/api/v1/ome", tags=["ome"])

logger = get_logger(__name__)


class TriggerRequest(BaseModel):
    """Request body for ``POST /api/v1/ome/trigger``."""

    name: str
    timeout: float = 120.0
    force: bool = False
    wait: bool = True
    scope_mode: str | None = None
    app_id: str | None = None
    project_id: str | None = None
    active_agent_ids: list[str] = Field(default_factory=list)
    active_session_ids: list[str] = Field(default_factory=list)


class TriggerResponse(BaseModel):
    """Response body for ``POST /api/v1/ome/trigger``."""

    status: str
    name: str
    run_id: str | None = None
    run_ids: list[str] = Field(default_factory=list)


@router.post("/trigger", response_model=TriggerResponse)
async def trigger(req: TriggerRequest) -> TriggerResponse:
    """Manually trigger a registered OME strategy."""
    # Deferred: avoid importing heavy OME engine at module level.
    from app.everos.service.memorize import _get_engine  # noqa: SLF001

    engine = _get_engine()
    event = _scoped_manual_event(req)
    try:
        if event is None:
            run_ids = await engine.trigger_manual(req.name, force=req.force)
        else:
            run_ids = await engine.trigger_manual(req.name, event=event, force=req.force)
    except KeyError:
        raise NotFoundError(f"strategy '{req.name}' not found") from None
    logger.info("ome_trigger_manual", strategy=req.name, wait=req.wait, run_ids=run_ids)
    if not req.wait:
        return TriggerResponse(
            status="started" if run_ids else "skipped",
            name=req.name,
            run_id=run_ids[0] if run_ids else None,
            run_ids=run_ids,
        )
    idle = await engine.wait_idle(timeout=req.timeout)
    if not idle:
        logger.warning("ome_trigger_timeout", strategy=req.name, timeout=req.timeout)
        return TriggerResponse(
            status="timeout",
            name=req.name,
            run_id=run_ids[0] if run_ids else None,
            run_ids=run_ids,
        )
    return TriggerResponse(
        status="ok",
        name=req.name,
        run_id=run_ids[0] if run_ids else None,
        run_ids=run_ids,
    )


def _scoped_manual_event(req: TriggerRequest) -> ScopedManualTick | None:
    """Build a scoped manual event when the caller supplies lifecycle scope."""
    if (
        req.scope_mode is None
        and req.app_id is None
        and req.project_id is None
        and not req.active_agent_ids
        and not req.active_session_ids
    ):
        return None
    return ScopedManualTick(
        strategy_name=req.name,
        scope_mode=req.scope_mode or "active_only",
        app_id=req.app_id or "default",
        project_id=req.project_id or "default",
        active_agent_ids=tuple(sorted(req.active_agent_ids)),
        active_session_ids=tuple(sorted(req.active_session_ids)),
    )


@router.get("/runs/{run_id}", response_model=RunRecord)
async def get_run_status(run_id: str) -> RunRecord:
    """Return the current persisted status for an OME run."""
    from app.everos.service.memorize import _get_engine  # noqa: SLF001

    engine = _get_engine()
    record = await engine.get_run_status(run_id)
    if record is None:
        raise NotFoundError(f"run '{run_id}' not found")
    return record
