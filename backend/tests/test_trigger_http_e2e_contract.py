import uuid
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from credential_test_helpers import encrypted_secret_data
from fastapi import FastAPI
from sqlalchemy import select

from app.joysafeter_api.api.v1 import triggers as trigger_api
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import SessionId, TaskId, TriggerId


class _FakeQueueRedis:
    def __init__(self) -> None:
        self.rpushed: list[tuple[str, str]] = []
        self.published: list[tuple[str, str]] = []

    async def rpush(self, key: str, value: str) -> None:
        self.rpushed.append((key, value))

    async def publish(self, channel: str, value: str) -> int:
        self.published.append((channel, value))
        return 1


def _ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="trigger-http-e2e-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
        project_role="admin",
    )


def _app(db, ctx: JoySafeterAuthContext) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(trigger_api.router, prefix="/api/v1/triggers")
    app.dependency_overrides[trigger_api.get_db] = lambda: db
    app.dependency_overrides[trigger_api.get_joysafeter_auth_context] = lambda: ctx
    app.dependency_overrides[trigger_api.require_joysafeter_write] = lambda: ctx
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _seed_project_agent_and_secret(db_session):
    unique = uuid.uuid4()
    org = Organization(name=f"Trigger E2E Org {unique}", slug=f"trigger-e2e-org-{unique}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="Trigger E2E Project", slug=f"trigger-e2e-project-{unique}")
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(name=f"trigger-e2e-agent-{unique}", project_id=project.id)
    secret = JoySafeterSecret(
        name="hook-secret",
        project_id=project.id,
        kind="generic",
        provider=None,
        protocol=None,
        data=encrypted_secret_data({"WEBHOOK_SECRET": "route-secret"}),
    )
    db_session.add_all([agent, secret])
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(project)
    return org, project, agent


@pytest.mark.asyncio
async def test_trigger_http_crud_manual_run_history_and_delete_flow(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    app = _app(db_session, _ctx(project.id, org.id))

    async with _client(app) as client:
        create_resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "Manual HTTP E2E",
                "type": "webhook",
                "agent_id": str(agent.id),
                "prompt_template": "handle {{ body.kind }}",
                "secret_ref": "hook-secret",
                "auth_methods": ["hmac"],
                "dedupe_header": "x-provider-delivery",
                "session_mode": "fresh",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        trigger_id = created["id"]
        assert created["webhook_url"] == f"http://test/api/v1/triggers/{trigger_id}/webhook"
        assert created["config"]["auth_methods"] == ["hmac"]
        assert created["config"]["dedupe_header"] == "x-provider-delivery"

        list_resp = await client.get("/api/v1/triggers", params={"type": "webhook"})
        assert list_resp.status_code == 200
        assert [item["id"] for item in list_resp.json()] == [trigger_id]

        get_resp = await client.get(f"/api/v1/triggers/{trigger_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Manual HTTP E2E"

        update_resp = await client.patch(
            f"/api/v1/triggers/{trigger_id}",
            json={"name": "Manual HTTP E2E Updated", "enabled": False, "dedupe_header": "x-next-delivery"},
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["name"] == "Manual HTTP E2E Updated"
        assert updated["enabled"] is False
        assert updated["config"]["dedupe_header"] == "x-next-delivery"

        run_resp = await client.post(
            f"/api/v1/triggers/{trigger_id}/run",
            headers={"Idempotency-Key": "manual-e2e-key"},
        )
        assert run_resp.status_code == 202
        fired = run_resp.json()
        assert fired["status"] == "fired"
        assert fired["task_id"].startswith("task_")
        assert fired["session_id"].startswith("sess_")
        assert fired["deduped"] is False

        replay_resp = await client.post(
            f"/api/v1/triggers/{trigger_id}/run",
            headers={"Idempotency-Key": "manual-e2e-key"},
        )
        assert replay_resp.status_code == 202
        assert replay_resp.json() == {**fired, "status": "deduped", "deduped": True}

        runs_resp = await client.get(f"/api/v1/triggers/{trigger_id}/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()["data"]
        assert len(runs) == 1
        assert runs[0]["id"] == fired["task_id"]
        assert runs[0]["trigger_id"] == trigger_id
        assert runs[0]["chat_session_id"] == fired["session_id"]

        typed_trigger_id = TriggerId.from_public(trigger_id)
        active_task = (
            await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.trigger_id == typed_trigger_id))
        ).scalar_one()
        original_task_trigger_id = active_task.trigger_id
        assert redis.rpushed == [("joysafeter:global_queue", str(active_task.id.uuid))]

        active_delete_resp = await client.delete(f"/api/v1/triggers/{trigger_id}")
        assert active_delete_resp.status_code == 409
        assert active_delete_resp.json()["code"] == "TRIGGER_HAS_ACTIVE_RUNS"
        assert active_delete_resp.json()["data"] == {
            "trigger_id": trigger_id,
            "active_task_ids": [str(active_task.id)],
        }

        active_task.status = JoySafeterTaskStatus.COMPLETED.value
        await db_session.commit()

        delete_resp = await client.delete(f"/api/v1/triggers/{trigger_id}")
        assert delete_resp.status_code == 204

        missing_resp = await client.get(f"/api/v1/triggers/{trigger_id}")
        assert missing_resp.status_code == 404
        assert missing_resp.json()["code"] == "TRIGGER_NOT_FOUND"

        list_after_delete_resp = await client.get("/api/v1/triggers", params={"type": "webhook"})
        assert list_after_delete_resp.status_code == 200
        assert [item["id"] for item in list_after_delete_resp.json()] == []

        deleted_runs_resp = await client.get(f"/api/v1/triggers/{trigger_id}/runs")
        assert deleted_runs_resp.status_code == 200
        deleted_runs = deleted_runs_resp.json()["data"]
        assert len(deleted_runs) == 1
        assert deleted_runs[0]["id"] == fired["task_id"]
        assert deleted_runs[0]["trigger_id"] == trigger_id

        detached_task = (
            await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == active_task.id))
        ).scalar_one()
        assert detached_task.trigger_id == original_task_trigger_id

        recreate_resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "Manual HTTP E2E Updated",
                "type": "webhook",
                "agent_id": str(agent.id),
                "prompt_template": "handle again",
                "secret_ref": "hook-secret",
                "auth_methods": ["hmac"],
            },
        )
        assert recreate_resp.status_code == 201
        assert recreate_resp.json()["id"] != trigger_id


