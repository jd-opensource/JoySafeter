"""JoySafeter event envelope for JoySafeter runner events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, cast

try:
    from uuid_extensions import uuid7 as _uuid7
except ImportError:
    _uuid7 = None


# Session status-change event types the two-phase bus routes persist-then-broadcast,
# and that the async batch/stream persisters skip (they are persisted inline). Shared
# here so the bus and both persist subscribers cannot drift out of sync.
STATUS_EVENT_TYPES = frozenset(
    {
        "session.status_running",
        "session.status_idle",
        "session.status_rescheduling",
        "session.status_terminated",
    }
)


def _new_event_id() -> uuid.UUID:
    """Generate a UUIDv7 (time-sortable) or fall back to uuid4."""
    if _uuid7 is not None:
        return cast(uuid.UUID, _uuid7())
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
    suppress_broadcast: bool = False
    stop_reason: Optional[dict[str, Any]] = None

    task_broadcast_payload: Optional[dict[str, Any]] = None
