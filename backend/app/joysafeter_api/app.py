"""FastAPI app assembly for the JoySafeter API service."""

from __future__ import annotations

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

from app.joysafeter_api.api import api_router
from app.joysafeter_api.api.v2.middleware import V2ResponseWrapperMiddleware
from app.joysafeter_api.api.v2.router import joysafeter_router
from app.joysafeter_api.websocket.auth import WebSocketCloseCode, authenticate_websocket, reject_websocket
from app.joysafeter_api.websocket.execution_subscription_handler import execution_subscription_handler
from app.joysafeter_api.websocket.notification_manager import NotificationType, notification_manager
from app.joysafeter_shared.runtime.app_factory import create_app


def create_api_app(*, lifespan) -> FastAPI:
    app = create_app(lifespan=lifespan)
    register_api_routes(app)
    register_websocket_routes(app)
    return app


def register_api_routes(app: FastAPI) -> None:
    app.add_middleware(V2ResponseWrapperMiddleware)
    app.include_router(api_router, prefix="/api")
    app.include_router(joysafeter_router, prefix="/api/v2")


def register_websocket_routes(app: FastAPI) -> None:
    async def _run_notification_loop(websocket: WebSocket, user_id: str) -> None:
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
                            {"type": NotificationType.PONG.value},
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

    @app.websocket("/ws/notifications")
    async def notification_websocket_endpoint(websocket: WebSocket):
        is_authenticated, user_id = await authenticate_websocket(websocket)
        if not is_authenticated or not user_id:
            await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
            return
        await _run_notification_loop(websocket, user_id)

    @app.websocket("/ws/executions")
    async def executions_websocket_endpoint(websocket: WebSocket):
        is_authenticated, user_id = await authenticate_websocket(websocket)
        if not is_authenticated or not user_id:
            await reject_websocket(websocket, code=WebSocketCloseCode.UNAUTHORIZED, reason="Authentication required")
            return
        await execution_subscription_handler.handle_connection(websocket, str(user_id))



__all__ = ["create_api_app", "register_api_routes", "register_websocket_routes"]
