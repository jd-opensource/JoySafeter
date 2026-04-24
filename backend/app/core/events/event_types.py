"""
Canonical execution event types — the single source of truth for event naming.

Backend emitters MUST use these constants.  The frontend type union mirrors them.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionEventType(StrEnum):
    # Content events (mapped from CLI message types by ExecutionRunner)
    ASSISTANT_TEXT = "assistant_text"
    THINKING = "thinking"
    TOOL_USE_START = "tool_use_start"
    TOOL_USE_END = "tool_use_end"
    ERROR = "error"
    ARTIFACT_CREATED = "artifact_created"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    USER_MESSAGE = "user_message"

    # Lifecycle events
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_STATUS_CHANGE = "execution_status_change"
