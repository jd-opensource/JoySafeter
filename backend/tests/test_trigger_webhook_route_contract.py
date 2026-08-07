import uuid
from types import SimpleNamespace

import httpx
import pytest
from credential_test_helpers import encrypted_secret_data
from fastapi import FastAPI

from app.joysafeter_api.api.v1 import triggers as trigger_api
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_domain.services.joysafeter_trigger_webhook_auth_service import WebhookAuthService
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.ids import SessionId, TaskId
from app.joysafeter_shared.rate_limit import _rate_limiter


def _app(db) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(trigger_api.router, prefix="/api/v1/triggers")
    app.dependency_overrides[trigger_api.get_db] = lambda: db
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed_webhook_trigger(
    db_session,
    *,
    config: dict,
    name: str = "route-hook",
) -> JoySafeterTrigger:
    unique = uuid.uuid4()
    org = Organization(name=f"Webhook Route Org {unique}", slug=f"webhook-route-org-{unique}")
    db_session.add(org)
    await db_session.flush()

    project = Project(org_id=org.id, name="Webhook Route Project", slug=f"webhook-route-project-{unique}")
    db_session.add(project)
    await db_session.flush()

    agent = JoySafeterAgent(name=f"webhook-route-agent-{unique}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()

    trigger = JoySafeterTrigger(
        name=f"{name}-{unique}",
        type="webhook",
        agent_id=agent.id,
        prompt_template="handle route delivery",
        enabled=True,
        filter={},
        secret_ref="hook-secret",
        secret_key="WEBHOOK_SECRET",
        config=config,
        last_payload={},
        project_id=project.id,
        user_id="owner-user",
        org_id=org.id,
    )
    db_session.add(trigger)
    await db_session.commit()
    await db_session.refresh(trigger)
    return trigger


@pytest.mark.asyncio
async def test_webhook_route_maps_hmac_headers_payload_and_delivery_id(db_session, monkeypatch):
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-provider-delivery"},
    )
    raw_body = b'{"kind":"wanted"}'
    captured: dict[str, object] = {}
    task_id = TaskId.new()
    session_id = SessionId.new()

    async def fake_verify(self, trigger_arg, raw_body_arg, signature, token):
        captured["verify"] = {
            "trigger_id": trigger_arg.id,
            "raw_body": raw_body_arg,
            "signature": signature,
            "token": token,
        }
        return True

    async def fake_fire(self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False):
        captured["fire"] = {
            "trigger_id": trigger_arg.id,
            "raw_body": raw_body,
            "payload": payload,
            "delivery_id": delivery_id,
            "auth_fingerprint": auth_fingerprint,
            "ignore_enabled": ignore_enabled,
        }
        return "fired", SimpleNamespace(id=task_id), session_id, False, None

    monkeypatch.setattr(JoySafeterTriggerService, "verify_webhook_auth", fake_verify)
    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    async with _client(app) as client:
        resp = await client.post(
            f"/api/v1/triggers/{trigger.id}/webhook",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "route-test",
                "X-Forwarded-For": "203.0.113.10",
                "X-JoySafeter-Signature": "sha256=primary",
                "X-Hub-Signature-256": "sha256=legacy",
                "X-JoySafeter-Delivery-Id": "joy-delivery",
                "X-GitHub-Delivery": "github-delivery",
                "X-Provider-Delivery": "provider-delivery",
            },
        )

    assert resp.status_code == 202
    assert resp.json() == {
        "status": "fired",
        "task_id": str(task_id),
        "session_id": str(session_id),
        "deduped": False,
        "reason": None,
    }
    assert captured["verify"] == {
        "trigger_id": trigger.id,
        "raw_body": raw_body,
        "signature": "sha256=primary",
        "token": None,
    }
    assert captured["fire"] == {
        "trigger_id": trigger.id,
        "raw_body": raw_body,
        "payload": {
            "body": {"kind": "wanted"},
            "headers": {
                "content_type": "application/json",
                "user_agent": "route-test",
                "forwarded_for": "203.0.113.10",
            },
            "trigger": {"id": str(trigger.id), "name": trigger.name, "type": "webhook"},
        },
        "delivery_id": "provider-delivery",
        "auth_fingerprint": "sha256=primary",
        "ignore_enabled": False,
    }


