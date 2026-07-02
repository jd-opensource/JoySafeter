"""Foundation 2 — poison-message dead-letter cap on the event-stream consumer.

A message that decodes but can never be persisted is never acked, so the
worker's ``xautoclaim`` reclaims it forever and starves the head of the queue.
The consumer now caps redeliveries: once a message's delivery count crosses
``event_stream_max_deliveries`` it is copied to the dead-letter stream and
acked, so a poison event can't loop indefinitely.
"""

import pytest

from app.joysafeter_worker.events.stream_consumer import (
    EventStreamWorker,
    _ids_over_delivery_limit,
)


def test_ids_over_delivery_limit_selects_only_exhausted():
    pending = [
        {"message_id": "a-0", "times_delivered": 5},   # at the cap, not over
        {"message_id": "b-0", "times_delivered": 6},   # over the cap
        {"message_id": "c-0"},                          # missing count -> treated as 0
    ]
    assert _ids_over_delivery_limit(pending, 5) == ["b-0"]


class _FakeRedis:
    """Minimal stand-in exercising the real _dead_letter_exhausted control flow."""

    def __init__(self, pending: list[dict], entries: dict[str, dict]):
        self._pending = pending
        self._entries = entries
        self.dead_added: list[tuple[str, dict]] = []
        self.acked: list[str] = []

    async def xpending_range(self, stream, group, min, max, count):
        return self._pending

    async def xrange(self, stream, min, max):
        fields = self._entries.get(min)
        return [(min, fields)] if fields is not None else []

    async def xadd(self, stream, fields):
        self.dead_added.append((stream, fields))
        return "dead-0"

    async def xack(self, stream, group, message_id):
        self.acked.append(message_id)


@pytest.mark.asyncio
async def test_poison_messages_are_dead_lettered_and_acked():
    worker = EventStreamWorker(stream_key="joysafeter:events", group="g")
    pending = [
        {"message_id": "1-0", "times_delivered": 99},  # poison
        {"message_id": "2-0", "times_delivered": 1},   # healthy, still retrying
        {"message_id": "3-0", "times_delivered": 99},  # poison
    ]
    entries = {"1-0": {"event_type": "agent.message"}, "3-0": {"event_type": "span.x"}}
    fake = _FakeRedis(pending, entries)

    n = await worker._dead_letter_exhausted(fake)

    assert n == 2, "both poison messages must be dead-lettered"
    assert fake.acked == ["1-0", "3-0"], "only poison messages are acked out of the pending list"
    assert [stream for stream, _ in fake.dead_added] == [
        "joysafeter:events:dead",
        "joysafeter:events:dead",
    ], "poison messages are copied to the dead-letter stream"
    # The healthy, still-retrying message is left untouched for normal reclaim.
    assert "2-0" not in fake.acked
    # The dead-letter payload is annotated so an operator can trace it.
    _, first_dead = fake.dead_added[0]
    assert first_dead["_original_message_id"] == "1-0"
    assert first_dead["_dead_letter_reason"] == "max_deliveries_exceeded"


@pytest.mark.asyncio
async def test_dead_letter_disabled_when_max_deliveries_zero(monkeypatch):
    from app.joysafeter_shared.config.settings import joysafeter_config

    monkeypatch.setattr(joysafeter_config, "event_stream_max_deliveries", 0)
    worker = EventStreamWorker(stream_key="joysafeter:events", group="g")
    fake = _FakeRedis([{"message_id": "1-0", "times_delivered": 999}], {"1-0": {}})

    n = await worker._dead_letter_exhausted(fake)

    assert n == 0 and fake.acked == [], "max_deliveries<=0 disables the dead-letter cap"
