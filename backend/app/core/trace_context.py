"""Trace context propagation via contextvars.

Provides a single trace_id that flows through the entire async call chain:
HTTP middleware / WS handler → StreamState → LangGraph → tools → persistence.
"""

import uuid
from contextvars import ContextVar

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def set_trace_id(trace_id: str | None = None) -> str:
    """Set trace_id for the current async context.

    Always normalizes to a valid UUID string. If the input is not a
    valid UUID (e.g., a free-form client request_id), a new UUID is
    generated instead. Returns the trace_id.
    """
    tid = _normalize_to_uuid(trace_id) if trace_id else str(uuid.uuid4())
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    """Get the current trace_id (empty string if not set)."""
    return _trace_id_var.get()


def _normalize_to_uuid(value: str) -> str:
    """Return value if it's a valid UUID string, otherwise generate a new UUID."""
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return str(uuid.uuid4())
