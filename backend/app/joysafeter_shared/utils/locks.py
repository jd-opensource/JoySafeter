"""Postgres advisory-lock key derivation for session-scoped locks."""

import uuid

from app.joysafeter_shared.ids import EntityId, as_uuid


def session_advisory_lock_key(session_id: "uuid.UUID | EntityId") -> int:
    """Derive the 64-bit signed key for a session's ``pg_advisory_xact_lock``.

    Every acquirer of a session's advisory lock — SessionService status/seq
    writes and the worker batch writer — MUST derive the key identically or they
    will not mutually exclude, which risks interleaved seq allocation and status
    writes. This is the single source of that derivation. Accepts a typed
    ``SessionId`` or a bare UUID and always keys off the physical UUID.
    """
    return int.from_bytes(as_uuid(session_id).bytes[8:], "big", signed=True)
