"""Compatibility entrypoint for the legacy single-process backend.

Use `app.joysafeter_api.main`, `app.joysafeter_orchestrator.main`, and
`app.joysafeter_worker.main` for the explicit three-service deployment.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
from loguru import logger

from app.joysafeter_shared.common.logging import setup_logging
from app.joysafeter_shared.config.service_role import is_orchestrator_role, is_worker_role
from app.joysafeter_shared.config.settings import ENV_FILE, settings
from app.joysafeter_api.app import create_api_app
from app.joysafeter_shared.runtime.lifecycle import _run_common_shutdown, _run_common_startup

load_dotenv(ENV_FILE, override=False)
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    await _run_common_startup()
    from app.joysafeter_api.startup import run_api_startup

    await run_api_startup()

    worker_tasks: list[asyncio.Task] = []
    if is_worker_role():
        from app.joysafeter_worker.lifecycle import start_worker_loops
        from app.joysafeter_worker.startup import run_worker_startup

        await run_worker_startup()
        worker_tasks = await start_worker_loops()
    else:
        logger.info("   Worker loops skipped for service role")

    if is_orchestrator_role() and not is_worker_role():
        from app.joysafeter_shared.runtime.lifecycle import _check_docker_availability

        await _check_docker_availability()

    if is_orchestrator_role():
        try:
            from app.joysafeter_orchestrator.lifespan import joysafeter_startup

            await joysafeter_startup()
        except Exception as e:
            logger.warning(f"   ⚠️  JoySafeter kernel startup failed: {e}")
    else:
        logger.info("   JoySafeter kernel skipped for service role")

    try:
        yield
    finally:
        if is_orchestrator_role():
            try:
                from app.joysafeter_orchestrator.lifespan import joysafeter_shutdown

                await joysafeter_shutdown()
            except Exception as e:
                logger.warning(f"   ⚠️  JoySafeter kernel shutdown failed: {e}")

        if worker_tasks:
            from app.joysafeter_worker.lifecycle import stop_worker_loops

            await stop_worker_loops(worker_tasks)
            from app.joysafeter_worker.startup import run_worker_shutdown

            await run_worker_shutdown()

        await _run_common_shutdown()


app = create_api_app(lifespan=lifespan)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.backend_port,
        reload=settings.reload,
        workers=settings.workers,
        loop="uvloop",
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
