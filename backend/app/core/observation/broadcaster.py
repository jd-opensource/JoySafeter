"""WebSocket broadcaster for observation events — reuses existing WS transport."""
from __future__ import annotations

import uuid
from typing import Any, Callable, Coroutine


class ObservationBroadcaster:
    def __init__(
        self,
        execution_id: uuid.UUID,
        *,
        broadcast_fn: Callable[[uuid.UUID, dict], Coroutine[Any, Any, None]] | None = None,
    ):
        self._execution_id = execution_id
        self._seq = 0
        self._broadcast_fn = broadcast_fn

    async def emit(self, event: str, observation: dict) -> None:
        self._seq += 1
        message = {
            "channel": "observation",
            "trace_id": str(self._execution_id),
            "seq": self._seq,
            "event": event,
            "observation": observation,
        }
        if self._broadcast_fn:
            await self._broadcast_fn(self._execution_id, message)
