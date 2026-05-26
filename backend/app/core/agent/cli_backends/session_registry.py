"""In-memory registry of active RuntimeSessions, keyed by execution_id."""

from __future__ import annotations

import uuid
from typing import Optional

from .base import RuntimeSession


class SessionRegistry:
    """Thread-safe registry of active execution sessions."""

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, RuntimeSession] = {}

    def register(self, execution_id: uuid.UUID, session: RuntimeSession) -> None:
        self._sessions[execution_id] = session

    def get(self, execution_id: uuid.UUID) -> Optional[RuntimeSession]:
        return self._sessions.get(execution_id)

    def unregister(self, execution_id: uuid.UUID) -> None:
        self._sessions.pop(execution_id, None)


# Module-level singleton
session_registry = SessionRegistry()
