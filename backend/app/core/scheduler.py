"""
Background scheduler loops for task auto-dispatch and stale execution reaping.

Registered in app lifespan (main.py). Each function is an infinite async loop
following the same pattern as _container_reaper.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from loguru import logger

from app.core.database import AsyncSessionLocal

_DISPATCH_INTERVAL = 30
_REAPER_INTERVAL = 30

_STALE_THRESHOLDS: list[tuple[tuple[str, ...], timedelta]] = [
    (
        ("pending", "dispatched"),
        timedelta(minutes=5),
    ),
    (
        ("running",),
        timedelta(minutes=10),
    ),
    (
        ("approval_wait",),
        timedelta(minutes=60),
    ),
]


async def task_dispatcher_loop() -> None:
    """Every 30s, find BACKLOG tasks with agent assignees and dispatch them."""
    while True:
        await asyncio.sleep(_DISPATCH_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select

                from app.models.task import Task

                # Find backlog tasks with assigned agents
                tasks = (
                    (
                        await db.execute(
                            select(Task).where(
                                Task.status == "backlog",
                                Task.agent_id.isnot(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                count = 0
                for task in tasks:
                    try:
                        from app.services.dispatch_service import DispatchService

                        dispatch = DispatchService(db)
                        await dispatch.dispatch_task(task.id, task.creator_id)
                        count += 1
                    except Exception as task_exc:
                        logger.warning(f"Auto-dispatch failed for task {task.id}: {task_exc}")

                if count:
                    logger.info(f"Scheduler: auto-dispatched {count} tasks")
        except Exception as exc:
            logger.warning(f"Task dispatcher error: {exc}")


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
        try:
            from app.core.observation.otel.provider import get_broadcast_processor, get_persistence_processor

            get_persistence_processor().reap_stale()
            get_broadcast_processor().reap_stale()
        except Exception as exc:
            logger.debug(f"Observation bucket reap failed: {exc}")
        try:
            await _reap_orphan_traces()
        except Exception as exc:
            logger.debug(f"Orphan trace reap failed: {exc}")


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
    """Shared logic for reaper loop and startup recovery.

    Delegates all business logic to ExecutionService.reap_stale_executions
    so the scheduler only decides *when* to run and *what thresholds* to use.
    """
    async with AsyncSessionLocal() as db:
        from app.services.execution_service import ExecutionService

        svc = ExecutionService(db)
        return await svc.reap_stale_executions(_STALE_THRESHOLDS)


async def _reap_orphan_traces() -> None:
    """Mark Trace rows as 'error' if their execution is already terminal but the Trace is still 'running'."""
    import sqlalchemy as sa
    from sqlalchemy.engine import CursorResult

    from app.core.observation.model import Trace
    from app.models.execution import Execution
    from app.utils.datetime import utc_now

    terminal = ("succeeded", "failed", "cancelled")
    async with AsyncSessionLocal() as db:
        result: CursorResult = await db.execute(  # type: ignore[assignment]
            sa.update(Trace)
            .where(
                Trace.status == "running",
                Trace.execution_id == Execution.id,
                Execution.status.in_(terminal),
            )
            .values(status="error", end_time=utc_now())
        )
        rows_fixed = result.rowcount
        if rows_fixed:
            await db.commit()
            logger.info(f"Scheduler: fixed {rows_fixed} orphan Trace rows")
