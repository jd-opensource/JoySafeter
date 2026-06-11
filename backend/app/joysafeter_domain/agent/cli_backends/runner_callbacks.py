"""
Callback protocol for ExecutionRunner — breaks circular dependency.

ExecutionRunner calls these hooks after finalize/failure.
The concrete implementation lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from app.joysafeter_domain.agent.cli_backends.base import CLIResult


@runtime_checkable
class RunnerCallbacks(Protocol):
    """Interface that ExecutionRunner uses to notify lifecycle events."""

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: str,
        result: CLIResult,
    ) -> None:
        """Called after execution reaches terminal state (completed/failed)."""
        ...

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called when runner catches an unhandled exception."""
        ...
