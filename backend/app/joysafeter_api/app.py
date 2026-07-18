"""FastAPI app assembly for the JoySafeter API service."""

from __future__ import annotations

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

from app.joysafeter_api.api.v1.middleware import (
    ApiV1ResponseWrapperMiddleware,
    CsrfProtectionMiddleware,
    RequestBodySizeLimitMiddleware,
)
from app.joysafeter_api.api.v1.router import joysafeter_router
from app.joysafeter_api.websocket.auth import WebSocketCloseCode, authenticate_websocket, reject_websocket
from app.joysafeter_api.websocket.notification_manager import NotificationType, notification_manager
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.runtime.app_factory import create_app


def create_api_app(*, lifespan) -> FastAPI:
    app = create_app(lifespan=lifespan)
    register_api_routes(app)
    register_websocket_routes(app)
    return app


def register_api_routes(app: FastAPI) -> None:
    # CSRF verification for cookie-authenticated mutations. Added before the
    # response wrapper so the wrapper stays outermost; a rejected request short
    # -circuits with a structured 403 that the wrapper passes through untouched.
    app.add_middleware(CsrfProtectionMiddleware)
    app.add_middleware(ApiV1ResponseWrapperMiddleware)
    # Body-size cap. Added LAST so it is the OUTERMOST middleware: an oversized
    # request is rejected (413) before CSRF/wrapper/router ever read the body,
    # bounding the memory a single request can force a worker to buffer.
    app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)
    # All API routes live under /api/v1/*.
    app.include_router(joysafeter_router, prefix="/api/v1")


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
            log_boundary_failure_loguru(
                logger,
                boundary="api_websocket",
                code="WEBSOCKET_NOTIFICATION_LOOP_FAILED",
                message="WebSocket notification loop failed",
                operation="run_notification_loop",
                error=e,
                data={"user_id": user_id},
            )
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


__all__ = ["create_api_app", "register_api_routes", "register_websocket_routes"]
