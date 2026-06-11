"""Worker service startup and shutdown loops."""

from __future__ import annotations

import asyncio

from loguru import logger


async def start_worker_loops() -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []

    try:
        from app.joysafeter_worker.runtime.cli_backends.container_pool import container_pool

        async def _container_reaper() -> None:
            while True:
                await asyncio.sleep(300)
                try:
                    removed = await container_pool.cleanup_idle()
                    if removed:
                        logger.info(f"Container reaper: removed {removed} idle containers")
                except Exception as e:
                    logger.warning(f"Container reaper error: {e}")

        tasks.append(asyncio.create_task(_container_reaper(), name="container-reaper"))
        logger.info("   ✓ Container pool reaper started (idle_timeout=30m)")
    except Exception as e:
        logger.warning(f"   ⚠️  Container pool reaper failed to start: {e}")

    try:
        from app.joysafeter_worker.reapers.execution import (
            execution_reaper_loop,
            recover_stale_on_startup,
            task_dispatcher_loop,
        )

        await recover_stale_on_startup()
        tasks.append(asyncio.create_task(task_dispatcher_loop(), name="task-dispatcher"))
        tasks.append(asyncio.create_task(execution_reaper_loop(), name="execution-reaper"))
        logger.info("   ✓ Task dispatcher and execution reaper started (interval=30s)")
    except Exception as e:
        logger.warning(f"   ⚠️  Scheduler startup failed: {e}")

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

    return tasks


async def stop_worker_loops(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()

    try:
        from app.joysafeter_worker.runtime.cli_backends.container_pool import container_pool as _cp

        await _cp.shutdown()
        logger.info("   ✓ Container pool shut down (containers left running)")
    except Exception as e:
        logger.warning(f"   ⚠️  Container pool shutdown failed: {e}")

    try:
        from app.joysafeter_worker.services import _sandbox_pool

        await _sandbox_pool.shutdown()
        logger.info("   ✓ Sandbox pool shut down")
    except Exception as e:
        logger.warning(f"   ⚠️  Sandbox pool shutdown failed: {e}")

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
