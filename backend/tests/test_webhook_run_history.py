"""Regression: webhook-fired tasks must carry trigger_id so run history shows them.

Found by live E2E (2026-07-28): the trigger detail page showed no run history for
webhook triggers. Root cause: ``fire_webhook`` built its ``AgentTriggerRunConfig``
WITHOUT ``trigger_id`` (cron ``_fire`` and ``fire_manual`` both set it), so the
fired task had ``trigger_id=NULL`` and ``list_runs`` (which filters by trigger_id)
returned nothing. Fix: stamp ``trigger_id=trigger.id`` on the webhook run config.
"""

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService


class _FakeRedis:
    async def rpush(self, key, value):
        return 1


@pytest.mark.asyncio
async def test_webhook_fire_stamps_trigger_id_so_runs_visible(db_session, monkeypatch):
    monkeypatch.setattr("app.joysafeter_shared.cache.redis.RedisClient.get_client", staticmethod(lambda: _FakeRedis()))
    org = Organization(name=f"wr-org-{uuid.uuid4()}", slug=f"wr-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug=f"wr-p-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()
    agent = JoySafeterAgent(name=f"wr-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    trigger = JoySafeterTrigger(
        name="hook",
        type="webhook",
        agent_id=agent.id,
        prompt_template="got {{ body.msg }}",
        enabled=True,
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        filter={},
        config={},
        last_payload={},
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)

    svc = JoySafeterTriggerService(db_session)
    status, task, session_id, deduped, reason = await svc.fire_webhook(
        trigger,
        raw_body=b'{"msg":"hi"}',
        payload={"body": {"msg": "hi"}, "trigger": {"id": str(trigger.id)}},
        delivery_id=f"d-{uuid.uuid4()}",
        auth_fingerprint="x",
    )
    assert status == "fired"
    assert task is not None
    assert task.trigger_id == trigger.id  # the fix: task is linked to the trigger

    runs = await svc.list_runs(trigger.id, project_id=project.id, limit=10)
    assert runs is not None and len(runs) == 1
    assert runs[0].id == task.id
