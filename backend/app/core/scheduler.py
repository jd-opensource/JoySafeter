"""
Background scheduler loops for task auto-dispatch and stale execution reaping.

Registered in app lifespan (main.py). Each function is an infinite async loop
following the same pattern as _container_reaper.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from loguru import logger

from app.core.agent.cli_backends.session_registry import session_registry
from app.core.database import AsyncSessionLocal
from app.core.engine.orchestrator import ExecutionOrchestrator
from app.repositories.execution import ExecutionRepository
from app.services.execution_service import ExecutionService
from app.utils.datetime import utc_now

_DISPATCH_INTERVAL = 30
_REAPER_INTERVAL = 30

_STALE_THRESHOLDS: list[tuple[tuple[str, ...], timedelta]] = [
    (
        ("queued", "dispatched"),
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


async def mission_dispatcher_loop() -> None:
    """Every 30s, find BACKLOG tasks with agent assignees and dispatch them."""
    while True:
        await asyncio.sleep(_DISPATCH_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select
                from app.models.task import Task

                # Find backlog tasks with assigned agents
                tasks = (await db.execute(
                    select(Task).where(
                        Task.status == "backlog",
                        Task.agent_id.isnot(None),
                    )
                )).scalars().all()

                count = 0
                for task in tasks:
                    try:
                        orchestrator = ExecutionOrchestrator(db)
                        await orchestrator.dispatch_task(task.id, task.creator_id)
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
                        status="failed",
                        error_code="stale_reaped",
                        error_message=f"No heartbeat for {int(threshold.total_seconds() // 60)}+ minutes",
                    )

                    await lifecycle._finalize_task(execution.id, "failed")

                    total += 1
                    logger.info(
                        f"Reaped stale execution {execution.id} "
                        f"(status={execution.status}, age={now - (execution.started_at or execution.created_at)})"
                    )
                except Exception as exc:
                    logger.warning(f"Failed to reap execution {execution.id}: {exc}")

    return total
