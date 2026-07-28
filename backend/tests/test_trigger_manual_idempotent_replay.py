"""Regression: idempotent replay of a manual/trigger run must not reference a
deleted orphan session.

Found by live E2E (2026-07-28): a second ``POST /triggers/{id}/run`` with the
same Idempotency-Key returned 500 — a ForeignKeyViolation on
``joysafeter_triggers.last_session_id``. Root cause: the executor auto-created a
fresh session for the replay attempt, ``create_and_dispatch`` deduped and DELETED
that orphan session, but ``run()`` still returned it as ``result.session``, so the
caller's ``mark_attempt(last_session_id=...)`` pointed at a deleted row.

Fix: on ``created=False`` with an auto-created session, ``run()`` returns the
pre-existing task's real session. This test drives the executor twice with the
same idempotency key and asserts the replay returns a LIVE session that can be
persisted onto the trigger (mimicking mark_attempt) without an FK error.
"""

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.agent_trigger_execution import AgentTriggerExecutor, AgentTriggerRunConfig


class _FakeRedis:
    async def rpush(self, key, value):
        return 1


async def _seed(db):
    org = Organization(name=f"idem-org-{uuid.uuid4()}", slug=f"idem-org-{uuid.uuid4()}")
    db.add(org)
    await db.flush()
    project = Project(org_id=org.id, name="P", slug=f"idem-p-{uuid.uuid4()}")
    db.add(project)
    await db.flush()
    agent = JoySafeterAgent(name=f"idem-agent-{uuid.uuid4()}", project_id=project.id)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    await db.refresh(project)
    trigger = JoySafeterTrigger(
        name="idem",
        type="webhook",
        agent_id=agent.id,
        prompt_template="p",
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        filter={},
        config={},
        last_payload={},
    )
    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)
    return org, project, agent, trigger


def _config(agent, project, org, key):
    return AgentTriggerRunConfig(
        agent=agent,
        name="idem",
        source="trigger:manual:test",
        prompt="do it",
        system_prompt=None,
        environment_ref=None,
        timeout_sec=7200,
        max_retries=2,
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        idempotency_key=key,
        session_mode="fresh",
        metadata={"trigger_type": "manual"},
    )


@pytest.mark.asyncio
async def test_idempotent_replay_returns_live_session_no_fk_violation(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client", staticmethod(lambda: _FakeRedis())
    )
    org, project, agent, trigger = await _seed(db_session)
    key = f"manual:{uuid.uuid4()}"

    cfg = AgentTriggerRunConfig(
        agent=agent, name="idem", source="trigger:manual:test", prompt="do it",
        system_prompt=None, environment_ref=None, timeout_sec=7200, max_retries=2,
        project_id=project.id, user_id="owner", org_id=org.id, idempotency_key=key,
        session_mode="fresh", trigger_id=trigger.id, metadata={"trigger_type": "manual"},
    )

    first = await AgentTriggerExecutor(db_session).run(cfg, enforce_user_quota=False)
    assert first.created is True

    # Replay with the SAME idempotency key — the fresh session created for this
    # attempt is deduped/deleted; run() must hand back the existing task's session.
    second = await AgentTriggerExecutor(db_session).run(cfg, enforce_user_quota=False)
    assert second.created is False
    assert second.task.id == first.task.id
    assert second.session.id == first.task.chat_session_id

    # The returned session must still exist (not the deleted orphan).
    live = await db_session.get(JoySafeterSession, second.session.id)
    assert live is not None

    # Mimic mark_attempt writing last_session_id — must commit without FK violation.
    trigger.last_session_id = second.session.id
    trigger.last_task_id = second.task.id
    await db_session.commit()
    await db_session.refresh(trigger)
    assert trigger.last_session_id == first.task.chat_session_id
