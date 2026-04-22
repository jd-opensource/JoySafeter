"""
Callback protocol for ExecutionRunner — breaks circular dependency.

ExecutionRunner calls these hooks after finalize/failure.
The concrete implementation lives in ExecutionLifecycleService.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from app.core.agent.cli_backends.base import CLIResult
# TODO: Phase 4/5 cleanup - MissionExecutionStatus removed; migrate to string literals
# from app.models.execution import MissionExecutionStatus
MissionExecutionStatus = type("MissionExecutionStatus", (), {
    "QUEUED": "queued", "DISPATCHED": "dispatched", "RUNNING": "running",
    "INTERRUPT_WAIT": "interrupt_wait", "APPROVAL_WAIT": "approval_wait",
    "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"
})()


@runtime_checkable
class RunnerCallbacks(Protocol):
    """Interface that ExecutionRunner uses to notify lifecycle events."""

    async def on_execution_finalized(
        self,
        execution_id: uuid.UUID,
        status: MissionExecutionStatus,
        result: CLIResult,
    ) -> None:
        """Called after execution reaches terminal state (COMPLETED/FAILED)."""
        ...

    async def on_execution_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        """Called when runner catches an unhandled exception."""
        ...