@pytest.mark.asyncio
async def test_trigger_http_manual_type_create_list_run_and_history(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    app = _app(db_session, _ctx(project.id, org.id))

    async with _client(app) as client:
        create_resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "Manual Type HTTP E2E",
                "type": "manual",
                "agent_id": str(agent.id),
                "prompt_template": "run {{ trigger.source_type }} via {{ trigger.type }}",
                "session_mode": "fresh",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        trigger_id = created["id"]
        assert created["type"] == "manual"
        assert created["webhook_url"] is None
        assert created["config"] == {}
        assert created["cron_expr"] is None
        assert created["run_at"] is None
        assert created["next_run_at"] is None
        assert created["secret_ref"] is None
        assert created["secret_key"] is None

        manual_list_resp = await client.get("/api/v1/triggers", params={"type": "manual"})
        assert manual_list_resp.status_code == 200
        assert [item["id"] for item in manual_list_resp.json()] == [trigger_id]

        run_resp = await client.post(
            f"/api/v1/triggers/{trigger_id}/run",
            headers={"Idempotency-Key": "manual-type-e2e-key"},
        )
        assert run_resp.status_code == 202
        fired = run_resp.json()
        assert fired["status"] == "fired"
        assert fired["task_id"].startswith("task_")
        assert fired["session_id"].startswith("sess_")

        runs_resp = await client.get(f"/api/v1/triggers/{trigger_id}/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()["data"]
        assert len(runs) == 1
        assert runs[0]["id"] == fired["task_id"]
        assert runs[0]["trigger_id"] == trigger_id

    task_uuid = uuid.UUID(fired["task_id"].removeprefix("task_"))
    db_session.expire_all()
    stored_task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_uuid))).scalar_one()
    stored_trigger = (
        await db_session.execute(
            select(JoySafeterTrigger).where(JoySafeterTrigger.id == TriggerId.from_public(trigger_id))
        )
    ).scalar_one()
    stored_session = (
        await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == stored_task.chat_session_id))
    ).scalar_one()
    assert stored_task.prompt == "run manual via manual"
    assert stored_task.trigger_id == stored_trigger.id
    assert stored_session.metadata_["trigger_type"] == "manual"
    assert stored_session.metadata_["source_trigger_type"] == "manual"
    assert stored_trigger.last_payload["trigger"]["type"] == "manual"
    assert stored_trigger.last_payload["trigger"]["source_type"] == "manual"
    assert stored_trigger.config == {}
    assert stored_trigger.secret_ref is None
    assert stored_trigger.secret_key is None
    assert redis.rpushed == [("joysafeter:global_queue", str(task_uuid))]


