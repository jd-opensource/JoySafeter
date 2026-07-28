"""Contract: advance_after_fire records an attempt only when told to.

A cron slot that was intentionally skipped (FORBID with a prior run still
active, or a missing/archived target) must advance the slot and release the
lock WITHOUT recording a success/failure attempt — otherwise a forbidden skip
would be bookkept as a success (clearing last_error / resetting
consecutive_failures / stamping last_success_at), which is misleading.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

pytestmark = pytest.mark.no_db

_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)
_SENTINEL_TS = datetime(2000, 1, 1, tzinfo=timezone.utc)


class _StubService(JoySafeterTriggerService):
    """Service with the DB-touching bits stubbed so advance_after_fire is unit-testable."""

    def __init__(self, trigger) -> None:
        self._trigger = trigger
        self.committed = False
        self.db = SimpleNamespace(commit=self._commit)

    async def _commit(self) -> None:
        self.committed = True

    async def get(self, trigger_id, project_id=None):
        return self._trigger

    async def _next_run_or_pause(self, trigger):
        return _FUTURE

    def _sync_config(self, trigger) -> None:
        pass


def _trigger():
    return SimpleNamespace(
        id="t1",
        session_mode="fresh",
        cron_expr="*/5 * * * *",
        timezone="UTC",
        enabled=True,
        locked_by="worker-1",
        locked_at=_SENTINEL_TS,
        next_run_at=None,
        last_fired_slot=None,
        last_attempt_at=_SENTINEL_TS,
        last_success_at=_SENTINEL_TS,
        last_error="prior error",
        consecutive_failures=3,
        last_task_id="prior-task",
        last_session_id="prior-session",
        reusable_session_id=None,
        last_payload={"prior": True},
    )


@pytest.mark.asyncio
async def test_skip_advances_slot_and_releases_lock_without_recording_attempt():
    trigger = _trigger()
    svc = _StubService(trigger)
    fired = datetime.now(timezone.utc) - timedelta(hours=1)

    await svc.advance_after_fire(trigger.id, fired, record_attempt=False)

    # Slot advanced + lock released.
    assert trigger.last_fired_slot == fired
    assert trigger.next_run_at == _FUTURE
    assert trigger.locked_by is None
    assert trigger.locked_at is None
    assert svc.committed is True
    # Attempt bookkeeping left byte-for-byte untouched (skip != success/failure).
    assert trigger.last_attempt_at == _SENTINEL_TS
    assert trigger.last_success_at == _SENTINEL_TS
    assert trigger.last_error == "prior error"
    assert trigger.consecutive_failures == 3
    assert trigger.last_task_id == "prior-task"
    assert trigger.last_payload == {"prior": True}


@pytest.mark.asyncio
async def test_fired_records_success_and_clears_error():
    trigger = _trigger()
    svc = _StubService(trigger)
    fired = datetime.now(timezone.utc)

    await svc.advance_after_fire(
        trigger.id, fired, success=True, task_id="new-task", session_id="new-session", payload={"ok": 1}
    )

    assert trigger.last_success_at is not None and trigger.last_success_at != _SENTINEL_TS
    assert trigger.last_error is None
    assert trigger.consecutive_failures == 0
    assert trigger.last_task_id == "new-task"
    assert trigger.last_session_id == "new-session"
    assert trigger.last_payload == {"ok": 1}
    assert trigger.locked_by is None


@pytest.mark.asyncio
async def test_failed_records_error_and_increments_failures():
    trigger = _trigger()
    svc = _StubService(trigger)
    fired = datetime.now(timezone.utc)

    await svc.advance_after_fire(trigger.id, fired, success=False, error="boom")

    assert trigger.last_error == "boom"
    assert trigger.consecutive_failures == 4
    assert trigger.last_success_at == _SENTINEL_TS  # not stamped on failure
    assert trigger.locked_by is None
