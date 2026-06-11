"""JoySafeter event envelope for JoySafeter runner events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    from uuid_extensions import uuid7 as _uuid7
except ImportError:
    _uuid7 = None


def _new_event_id() -> uuid.UUID:
    """Generate a UUIDv7 (time-sortable) or fall back to uuid4."""
    if _uuid7 is not None:
        return _uuid7()
    return uuid.uuid4()


@dataclass
class JoySafeterEventEnvelope:
    """Single event flowing through the JoySafeterEventBus."""

    session_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]

    task_id: Optional[uuid.UUID] = None
    sandbox_id: Optional[uuid.UUID] = None
    event_id: Optional[uuid.UUID] = field(default_factory=_new_event_id)
    seq: int | None = None

    flush_immediately: bool = False
    is_status_change: bool = False
    stop_reason: Optional[dict[str, Any]] = None

    task_broadcast_payload: Optional[dict[str, Any]] = None
