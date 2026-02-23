"""
FastAPI Main Application
"""

import traceback
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from sqlalchemy import text

from app.api import api_router
from app.api.graph.variables import router as graph_variables_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.files import router as files_router
from app.api.v1.memory import router as memory_router
from app.api.v1.sessions import router as sessions_router
from app.common.exceptions import register_exception_handlers
from app.common.logging import LoggingMiddleware, setup_logging
from app.core.database import AsyncSessionLocal, close_db, engine
from app.core.redis import RedisClient
from app.core.settings import settings
from app.services.session_service import SessionService
from app.websocket.auth import WebSocketCloseCode, authenticate_websocket, reject_websocket
from app.websocket.chat_handler import ChatHandler
from app.websocket.copilot_handler import copilot_handler
from app.websocket.notification_manager import NotificationType, notification_manager

setup_logging()


async def _check_db_connection():
    """Quickly check database connectivity on startup."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select 1"))
        logger.info("   Database connection check: OK")
    except Exception as e:
        logger.error(f"   ⚠️  Database connection check failed: {e}")
        traceback.print_exc()


async def _check_redis_connection():
    """Quickly check Redis connectivity on startup."""
    if not settings.redis_url:
        logger.info("   Redis connection check: Skipped (not configured)")
        return

    try:
        is_healthy = await RedisClient.health_check()
        if is_healthy:
            logger.info("   Redis connection check: OK")
        else:
            logger.error("   ⚠️  Redis connection check failed: Health check returned False")
    except Exception as e:
        logger.error(f"   ⚠️  Redis connection check failed: {e}")
        traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application Lifecycle"""
    # Startup
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print(f"   Environment: {settings.environment}")
    print(f"   Debug: {settings.debug}")
    print("   Architecture: MVC (Model-View-Controller)")

    # Note: Database tables are created via Alembic migrations, create_all is no longer used
    # To initialize database, run: alembic upgrade head
    # init_db() is deprecated and no longer called

    # Warning for misconfigured FRONTEND_URL in production
    if settings.environment == "production" and "localhost" in settings.frontend_url:
        logger.warning(
            "⚠️  WARNING: You are running in 'production' environment, but FRONTEND_URL "
            "contains 'localhost'. This will break email links, OAuth callbacks, "
            "and other frontend integrations! Please update FRONTEND_URL in your .env file."
        )

    # Initialize Redis
    if settings.redis_url:
        try:
            await RedisClient.init()
            logger.info(f"   Redis connected (pool_size={settings.redis_pool_size})")
        except Exception as e:
            logger.error(f"   ⚠️  Redis connection failed: {e}")
    else:
        logger.info("   Redis not configured (caching/rate-limiting disabled)")

    # Check database connection (regardless of environment)
    await _check_db_connection()

    # Check Redis connection (if configured)
    await _check_redis_connection()

    # Automatically sync providers and models to database on startup (if not present)
    try:
        from app.repositories.model_provider import ModelProviderRepository
        from app.services.model_provider_service import ModelProviderService

        # Use distributed lock to prevent concurrent execution by multiple instances/workers
        async with RedisClient.lock("init:model_providers", timeout=60, blocking_timeout=60):
            async with AsyncSessionLocal() as db:
                provider_repo = ModelProviderRepository(db)
                # Check if providers already exist in database
                provider_count = await provider_repo.count()

                if provider_count == 0:
                    logger.info("   No providers in database, starting auto-sync...")
                    service = ModelProviderService(db)
                    result = await service.sync_all()
                    logger.info(f"   ✓ Auto-sync completed: {result['providers']} providers, {result['models']} models")
                    if result.get("errors"):
                        for error in result["errors"]:
                            logger.warning(f"   ⚠️  {error}")
                else:
                    logger.info(f"   ✓ {provider_count} providers already exist, skipping auto-sync")
    except Exception as e:
        logger.warning(f"   ⚠️  Auto-sync providers failed: {e}")
        logger.warning("   App will continue starting, you can manually call /api/v1/model-providers/sync later")

    # Initialize MCP tools on startup (load tools from all enabled MCP servers to registry)
    try:
        from app.services.tool_service import initialize_mcp_tools_on_startup

        # Use distributed lock. Although initialize_mcp_tools_on_startup might only load to memory,
        # if it involves DB updates or to avoid concurrent external service queries, locking is safe.
        async with RedisClient.lock("init:mcp_tools", timeout=60, blocking_timeout=60):
            async with AsyncSessionLocal() as db:
                total_tools = await initialize_mcp_tools_on_startup(db)
                if total_tools > 0:
                    logger.info(f"   ✓ Loaded {total_tools} MCP tools to registry")
                else:
                    logger.info("   ✓ MCP tools initialization completed (no enabled servers)")
    except Exception as e:
        logger.warning(f"   ⚠️  MCP tools initialization failed: {e}")
        logger.warning("   App will continue starting, MCP tools will be loaded on first use")

    # Initialize default model cache
    try:
        from app.core.database import get_db
        from app.core.settings import set_default_model_config
        from app.repositories.model_instance import ModelInstanceRepository
        from app.repositories.model_provider import ModelProviderRepository
        from app.services.model_credential_service import ModelCredentialService

        # Lock here as well. Although it's mostly reading DB and writing config,
        # serialization ensures orderly logs during multi-instance startup.
        async with RedisClient.lock("init:default_model_config", timeout=30, blocking_timeout=30):
            async for db in get_db():
                repo = ModelInstanceRepository(db)
                provider_repo = ModelProviderRepository(db)
                credential_service = ModelCredentialService(db)

                # Get default model instance
                default_instance = await repo.get_default()
                if default_instance and default_instance.provider:
                    # Get credentials
                    credentials = await credential_service.get_current_credentials(
                        provider_name=default_instance.provider.name,
                        model_type="chat",
                        model_name=default_instance.model_name,
                    )

                    if credentials:
                        config = {
                            "model": default_instance.model_name,
                            "api_key": credentials.get("api_key", ""),
                            "base_url": credentials.get("base_url"),
                            "timeout": default_instance.model_parameters.get("timeout", 30)
                            if default_instance.model_parameters
                            else 30,
                        }
                        set_default_model_config(config)
                        logger.info("   ✓ Default model cache initialized")
                    else:
                        logger.warning("   ⚠️  Default model credentials not found")
                else:
                    logger.info("   ✓ No default model configuration")
    except Exception as e:
        logger.warning(f"   ⚠️  Default model cache initialization failed: {e}")
        logger.warning("   App will continue starting, LLM features available after configuring default model")

    # Initialize Dynamic Agent storage system
    try:
        from app.dynamic_agent.main import startup as agent_startup

        await agent_startup()
        logger.info("   ✓ Dynamic Agent storage system initialized")
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.warning(f"   ⚠️  Dynamic Agent storage system initialization failed: {e}")
        logger.warning("   App will continue starting, Dynamic Agent features may be unavailable")

    # Initialize Checkpointer connection pool
    try:
        from app.core.agent.checkpointer.checkpointer import CheckpointerManager

        await CheckpointerManager.initialize()
        logger.info("   ✓ Checkpointer connection pool initialized")
    except Exception as e:
        logger.warning(f"   ⚠️  Checkpointer initialization failed: {e}")
        logger.warning("   App will continue starting, checkpoint features may be unavailable")

    yield

    # Shutdown: Close Checkpointer connection pool
    try:
        from app.core.agent.checkpointer.checkpointer import CheckpointerManager

        await CheckpointerManager.close()
    except Exception:
        pass

    try:
        await RedisClient.close()
    except Exception:
        pass
    await close_db()
    print("👋 Application shutdown")


