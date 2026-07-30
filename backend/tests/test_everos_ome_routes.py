from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from app.everos.entrypoints.api.routes import ome
from app.everos.infra.ome.events import ScopedManualTick
from app.everos.infra.ome.records import RunRecord, RunStatus


@pytest.mark.asyncio
async def test_trigger_without_wait_returns_run_ids_without_waiting(monkeypatch):
    class _Engine:
        def __init__(self):
            self.wait_idle_called = False

        async def trigger_manual(self, name: str, *, force: bool):
            assert name == "reflect_episodes"
            assert force is False
            return ["run-1"]

        async def wait_idle(self, *, timeout: float):
            self.wait_idle_called = True
            return True

    engine = _Engine()

    memorize = importlib.import_module("app.everos.service.memorize")

    monkeypatch.setattr(memorize, "_get_engine", lambda: engine)

    response = await ome.trigger(
        ome.TriggerRequest(name="reflect_episodes", timeout=45.0, wait=False)
    )

    assert response.status == "started"
    assert response.name == "reflect_episodes"
    assert response.run_id == "run-1"
    assert response.run_ids == ["run-1"]
    assert engine.wait_idle_called is False


@pytest.mark.asyncio
async def test_trigger_with_scope_passes_scoped_manual_event_to_engine(monkeypatch):
    class _Engine:
        def __init__(self):
            self.event = None

        async def trigger_manual(self, name: str, *, event, force: bool):
            assert name == "reflect_episodes"
            assert force is False
            self.event = event
            return ["run-1"]

        async def wait_idle(self, *, timeout: float):
            return True

    engine = _Engine()
    memorize = importlib.import_module("app.everos.service.memorize")

    monkeypatch.setattr(memorize, "_get_engine", lambda: engine)

    response = await ome.trigger(
        ome.TriggerRequest(
            name="reflect_episodes",
            timeout=45.0,
            wait=False,
            scope_mode="active_only",
            app_id="joysafeter",
            project_id="project-slug__project-1",
            active_agent_ids=["agent-2", "agent-1"],
            active_session_ids=["session-2", "session-1"],
        )
    )

    assert response.status == "started"
    assert isinstance(engine.event, ScopedManualTick)
    assert engine.event.strategy_name == "reflect_episodes"
    assert engine.event.scope_mode == "active_only"
    assert engine.event.app_id == "joysafeter"
    assert engine.event.project_id == "project-slug__project-1"
    assert engine.event.active_agent_ids == ("agent-1", "agent-2")
    assert engine.event.active_session_ids == ("session-1", "session-2")


@pytest.mark.asyncio
async def test_get_run_status_returns_record(monkeypatch):
    record = RunRecord(
        run_id="run-1",
        strategy_name="reflect_episodes",
        status=RunStatus.RUNNING,
        attempt=0,
        started_at=datetime(2026, 7, 27, tzinfo=UTC),
        event_topic="app.everos.infra.ome.events:ManualTick",
        event_payload='{"event_id":"evt-1","strategy_name":"reflect_episodes"}',
        max_retries_snapshot=3,
        event_id="evt-1",
    )

    class _Engine:
        async def get_run_status(self, run_id: str):
            assert run_id == "run-1"
            return record

    memorize = importlib.import_module("app.everos.service.memorize")

    monkeypatch.setattr(memorize, "_get_engine", lambda: _Engine())

    response = await ome.get_run_status("run-1")

    assert response == record
