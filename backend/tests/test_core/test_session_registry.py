"""Tests for SessionRegistry."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.core.agent.cli_backends.session_registry import SessionRegistry


def _make_session() -> MagicMock:
    """Return a lightweight stand-in for RuntimeSession (registry only checks identity)."""
    return MagicMock()


def test_register_and_get():
    registry = SessionRegistry()
    eid = uuid.uuid4()
    session = _make_session()
    registry.register(eid, session)
    assert registry.get(eid) is session


def test_unregister():
    registry = SessionRegistry()
    eid = uuid.uuid4()
    session = _make_session()
    registry.register(eid, session)
    registry.unregister(eid)
    assert registry.get(eid) is None


def test_get_nonexistent():
    registry = SessionRegistry()
    assert registry.get(uuid.uuid4()) is None


def test_unregister_nonexistent_is_noop():
    registry = SessionRegistry()
    # Should not raise
    registry.unregister(uuid.uuid4())


def test_register_overwrites():
    registry = SessionRegistry()
    eid = uuid.uuid4()
    session1 = _make_session()
    session2 = _make_session()
    registry.register(eid, session1)
    registry.register(eid, session2)
    assert registry.get(eid) is session2
