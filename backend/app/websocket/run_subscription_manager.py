"""In-memory run subscription manager."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class RunSubscriptionManager:
    def __init__(self) -> None:
        self._run_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._connection_runs: dict[WebSocket, set[str]] = defaultdict(set)

    async def add_subscription(self, websocket: WebSocket, run_id: str) -> None:
        self._run_connections[run_id].add(websocket)
        self._connection_runs[websocket].add(run_id)

    def remove_subscription(self, websocket: WebSocket, run_id: str) -> None:
        runs = self._connection_runs.get(websocket)
        if runs:
            runs.discard(run_id)
            if not runs:
                self._connection_runs.pop(websocket, None)

        connections = self._run_connections.get(run_id)
        if connections:
            connections.discard(websocket)
            if not connections:
                self._run_connections.pop(run_id, None)

    def disconnect(self, websocket: WebSocket) -> None:
        run_ids = list(self._connection_runs.get(websocket, set()))
        for run_id in run_ids:
            self.remove_subscription(websocket, run_id)

    async def broadcast_event(self, run_id: str, message: dict[str, Any]) -> int:
        connections = list(self._run_connections.get(run_id, set()))
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


run_subscription_manager = RunSubscriptionManager()

