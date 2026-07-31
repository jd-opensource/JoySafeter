"""Utility functions for parsing and serializing prefixed joysafeter entity IDs.

The Rust agentd uses prefixed IDs in API responses (e.g., "agent_<uuid>", "sess_<uuid>").
These utilities handle bidirectional conversion.
"""

import uuid
from typing import Any


def same_id(left: Any, right: Any) -> bool:
    """Compare UUID-like identifiers by value across driver/uuid implementations."""
    return left is not None and right is not None and str(left) == str(right)


def parse_prefixed_id(value: str, prefix: str) -> uuid.UUID:
    """Strip an optional prefix and parse the remaining string as a UUID."""
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return uuid.UUID(value)


def serialize_prefixed_id(value: uuid.UUID, prefix: str) -> str:
    """Serialize a UUID with a prefix."""
    return f"{prefix}{value}"


def parse_agent_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "agent_")


def serialize_agent_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "agent_")


def parse_session_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "sess_")


def serialize_session_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "sess_")


def parse_task_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "task_")


def serialize_task_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "task_")


def parse_environment_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "env_")


def serialize_environment_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "env_")


def parse_memory_store_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "memstore_")


def serialize_memory_store_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "memstore_")


def parse_memory_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "mem_")


def serialize_memory_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "mem_")


def parse_memory_version_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "memver_")


def serialize_memory_version_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "memver_")


def parse_vault_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "vault_")


def serialize_vault_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "vault_")


def parse_credential_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "cred_")


def serialize_credential_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "cred_")


def parse_event_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "evt_")


def serialize_event_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "evt_")


def parse_session_memory_store_id(value: str) -> uuid.UUID:
    return parse_prefixed_id(value, "sesrsc_")


def serialize_session_memory_store_id(value: uuid.UUID) -> str:
    return serialize_prefixed_id(value, "sesrsc_")
