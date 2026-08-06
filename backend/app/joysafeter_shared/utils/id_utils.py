"""Identifier helpers shared by domain services."""

import uuid
from typing import Any


def same_id(left: Any, right: Any) -> bool:
    """Compare UUID-like identifiers by value across driver/uuid implementations."""
    return left is not None and right is not None and str(left) == str(right)


def format_prefixed_id(value: Any, prefix: str) -> str:
    """Format a UUID-like value using the canonical public entity prefix."""
    normalized = str(value)
    return normalized if normalized.startswith(prefix) else f"{prefix}{normalized}"


def format_agent_id(value: Any) -> str:
    return format_prefixed_id(value, "agent_")


def format_session_id(value: Any) -> str:
    return format_prefixed_id(value, "sess_")


def format_task_id(value: Any) -> str:
    return format_prefixed_id(value, "task_")


def format_sandbox_id(value: Any) -> str:
    return format_prefixed_id(value, "sbx_")


def _parse_prefixed_id(value: str, prefix: str) -> uuid.UUID:
    """Strip an optional prefix and parse the remaining string as a UUID."""
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return uuid.UUID(value)


def parse_event_id(value: str) -> uuid.UUID:
    return _parse_prefixed_id(value, "evt_")