@pytest.mark.asyncio
async def test_webhook_route_resolves_project_secret_and_verifies_real_hmac(db_session, monkeypatch):
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        name="real-hmac-route-hook",
    )
    secret_value = "route-secret"
    db_session.add(
        JoySafeterSecret(
            name="hook-secret",
            project_id=trigger.project_id,
            provider="custom",
            protocol="custom",
            data=encrypted_secret_data({"WEBHOOK_SECRET": secret_value}),
        )
    )
    await db_session.commit()

    raw_body = b'{"kind":"real-hmac"}'
    signature = f"sha256={WebhookAuthService.sign(secret_value, raw_body)}"
    task_id = TaskId.new()
    session_id = SessionId.new()
    captured: dict[str, object] = {}

    async def fake_fire(self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False):
        captured["fire"] = {
            "trigger_id": trigger_arg.id,
            "delivery_id": delivery_id,
            "auth_fingerprint": auth_fingerprint,
        }
        return "fired", SimpleNamespace(id=task_id), session_id, False, None

    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    async with _client(app) as client:
        resp = await client.post(
            f"/api/v1/triggers/{trigger.id}/webhook",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-JoySafeter-Signature": signature,
                "X-JoySafeter-Delivery-Id": "real-hmac-delivery",
            },
        )

    assert resp.status_code == 202
    assert resp.json()["task_id"] == str(task_id)
    assert captured["fire"] == {
        "trigger_id": trigger.id,
        "delivery_id": "real-hmac-delivery",
        "auth_fingerprint": signature,
    }


@pytest.mark.asyncio
async def test_webhook_route_accepts_bearer_token_and_wraps_non_json_body(db_session, monkeypatch):
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["bearer"], "dedupe_header": "x-joysafeter-delivery"},
        name="bearer-route-hook",
    )
    raw_body = b"plain text payload"
    captured: dict[str, object] = {}
    task_id = TaskId.new()
    session_id = SessionId.new()

    async def fake_verify(self, trigger_arg, raw_body_arg, signature, token):
        captured["verify"] = {
            "trigger_id": trigger_arg.id,
            "raw_body": raw_body_arg,
            "signature": signature,
            "token": token,
        }
        return True

    async def fake_fire(self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False):
        captured["fire"] = {
            "payload": payload,
            "delivery_id": delivery_id,
            "auth_fingerprint": auth_fingerprint,
            "ignore_enabled": ignore_enabled,
        }
        return "deduped", SimpleNamespace(id=task_id), session_id, True, None

    monkeypatch.setattr(JoySafeterTriggerService, "verify_webhook_auth", fake_verify)
    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    async with _client(app) as client:
        resp = await client.post(
            f"/api/v1/triggers/{trigger.id}/webhook",
            content=raw_body,
            headers={
                "Authorization": "Bearer token-secret",
                "Content-Type": "text/plain",
                "X-JoySafeter-Delivery-Id": "token-delivery",
            },
        )

    assert resp.status_code == 202
    assert resp.json()["status"] == "deduped"
    assert resp.json()["deduped"] is True
    assert captured["verify"] == {
        "trigger_id": trigger.id,
        "raw_body": raw_body,
        "signature": None,
        "token": "token-secret",
    }
    assert captured["fire"] == {
        "payload": {
            "body": {"raw": "plain text payload"},
            "headers": {
                "content_type": "text/plain",
                "user_agent": "python-httpx/0.28.1",
                "forwarded_for": None,
            },
            "trigger": {"id": str(trigger.id), "name": trigger.name, "type": "webhook"},
        },
        "delivery_id": "token-delivery",
        "auth_fingerprint": "token-secret",
        "ignore_enabled": False,
    }


@pytest.mark.asyncio
async def test_webhook_route_rejects_invalid_auth_before_fire(db_session, monkeypatch):
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        name="reject-route-hook",
    )

    async def fake_verify(self, trigger_arg, raw_body_arg, signature, token):
        return False

    async def fake_fire(self, *args, **kwargs):
        raise AssertionError("invalid webhook auth must not fire the trigger")

    monkeypatch.setattr(JoySafeterTriggerService, "verify_webhook_auth", fake_verify)
    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    async with _client(app) as client:
        resp = await client.post(
            f"/api/v1/triggers/{trigger.id}/webhook",
            json={"kind": "wanted"},
            headers={"X-JoySafeter-Signature": "sha256=bad"},
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_WEBHOOK_UNAUTHORIZED"
    assert resp.json()["user_action"] == "fix_input"


@pytest.mark.asyncio
async def test_webhook_route_hides_secret_resolution_errors_from_public_callers(db_session, monkeypatch):
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        name="missing-secret-route-hook",
    )

    async def fake_fire(self, *args, **kwargs):
        raise AssertionError("misconfigured webhook auth must not fire the trigger")

    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    async with _client(app) as client:
        resp = await client.post(
            f"/api/v1/triggers/{trigger.id}/webhook",
            json={"kind": "wanted"},
            headers={"X-JoySafeter-Signature": "sha256=" + "0" * 64},
        )

    assert resp.status_code == 422
    assert resp.json()["code"] == "TRIGGER_WEBHOOK_UNAUTHORIZED"
    assert resp.json()["data"] == {}
    assert "hook-secret" not in resp.text
    assert str(trigger.id) not in resp.text


