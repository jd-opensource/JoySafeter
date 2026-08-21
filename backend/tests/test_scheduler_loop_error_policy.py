"""Scheduler fire-failure policy: transient vs permanent classification.

A failed fire is routed through ``record_fire_failure`` with a ``transient``
flag rather than the old release/advance split:
  - Half-done REPLACE cancel errors and any retryable AppError are *transient*
    (retried on the same slot with backoff).
  - Any other exception is *permanent* (slot advanced, one failure counted).

These are ``no_db`` unit tests: the service methods are stubbed so we assert only
how the loop classifies and dispatches the failure.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.joysafeter_shared.common.app_errors import ServiceUnavailableError
from app.joysafeter_shared.ids import AgentId
from app.joysafeter_worker.scheduler.loop import SchedulerLoop

pytestmark = pytest.mark.no_db


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_session_factory():
    return _FakeSession()


def _patch_claim(monkeypatch, trigger):
    """Stub the in-fire re-lock so no_db tests reach the classification logic.

    ``_fire`` re-acquires the claimed trigger under a row lock in its own
    session (``get_claimed_for_fire``) before doing any work. That method does
    DB I/O, so these no_db tests must stub it just like the other service
    methods; it returns the already-claimed trigger the loop passed in.
    """

    async def get_claimed_for_fire(self, trigger_id, *, expected_locked_by):
        return trigger

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.get_claimed_for_fire",
        get_claimed_for_fire,
    )


class _FakeSubmission:
    def __init__(self, db):
        self.tasks = SimpleNamespace(get_by_idempotency_key=self.get_by_idempotency_key)

    async def get_by_idempotency_key(self, idempotency_key, project_id=None):
        return SimpleNamespace(id=uuid4())

    async def enforce_admission(self, **kwargs):
        return None


class _ExplodingSubmission(_FakeSubmission):
    async def enforce_admission(self, **kwargs):
        raise AssertionError("paused project must skip before task admission")


class _QuotaFullSubmission(_FakeSubmission):
    async def enforce_admission(self, **kwargs):
        raise AssertionError("idempotent same-slot replay must not be blocked by admission quota")


class _FakeAgentService:
    def __init__(self, db):
        pass

    async def get_agent(self, agent_id, project_id=None):
        return SimpleNamespace(id=agent_id, archived_at=None, environment_ref=None, version=1, name="Agent", model=None)


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


def _install_common(monkeypatch, *, claimed, captured):
    async def claim_due(self, **kwargs):
        return claimed

    async def record_fire_failure(self, trigger_id, fired_slot, *, error, transient, expected_locked_by=None):
        captured.append(("fail", trigger_id, transient, expected_locked_by))
        return False

    async def advance_after_fire(self, trigger_id, fired_slot, **kwargs):
        captured.append(("advance", trigger_id, kwargs.get("expected_locked_by")))

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.claim_due_cron_triggers",
        claim_due,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.record_fire_failure",
        record_fire_failure,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.advance_after_fire",
        advance_after_fire,
    )


def _trigger():
    return SimpleNamespace(id=uuid4(), next_run_at=datetime.now(timezone.utc), pending_slot_at=None)


@pytest.mark.parametrize(
    "code",
    ["TASK_CANCEL_REDIS_RELAY_FAILED", "TASK_CANCEL_STATE_SYNC_FAILED", "TASK_CANCEL_SESSION_SYNC_FAILED"],
)
@pytest.mark.asyncio
async def test_retryable_cancel_error_is_transient(monkeypatch, code):
    trigger = _trigger()
    captured: list = []
    _install_common(monkeypatch, claimed=[trigger], captured=captured)

    async def fail_fire(self, trigger_arg, fired_slot):
        raise ServiceUnavailableError(
            code=code, message="cancel half-done", source="runtime", retryable=True, user_action="retry"
        )

    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)
    await SchedulerLoop(worker_id="test-worker")._tick()

    assert captured == [("fail", trigger.id, True, "test-worker")]


@pytest.mark.asyncio
async def test_generic_retryable_apperror_is_transient(monkeypatch):
    trigger = _trigger()
    captured: list = []
    _install_common(monkeypatch, claimed=[trigger], captured=captured)

    async def fail_fire(self, trigger_arg, fired_slot):
        raise ServiceUnavailableError(
            code="TASK_ENQUEUE_FAILED", message="redis down", source="runtime", retryable=True, user_action="retry"
        )

    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)
    await SchedulerLoop(worker_id="test-worker")._tick()

    assert captured == [("fail", trigger.id, True, "test-worker")]


@pytest.mark.asyncio
async def test_unexpected_error_is_permanent(monkeypatch):
    trigger = _trigger()
    captured: list = []
    _install_common(monkeypatch, claimed=[trigger], captured=captured)

    async def fail_fire(self, trigger_arg, fired_slot):
        raise RuntimeError("unexpected scheduler failure")

    monkeypatch.setattr(SchedulerLoop, "_fire", fail_fire)
    await SchedulerLoop(worker_id="test-worker")._tick()

    assert captured == [("fail", trigger.id, False, "test-worker")]


@pytest.mark.asyncio
async def test_idempotent_slot_precheck_skips_auto_session_creation(monkeypatch):
    trigger = SimpleNamespace(
        id=uuid4(),
        agent_id=AgentId.from_uuid(uuid4()),
        project_id="project-a",
        user_id="user-a",
        org_id="org-a",
        name="Daily",
        prompt="summarize",
        prompt_template="summarize",
        system_prompt=None,
        environment_ref=None,
        concurrency_policy="allow",
        timeout_sec=7200,
        max_retries=2,
        slot_attempts=0,
        cron_expr="0 0 * * *",
        timezone="UTC",
        last_fired_slot=None,
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
    )

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.TaskSubmissionService", _FakeSubmission)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.JoySafeterAgentService", _FakeAgentService)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.EnvironmentService", _FakeEnvironmentService)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.SessionService", _ExplodingSessionService)
    _patch_claim(monkeypatch, trigger)

    async def trigger_runtime_block_reason(self, trigger_arg):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.trigger_runtime_block_reason",
        trigger_runtime_block_reason,
    )

    outcome = await SchedulerLoop()._fire(trigger, datetime.now(timezone.utc))
    assert outcome.status == "deduped"


@pytest.mark.parametrize("policy", ["forbid", "replace"])
@pytest.mark.asyncio
async def test_idempotent_slot_replay_precedes_concurrency_policy(monkeypatch, policy):
    trigger = SimpleNamespace(
        id=uuid4(),
        agent_id=AgentId.from_uuid(uuid4()),
        project_id="project-a",
        user_id="user-a",
        org_id="org-a",
        name="Daily",
        prompt_template="summarize",
        system_prompt=None,
        environment_ref=None,
        concurrency_policy=policy,
        timeout_sec=7200,
        max_retries=2,
        slot_attempts=0,
        cron_expr="0 0 * * *",
        timezone="UTC",
        last_fired_slot=None,
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
    )

    async def trigger_runtime_block_reason(self, trigger_arg):
        return None

    async def get_active_tasks(self, trigger_id):
        raise AssertionError("same-slot idempotent replay must be resolved before concurrency policy")

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.TaskSubmissionService", _FakeSubmission)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.trigger_runtime_block_reason",
        trigger_runtime_block_reason,
    )
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.get_active_tasks",
        get_active_tasks,
    )
    _patch_claim(monkeypatch, trigger)

    outcome = await SchedulerLoop()._fire(trigger, datetime.now(timezone.utc))

    assert outcome.status == "deduped"


@pytest.mark.asyncio
async def test_idempotent_slot_replay_precedes_admission_quota(monkeypatch):
    trigger = SimpleNamespace(
        id=uuid4(),
        agent_id=AgentId.from_uuid(uuid4()),
        project_id="project-at-quota",
        user_id="user-a",
        org_id="org-a",
        name="Daily",
        prompt_template="summarize",
        system_prompt=None,
        environment_ref=None,
        concurrency_policy="allow",
        timeout_sec=7200,
        max_retries=2,
        slot_attempts=0,
        cron_expr="0 0 * * *",
        timezone="UTC",
        last_fired_slot=None,
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
    )

    async def trigger_runtime_block_reason(self, trigger_arg):
        return None

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.TaskSubmissionService", _QuotaFullSubmission)
    _patch_claim(monkeypatch, trigger)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.trigger_runtime_block_reason",
        trigger_runtime_block_reason,
    )

    outcome = await SchedulerLoop()._fire(trigger, datetime.now(timezone.utc))

    assert outcome.status == "deduped"


@pytest.mark.asyncio
async def test_fire_rechecks_project_pause_after_claim_before_admission(monkeypatch):
    trigger = SimpleNamespace(
        id=uuid4(),
        agent_id=AgentId.from_uuid(uuid4()),
        project_id="project-paused-after-claim",
        user_id="user-a",
        org_id="org-a",
        name="Daily",
        prompt_template="summarize",
        system_prompt=None,
        environment_ref=None,
        concurrency_policy="allow",
        timeout_sec=7200,
        max_retries=2,
        slot_attempts=0,
        cron_expr="0 0 * * *",
        timezone="UTC",
        last_fired_slot=None,
        session_mode="fresh",
        pinned_session_id=None,
        reusable_session_id=None,
    )

    async def trigger_runtime_block_reason(self, trigger_arg):
        assert trigger_arg.project_id == "project-paused-after-claim"
        return "triggers are paused for this project"

    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.AsyncSessionLocal", _fake_session_factory)
    monkeypatch.setattr("app.joysafeter_worker.scheduler.loop.TaskSubmissionService", _ExplodingSubmission)
    _patch_claim(monkeypatch, trigger)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.trigger_runtime_block_reason",
        trigger_runtime_block_reason,
    )

    outcome = await SchedulerLoop()._fire(trigger, datetime.now(timezone.utc))

    assert outcome.status == "skipped"
