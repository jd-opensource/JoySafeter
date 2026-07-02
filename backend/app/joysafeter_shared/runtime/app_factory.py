"""FastAPI app factory helpers for JoySafeter service roles."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.logging import TracingMiddleware
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import settings


def create_app(*, lifespan, title_suffix: str = "", expose_docs: bool = True) -> FastAPI:
    title = settings.app_name if not title_suffix else f"{settings.app_name} {title_suffix}"
    docs_enabled = expose_docs and (settings.debug or settings.environment == "development")
    app = FastAPI(
        title=title,
        version=settings.app_version,
        description="""
## JoySafeter - Agent Platform Backend Service
### Tech Stack
- **FastAPI** - Web Framework
- **PostgreSQL** - Database
- **SQLAlchemy 2.0** - ORM (Async)
- **LangChain 1.0 + LangGraph 1.0** - AI Framework
        """,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "status": "ok",
            "message": "JoySafeter backend is running!",
            "role": current_role().value,
            "docs": "/docs",
            "redoc": "/redoc",
        }

    @app.get("/health", tags=["Health"])
    async def health():
        role = current_role().value
        checks: dict = {"role": role, "status": "ok"}

        # For worker role, verify critical background tasks are alive
        if role == "worker":
            try:
                from app.joysafeter_worker.lifecycle import _worker_tasks

                dead_tasks = []
                for task in _worker_tasks:
                    if task.done():
                        if task.cancelled():
                            dead_tasks.append(f"{task.get_name()}: cancelled")
                        else:
                            exc = task.exception()
                            dead_tasks.append(f"{task.get_name()}: {exc}")
                if dead_tasks:
                    checks["status"] = "degraded"
                    checks["dead_tasks"] = dead_tasks
            except Exception:
                pass

        # Check DB connectivity
        try:
            from app.joysafeter_shared.database import engine

            async with engine.connect() as conn:
                from sqlalchemy import text

                await conn.execute(text("SELECT 1"))
        except Exception as e:
            checks["status"] = "unhealthy"
            checks["db_error"] = str(e)

        from fastapi.responses import JSONResponse

        status_code = 200 if checks["status"] == "ok" else 503
        return JSONResponse(content=checks, status_code=status_code)

    return app
