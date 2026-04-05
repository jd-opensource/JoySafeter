"""WebSocket handler for durable run subscriptions."""

from __future__ import annotations

import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.core.database import AsyncSessionLocal
from app.services.run_service import RunService
from app.websocket.run_subscription_manager import run_subscription_manager


class RunSubscriptionHandler:
    """Handles subscribe/unsubscribe frames for durable run event streams."""

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

        async with AsyncSessionLocal() as db:
            service = RunService(db)
            run = await service.get_run(run_id, user_id)
            if run is None:
                await websocket.send_text(json.dumps({"type": "ws_error", "message": "run not found"}))
                return

            snapshot = await service.get_snapshot(run_id, user_id)
            if snapshot is None:
                await websocket.send_text(json.dumps({"type": "ws_error", "message": "snapshot not found"}))
                return

            snapshot_last_seq = int(snapshot.last_seq or 0)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "snapshot",
                        "run_id": str(run_id),
                        "last_seq": snapshot_last_seq,
                        "data": snapshot.projection,
                    }
                )
            )

            await run_subscription_manager.add_subscription(websocket, str(run_id))

            catchup_after_seq = max(after_seq, snapshot_last_seq)
            events = await service.list_events_after(run_id, user_id, after_seq=catchup_after_seq, limit=1000)
            replay_last_seq = snapshot_last_seq
            for event in events:
                replay_last_seq = max(replay_last_seq, int(event.seq))
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "event",
                            "run_id": str(run_id),
                            "seq": event.seq,
                            "event_type": event.event_type,
                            "data": event.payload,
                            "trace_id": str(event.trace_id) if event.trace_id else None,
                            "observation_id": str(event.observation_id) if event.observation_id else None,
                            "parent_observation_id": (
                                str(event.parent_observation_id) if event.parent_observation_id else None
                            ),
                            "created_at": event.created_at.isoformat() if event.created_at else None,
                        }
                    )
                )

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "replay_done",
                        "run_id": str(run_id),
                        "last_seq": replay_last_seq,
                    }
                )
            )


run_subscription_handler = RunSubscriptionHandler()
