"""Foundation 2 — event batch queue saturation must not drop durable events."""

import asyncio
import uuid

import pytest

from app.joysafeter_shared.ids import SessionId
from app.joysafeter_worker.events import batch_writer as bw
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchConfig, EventBatchSender

pytestmark = pytest.mark.no_db


def _event() -> BufferedEvent:
    return BufferedEvent(
        session_id=SessionId.new(),
        event_type="agent.message",
        payload={"content": "hello"},
        seq=1,
        id=uuid.uuid4(),
    )


async def _queue_put_timeout(awaitable, timeout):
    # ``Queue.put`` has already produced a coroutine before wait_for is called.
    # Close it so the test does not leave an un-awaited coroutine warning.
    if hasattr(awaitable, "close"):
        awaitable.close()
    raise asyncio.TimeoutError


@pytest.mark.asyncio
async def test_queue_full_writes_synchronously_instead_of_dropping(monkeypatch):
    sender = EventBatchSender(EventBatchConfig(enabled=True, max_size=1))
    event = _event()
    persisted: list[BufferedEvent] = []
    published: list[BufferedEvent] = []

    async def write_single(evt):
        persisted.append(evt)
        return evt

    async def publish_inserted(events):
        published.extend(events)

    monkeypatch.setattr(bw.asyncio, "wait_for", _queue_put_timeout)
    monkeypatch.setattr(sender, "_write_single", write_single)
    monkeypatch.setattr(sender, "_publish_inserted", publish_inserted)

    await sender.send(event)

    assert persisted == [event], "queue saturation must fall back to durable synchronous write"
    assert published == [event], "synchronously inserted events must still reach realtime subscribers"


@pytest.mark.asyncio
async def test_queue_full_sync_write_failure_propagates(monkeypatch):
    sender = EventBatchSender(EventBatchConfig(enabled=True, max_size=1))

    async def write_single(_evt):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(bw.asyncio, "wait_for", _queue_put_timeout)
    monkeypatch.setattr(sender, "_write_single", write_single)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await sender.send(_event())


@pytest.mark.asyncio
async def test_individual_retry_exhaustion_is_visible_in_health(monkeypatch):
    sender = EventBatchSender(EventBatchConfig(enabled=True, max_size=1))
    event = _event()

    async def write_single(_evt):
        raise RuntimeError("database unavailable")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(sender, "_write_single", write_single)
    monkeypatch.setattr(bw.asyncio, "sleep", no_sleep)

    await sender._retry_individual([event])

    health = sender.health_snapshot()
    assert health["status"] == "degraded"
    assert health["lost_event_count"] == 1
    assert health["last_lost_event"]["event_type"] == event.event_type
    assert "database unavailable" in health["last_lost_event"]["error"]
