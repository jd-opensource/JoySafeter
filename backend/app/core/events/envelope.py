"""
Canonical event envelope — the single shape all subscribers receive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.utils.datetime import utc_now


@dataclass
class ExecutionEventEnvelope:
    """Event envelope flowing through the event bus.

    Phase 1 subscribers (PersistenceSubscriber) fill in ``seq`` after
    persisting the event row.  All other fields are set by the publisher.
    ``seq`` is safe to mutate because Phase 2 runs only after Phase 1 commits.
    """

    execution_id: uuid.UUID
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    seq: int = 0

    # Run metadata — subscribers use these for routing decisions
    trigger_source: Optional[str] = None
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None

    # Completion-only fields
    terminal_status: Optional[str] = None
    result_summary: Optional[str] = None
