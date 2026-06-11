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
    RUN_STATUS_CHANGE = "run_status_change"

    # Copilot events (mapped from CopilotService stream events by CopilotEngine)
    COPILOT_STATUS = "copilot_status"
    COPILOT_CONTENT = "copilot_content"
    COPILOT_THOUGHT_STEP = "copilot_thought_step"
    COPILOT_TOOL_CALL = "copilot_tool_call"
    COPILOT_TOOL_RESULT = "copilot_tool_result"
    COPILOT_RESULT = "copilot_result"
