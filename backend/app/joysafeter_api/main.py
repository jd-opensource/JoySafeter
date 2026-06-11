"""JoySafeter API service entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI

os.environ.setdefault("JOYSAFETER_SERVICE_ROLE", "api")

from app.joysafeter_shared.common.logging import setup_logging
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
    try:
        yield
    finally:
        await _run_common_shutdown()


app = create_api_app(lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.joysafeter_api.main:app",
        host="0.0.0.0",
        port=settings.backend_port,
        reload=settings.reload,
        workers=settings.workers,
        loop="uvloop",
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
