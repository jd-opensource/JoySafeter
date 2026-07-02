"""Worker service startup hooks."""

from __future__ import annotations


async def run_worker_startup() -> None:
    await _check_docker_availability()


async def _check_docker_availability() -> None:
    from app.joysafeter_shared.runtime.lifecycle import _check_docker_availability as _check

    await _check()


async def run_worker_shutdown() -> None:
    # The legacy execution_event_bus subscribers, CheckpointerManager
    # (LangGraph Postgres saver), and CLI container pool were removed
    # during prior cleanup waves. Nothing to tear down here for now; we
    # keep the symbol so callers don't need to special-case the absence
    # of a shutdown hook.
    return None
