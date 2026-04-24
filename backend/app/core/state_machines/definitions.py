"""
Centralized state transition definitions for all domain entities.

This is the single source of truth for:
- What statuses each entity can have
- What transitions are allowed between statuses
- Which statuses are terminal (no outbound transitions)
- How Run completion maps to Task status
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
AGENT_STATES: dict[str, set[str]] = {
    "draft":    {"active", "archived"},
    "active":   {"archived"},
    "archived": {"draft"},
}
AGENT_TERMINAL: set[str] = set()  # archived can be reverted

# ---------------------------------------------------------------------------
# AgentVersion
# ---------------------------------------------------------------------------
VERSION_STATES: dict[str, set[str]] = {
    "draft":  {"frozen"},
    "frozen": {"draft"},  # unfreeze
}
VERSION_TERMINAL: set[str] = set()

# ---------------------------------------------------------------------------
# AgentRelease
# ---------------------------------------------------------------------------
RELEASE_STATES: dict[str, set[str]] = {
    "ready":   {"retired"},
    "failed":  {"retired"},
    "retired": set(),
}
RELEASE_TERMINAL: set[str] = {"retired"}

# ---------------------------------------------------------------------------
# AgentRun
# ---------------------------------------------------------------------------
RUN_STATES: dict[str, set[str]] = {
    "pending":   {"running", "cancelled"},
    "running":   {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed":    set(),
    "cancelled": set(),
}
RUN_TERMINAL: set[str] = {"succeeded", "failed", "cancelled"}

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
EXECUTION_STATES: dict[str, set[str]] = {
    "pending":       {"dispatched", "running", "cancelled", "failed"},
    "dispatched":    {"running", "failed", "cancelled"},
    "running":       {"approval_wait", "succeeded", "failed", "cancelled"},
    "approval_wait": {"running", "cancelled"},
    "succeeded":     set(),
    "failed":        set(),
    "cancelled":     set(),
}
EXECUTION_TERMINAL: set[str] = {"succeeded", "failed", "cancelled"}

# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
TASK_STATES: dict[str, set[str]] = {
    "backlog":     {"todo", "in_progress", "cancelled"},
    "todo":        {"in_progress", "backlog", "cancelled"},
    "in_progress": {"done", "in_review", "cancelled", "backlog"},
    "in_review":   {"in_progress", "done", "backlog", "cancelled"},
    "done":        {"backlog"},
    "cancelled":   {"backlog"},
}
TASK_TERMINAL: set[str] = set()  # done/cancelled can be reopened via backlog

# ---------------------------------------------------------------------------
# Cross-entity sync: Run terminal status -> Task target status
# ---------------------------------------------------------------------------
RUN_TO_TASK_SYNC: dict[str, str] = {
    "pending":   "in_progress",
    "running":   "in_progress",
    "succeeded": "done",
    "failed":    "in_review",
    "cancelled": "backlog",
}
