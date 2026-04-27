"""WebSocket handler for execution event subscriptions."""

from __future__ import annotations

import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.common.app_errors import AppError, InvalidRequestError, NotFoundError
from app.core.database import AsyncSessionLocal
from app.services.execution_service import ExecutionService
from app.websocket.execution_subscription_manager import execution_subscription_manager


def _ws_error_frame(error: AppError) -> dict[str, object]:
    return {
        "type": "ws_error",
        "error": error.to_payload(),
    }


class ExecutionSubscriptionHandler:
    """Handles subscribe/unsubscribe frames for execution event streams."""

    async def handle_connection(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_text()
                await self._handle_frame(websocket, user_id, raw)
        except WebSocketDisconnect:
            pass
        finally:
            execution_subscription_manager.disconnect(websocket)

    async def _handle_frame(self, websocket: WebSocket, user_id: str, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_text(
                json.dumps(
                    _ws_error_frame(
                        InvalidRequestError(
                            "无效的 websocket 帧",
                            code="WEBSOCKET_INVALID_JSON",
                            data={"detail": "The execution subscription frame is not valid JSON."},
                        )
                    )
                )
            )
            return

        frame_type = frame.get("type")
        if frame_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
            return

        if frame_type == "unsubscribe":
            execution_id = frame.get("execution_id")
            if execution_id:
                execution_subscription_manager.remove_subscription(websocket, str(execution_id))
            return

        if frame_type != "subscribe":
            await websocket.send_text(
                json.dumps(
                    _ws_error_frame(
                        InvalidRequestError(
                            "未知的 websocket 帧类型",
                            code="WEBSOCKET_UNKNOWN_FRAME_TYPE",
                            data={"frame_type": frame_type},
                        )
                    )
                )
            )
            return

        execution_id_raw = frame.get("execution_id")
        if not execution_id_raw:
            await websocket.send_text(
                json.dumps(
                    _ws_error_frame(
                        InvalidRequestError(
                            "execution_id 是必填项",
                            code="WEBSOCKET_EXECUTION_ID_REQUIRED",
                            data=None,
                        )
                    )
                )
            )
            return

        try:
            execution_id = uuid.UUID(str(execution_id_raw))
        except ValueError:
            await websocket.send_text(
                json.dumps(
                    _ws_error_frame(
                        InvalidRequestError(
                            "execution_id 无效",
                            code="WEBSOCKET_INVALID_EXECUTION_ID",
                            data={"execution_id": execution_id_raw},
                        )
                    )
                )
            )
            return

        try:
            after_seq = int(frame.get("after_seq") or 0)
        except (ValueError, TypeError):
            await websocket.send_text(
                json.dumps(
                    _ws_error_frame(
                        InvalidRequestError(
                            "after_seq 无效",
                            code="WEBSOCKET_INVALID_AFTER_SEQ",
                            data={"after_seq": frame.get("after_seq")},
                        )
                    )
                )
            )
            return

        async with AsyncSessionLocal() as db:
            service = ExecutionService(db)
            execution = await service.get_execution(execution_id, user_id)
            if execution is None:
                await websocket.send_text(
                    json.dumps(
                        _ws_error_frame(
                            NotFoundError(
                                "执行不存在",
                                code="EXECUTION_NOT_FOUND",
                                data={"execution_id": str(execution_id)},
                            )
                        )
                    )
                )
                return

            snapshot = await service.get_snapshot(execution_id, user_id)
            if snapshot is None:
                await websocket.send_text(
                    json.dumps(
                        _ws_error_frame(
                            NotFoundError(
                                "执行快照不存在",
                                code="EXECUTION_SNAPSHOT_NOT_FOUND",
                                data={"execution_id": str(execution_id)},
                            )
                        )
                    )
                )
                return

            snapshot_last_seq = int(snapshot.last_seq or 0)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "snapshot",
                        "execution_id": str(execution_id),
                        "last_seq": snapshot_last_seq,
                        "status": snapshot.projection.get("status"),
                        "error": snapshot.projection.get("error"),
                        "events": [],
                    }
                )
            )

            await execution_subscription_manager.add_subscription(websocket, str(execution_id))

            catchup_after_seq = max(after_seq, snapshot_last_seq)
            events = await service.list_events_after(execution_id, user_id, after_seq=catchup_after_seq, limit=1000)
            replay_last_seq = snapshot_last_seq
            for event in events:
                seq = int(event.sequence_no)
                replay_last_seq = max(replay_last_seq, seq)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "event",
                            "execution_id": str(execution_id),
                            "seq": seq,
                            "event_type": event.event_type,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat() if event.created_at else None,
                        }
                    )
                )

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "replay_done",
                        "execution_id": str(execution_id),
                        "last_seq": replay_last_seq,
                    }
                )
            )


execution_subscription_handler = ExecutionSubscriptionHandler()
