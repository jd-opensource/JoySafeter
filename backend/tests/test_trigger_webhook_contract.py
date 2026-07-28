import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.joysafeter_api.api.v1.triggers import _webhook_delivery_id
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService


class _FakeQueueRedis:
    def __init__(self):
        self.rpushed: list[tuple[str, str]] = []
        self.published: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))

    async def publish(self, channel: str, value: str) -> int:
        self.published.append((channel, value))
        return 1


def _request_with_headers(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/api/v1/triggers/trig_test/webhook",
            "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()],
            "query_string": b"",
        }
    )


async def _seed_webhook_trigger(db_session) -> JoySafeterTrigger:
    org = Organization(name=f"Webhook Org {uuid.uuid4()}", slug=f"webhook-org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="Webhook Project", slug=f"webhook-project-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(name=f"webhook-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()

    trigger = JoySafeterTrigger(
        name=f"hook-{uuid.uuid4()}",
        type="webhook",
        agent_id=agent.id,
        prompt_template="handle {{ body.kind }}",
        enabled=True,
        filter={},
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        last_payload={},
        project_id=project.id,
        user_id="owner-user",
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


@pytest.mark.no_db
def test_webhook_delivery_id_honors_configured_header_before_legacy_fallbacks():
    request = _request_with_headers(
        {
            "X-Custom-Delivery": "custom-1",
            "X-GitHub-Delivery": "github-1",
        }
    )
    trigger = SimpleNamespace(config={"dedupe_header": "x-custom-delivery"})

    assert (
        _webhook_delivery_id(
            request,
            trigger,
            fallback_delivery_id=None,
            github_delivery_id="github-1",
            request_id="request-1",
        )
        == "custom-1"
    )


@pytest.mark.no_db
def test_webhook_delivery_id_keeps_legacy_fallback_when_configured_header_missing():
    request = _request_with_headers({"X-GitHub-Delivery": "github-1"})
    trigger = SimpleNamespace(config={"dedupe_header": "x-custom-delivery"})

    assert (
        _webhook_delivery_id(
            request,
            trigger,
            fallback_delivery_id=None,
            github_delivery_id="github-1",
            request_id="request-1",
        )
        == "github-1"
    )


@pytest.mark.asyncio
async def test_fire_webhook_stamps_trigger_id_for_run_history(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    trigger = await _seed_webhook_trigger(db_session)

    status, task, session_id, deduped, reason = await JoySafeterTriggerService(db_session).fire_webhook(
        trigger,
        raw_body=b'{"kind":"wanted"}',
        payload={"body": {"kind": "wanted"}},
        delivery_id="delivery-1",
        auth_fingerprint="signature-1",
    )
    trigger_id = trigger.id
    project_id = trigger.project_id

    assert status == "fired"
    assert task is not None
    assert session_id is not None
    assert deduped is False
    assert reason is None
    assert redis.rpushed == [("joysafeter:global_queue", str(task.id))]
    task_id = task.id

    db_session.expire_all()
    stored_task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_id))).scalar_one()
    assert stored_task.trigger_id == trigger_id

    runs = await JoySafeterTriggerService(db_session).list_runs(trigger_id, project_id=project_id)
    assert runs is not None
    assert [run.id for run in runs] == [task_id]
