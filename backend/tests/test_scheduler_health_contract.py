from contextlib import asynccontextmanager

import httpx
import pytest

from app.joysafeter_shared.config.settings import joysafeter_config, settings
from app.joysafeter_shared.runtime.app_factory import create_app
from app.joysafeter_worker.scheduler import scheduler_heartbeat

pytestmark = pytest.mark.no_db


@asynccontextmanager
async def _noop_lifespan(app):
    yield


class _FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return None


class _FakeEngine:
    def connect(self):
        return _FakeConnection()


@pytest.mark.asyncio
async def test_worker_health_exposes_scheduler_heartbeat(monkeypatch):
    monkeypatch.setattr(settings, "service_role", "worker")
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(joysafeter_config, "event_stream_enabled", False)
    monkeypatch.setattr("app.joysafeter_shared.database.engine", _FakeEngine())
    scheduler_heartbeat().mark_tick(claimed=7)

    app = create_app(lifespan=_noop_lifespan)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "worker"
    assert data["scheduler"]["last_claimed"] == 7
    assert "last_tick_at" in data["scheduler"]
