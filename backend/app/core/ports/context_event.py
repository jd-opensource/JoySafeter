"""Context event bridge — typed interface for ExecutionContext callbacks."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from app.common.app_errors import AppError
from app.core.events.event_types import ExecutionEventType


@runtime_checkable
class ContextEventBridge(Protocol):
    """Typed callback bridge injected into ExecutionContext by the launcher.

    Replaces the untyped _emit_fn / _status_fn / _complete_fn fields.
    Engines call context.emit/update_status/complete which delegate here.
    """

    async def emit(self, event_type: ExecutionEventType, payload: dict) -> None: ...

    async def update_status(self, status: str) -> None: ...

    async def complete(
        self,
        status: str,
        result_summary: Optional[str] = None,
        error: Optional[AppError] = None,
    ) -> None: ...
