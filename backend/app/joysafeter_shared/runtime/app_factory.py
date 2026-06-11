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
        return {"status": "ok", "role": current_role().value}

    return app
