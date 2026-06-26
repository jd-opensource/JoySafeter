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
        logger.warning(f"   ⚠️  JoySafeter event stream worker failed to start: {e}")

    _worker_tasks = list(tasks)
    return tasks


async def stop_worker_loops(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
