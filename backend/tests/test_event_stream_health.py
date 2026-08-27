"""Event-stream health exposes backlog and dead-letter risk."""

import pytest

from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_worker.events.health import collect_event_stream_health

pytestmark = pytest.mark.no_db


class _FakeRedis:
    def __init__(self, lengths: dict[str, int], pending=0):
        self.lengths = lengths
        self.pending = pending

    async def xlen(self, key):
        return self.lengths.get(key, 0)

    async def xpending(self, stream, group):
        return {"pending": self.pending}


class _BrokenRedis:
    async def xlen(self, key):
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_event_stream_health_degrades_when_dead_letters_exist(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "event_stream_key", "joysafeter:test:events")
    monkeypatch.setattr(joysafeter_config, "event_stream_dead_letter_suffix", ":dead")
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    redis = _FakeRedis(
        {
            "joysafeter:test:events": 10,
            "joysafeter:test:events:dead": 2,
        },
        pending=3,
    )

    health = await collect_event_stream_health(redis)

    assert health["status"] == "degraded"
    assert health["reason"] == "dead_letters_present"
    assert health["dead_letter_length"] == 2
    assert health["pending_count"] == 3


@pytest.mark.asyncio
async def test_event_stream_health_degrades_at_high_water(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "event_stream_key", "joysafeter:test:events")
    monkeypatch.setattr(joysafeter_config, "event_stream_dead_letter_suffix", ":dead")
    monkeypatch.setattr(joysafeter_config, "event_stream_high_water_mark", 100)
    redis = _FakeRedis(
        {
            "joysafeter:test:events": 100,
            "joysafeter:test:events:dead": 0,
        }
    )

    health = await collect_event_stream_health(redis)

    assert health["status"] == "degraded"
    assert health["reason"] == "stream_at_high_water_mark"
    assert health["stream_length"] == 100


@pytest.mark.asyncio
async def test_event_stream_health_unhealthy_when_redis_cannot_be_inspected(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "event_stream_key", "joysafeter:test:events")

    health = await collect_event_stream_health(_BrokenRedis())

    assert health["status"] == "unhealthy"
    assert "redis unavailable" in health["error"]
