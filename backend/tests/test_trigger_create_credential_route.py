"""Route-level test for the 9e consumer sweep: the trigger `create` route wires
the request's ``webhook_auth_credential_id`` / ``webhook_auth_field`` through to
the service (the old name-based ``secret_ref`` / ``secret_key`` kwargs are gone).

The full app is intentionally un-loadable mid-cutover, so this exercises the
route function directly with a stubbed service that captures the kwargs it
receives, rather than via TestClient.
"""

import uuid

import pytest
from starlette.requests import Request

from app.joysafeter_api.api.v1 import triggers as trigger_api
from app.joysafeter_api.api.v1.triggers import create_trigger
from app.joysafeter_application.triggers import TriggerApplicationService
from app.joysafeter_domain.schemas.joysafeter_trigger import TriggerCreateRequest
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import AgentId, CredentialId

pytestmark = pytest.mark.no_db


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id="proj-a",
        role=JoySafeterRole.MEMBER,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/triggers",
            "headers": [(b"host", b"test")],
            "query_string": b"",
        }
    )


def _create_req(cred_id: CredentialId) -> TriggerCreateRequest:
    return TriggerCreateRequest(
        name="hook",
        type="webhook",
        agent_id=AgentId.new(),
        prompt_template="handle delivery",
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
    )


@pytest.mark.asyncio
async def test_create_route_passes_credential_id_and_field(monkeypatch):
    cred_id = CredentialId.new()
    captured: dict[str, object] = {}

    class _Trigger:
        id = uuid.uuid4()
        type = "webhook"

    async def fake_create(self, **kwargs):
        captured.update(kwargs)
        return _Trigger()

    monkeypatch.setattr(TriggerApplicationService, "create", fake_create)
    # Neutralize response URL building (needs no real work for kwarg assertions).
    monkeypatch.setattr(trigger_api, "_response", lambda trigger, request: trigger)

    await create_trigger(_request(), _create_req(cred_id), db=None, auth_ctx=_auth_ctx())

    assert captured["webhook_auth_credential_id"] == cred_id
    assert captured["webhook_auth_field"] == "WEBHOOK_SECRET"
    # The dead name-based kwargs must not be forwarded.
    assert "secret_ref" not in captured
    assert "secret_key" not in captured


def test_trigger_create_schema_has_no_secret_ref_field():
    assert "webhook_auth_credential_id" in TriggerCreateRequest.model_fields
    assert "secret_ref" not in TriggerCreateRequest.model_fields
    assert "secret_key" not in TriggerCreateRequest.model_fields
