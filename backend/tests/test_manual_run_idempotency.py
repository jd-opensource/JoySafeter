"""Manual ``/run`` idempotency key derivation (double-click de-duplication).

The old key was a random uuid, so every click produced a new run. The manual
provider now derives a deterministic key: an explicit ``Idempotency-Key`` header
when supplied, else a per-(trigger, user, 10s-window) key that collapses
accidental double-clicks. The task table's unique idempotency constraint then
enforces the actual de-dup.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.triggers import get_provider

pytestmark = pytest.mark.no_db


def _trigger():
    return SimpleNamespace(id="TID", name="run me", type="webhook", cron_expr=None, timezone=None, last_fired_slot=None)


def test_explicit_header_is_used_verbatim():
    key = get_provider("manual").idempotency_key(_trigger(), idempotency_header="abc-123", user_id="u")
    assert key == "trigger:TID:manual:abc-123"


def test_same_user_same_window_dedups():
    provider = get_provider("manual")
    t = _trigger()
    now = datetime(2026, 7, 27, 12, 0, 3, tzinfo=timezone.utc)
    later_same_window = datetime(2026, 7, 27, 12, 0, 9, tzinfo=timezone.utc)
    assert provider.idempotency_key(t, user_id="u", now=now) == provider.idempotency_key(
        t, user_id="u", now=later_same_window
    )


def test_next_window_is_distinct():
    provider = get_provider("manual")
    t = _trigger()
    now = datetime(2026, 7, 27, 12, 0, 3, tzinfo=timezone.utc)
    next_window = datetime(2026, 7, 27, 12, 0, 33, tzinfo=timezone.utc)
    assert provider.idempotency_key(t, user_id="u", now=now) != provider.idempotency_key(
        t, user_id="u", now=next_window
    )


def test_different_user_is_distinct():
    provider = get_provider("manual")
    t = _trigger()
    now = datetime(2026, 7, 27, 12, 0, 3, tzinfo=timezone.utc)
    assert provider.idempotency_key(t, user_id="a", now=now) != provider.idempotency_key(t, user_id="b", now=now)
