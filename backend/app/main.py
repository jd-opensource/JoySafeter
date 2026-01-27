"""
FastAPI 主应用
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
    """启动时快速检查数据库连通性。"""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select 1"))
        logger.info("   Database connection check: OK")
    except Exception as e:
        logger.error(f"   ⚠️  Database connection check failed: {e}")
        traceback.print_exc()


async def _check_redis_connection():
    """启动时快速检查 Redis 连通性。"""
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
    """应用生命周期"""
    # Startup
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print(f"   Environment: {settings.environment}")
    print(f"   Debug: {settings.debug}")
    print("   Architecture: MVC (Model-View-Controller)")

    # 注意：数据库表通过 Alembic 迁移创建，不再使用 create_all
    # 如需初始化数据库，请运行: alembic upgrade head
    # init_db() 已弃用，不再调用

    # 初始化 Redis
    if settings.redis_url:
        try:
            await RedisClient.init()
            logger.info(f"   Redis connected (pool_size={settings.redis_pool_size})")
        except Exception as e:
            logger.error(f"   ⚠️  Redis connection failed: {e}")
    else:
        logger.info("   Redis not configured (caching/rate-limiting disabled)")

    # 检查数据库连通性（无论环境）
    await _check_db_connection()

    # 检查 Redis 连通性（如果配置了 Redis）
    await _check_redis_connection()

    # 启动时自动同步供应商和模型到数据库（如果数据库中没有）
    try:
        from app.repositories.model_provider import ModelProviderRepository
        from app.services.model_provider_service import ModelProviderService

        async with AsyncSessionLocal() as db:
            provider_repo = ModelProviderRepository(db)
            # 检查数据库中是否已有供应商
            provider_count = await provider_repo.count()

            if provider_count == 0:
                logger.info("   数据库中没有供应商，开始自动同步...")
                service = ModelProviderService(db)
                result = await service.sync_all()
                logger.info(f"   ✓ 自动同步完成：供应商 {result['providers']} 个，模型 {result['models']} 个")
                if result.get('errors'):
                    for error in result['errors']:
                        logger.warning(f"   ⚠️  {error}")
            else:
                logger.info(f"   ✓ 数据库中已有 {provider_count} 个供应商，跳过自动同步")
    except Exception as e:
        logger.warning(f"   ⚠️  自动同步供应商失败: {e}")
        logger.warning("   应用将继续启动，可以稍后手动调用 /api/v1/model-providers/sync 接口")

    # 启动时初始化 MCP 工具（加载所有启用的 MCP 服务器的工具到 registry）
    try:
        from app.services.tool_service import initialize_mcp_tools_on_startup
        async with AsyncSessionLocal() as db:
            total_tools = await initialize_mcp_tools_on_startup(db)
            if total_tools > 0:
                logger.info(f"   ✓ 已加载 {total_tools} 个 MCP 工具到 registry")
            else:
                logger.info("   ✓ MCP 工具初始化完成（无启用的服务器）")
    except Exception as e:
        logger.warning(f"   ⚠️  MCP 工具初始化失败: {e}")
        logger.warning("   应用将继续启动，MCP 工具将在首次使用时加载")

    # 初始化默认模型缓存
    try:
        from app.core.database import get_db
        from app.core.settings import set_default_model_config
        from app.repositories.model_instance import ModelInstanceRepository
        from app.repositories.model_provider import ModelProviderRepository
        from app.services.model_credential_service import ModelCredentialService

        async for db in get_db():
            repo = ModelInstanceRepository(db)
            provider_repo = ModelProviderRepository(db)
            credential_service = ModelCredentialService(db)

            # 获取默认模型实例
            default_instance = await repo.get_default()
            if default_instance and default_instance.provider:
                # 获取凭据
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
                        "timeout": default_instance.model_parameters.get("timeout", 30) if default_instance.model_parameters else 30,
                    }
                    set_default_model_config(config)
                    logger.info("   ✓ 默认模型缓存初始化完成")
                else:
                    logger.warning("   ⚠️  默认模型凭据未找到")
            else:
                logger.info("   ✓ 无默认模型配置")
    except Exception as e:
        logger.warning(f"   ⚠️  默认模型缓存初始化失败: {e}")
        logger.warning("   应用将继续启动，LLM功能将在配置默认模型后可用")

    # 初始化 Dynamic Agent 存储系统
    try:
        from app.dynamic_agent.main import startup as agent_startup
        await agent_startup()
        logger.info("   ✓ Dynamic Agent 存储系统初始化完成")
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.warning(f"   ⚠️  Dynamic Agent 存储系统初始化失败: {e}")
        logger.warning("   应用将继续启动，Dynamic Agent 功能可能不可用")

    # 初始化 Checkpointer 连接池
    try:
        from app.core.agent.checkpointer.checkpointer import CheckpointerManager
        await CheckpointerManager.initialize()
        logger.info("   ✓ Checkpointer 连接池初始化完成")
    except Exception as e:
        logger.warning(f"   ⚠️  Checkpointer 初始化失败: {e}")
        logger.warning("   应用将继续启动，checkpoint 功能可能不可用")

    yield

    # Shutdown: 关闭 Checkpointer 连接池
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

# 创建应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## AutoSec Agent Platform - 智能体平台后端服务
### 技术栈
- **FastAPI** - Web 框架
- **PostgreSQL** - 数据库
- **SQLAlchemy 2.0** - ORM (异步)
- **LangChain 1.0 + LangGraph 1.0** - AI 框架
    """,
    docs_url="/docs" if settings.debug or settings.environment == "development" else None,
    redoc_url="/redoc" if settings.debug or settings.environment == "development" else None,
    lifespan=lifespan,
)


