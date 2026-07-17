from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.joysafeter_shared.common.app_errors import ServiceUnavailableError
from app.joysafeter_worker.scheduler.loop import SchedulerLoop

pytestmark = pytest.mark.no_db


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_session_factory():
    return _FakeSession()


class _FakeSubmission:
    def __init__(self, db):
        self.tasks = SimpleNamespace(get_by_idempotency_key=self.get_by_idempotency_key)

    async def get_by_idempotency_key(self, idempotency_key, project_id=None):
        return SimpleNamespace(id=uuid4())

    async def enforce_admission(self, **kwargs):
        return None


class _FakeAgentService:
    def __init__(self, db):
        pass

    async def get_agent(self, agent_id, project_id=None):
        return SimpleNamespace(
            id=agent_id,
            archived_at=None,
            environment_ref=None,
            version=1,
            name="Agent",
            model=None,
        )


class _FakeEnvironmentService:
    def __init__(self, db):
        pass

    async def get_environment_by_ref(self, environment_ref, project_id=None):
        return None


class _ExplodingSessionService:
    def __init__(self, db):
        pass

    async def create_session(self, **kwargs):
        raise AssertionError("duplicate scheduled slot must not create an auto session")


@pytest.mark.asyncio
async def test_scheduler_retryable_replace_cancel_error_releases_claim_without_advancing(monkeypatch):
    schedule = SimpleNamespace(id=uuid4(), next_run_at=datetime.now(timezone.utc))
    calls: list[tuple[str, object]] = []

    async def claim_due_schedules(self, **kwargs):
        return [schedule]

    async def release_claim(self, schedule_id):
        calls.append(("release", schedule_id))

    async def advance_after_fire(self, schedule_id, fired_slot):
        calls.append(("advance", schedule_id))

    async def fail_fire(self, schedule_arg, fired_slot):
        raise ServiceUnavailableError(
            code="TASK_CANCEL_REDIS_RELAY_FAILED",
            message="Failed to cancel task in sandbox runtime.",
            source="runtime",
            retryable=True,
            user_action="retry",
        )

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.claim_due_schedules",
        claim_due_schedules,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.release_claim",
        release_claim,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.advance_after_fire",
        advance_after_fire,
    )
    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)

    await SchedulerLoop()._tick()

    assert calls == [("release", schedule.id)]


@pytest.mark.asyncio
async def test_scheduler_session_sync_cancel_error_releases_claim_without_advancing(monkeypatch):
    # A REPLACE fire that cancels the prior run but then fails to mark the
    # linked session idle raises TASK_CANCEL_SESSION_SYNC_FAILED. The prior run
    # is already cancelled, so advancing here would skip the slot after killing
    # the old run and never dispatch a replacement. The slot must be kept due.
    schedule = SimpleNamespace(id=uuid4(), next_run_at=datetime.now(timezone.utc))
    calls: list[tuple[str, object]] = []

    async def claim_due_schedules(self, **kwargs):
        return [schedule]

    async def release_claim(self, schedule_id):
        calls.append(("release", schedule_id))

    async def advance_after_fire(self, schedule_id, fired_slot):
        calls.append(("advance", schedule_id))

    async def fail_fire(self, schedule_arg, fired_slot):
        raise ServiceUnavailableError(
            code="TASK_CANCEL_SESSION_SYNC_FAILED",
            message="Task was cancelled, but failed to mark the linked session idle.",
            source="api",
            retryable=True,
            user_action="refresh",
        )

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.claim_due_schedules",
        claim_due_schedules,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.release_claim",
        release_claim,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.advance_after_fire",
        advance_after_fire,
    )
    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)

    await SchedulerLoop()._tick()

    assert calls == [("release", schedule.id)]


@pytest.mark.asyncio
async def test_scheduler_non_retryable_fire_error_advances_slot(monkeypatch):
    schedule = SimpleNamespace(id=uuid4(), next_run_at=datetime.now(timezone.utc))
    calls: list[tuple[str, object]] = []

    async def claim_due_schedules(self, **kwargs):
        return [schedule]

    async def release_claim(self, schedule_id):
        calls.append(("release", schedule_id))

    async def advance_after_fire(self, schedule_id, fired_slot):
        calls.append(("advance", schedule_id))

    async def fail_fire(self, schedule_arg, fired_slot):
        raise RuntimeError("unexpected scheduler failure")

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.claim_due_schedules",
        claim_due_schedules,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.release_claim",
        release_claim,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_schedule_service.JoySafeterScheduleService.advance_after_fire",
        advance_after_fire,
    )
    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)

    await SchedulerLoop()._tick()

    assert calls == [("advance", schedule.id)]


@pytest.mark.asyncio
async def test_scheduler_idempotent_slot_precheck_skips_auto_session_creation(monkeypatch):
    schedule = SimpleNamespace(
        id=uuid4(),
        agent_id=uuid4(),
        project_id="project-a",
        user_id="user-a",
        org_id="org-a",
        name="Daily",
        prompt="summarize",
        system_prompt=None,
        environment_ref=None,
        concurrency_policy="allow",
        timeout_sec=7200,
        max_retries=2,
    )

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.TaskSubmissionService", _FakeSubmission)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.JoySafeterAgentService", _FakeAgentService)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.EnvironmentService", _FakeEnvironmentService)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.SessionService", _ExplodingSessionService)

    await SchedulerLoop()._fire(schedule, datetime.now(timezone.utc))
