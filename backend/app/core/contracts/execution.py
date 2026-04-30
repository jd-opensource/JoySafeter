"""Canonical execution contract values."""

from __future__ import annotations

from typing import Literal

RunStatusLiteral = Literal["pending", "running", "succeeded", "failed", "cancelled"]
ExecutionStatusLiteral = Literal[
    "pending",
    "dispatched",
    "running",
    "approval_wait",
    "succeeded",
    "failed",
    "cancelled",
]
ReleaseStatusLiteral = Literal["ready", "active", "superseded", "failed", "retired"]
TriggerMediumLiteral = Literal[
    "api",
    "scheduler",
    "system",
    "ui",
]
RunPurposeLiteral = Literal[
    "production",
    "draft_test",
    "debug",
    "internal_builder",
]

RUN_STATUSES: set[str] = {"pending", "running", "succeeded", "failed", "cancelled"}
ACTIVE_RUN_STATUSES: set[str] = {"pending", "running"}
TERMINAL_RUN_STATUSES: set[str] = {"succeeded", "failed", "cancelled"}

EXECUTION_STATUSES: set[str] = {
    "pending",
    "dispatched",
    "running",
    "approval_wait",
    "succeeded",
    "failed",
    "cancelled",
}
ACTIVE_EXECUTION_STATUSES: set[str] = {"pending", "dispatched", "running", "approval_wait"}
TERMINAL_EXECUTION_STATUSES: set[str] = {"succeeded", "failed", "cancelled"}

RELEASE_STATUSES: set[str] = {"ready", "active", "superseded", "failed", "retired"}
TRIGGER_MEDIUMS: set[str] = {
    "api",
    "scheduler",
    "system",
    "ui",
}
RUN_PURPOSES: set[str] = {
    "production",
    "draft_test",
    "debug",
    "internal_builder",
}
