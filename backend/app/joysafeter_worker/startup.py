"""Worker service startup hooks."""

from __future__ import annotations

from loguru import logger


async def run_worker_startup() -> None:
    await _check_docker_availability()
    await _initialize_checkpointer()
    await _initialize_cli_runtime_providers()
    await _register_execution_event_subscribers()


async def _check_docker_availability() -> None:
    from app.joysafeter_shared.runtime.lifecycle import _check_docker_availability as _check

    await _check()


async def _initialize_checkpointer() -> None:
    try:
        from app.joysafeter_worker.runtime.checkpointer.checkpointer import CheckpointerManager

        await CheckpointerManager.initialize()
        logger.info("   ✓ Checkpointer connection pool initialized")
    except Exception as e:
        logger.warning(f"   ⚠️  Checkpointer initialization failed: {e}")
        logger.warning("   App will continue starting, checkpoint features may be unavailable")


async def _initialize_cli_runtime_providers() -> None:
    try:
        from app.joysafeter_worker.runtime.cli_backends.registry import init_providers

        init_providers()
        logger.info("   ✓ CLI runtime providers initialized")
    except Exception as e:
        logger.warning(f"   ⚠️  CLI runtime provider initialization failed: {e}")


async def _register_execution_event_subscribers() -> None:
    try:
        from app.joysafeter_worker.services import (
            PersistenceSubscriber,
            StateTransitionSubscriber,
            TaskSyncSubscriber,
            WebSocketSubscriber,
            execution_event_bus,
        )

        execution_event_bus.register(PersistenceSubscriber())
        execution_event_bus.register(StateTransitionSubscriber())
        execution_event_bus.register(WebSocketSubscriber())
        execution_event_bus.register(TaskSyncSubscriber())
        logger.info("   ✓ Execution event bus subscribers registered")
    except Exception as e:
        logger.error(f"   ⚠️  Event bus subscriber registration failed: {e}")


async def run_worker_shutdown() -> None:
    try:
        from app.joysafeter_worker.runtime.checkpointer.checkpointer import CheckpointerManager

        await CheckpointerManager.close()
    except Exception:
        logger.debug("Failed to close CheckpointerManager during shutdown", exc_info=True)
