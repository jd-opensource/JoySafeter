"""Foundation 2 — backpressure on Redis-Stream overflow (Option 2: DB fallback).

Under sustained load the worker can fall behind and the stream reaches its
maxlen; a plain xadd(maxlen, approximate) then trims the oldest un-consumed
entries and loses them SILENTLY. The publisher now checks the stream length
against a high-water mark and, when saturated, routes the event to the durable
DB buffer instead of letting it be trimmed — overflow degrades to
slower-but-lossless rather than silent loss.
"""

import logging
import uuid

import pytest

from app.joysafeter_orchestrator.events import stream_publisher as sp
from app.joysafeter_orchestrator.events.stream_publisher import EventStreamPersistSubscriber
from app.joysafeter_shared.config.settings import joysafeter_config


class _Env:
    def __init__(self, *, session_id, event_id, flush_immediately=True):
        self.session_id = session_id
        self.event_id = event_id
        self.event_type = "agent.message"
        self.payload = {"x": 1}
        self.seq = 1
        self.flush_immediately = flush_immediately
        self.is_status_change = False


class _FakeRedis:
    def __init__(self, length: int):
        self._length = length
        self.xadds: list = []

    async def xlen(self, key):
        return self._length

    async def xadd(self, key, payload, maxlen=None, approximate=None):
        self.xadds.append((key, payload))
        return "1-0"


class _FailingXaddRedis(_FakeRedis):
    async def xadd(self, key, payload, maxlen=None, approximate=None):
        raise RuntimeError("xadd failed")


class _FakeBuffer:
    def __init__(self):
        self.sent: list = []
        self.flushes = 0

    async def send(self, event):
        self.sent.append(event)

    async def flush(self):
        self.flushes += 1


def _env():
    return _Env(session_id=uuid.uuid4(), event_id=uuid.uuid4())


def _logged_errors(caplog):
    return [getattr(record, "error", None) for record in caplog.records if getattr(record, "error", None)]


@pytest.mark.asyncio
async def test_below_high_water_uses_stream(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: _FakeRedis(length=10)))
    buf = _FakeBuffer()
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=buf)

    await sub.handle(_env())

    assert len(sub._fallback_event_buffer.sent) == 0, "below high-water must NOT use the DB fallback"
    # xadd happened on the fake redis (the normal, fast path).
    # (RedisClient.get_client returns a fresh fake each call, so assert via a captured one below.)


@pytest.mark.asyncio
async def test_saturated_routes_to_db_fallback_instead_of_trimming(monkeypatch):
    fake = _FakeRedis(length=999)  # >= high-water: an xadd would trim
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: fake))
    buf = _FakeBuffer()
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=buf)

    ev = _env()
    await sub.handle(ev)

    assert fake.xadds == [], "when saturated the event must NOT be xadded (would trim/lose)"
    assert len(buf.sent) == 1, "the event must be routed to the durable DB buffer"
    assert buf.sent[0].id == ev.event_id, "the same event is persisted via fallback"
    assert buf.flushes == 1, "flush_immediately events are flushed through the fallback"


@pytest.mark.asyncio
async def test_saturated_fallback_logs_structured_boundary_error(monkeypatch, caplog):
    fake = _FakeRedis(length=999)
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: fake))
    buf = _FakeBuffer()
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=buf)

    with caplog.at_level(logging.WARNING, logger=sp.__name__):
        await sub.handle(_env())

    error = _logged_errors(caplog)[0]
    assert error["code"] == "EVENT_STREAM_SATURATED_FALLBACK"
    assert error["data"]["boundary"] == "event_stream_persist"
    assert error["data"]["operation"] == "saturation_fallback"
    assert error["data"]["stream_key"] == "joysafeter:events"


@pytest.mark.asyncio
async def test_saturated_without_fallback_degrades_to_stream_not_crash(monkeypatch):
    fake = _FakeRedis(length=999)
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: fake))
    # No fallback buffer configured -> accept bounded loss, but must still make
    # progress (best-effort xadd), never hang or raise.
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=None)

    await sub.handle(_env())

    assert len(fake.xadds) == 1, "with no fallback, saturation falls through to a best-effort xadd"


@pytest.mark.asyncio
async def test_xadd_failure_fallback_logs_structured_boundary_error(monkeypatch, caplog):
    fake = _FailingXaddRedis(length=10)
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: fake))
    buf = _FakeBuffer()
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=buf)

    with caplog.at_level(logging.WARNING, logger=sp.__name__):
        await sub.handle(_env())

    error = _logged_errors(caplog)[0]
    assert error["code"] == "EVENT_STREAM_APPEND_FALLBACK"
    assert error["detail"] == "RuntimeError"
    assert error["data"]["operation"] == "xadd_fallback"


@pytest.mark.asyncio
async def test_below_high_water_actually_xadds(monkeypatch):
    fake = _FakeRedis(length=10)
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    monkeypatch.setattr(sp.RedisClient, "get_client", staticmethod(lambda: fake))
    buf = _FakeBuffer()
    sub = EventStreamPersistSubscriber(stream_key="joysafeter:events", fallback_event_buffer=buf)

    await sub.handle(_env())

    assert len(fake.xadds) == 1 and len(buf.sent) == 0, "normal path xadds and does not touch fallback"
