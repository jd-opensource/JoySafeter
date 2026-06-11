"""JoySafeter orchestrator service entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

os.environ.setdefault("JOYSAFETER_SERVICE_ROLE", "orchestrator")

from app.joysafeter_shared.common.logging import setup_logging  # noqa: E402
from app.joysafeter_shared.config.settings import settings  # noqa: E402
from app.joysafeter_shared.runtime.app_factory import create_app  # noqa: E402
from app.joysafeter_shared.runtime.lifecycle import _run_common_shutdown, _run_common_startup  # noqa: E402

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    await _run_common_startup()
    from app.joysafeter_shared.runtime.lifecycle import _check_docker_availability

    await _check_docker_availability()
    try:
        from app.joysafeter_orchestrator.lifespan import joysafeter_startup

        await joysafeter_startup()
        yield
    finally:
        try:
            from app.joysafeter_orchestrator.lifespan import joysafeter_shutdown

            await joysafeter_shutdown()
        finally:
            await _run_common_shutdown()


app = create_app(lifespan=lifespan, title_suffix="Orchestrator", expose_docs=False)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.joysafeter_orchestrator.main:app",
        host=settings.orchestrator_http_host,
        port=settings.backend_port,
        reload=settings.reload,
        workers=1,
        loop="uvloop",
    )
