"""Worker service startup and shutdown loops.

Active worker background tasks:
  - joysafeter-event-stream-worker — Redis Stream consumer that persists
    session events emitted by orchestrator-rs.

The legacy "task-dispatcher" / "execution-reaper" / "container-reaper" loops
and the in-process ``execution_event_bus`` subscribers were removed along
with the old DispatchService / ExecutionOrchestrator / AgentRun / Execution
dispatch chain and the old CLI container pool. All sandbox dispatch now
flows through the orchestrator gRPC ↔ sandbox-runner path; the worker only
persists the resulting events.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

# Module-level reference to background tasks for health check inspection
_worker_tasks: list[asyncio.Task] = []


async def start_worker_loops() -> list[asyncio.Task]:
    global _worker_tasks
    tasks: list[asyncio.Task] = []

    try:
        from app.joysafeter_shared.config.settings import joysafeter_config

        if joysafeter_config.event_stream_enabled:
            from app.joysafeter_worker.events.stream_consumer import EventStreamWorker

            stream_worker = EventStreamWorker(
                stream_key=joysafeter_config.event_stream_key,
                group=joysafeter_config.event_stream_group,
                batch_size=joysafeter_config.event_stream_batch_size,
                block_ms=joysafeter_config.event_stream_block_ms,
            )
            tasks.append(asyncio.create_task(stream_worker.run(), name="joysafeter-event-stream-worker"))
            logger.info("   ✓ JoySafeter event stream worker started")
        else:
            logger.info("   JoySafeter event stream worker disabled")
    except Exception as e:
        logger.bind(
            error=async_boundary_error_payload(
                code="WORKER_EVENT_STREAM_START_FAILED",
                message="JoySafeter event stream worker failed to start.",
                boundary="worker_lifecycle",
                operation="start_worker_loops",
                data={},
                source="worker",
                detail=e.__class__.__name__,
                retryable=True,
                user_action="retry",
            )
        ).warning(f"   ⚠️  JoySafeter event stream worker failed to start: {e}")

    try:
        from app.joysafeter_shared.config.settings import settings

        if settings.scheduler_enabled:
            from app.joysafeter_worker.scheduler import SchedulerLoop

            scheduler = SchedulerLoop(
                poll_interval_sec=settings.scheduler_poll_interval_sec,
                claim_batch=settings.scheduler_claim_batch,
                lock_grace_sec=settings.scheduler_lock_grace_sec,
            )
            tasks.append(asyncio.create_task(scheduler.run(), name="joysafeter-scheduler-loop"))
            logger.info("   ✓ JoySafeter scheduler loop started")
        else:
            logger.info("   JoySafeter scheduler loop disabled")
    except Exception as e:
        logger.bind(
            error=async_boundary_error_payload(
                code="WORKER_SCHEDULER_START_FAILED",
                message="JoySafeter scheduler loop failed to start.",
                boundary="worker_lifecycle",
                operation="start_worker_loops",
                data={},
                source="worker",
                detail=e.__class__.__name__,
                retryable=True,
                user_action="retry",
            )
        ).warning(f"   ⚠️  JoySafeter scheduler loop failed to start: {e}")

    _worker_tasks = list(tasks)
    return tasks


async def stop_worker_loops(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def scheduler_health() -> dict:
    """Scheduler liveness/throughput snapshot for the worker health check.

    Returns the process-wide scheduler heartbeat (last tick time, claimed/fired/
    failed counts, max fire lag) so a health endpoint can tell whether the cron
    loop is alive and keeping up.
    """
    from app.joysafeter_worker.scheduler import scheduler_heartbeat

    return scheduler_heartbeat().snapshot()
