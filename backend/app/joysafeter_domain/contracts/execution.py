"""Canonical execution contract values.

Single source of truth for all status literals, trigger mediums, and run
purposes.  The StrEnum classes are the authoritative definitions; Literal
types and plain sets are derived from them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal


# ---------------------------------------------------------------------------
# Trigger medium — HOW the run was initiated
# ---------------------------------------------------------------------------
class TriggerMedium(StrEnum):
    API = "api"
    SCHEDULER = "scheduler"
    SYSTEM = "system"
    UI = "ui"


TriggerMediumLiteral = Literal["api", "scheduler", "system", "ui"]
TRIGGER_MEDIUMS: set[str] = {m.value for m in TriggerMedium}


# ---------------------------------------------------------------------------
# Run purpose — WHY the run exists
# ---------------------------------------------------------------------------
class RunPurpose(StrEnum):
    PRODUCTION = "production"
    DRAFT_TEST = "draft_test"
    DEBUG = "debug"
    INTERNAL_BUILDER = "internal_builder"


RunPurposeLiteral = Literal["production", "draft_test", "debug", "internal_builder"]
RUN_PURPOSES: set[str] = {p.value for p in RunPurpose}


# ---------------------------------------------------------------------------
# Status literals & sets
# ---------------------------------------------------------------------------
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
