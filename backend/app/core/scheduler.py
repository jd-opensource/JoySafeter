"""
Background scheduler loops for mission auto-dispatch and stale execution reaping.

Registered in app lifespan (main.py). Each function is an infinite async loop
following the same pattern as _container_reaper.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from loguru import logger

from app.core.agent.cli_backends.session_registry import session_registry
from app.core.database import AsyncSessionLocal
# TODO: Phase 4/5 cleanup - MissionExecutionStatus removed; migrate to string literals
# from app.models.execution import MissionExecutionStatus
MissionExecutionStatus = type("MissionExecutionStatus", (), {
    "QUEUED": "queued", "DISPATCHED": "dispatched", "RUNNING": "running",
    "INTERRUPT_WAIT": "interrupt_wait", "APPROVAL_WAIT": "approval_wait",
    "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"
})()
from app.repositories.execution import ExecutionRepository
from app.services.execution_lifecycle_service import ExecutionLifecycleService
from app.services.execution_service import ExecutionService
from app.utils.datetime import utc_now

_DISPATCH_INTERVAL = 30
_REAPER_INTERVAL = 30

_STALE_THRESHOLDS: list[tuple[tuple[MissionExecutionStatus, ...], timedelta]] = [
    (
        (MissionExecutionStatus.QUEUED, MissionExecutionStatus.DISPATCHED),
        timedelta(minutes=5),
    ),
    (
        (MissionExecutionStatus.RUNNING,),
        timedelta(minutes=10),
    ),
    (
        (MissionExecutionStatus.APPROVAL_WAIT,),
        timedelta(minutes=60),
    ),
]


async def mission_dispatcher_loop() -> None:
    """Every 30s, find TODO missions with agent assignees and dispatch them."""
    while True:
        await asyncio.sleep(_DISPATCH_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                lifecycle = ExecutionLifecycleService(db)
                count = await lifecycle.dispatch_all_ready_missions()
                if count:
                    logger.info(f"Scheduler: auto-dispatched {count} missions")
        except Exception as exc:
            logger.warning(f"Mission dispatcher error: {exc}")


async def execution_reaper_loop() -> None:
    """Every 30s, find stale executions and mark them failed."""
    while True:
        await asyncio.sleep(_REAPER_INTERVAL)
        try:
            reaped = await _reap_stale_executions()
            if reaped:
                logger.info(f"Scheduler: reaped {reaped} stale executions")
        except Exception as exc:
            logger.warning(f"Execution reaper error: {exc}")


async def recover_stale_on_startup() -> None:
    """One-shot: catch executions that went stale during downtime."""
    try:
        reaped = await _reap_stale_executions()
        if reaped:
            logger.info(f"Startup recovery: reaped {reaped} stale executions")
        else:
            logger.info("Startup recovery: no stale executions found")
    except Exception as exc:
        logger.warning(f"Startup stale execution recovery failed: {exc}")


async def _reap_stale_executions() -> int:
    """Shared logic for reaper loop and startup recovery."""
    now = utc_now()
    total = 0

    async with AsyncSessionLocal() as db:
        exec_repo = ExecutionRepository(db)
        exec_svc = ExecutionService(db)
        lifecycle = ExecutionLifecycleService(db)

        for statuses, threshold in _STALE_THRESHOLDS:
            stale = await exec_repo.list_recoverable_stale(
                statuses=statuses,
                stale_before=now - threshold,
            )
            for execution in stale:
                try:
                    session = session_registry.get(execution.id)
                    if session:
                        await session.cancel()

                    await exec_svc.mark_status(
                        execution_id=execution.id,
                        status=MissionExecutionStatus.FAILED,
                        error_code="stale_reaped",
                        error_message=f"No heartbeat for {int(threshold.total_seconds() // 60)}+ minutes",
                    )

                    if execution.mission_id:
                        await lifecycle._finalize_mission(execution.id, MissionExecutionStatus.FAILED)

                    total += 1
                    logger.info(
                        f"Reaped stale execution {execution.id} "
                        f"(status={execution.status.value}, age={now - (execution.last_heartbeat_at or execution.updated_at)})"
                    )
                except Exception as exc:
                    logger.warning(f"Failed to reap execution {execution.id}: {exc}")

    return total
