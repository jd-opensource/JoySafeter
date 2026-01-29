"""WebSocket connection manager for real-time communication."""

import json
from datetime import datetime
from typing import Dict, List, Optional, Set

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages WebSocket connections for real-time communication."""

    def __init__(self):
        # Store active connections by session_id
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Store connection metadata
        self.connection_metadata: Dict[WebSocket, Dict] = {}

    async def connect(
        self, websocket: WebSocket, session_id: str, user_id: Optional[int] = None, already_accepted: bool = True
    ):
        """Accept a WebSocket connection and add it to the session group."""
        if not already_accepted:
            await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()

        self.active_connections[session_id].add(websocket)

        self.connection_metadata[websocket] = {
            "session_id": session_id,
            "user_id": user_id,
            "connected_at": str(datetime.utcnow()),
        }

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        metadata = self.connection_metadata.get(websocket)
        if not metadata:
            return

        session_id = metadata["session_id"]

        # Remove from session group
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

        # Remove metadata
        del self.connection_metadata[websocket]

        logger.info(f"WebSocket disconnected for session {session_id}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific WebSocket connection."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            self.disconnect(websocket)

    async def broadcast_to_session(self, message: dict, session_id: str):
        """Broadcast a message to all connections in a session."""
        if session_id not in self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting to connection: {e}")
                disconnected.add(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_to_all(self, message: dict):
        """Broadcast a message to all active connections."""
        for session_id in list(self.active_connections.keys()):
            await self.broadcast_to_session(message, session_id)

    def get_connection_count(self, session_id: Optional[str] = None) -> int:
        """Get number of active connections."""
        if session_id:
            return len(self.active_connections.get(session_id, set()))
        return sum(len(connections) for connections in self.active_connections.values())

    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self.active_connections.keys())

    def is_session_active(self, session_id: str) -> bool:
        """Check if a session has active connections."""
        return session_id in self.active_connections and len(self.active_connections[session_id]) > 0


# Global connection manager instance
manager = ConnectionManager()


# Import datetime for connection metadata