@pytest.mark.asyncio
async def test_webhook_route_rate_limits_by_trigger_and_client_ip(db_session, monkeypatch):
    _rate_limiter._requests.clear()
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        name="rate-limit-route-hook",
    )
    task_id = TaskId.new()
    session_id = SessionId.new()
    fire_count = 0

    async def fake_verify(self, trigger_arg, raw_body_arg, signature, token):
        return True

    async def fake_fire(self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False):
        nonlocal fire_count
        fire_count += 1
        return "fired", SimpleNamespace(id=task_id), session_id, False, None

    monkeypatch.setattr(JoySafeterTriggerService, "verify_webhook_auth", fake_verify)
    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    try:
        async with _client(app) as client:
            for index in range(60):
                resp = await client.post(
                    f"/api/v1/triggers/{trigger.id}/webhook",
                    json={"attempt": index},
                    headers={
                        "X-Forwarded-For": "203.0.113.60",
                        "X-JoySafeter-Signature": "sha256=ok",
                        "X-JoySafeter-Delivery-Id": f"rate-limit-{index}",
                    },
                )
                assert resp.status_code == 202

            limited_resp = await client.post(
                f"/api/v1/triggers/{trigger.id}/webhook",
                json={"attempt": 60},
                headers={
                    "X-Forwarded-For": "203.0.113.60",
                    "X-JoySafeter-Signature": "sha256=ok",
                    "X-JoySafeter-Delivery-Id": "rate-limit-60",
                },
            )
    finally:
        _rate_limiter._requests.clear()

    assert limited_resp.status_code == 429
    assert limited_resp.json()["code"] == "RATE_LIMITED"
    assert fire_count == 60


@pytest.mark.asyncio
async def test_webhook_route_rate_limit_cannot_be_bypassed_by_spoofing_forwarded_for(db_session, monkeypatch):
    _rate_limiter._requests.clear()
    trigger = await _seed_webhook_trigger(
        db_session,
        config={"auth_methods": ["hmac"], "dedupe_header": "x-joysafeter-delivery"},
        name="rate-limit-spoof-route-hook",
    )
    task_id = TaskId.new()
    session_id = SessionId.new()
    fire_count = 0

    async def fake_verify(self, trigger_arg, raw_body_arg, signature, token):
        return True

    async def fake_fire(self, trigger_arg, *, raw_body, payload, delivery_id, auth_fingerprint, ignore_enabled=False):
        nonlocal fire_count
        fire_count += 1
        return "fired", SimpleNamespace(id=task_id), session_id, False, None

    monkeypatch.setattr(JoySafeterTriggerService, "verify_webhook_auth", fake_verify)
    monkeypatch.setattr(JoySafeterTriggerService, "fire_webhook", fake_fire)

    app = _app(db_session)
    try:
        async with _client(app) as client:
            for index in range(60):
                resp = await client.post(
                    f"/api/v1/triggers/{trigger.id}/webhook",
                    json={"attempt": index},
                    headers={
                        "X-Forwarded-For": f"203.0.113.{index}",
                        "X-JoySafeter-Signature": "sha256=ok",
                        "X-JoySafeter-Delivery-Id": f"spoof-rate-limit-{index}",
                    },
                )
                assert resp.status_code == 202

            limited_resp = await client.post(
                f"/api/v1/triggers/{trigger.id}/webhook",
                json={"attempt": 60},
                headers={
                    "X-Forwarded-For": "198.51.100.200",
                    "X-JoySafeter-Signature": "sha256=ok",
                    "X-JoySafeter-Delivery-Id": "spoof-rate-limit-60",
                },
            )
    finally:
        _rate_limiter._requests.clear()

    assert limited_resp.status_code == 429
    assert limited_resp.json()["code"] == "RATE_LIMITED"
    assert fire_count == 60
