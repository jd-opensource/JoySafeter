from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConductorEventEnvelope:
    """Single event flowing through the ConductorEventBus.

    Constructed by the gRPC server; consumed by subscribers.
    """

    session_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]

    task_id: Optional[uuid.UUID] = None
    sandbox_id: Optional[uuid.UUID] = None
    event_id: Optional[uuid.UUID] = None
    seq: int = 0

    flush_immediately: bool = False
    is_status_change: bool = False
    stop_reason: Optional[dict[str, Any]] = None

    task_broadcast_payload: Optional[dict[str, Any]] = None
