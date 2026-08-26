"""WebSocket notification manager for real-time user notifications."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, TypedDict

from fastapi import WebSocket

from app.joysafeter_shared.ids import UserId
from app.joysafeter_shared.json_boundary import normalize_json_value
from app.joysafeter_shared.utils.datetime import utc_now


class NotificationType(str, Enum):
    """Types of real-time notification events."""

    INVITATION_RECEIVED = "invitation_received"
    INVITATION_ACCEPTED = "invitation_accepted"
    INVITATION_REJECTED = "invitation_rejected"
    INVITATION_CANCELLED = "invitation_cancelled"
    TASK_ACTIVITY_ADDED = "task_activity_added"
    TASK_UPDATED = "task_updated"
    EXECUTION_STATUS_CHANGED = "execution_status_changed"
    PING = "ping"
    PONG = "pong"
    CONNECTED = "connected"


class ConnectionMetadata(TypedDict):
    """Typed metadata retained for each active notification connection."""

    user_id: UserId
    connected_at: str


class NotificationManager:
    """Manages user-based WebSocket connections for notifications."""

    def __init__(self):
        """Initialize with empty connection registries."""
        self.user_connections: dict[UserId, set[WebSocket]] = {}
        self.connection_metadata: dict[WebSocket, ConnectionMetadata] = {}

    async def connect(self, websocket: WebSocket, user_id: UserId, already_accepted: bool = True) -> None:
        """Register a WebSocket connection for a user and send a connected event."""
        if not already_accepted:
            await websocket.accept()

        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()

        self.user_connections[user_id].add(websocket)
        self.connection_metadata[websocket] = {
            "user_id": user_id,
            "connected_at": utc_now().isoformat(),
        }

        await self.send_to_connection(
            websocket,
            {
                "type": NotificationType.CONNECTED.value,
                "timestamp": utc_now().isoformat(),
            },
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket and clean up its metadata."""
        metadata = self.connection_metadata.get(websocket)
        if not metadata:
            return

        user_id = metadata["user_id"]

        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

        del self.connection_metadata[websocket]

    async def send_to_connection(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        """Send a message to a single connection, disconnecting on failure."""
        try:
            await websocket.send_text(json.dumps(normalize_json_value(message), allow_nan=False))
            return True
        except Exception:
            self.disconnect(websocket)
            return False

    async def send_to_user(self, user_id: UserId, message: dict[str, Any]) -> int:
        """Send a message to all connections for a user.

        Returns:
            The number of connections that received the message.
        """
        if user_id not in self.user_connections:
            return 0

        if "timestamp" not in message:
            message["timestamp"] = utc_now().isoformat()

        success_count = 0
        disconnected = set()

        for connection in self.user_connections[user_id]:
            try:
                await connection.send_text(json.dumps(normalize_json_value(message), allow_nan=False))
                success_count += 1
            except Exception:
                disconnected.add(connection)

        for connection in disconnected:
            self.disconnect(connection)

        return success_count

    async def send_to_users(self, user_ids: list[UserId], message: dict[str, Any]) -> dict[UserId, int]:
        """Send a message to multiple users, returning per-user delivery counts."""
        results = {}
        for user_id in user_ids:
            results[user_id] = await self.send_to_user(user_id, message)
        return results

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Send a message to all connected users."""
        total_sent = 0
        for user_id in list(self.user_connections.keys()):
            total_sent += await self.send_to_user(user_id, message)
        return total_sent

    def is_user_online(self, user_id: UserId) -> bool:
        """Return True if the user has at least one active connection."""
        return user_id in self.user_connections and len(self.user_connections[user_id]) > 0

    def get_online_users(self) -> list[UserId]:
        """Return a list of user IDs with active connections."""
        return list(self.user_connections.keys())

    def get_user_connection_count(self, user_id: UserId) -> int:
        """Return the number of active connections for a user."""
        return len(self.user_connections.get(user_id, set()))

    def get_total_connections(self) -> int:
        """Return the total number of active WebSocket connections."""
        return sum(len(conns) for conns in self.user_connections.values())


notification_manager = NotificationManager()
