"""Bounded backoff retry of a failed cron slot (resilience).

A *transient* fire failure must keep the SAME logical slot due (retained
``pending_slot_at``) and push ``next_run_at`` out by an exponential backoff, up
to ``scheduler_slot_max_retries`` attempts, without counting a consecutive
failure. Once retries are exhausted the slot is abandoned (advanced) and one
consecutive failure is recorded.

Unit-tested against a stubbed service so the state machine is exercised without a
database.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

pytestmark = pytest.mark.no_db

_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)


class _StubService(JoySafeterTriggerService):
    def __init__(self, trigger) -> None:
        self._trigger = trigger
        self.committed = 0
        self.db = SimpleNamespace(commit=self._commit)

    async def _commit(self) -> None:
        self.committed += 1

    async def get(self, trigger_id, project_id=None):
        return self._trigger

    async def _next_run_or_pause(self, trigger):
        return _FUTURE

    def _sync_config(self, trigger) -> None:
        pass


def _trigger():
    return SimpleNamespace(
        id="t1",
        slot_attempts=0,
        pending_slot_at=None,
        consecutive_failures=0,
        next_run_at=None,
        last_fired_slot=None,
        last_attempt_at=None,
        last_error=None,
        locked_by="worker-1",
        locked_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        enabled=True,
        auto_disabled_at=None,
        disabled_reason=None,
    )


@pytest.fixture(autouse=True)
def _fixed_scheduler_settings(monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    monkeypatch.setattr(settings, "scheduler_slot_max_retries", 3)
    monkeypatch.setattr(settings, "scheduler_retry_backoff_base_sec", 10)
    monkeypatch.setattr(settings, "scheduler_retry_backoff_cap_sec", 300)
    monkeypatch.setattr(settings, "scheduler_failure_threshold", 5)


@pytest.mark.asyncio
async def test_transient_failure_retries_same_slot_with_exponential_backoff():
    trigger = _trigger()
    svc = _StubService(trigger)
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    for expected_attempt, expected_backoff in [(1, 10), (2, 20), (3, 40)]:
        dead = await svc.record_fire_failure(trigger.id, slot, error="temp", transient=True)
        assert dead is False
        assert trigger.slot_attempts == expected_attempt
        # Same logical slot is retained so the retry keeps a coherent idempotency key.
        assert trigger.pending_slot_at == slot
        # Retry does NOT count a consecutive failure.
        assert trigger.consecutive_failures == 0
        assert trigger.locked_by is None and trigger.locked_at is None
        delta = (trigger.next_run_at - datetime.now(timezone.utc)).total_seconds()
        assert abs(delta - expected_backoff) < 2


@pytest.mark.asyncio
async def test_backoff_is_capped():
    from app.joysafeter_shared.config.settings import settings

    monkeypatch_cap = 25
    settings.scheduler_retry_backoff_cap_sec = monkeypatch_cap
    settings.scheduler_slot_max_retries = 9
    trigger = _trigger()
    trigger.slot_attempts = 5  # next attempt -> 6, base*2**5 = 320 >> cap
    svc = _StubService(trigger)
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    await svc.record_fire_failure(trigger.id, slot, error="temp", transient=True)
    delta = (trigger.next_run_at - datetime.now(timezone.utc)).total_seconds()
    assert abs(delta - monkeypatch_cap) < 2


@pytest.mark.asyncio
async def test_exhausted_retries_abandon_slot_and_count_one_failure():
    trigger = _trigger()
    trigger.slot_attempts = 3  # already at max; next transient attempt exhausts
    svc = _StubService(trigger)
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    dead = await svc.record_fire_failure(trigger.id, slot, error="temp", transient=True)
    assert dead is False
    # Slot abandoned: advanced to the next future instant, retry state reset.
    assert trigger.slot_attempts == 0
    assert trigger.pending_slot_at is None
    assert trigger.next_run_at == _FUTURE
    assert trigger.last_fired_slot == slot
    assert trigger.consecutive_failures == 1


@pytest.mark.asyncio
async def test_permanent_failure_advances_immediately_without_retry():
    trigger = _trigger()
    svc = _StubService(trigger)
    slot = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

    dead = await svc.record_fire_failure(trigger.id, slot, error="missing agent", transient=False)
    assert dead is False
    # A permanent failure is not retried: straight to advance + one failure.
    assert trigger.slot_attempts == 0
    assert trigger.pending_slot_at is None
    assert trigger.next_run_at == _FUTURE
    assert trigger.consecutive_failures == 1
