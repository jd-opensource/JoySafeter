"""WebSocket handler for durable run subscriptions (deprecated).

This endpoint is deprecated. Clients should use /ws/executions instead.
"""

from __future__ import annotations

import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.websocket.run_subscription_manager import run_subscription_manager


class RunSubscriptionHandler:
    """Handles subscribe/unsubscribe frames for durable run event streams.

    Deprecated: run event streaming has moved to /ws/executions.
    This handler remains for backward compatibility and directs clients
    to the new endpoint.
    """

    async def handle_connection(self, websocket: WebSocket, user_id: str) -> None:
        """Accept the WebSocket and process frames until disconnect."""
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_text()
                await self._handle_frame(websocket, user_id, raw)
        except WebSocketDisconnect:
            pass
        finally:
            run_subscription_manager.disconnect(websocket)

    async def _handle_frame(self, websocket: WebSocket, user_id: str, raw: str) -> None:
        """Parse a raw JSON frame and handle subscribe, unsubscribe, or ping."""
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_text(json.dumps({"type": "ws_error", "message": "invalid json frame"}))
            return

        frame_type = frame.get("type")
        if frame_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
            return

        if frame_type == "unsubscribe":
            run_id = frame.get("run_id")
            if run_id:
                run_subscription_manager.remove_subscription(websocket, str(run_id))
            return

        if frame_type != "subscribe":
            await websocket.send_text(json.dumps({"type": "ws_error", "message": f"unknown frame type: {frame_type}"}))
            return

        run_id_raw = frame.get("run_id")
        if not run_id_raw:
            await websocket.send_text(json.dumps({"type": "ws_error", "message": "run_id is required"}))
            return

        try:
            run_id = uuid.UUID(str(run_id_raw))
        except ValueError:
            await websocket.send_text(json.dumps({"type": "ws_error", "message": "invalid run_id"}))
            return

        try:
            after_seq = int(frame.get("after_seq") or 0)
        except (ValueError, TypeError):
            await websocket.send_text(json.dumps({"type": "ws_error", "message": "invalid after_seq"}))
            return

        # This endpoint is deprecated; run event streaming uses /ws/executions.
        await websocket.send_text(json.dumps({
            "type": "ws_error",
            "message": "This endpoint is deprecated. Use /ws/executions instead.",
        }))
        return


run_subscription_handler = RunSubscriptionHandler()
