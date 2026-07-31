"""A hung fire must not wedge the sweep — it is bounded and retried.

Each fire is wrapped in ``asyncio.wait_for(_fire, timeout=scheduler_fire_timeout_sec)``.
When a fire exceeds the timeout the resulting ``asyncio.TimeoutError`` is
classified transient, so ``record_fire_failure(transient=True)`` retries the slot
on a later tick instead of the hung fire blocking every other trigger.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.joysafeter_worker.scheduler.loop import SchedulerLoop, _is_transient_fire_error

pytestmark = pytest.mark.no_db


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_timeout_error_classified_transient():
    assert _is_transient_fire_error(asyncio.TimeoutError()) is True


@pytest.mark.asyncio
async def test_hung_fire_times_out_and_is_retried_transiently(monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    monkeypatch.setattr(settings, "scheduler_fire_timeout_sec", 0.05)

    trigger = SimpleNamespace(id=uuid4(), next_run_at=datetime.now(timezone.utc), pending_slot_at=None)
    captured: list = []

    async def claim_due(self, **kwargs):
        return [trigger]

    async def record_fire_failure(self, trigger_id, fired_slot, *, error, transient, expected_locked_by=None):
        captured.append((trigger_id, transient, expected_locked_by))
        return False

    async def hung_fire(self, trigger_arg, fired_slot):
        await asyncio.sleep(5)  # far exceeds the 0.05s fire timeout

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.claim_due_cron_triggers",
        claim_due,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.record_fire_failure",
        record_fire_failure,
    )
    monkeypatch.setattr(SchedulerLoop, "_fire", hung_fire)

    await SchedulerLoop(worker_id="timeout-worker")._tick()

    assert captured == [(trigger.id, True, "timeout-worker")]
