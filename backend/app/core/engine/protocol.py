"""
Execution engine protocol — the stable abstraction layer.

All execution engines (sandbox, graph, code, future engines) implement this protocol.
The orchestrator dispatches to engines via the registry; engines emit events via context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.common.app_errors import AppError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.event_types import ExecutionEventType


@dataclass
class ExecutionContext:
    """
    Provided to every engine at start time.

    Engines use this to emit events, update status, and signal completion.
    The context handles persistence (ExecutionEvent rows) and real-time push
    (WebSocket broadcast) — engines never touch those layers directly.
    """

    db: AsyncSession
    execution_id: uuid.UUID
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    credentials: dict[str, str] = field(default_factory=dict)
    auto_approve: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    debug: bool = False
    collector: Any = None  # ObservationCollector | None — import avoided for no circular deps

    # ---- set by orchestrator after construction ----
    _emit_fn: Any = None  # async (event_type, payload) -> None
    _status_fn: Any = None  # async (status) -> None
    _complete_fn: Any = None  # async (status, result_summary, error) -> None

    async def emit(self, event_type: ExecutionEventType, payload: dict | None = None) -> None:
        """Emit an execution event → persisted + broadcast."""
        if self._emit_fn:
            await self._emit_fn(event_type, payload or {})

    async def update_status(self, status: str) -> None:
        """Update Execution.status without completing."""
        if self._status_fn:
            await self._status_fn(status)

    async def complete(
        self,
        status: str,
        result_summary: str | None = None,
        error: AppError | None = None,
    ) -> None:
        """Mark execution as terminal → updates Run + Task status."""
        if self._complete_fn:
            await self._complete_fn(status, result_summary, error)


@runtime_checkable
class ExecutionEngine(Protocol):
    """
    Stable interface for all execution engines.

    Implementations:
      - CLIEngine   (runtime_kind: sandbox) — Docker + CLI-backed agent runtime
      - GraphEngine (runtime_kind: graph)   — LangGraph compiler
      - CodeEngine  (runtime_kind: code)    — in-process code agent runtime
    """

    engine_kind: str

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        definition_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """
        Start execution. Events flow through context.emit().

        Args:
            context: execution context with emit/status/complete callbacks
            release_runtime_binding: from AgentRelease.runtime_binding
            definition_kind: "graph" | "code" | "claude_code" | "codex" | "openclaw"
            definition_payload: from AgentVersion.definition_payload
            prompt: the user prompt or task goal
        """
        ...

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running execution."""
        ...

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Inject a human message into a running execution."""
        ...