@pytest.mark.asyncio
async def test_trigger_http_webhook_test_fire_and_sample_flow(db_session, monkeypatch):
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    trigger = JoySafeterTrigger(
        name="Webhook HTTP E2E",
        type="webhook",
        agent_id=agent.id,
        prompt_template="handle {{ body.kind }}",
        enabled=False,
        filter={},
        secret_ref="hook-secret",
        secret_key="WEBHOOK_SECRET",
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        last_payload={},
        project_id=project.id,
        user_id="trigger-http-e2e-user",
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)

    task_id = TaskId.new()
    session_id = SessionId.new()
    captured: dict[str, object] = {}

    async def fake_fire_webhook(
        self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False
    ):
        captured["fire"] = {
            "trigger_id": trigger_arg.id,
            "raw_body": raw_body,
            "payload": payload,
            "delivery_id": delivery_id,
            "auth_fingerprint": auth_fingerprint,
            "ignore_enabled": ignore_enabled,
        }
        return "fired", SimpleNamespace(id=task_id), session_id, False, None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_trigger_service.JoySafeterTriggerService.fire_webhook",
        fake_fire_webhook,
    )
    app = _app(db_session, _ctx(project.id, org.id))
    trigger_id = str(trigger.id)

    async with _client(app) as client:
        sample_resp = await client.get(f"/api/v1/triggers/{trigger_id}/webhook-sample")
        assert sample_resp.status_code == 200
        sample = sample_resp.json()
        assert sample["url"] == f"http://test/api/v1/triggers/{trigger_id}/webhook"
        assert sample["signature_header"] == "X-JoySafeter-Signature"
        assert "X-JoySafeter-Signature: sha256=" in sample["curl"]
        assert '-d \'{"example":"payload"}\'' in sample["curl"]

        test_resp = await client.post(
            f"/api/v1/triggers/{trigger_id}/test",
            json={"kind": "sample"},
        )
        assert test_resp.status_code == 202
        assert test_resp.json() == {
            "status": "fired",
            "task_id": str(task_id),
            "session_id": str(session_id),
            "deduped": False,
            "reason": None,
        }

    assert captured["fire"]["trigger_id"] == trigger.id
    assert captured["fire"]["raw_body"] == b'{"kind": "sample"}'
    assert captured["fire"]["payload"] == {
        "body": {"kind": "sample"},
        "headers": {"content_type": "application/json", "user_agent": "joysafeter-test", "forwarded_for": None},
        "trigger": {"id": str(trigger.id), "name": "Webhook HTTP E2E", "type": "webhook", "test": True},
    }
    assert str(captured["fire"]["delivery_id"]).startswith("test:")
    assert captured["fire"]["auth_fingerprint"] == "test"
    assert captured["fire"]["ignore_enabled"] is True


