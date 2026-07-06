"""Foundation 2 — EventBus persist failures must be visible to health checks."""

import uuid

import pytest

from app.joysafeter_orchestrator.events.bus import JoySafeterEventBus
from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.events.event_persist import EventPersistSubscriber
from app.joysafeter_orchestrator.events.stream_publisher import EventStreamPersistSubscriber
from app.joysafeter_orchestrator.events.subscriber import SubscriberPhase


class _FailingPersistSubscriber:
    name = "failing_persist"
    phase = SubscriberPhase.PERSIST

    async def handle(self, envelope):
        raise RuntimeError(f"persist failed for {envelope.event_type}")


class _NoopBroadcastSubscriber:
    name = "noop_broadcast"
    phase = SubscriberPhase.BROADCAST

    async def handle(self, envelope):
        return None


class _SuppressingPersistSubscriber:
    name = "suppressing_persist"
    phase = SubscriberPhase.PERSIST

    async def handle(self, envelope):
        envelope.suppress_broadcast = True


class _RecordingBroadcastSubscriber:
    name = "recording_broadcast"
    phase = SubscriberPhase.BROADCAST

    def __init__(self):
        self.events = []

    async def handle(self, envelope):
        self.events.append(envelope)


class _RecordingPersistSubscriber:
    name = "recording_persist"
    phase = SubscriberPhase.PERSIST

    def __init__(self):
        self.events = []

    async def handle(self, envelope):
        self.events.append(envelope)


class _RecordingEventBuffer:
    def __init__(self):
        self.events = []

    async def send(self, event):
        self.events.append(event)

    async def flush(self):
        return None


def _envelope(event_type: str = "agent.message") -> JoySafeterEventEnvelope:
    return JoySafeterEventEnvelope(
        session_id=uuid.uuid4(),
        event_type=event_type,
        payload={"content": "hello"},
    )


@pytest.mark.asyncio
async def test_publish_records_persist_failure_in_health_snapshot():
    bus = JoySafeterEventBus()
    bus.register(_FailingPersistSubscriber())
    bus.register(_NoopBroadcastSubscriber())

    await bus.publish(_envelope("agent.message"))

    health = bus.health_snapshot()
    assert health["status"] == "degraded"
    assert health["persist_failure_count"] == 1
    assert health["last_persist_failure"]["event_type"] == "agent.message"
    assert "persist failed" in health["last_persist_failure"]["error"]


@pytest.mark.asyncio
async def test_status_change_suppressed_by_persist_subscriber_is_not_broadcast():
    bus = JoySafeterEventBus()
    recorder = _RecordingBroadcastSubscriber()
    bus.register(_SuppressingPersistSubscriber())
    bus.register(recorder)

    await bus.publish(
        JoySafeterEventEnvelope(
            session_id=uuid.uuid4(),
            event_type="session.status_idle",
            payload={"stop_reason": {"type": "end_turn"}},
            is_status_change=True,
            stop_reason={"type": "end_turn"},
        )
    )

    assert recorder.events == []


@pytest.mark.asyncio
async def test_status_event_type_is_normalized_to_status_change_before_persist_phase():
    bus = JoySafeterEventBus()
    recorder = _RecordingPersistSubscriber()
    bus.register(recorder)

    await bus.publish(
        JoySafeterEventEnvelope(
            session_id=uuid.uuid4(),
            event_type="session.status_idle",
            payload={"stop_reason": {"type": "end_turn"}},
        )
    )

    assert len(recorder.events) == 1
    assert recorder.events[0].is_status_change is True


@pytest.mark.asyncio
async def test_generic_event_persist_skips_status_changes():
    buffer = _RecordingEventBuffer()
    sub = EventPersistSubscriber(buffer)  # type: ignore[arg-type]

    await sub.handle(
        JoySafeterEventEnvelope(
            session_id=uuid.uuid4(),
            event_type="session.status_idle",
            payload={"task_id": str(uuid.uuid4()), "stop_reason": {"type": "end_turn"}},
            is_status_change=True,
            stop_reason={"type": "end_turn"},
        )
    )

    assert buffer.events == []


@pytest.mark.asyncio
async def test_generic_event_persist_skips_unflagged_status_event_types():
    buffer = _RecordingEventBuffer()
    sub = EventPersistSubscriber(buffer)  # type: ignore[arg-type]

    await sub.handle(
        JoySafeterEventEnvelope(
            session_id=uuid.uuid4(),
            event_type="session.status_idle",
            payload={"task_id": str(uuid.uuid4()), "stop_reason": {"type": "end_turn"}},
        )
    )

    assert buffer.events == []


@pytest.mark.asyncio
async def test_stream_event_persist_skips_status_changes_before_redis():
    sub = EventStreamPersistSubscriber("test-stream")

    await sub.handle(
        JoySafeterEventEnvelope(
            session_id=uuid.uuid4(),
            event_type="session.status_idle",
            payload={"task_id": str(uuid.uuid4()), "stop_reason": {"type": "end_turn"}},
            is_status_change=True,
            stop_reason={"type": "end_turn"},
        )
    )


@pytest.mark.asyncio
async def test_publish_batch_records_persist_failure_in_health_snapshot():
    bus = JoySafeterEventBus()
    bus.register(_FailingPersistSubscriber())

    await bus.publish_batch([_envelope("agent.message"), _envelope("agent.result")])

    health = bus.health_snapshot()
    assert health["status"] == "degraded"
    assert health["persist_failure_count"] == 1
    assert health["last_persist_failure"]["event_type"] == "agent.message"
