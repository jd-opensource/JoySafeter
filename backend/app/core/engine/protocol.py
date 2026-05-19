"""
Execution engine protocol — the stable abstraction layer.

All execution engines implement this protocol.
The orchestrator dispatches to engines via the registry; engines emit events via context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import AppError
from app.core.events.event_types import ExecutionEventType
from app.core.ports.context_event import ContextEventBridge
from app.core.ports.model import ModelPort
from app.core.ports.observation import ObservationCollectorPort


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

    # Ports — injected by launcher, used by engines.
    collector: ObservationCollectorPort | None = None
    model_port: ModelPort | None = None
    runner_factory: Any = None  # Callable[[AsyncSession], ExecutionRunner]
    _event_bridge: ContextEventBridge | None = None

    async def emit(self, event_type: ExecutionEventType, payload: dict | None = None) -> None:
        """Emit an execution event → persisted + broadcast."""
        if self._event_bridge:
            await self._event_bridge.emit(event_type, payload or {})

    async def update_status(self, status: str) -> None:
        """Update Execution.status without completing."""
        if self._event_bridge:
            await self._event_bridge.update_status(status)

    async def complete(
        self,
        status: str,
        result_summary: str | None = None,
        error: AppError | None = None,
    ) -> None:
        """Mark execution as terminal → updates Run + Task status."""
        if self._event_bridge:
            await self._event_bridge.complete(status, result_summary, error)


@dataclass(frozen=True)
class EngineCapabilities:
    supports_cancel: bool = False
    supports_message_injection: bool = False
    supports_debug_observation: bool = False
    supports_artifacts: bool = False
    supports_approval: bool = False


@runtime_checkable
class ExecutionEngine(Protocol):
    """
    Stable interface for all execution engines.

    User-facing engines:
      - LangGraphVisualEngine  (engine_kind: langgraph_visual)
      - LangGraphCodeEngine    (engine_kind: langgraph_code)
      - ClaudeCodeEngine       (engine_kind: claude_code)
      - CodexEngine            (engine_kind: codex)
      - OpenClawEngine         (engine_kind: openclaw)

    Internal platform engines:
      - CopilotEngine          (engine_kind: build_copilot)
    """

    engine_kind: str
    capabilities: EngineCapabilities

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """
        Start execution. Events flow through context.emit().

        Args:
            context: execution context with emit/status/complete callbacks
            release_runtime_binding: from AgentRelease.runtime_binding
            engine_kind: "langgraph_visual" | "langgraph_code" | "claude_code" | "codex" | "openclaw"
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