@pytest.mark.asyncio
async def test_trigger_http_cron_create_toggle_run_and_webhook_only_errors(db_session, monkeypatch):
    redis = _FakeQueueRedis()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: redis),
    )
    org, project, agent = await _seed_project_agent_and_secret(db_session)
    app = _app(db_session, _ctx(project.id, org.id))

    async with _client(app) as client:
        create_resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "Cron HTTP E2E",
                "type": "cron",
                "agent_id": str(agent.id),
                "prompt_template": "run {{ trigger.source_type }}",
                "cron_expr": "*/5 * * * *",
                "timezone": "UTC",
                "concurrency_policy": "forbid",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        trigger_id = created["id"]
        assert created["type"] == "cron"
        assert created["webhook_url"] is None
        assert created["cron_expr"] == "*/5 * * * *"
        assert created["config"]["concurrency_policy"] == "forbid"
        assert created["next_run_at"] is not None

        cron_list_resp = await client.get("/api/v1/triggers", params={"type": "cron"})
        assert cron_list_resp.status_code == 200
        assert [item["id"] for item in cron_list_resp.json()] == [trigger_id]

        webhook_list_resp = await client.get("/api/v1/triggers", params={"type": "webhook"})
        assert webhook_list_resp.status_code == 200
        assert webhook_list_resp.json() == []

        disable_resp = await client.patch(f"/api/v1/triggers/{trigger_id}", json={"enabled": False})
        assert disable_resp.status_code == 200
        disabled = disable_resp.json()
        assert disabled["enabled"] is False
        assert disabled["next_run_at"] is None
        assert disabled["config"]["next_run_at"] is None

        enable_resp = await client.patch(f"/api/v1/triggers/{trigger_id}", json={"enabled": True})
        assert enable_resp.status_code == 200
        enabled = enable_resp.json()
        assert enabled["enabled"] is True
        assert enabled["next_run_at"] is not None
        assert _parse_iso_datetime(enabled["config"]["next_run_at"]) == _parse_iso_datetime(enabled["next_run_at"])

        sample_resp = await client.get(f"/api/v1/triggers/{trigger_id}/webhook-sample")
        assert sample_resp.status_code == 422
        assert sample_resp.json()["code"] == "TRIGGER_NOT_WEBHOOK"

        test_resp = await client.post(f"/api/v1/triggers/{trigger_id}/test", json={"kind": "sample"})
        assert test_resp.status_code == 422
        assert test_resp.json()["code"] == "TRIGGER_NOT_WEBHOOK"

        run_resp = await client.post(
            f"/api/v1/triggers/{trigger_id}/run",
            headers={"Idempotency-Key": "cron-manual-e2e-key"},
        )
        assert run_resp.status_code == 202
        fired = run_resp.json()
        assert fired["status"] == "fired"
        assert fired["task_id"].startswith("task_")
        assert fired["session_id"].startswith("sess_")

        runs_resp = await client.get(f"/api/v1/triggers/{trigger_id}/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()["data"]
        assert len(runs) == 1
        assert runs[0]["id"] == fired["task_id"]
        assert runs[0]["trigger_id"] == trigger_id

    task_uuid = uuid.UUID(fired["task_id"].removeprefix("task_"))
    db_session.expire_all()
    stored_task = (await db_session.execute(select(JoySafeterTask).where(JoySafeterTask.id == task_uuid))).scalar_one()
    assert stored_task.prompt == "run cron"
    assert stored_task.trigger_id == TriggerId.from_public(trigger_id)
    assert redis.rpushed == [("joysafeter:global_queue", str(task_uuid))]


@pytest.mark.asyncio
async def test_trigger_http_management_endpoints_are_project_scoped(db_session, monkeypatch):
    org_a, project_a, _agent_a = await _seed_project_agent_and_secret(db_session)
    org_b, project_b, agent_b = await _seed_project_agent_and_secret(db_session)
    trigger_b = JoySafeterTrigger(
        name="Project B Webhook",
        type="webhook",
        agent_id=agent_b.id,
        prompt_template="handle cross project",
        enabled=True,
        filter={},
        secret_ref="hook-secret",
        secret_key="WEBHOOK_SECRET",
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        last_payload={},
        project_id=project_b.id,
        user_id="project-b-user",
        org_id=org_b.id,
    )
    db_session.add(trigger_b)
    await db_session.commit()
    await db_session.refresh(trigger_b)
    trigger_b_uuid = trigger_b.id

    async def fail_fire_manual(self, *args, **kwargs):
        raise AssertionError("cross-project trigger must not reach fire_manual")

    monkeypatch.setattr(JoySafeterTriggerService, "fire_manual", fail_fire_manual)
    app = _app(db_session, _ctx(project_a.id, org_a.id))
    trigger_id = str(trigger_b.id)

    async with _client(app) as client:
        list_resp = await client.get("/api/v1/triggers")
        assert list_resp.status_code == 200
        assert all(item["id"] != trigger_id for item in list_resp.json())

        get_resp = await client.get(f"/api/v1/triggers/{trigger_id}")
        patch_resp = await client.patch(f"/api/v1/triggers/{trigger_id}", json={"name": "stolen"})
        run_resp = await client.post(f"/api/v1/triggers/{trigger_id}/run")
        runs_resp = await client.get(f"/api/v1/triggers/{trigger_id}/runs")
        delete_resp = await client.delete(f"/api/v1/triggers/{trigger_id}")

        for resp in (get_resp, patch_resp, run_resp, runs_resp, delete_resp):
            assert resp.status_code == 404
            assert resp.json()["code"] == "TRIGGER_NOT_FOUND"

        create_resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "Cross Project Create",
                "type": "webhook",
                "agent_id": str(agent_b.id),
                "prompt_template": "must not bind",
                "secret_ref": "hook-secret",
                "auth_methods": ["hmac"],
            },
        )
        assert create_resp.status_code == 404
        assert create_resp.json()["code"] == "TRIGGER_AGENT_NOT_FOUND"

    db_session.expire_all()
    stored = (
        await db_session.execute(select(JoySafeterTrigger).where(JoySafeterTrigger.id == trigger_b_uuid))
    ).scalar_one()
    assert stored.name == "Project B Webhook"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/api/v1/triggers/not-a-trigger", {}),
        ("PATCH", "/api/v1/triggers/not-a-trigger", {"json": {"name": "bad"}}),
        ("DELETE", "/api/v1/triggers/not-a-trigger", {}),
        ("POST", "/api/v1/triggers/not-a-trigger/run", {}),
        ("GET", "/api/v1/triggers/not-a-trigger/runs", {}),
        ("GET", "/api/v1/triggers/not-a-trigger/webhook-sample", {}),
        ("POST", "/api/v1/triggers/not-a-trigger/test", {"json": {"kind": "sample"}}),
    ],
)
async def test_trigger_http_management_endpoints_return_structured_invalid_id(db_session, method, path, kwargs):
    org, project, _agent = await _seed_project_agent_and_secret(db_session)
    app = _app(db_session, _ctx(project.id, org.id))

    async with _client(app) as client:
        resp = await client.request(method, path, **kwargs)

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "TRIGGER_ID_INVALID"
    assert body["data"] == {
        "field": "trigger_id",
        "trigger_id": "not-a-trigger",
        "expected_prefix": "trig_",
    }
