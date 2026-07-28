"""Dead-letter: auto-disable a trigger after repeated fire failures.

A trigger that fails every slot must not silently churn forever. Once
``scheduler_failure_threshold`` consecutive failures accrue, ``record_fire_failure``
auto-disables the trigger (``enabled=False`` + ``auto_disabled_at`` +
``disabled_reason``, ``next_run_at=None``) and reports the dead-letter so the
scheduler can emit an alert. Re-enabling via ``update`` clears the dead-letter
and resumes the schedule.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)


class _StubService(JoySafeterTriggerService):
    def __init__(self, trigger) -> None:
        self._trigger = trigger
        self.db = SimpleNamespace(commit=self._commit)

    async def _commit(self) -> None:
        pass

    async def get(self, trigger_id, project_id=None):
        return self._trigger

    async def _next_run_or_pause(self, trigger):
        return _FUTURE

    def _sync_config(self, trigger) -> None:
        pass


def _trigger(**over):
    base = dict(
        id="t1",
        slot_attempts=0,
        pending_slot_at=None,
        consecutive_failures=0,
        next_run_at=_FUTURE,
        last_fired_slot=None,
        last_attempt_at=None,
        last_error=None,
        locked_by="worker-1",
        locked_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        enabled=True,
        auto_disabled_at=None,
        disabled_reason=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _threshold(monkeypatch):
    from app.joysafeter_shared.config.settings import settings

    monkeypatch.setattr(settings, "scheduler_failure_threshold", 5)
    monkeypatch.setattr(settings, "scheduler_slot_max_retries", 3)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_below_threshold_does_not_disable():
    trigger = _trigger(consecutive_failures=3)
    svc = _StubService(trigger)
    dead = await svc.record_fire_failure(trigger.id, datetime.now(timezone.utc), error="boom", transient=False)
    assert dead is False
    assert trigger.enabled is True
    assert trigger.auto_disabled_at is None
    assert trigger.consecutive_failures == 4
    assert trigger.next_run_at == _FUTURE


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_crossing_threshold_dead_letters_and_disables():
    trigger = _trigger(consecutive_failures=4)  # next failure -> 5 == threshold
    svc = _StubService(trigger)
    dead = await svc.record_fire_failure(trigger.id, datetime.now(timezone.utc), error="still failing", transient=False)
    assert dead is True
    assert trigger.enabled is False
    assert trigger.auto_disabled_at is not None
    assert "5 consecutive" in (trigger.disabled_reason or "")
    assert trigger.next_run_at is None  # paused; no further slots


@pytest.mark.asyncio
async def test_re_enable_clears_dead_letter_and_resumes(db_session):
    """Integration: PATCH enabled=True on an auto-disabled trigger resets state."""
    import uuid

    from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
    from app.joysafeter_domain.models.joysafeter_organization import Organization
    from app.joysafeter_domain.models.joysafeter_project import Project
    from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger

    org = Organization(name=f"dl-org-{uuid.uuid4()}", slug=f"dl-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug=f"dl-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(name=f"dl-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)

    trigger = JoySafeterTrigger(
        name="dead",
        type="cron",
        agent_id=agent.id,
        prompt_template="x",
        cron_expr="0 0 * * *",
        timezone="UTC",
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        enabled=False,
        consecutive_failures=5,
        auto_disabled_at=datetime.now(timezone.utc),
        disabled_reason="Auto-disabled after 5 consecutive fire failures: boom",
        next_run_at=None,
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)

    updated = await JoySafeterTriggerService(db_session).update(trigger.id, project.id, enabled=True)

    assert updated is not None
    assert updated.enabled is True
    assert updated.consecutive_failures == 0
    assert updated.auto_disabled_at is None
    assert updated.disabled_reason is None
    assert updated.next_run_at is not None  # schedule resumed