# Create application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## JoySafeter - Agent Platform Backend Service
### Tech Stack
- **FastAPI** - Web Framework
- **PostgreSQL** - Database
- **SQLAlchemy 2.0** - ORM (Async)
- **LangChain 1.0 + LangGraph 1.0** - AI Framework
    """,
    docs_url="/docs" if settings.debug or settings.environment == "development" else None,
    redoc_url="/redoc" if settings.debug or settings.environment == "development" else None,
    lifespan=lifespan,
)


# Exception handling
register_exception_handlers(app)


# Add logging middleware
app.add_middleware(LoggingMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_cache_for_api(request: Request, call_next):
    response: Response = await call_next(request)

    if request.url.path.startswith("/dynamic/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        # Core: Remove conditional cache headers
        # response.headers.pop("ETag", None)
        # response.headers.pop("Last-Modified", None)

    return response


from app.dynamic_agent.server import DYNAMIC_AGENT_PREFIX  # noqa: E402
from app.dynamic_agent.server import app as dynamic_agent_app  # noqa: E402

# ENV = os.getenv("ENV", "dev")  # dev / prod


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Register API Router
app.include_router(dynamic_agent_app, prefix=DYNAMIC_AGENT_PREFIX)

app.include_router(api_router, prefix="/api")

# Graph Variables Router (/api/graph/{graph_id}/variables)
app.include_router(graph_variables_router, prefix="/api", tags=["Graph Variables"])


# Register Conversation Management Router
app.include_router(conversations_router, prefix="/api/v1")

# Register File Management Router
app.include_router(files_router, prefix="/api/v1")

# Include API routers
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
app.include_router(memory_router, prefix="/api/v1/memory", tags=["memory"])


# Register Router
@app.get("/", tags=["Root"])
async def root():
    """Root path, health check"""
    return {
        "status": "ok",
        "message": "Langchain+fastapi production-grade backend is running!",
        "docs": "/docs",
        "redoc": "/redoc",
    }


# WebSocket endpoint for real-time chat
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
):
    """WebSocket endpoint for real-time chat with JWT authentication."""
    # 1. Verify authentication
    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
        return

    try:
        async with AsyncSessionLocal() as db:
            session_service = SessionService(db)

            # 2. Verify session ownership
            session = await session_service.get_session_for_user(session_id, user_id)
            if not session:
                await reject_websocket(
                    websocket, code=WebSocketCloseCode.FORBIDDEN, reason="Session not found or access denied"
                )
                return

            # 3. Establish connection
            await websocket.accept()
            chat_handler = ChatHandler(session_service)
            await chat_handler.handle_connection(websocket, session_id, int(user_id))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@app.websocket("/ws/notifications")
async def notification_websocket_endpoint(websocket: WebSocket):
    import json

    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
        return

    try:
        await websocket.accept()
        await notification_manager.connect(websocket, user_id)

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await notification_manager.send_to_connection(
                        websocket,
                        {
                            "type": NotificationType.PONG.value,
                        },
                    )

            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket notification error for user {user_id}: {e}")
    finally:
        notification_manager.disconnect(websocket)
        logger.info(f"WebSocket notification disconnected for user {user_id}")


@app.websocket("/ws/notifications/{user_id}")
async def notification_websocket_endpoint_legacy(websocket: WebSocket, user_id: str):
    import json

    is_authenticated, token_user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not token_user_id:
        await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
        return

    if str(token_user_id) != str(user_id):
        await reject_websocket(websocket, code=WebSocketCloseCode.FORBIDDEN, reason="User ID mismatch")
        return

    try:
        await websocket.accept()
        await notification_manager.connect(websocket, user_id)

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await notification_manager.send_to_connection(
                        websocket,
                        {
                            "type": NotificationType.PONG.value,
                        },
                    )

            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket notification error for user {user_id}: {e}")
    finally:
        notification_manager.disconnect(websocket)
        logger.info(f"WebSocket notification disconnected for user {user_id}")


@app.websocket("/ws/copilot/{session_id}")
async def copilot_websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for Copilot session subscription.
    Subscribes to Redis Pub/Sub and forwards events to clients.

    Args:
        session_id: Copilot session ID to subscribe to
    """
    # Authenticate WebSocket connection
    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
        return

    # Handle connection
    await copilot_handler.handle_connection(websocket, session_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
    )