# 异常处理
register_exception_handlers(app)


# 添加日志中间件
app.add_middleware(LoggingMiddleware)

# CORS 中间件
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

        # 核心：移除条件缓存相关头
        # response.headers.pop("ETag", None)
        # response.headers.pop("Last-Modified", None)

    return response

from app.dynamic_agent.server import DYNAMIC_AGENT_PREFIX
from app.dynamic_agent.server import app as dynamic_agent_app

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

# 注册 API 路由
app.include_router(dynamic_agent_app, prefix=DYNAMIC_AGENT_PREFIX)

app.include_router(api_router, prefix="/api")

# 图变量分析路由（/api/graph/{graph_id}/variables）
app.include_router(graph_variables_router, prefix="/api", tags=["Graph Variables"])



# 注册会话管理路由
app.include_router(conversations_router, prefix="/api/v1")

# 注册文件管理路由
app.include_router(files_router, prefix="/api/v1")

# Include API routers
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
app.include_router(memory_router, prefix="/api/v1/memory", tags=["memory"])


# 注册路由
@app.get("/", tags=["Root"])
async def root():
    """根路径，健康检查"""
    return {
        "status": "ok",
        "message": "Langchain+fastapi生产级后端 is running!",
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
    # 1. 验证认证
    is_authenticated, user_id = await authenticate_websocket(websocket)

    if not is_authenticated or not user_id:
        await reject_websocket(
            websocket,
            code=WebSocketCloseCode.UNAUTHORIZED,
            reason="Authentication required"
        )
        return

    try:
        async with AsyncSessionLocal() as db:
            session_service = SessionService(db)

            # 2. 验证 session 归属
            session = await session_service.get_session_for_user(session_id, user_id)
            if not session:
                await reject_websocket(
                    websocket,
                    code=WebSocketCloseCode.FORBIDDEN,
                    reason="Session not found or access denied"
                )
                return

            # 3. 建立连接
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
        await reject_websocket(
            websocket,
            code=WebSocketCloseCode.UNAUTHORIZED,
            reason="Authentication required"
        )
        return

    try:
        await websocket.accept()
        await notification_manager.connect(websocket, user_id)

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await notification_manager.send_to_connection(websocket, {
                        "type": NotificationType.PONG.value,
                    })

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
        await reject_websocket(
            websocket,
            code=WebSocketCloseCode.UNAUTHORIZED,
            reason="Authentication required"
        )
        return

    if str(token_user_id) != str(user_id):
        await reject_websocket(
            websocket,
            code=WebSocketCloseCode.FORBIDDEN,
            reason="User ID mismatch"
        )
        return

    try:
        await websocket.accept()
        await notification_manager.connect(websocket, user_id)

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await notification_manager.send_to_connection(websocket, {
                        "type": NotificationType.PONG.value,
                    })

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
        await reject_websocket(
            websocket,
            code=WebSocketCloseCode.UNAUTHORIZED,
            reason="Authentication required"
        )
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
