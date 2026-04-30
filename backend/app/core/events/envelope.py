"""
Canonical event envelope — the single shape all subscribers receive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.core.events.event_types import ExecutionEventType
from app.utils.datetime import utc_now


@dataclass
class ExecutionEventEnvelope:
    """Canonical event envelope flowing through the event bus."""

    execution_id: uuid.UUID
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: ExecutionEventType | str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    seq: int = 0  # filled by PersistenceSubscriber in Phase 1

    # Run metadata — subscribers use these for routing decisions
    trigger_medium: Optional[str] = None
    run_purpose: Optional[str] = None
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None

    # Completion-only fields
    terminal_status: Optional[str] = None
    result_summary: Optional[str] = None
    error: Optional[dict[str, Any]] = None  # ErrorDescriptor via AppError.to_payload()

    # Status-change fields (used by execution_status_change events)
    target_status: Optional[str] = None
    container_id: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
