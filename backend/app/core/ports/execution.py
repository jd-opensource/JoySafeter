"""
Execution ports — Protocol interfaces for core/ ↔ services/ decoupling.

core/ modules depend on these Protocols (not concrete service classes).
services/ modules provide the implementations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from app.core.events.event_types import ExecutionEventType


@dataclass
class EventContext:
    """Run-level metadata injected by the caller (e.g. ExecutionRunner).

    Allows event publishing to construct complete envelopes
    without querying the DB for run metadata on every event.
    """

    run_id: uuid.UUID
    workspace_id: uuid.UUID
    trigger_medium: Optional[str] = None
    run_purpose: Optional[str] = None
    thread_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None


@runtime_checkable
class ExecutionEventPort(Protocol):
    """Port for publishing execution events through the event bus.

    Implemented by: services/execution_event_adapter.py
    Used by: core/agent/cli_backends/execution_runner.py
    """

    def set_event_context(self, ctx: EventContext) -> None: ...

    async def mark_status(
        self,
        *,
        execution_id: uuid.UUID,
        status: str,
        container_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error: Mapping[str, Any] | None = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> Any: ...

    async def append_event(
        self,
        *,
        execution_id: uuid.UUID,
        event_type: ExecutionEventType,
        payload: dict[str, Any],
    ) -> Any: ...

    async def batch_append_events(
        self,
        *,
        execution_id: uuid.UUID,
        events: list[dict[str, Any]],
    ) -> list: ...

    async def complete_execution(
        self,
        *,
        execution_id: uuid.UUID,
        terminal_status: str,
        result_summary: Optional[dict] = None,
        error: Mapping[str, Any] | None = None,
        session_id: Optional[str] = None,
    ) -> None: ...


@runtime_checkable
class ExecutionReaderPort(Protocol):
    """Port for reading execution data without direct ORM queries in core/.

    Implemented by: services/execution_reader_adapter.py (Phase 2)
    Used by: core/agent/cli_backends/execution_runner.py
    """

    async def get_execution(self, execution_id: uuid.UUID) -> Any: ...

    async def get_run_for_execution(self, execution_id: uuid.UUID) -> Any: ...

    async def get_release_for_run(self, run_id: uuid.UUID) -> Any: ...

    async def get_task_auto_approve(self, task_id: uuid.UUID) -> bool: ...

    async def load_thread_history(
        self,
        thread_id: uuid.UUID,
        *,
        before_run_id: Optional[uuid.UUID] = None,
        max_turns: int = 20,
    ) -> list[tuple[str, str]]:
        """Return completed turn history for a Thread in chronological order.

        Each entry is ``(role, content)`` with ``role`` being ``"user"`` or
        ``"assistant"``. Entries for ``before_run_id`` and later are excluded
        so the caller can rebuild a prompt prefix for session recovery.
        ``max_turns`` caps how many *prior runs* are returned.
        """
        ...
