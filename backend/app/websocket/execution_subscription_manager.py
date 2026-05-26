"""In-memory execution subscription manager."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ExecutionSubscriptionManager:
    """Tracks which WebSocket connections are subscribed to which execution IDs.

    Mirrors RunSubscriptionManager but scoped to CLI agent executions.
    """

    def __init__(self) -> None:
        self._exec_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._connection_execs: dict[WebSocket, set[str]] = defaultdict(set)

    async def add_subscription(self, websocket: WebSocket, execution_id: str) -> None:
        self._exec_connections[execution_id].add(websocket)
        self._connection_execs[websocket].add(execution_id)

    def remove_subscription(self, websocket: WebSocket, execution_id: str) -> None:
        execs = self._connection_execs.get(websocket)
        if execs:
            execs.discard(execution_id)
            if not execs:
                self._connection_execs.pop(websocket, None)

        connections = self._exec_connections.get(execution_id)
        if connections:
            connections.discard(websocket)
            if not connections:
                self._exec_connections.pop(execution_id, None)

    def disconnect(self, websocket: WebSocket) -> None:
        exec_ids = list(self._connection_execs.get(websocket, set()))
        for exec_id in exec_ids:
            self.remove_subscription(websocket, exec_id)

    async def broadcast_event(self, execution_id: str, message: dict[str, Any]) -> int:
        connections = list(self._exec_connections.get(execution_id, set()))
        success_count = 0
        disconnected: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_text(json.dumps(message, default=str))
                success_count += 1
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

        return success_count


execution_subscription_manager = ExecutionSubscriptionManager()
