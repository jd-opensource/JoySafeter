import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.joysafeter_api.id_validation_error import app_error_for_id_validation
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.ids import AgentId

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_agent_id_invalid_maps_to_canonical_contract():
    # Simulated pydantic error loc/input for an AgentId field named "agent_id".
    err = {"loc": ("body", "agent_id"), "input": "agent_not-a-uuid", "ctx": {"id_cls": AgentId}}
    app_error = app_error_for_id_validation(err)
    assert app_error is not None
    assert await handled_app_error_payload(app_error, status_code=400) == {
        "code": "AGENT_ID_INVALID",
        "message": "Invalid agent_id: agent_not-a-uuid",
        "data": {"field": "agent_id", "agent_id": "agent_not-a-uuid", "expected_prefix": "agent_"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


def test_marker_path_recovers_id_cls_without_ctx():
    # No ctx.id_cls — must recover the class from the raised marker message,
    # proving the real-pydantic path (ValueError("__entity_id__:AgentId")) works.
    err = {"loc": ("body", "agent_id"), "input": "agent_bad", "msg": "Value error, __entity_id__:AgentId"}
    app_error = app_error_for_id_validation(err)
    assert app_error is not None
    assert app_error.code == "AGENT_ID_INVALID"
    assert app_error.data["expected_prefix"] == "agent_"


def test_non_id_error_returns_none():
    err = {"loc": ("body", "name"), "input": "", "msg": "field required"}
    assert app_error_for_id_validation(err) is None


def _build_typed_id_app() -> FastAPI:
    """Minimal self-contained app with a real AgentId body field."""
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        agent_id: AgentId

    @app.post("/typed")
    async def _create(body: Body) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(body.agent_id)}

    return app


def test_integration_invalid_agent_id_yields_canonical_400():
    client = TestClient(_build_typed_id_app())
    resp = client.post("/typed", json={"agent_id": "agent_not-a-uuid"})
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["code"] == "AGENT_ID_INVALID"
    assert payload["message"] == "Invalid agent_id: agent_not-a-uuid"
    assert payload["data"] == {
        "field": "agent_id",
        "agent_id": "agent_not-a-uuid",
        "expected_prefix": "agent_",
    }
    assert payload["source"] == "api"
    assert payload["retryable"] is False
    assert payload["user_action"] == "fix_input"


def test_integration_valid_agent_id_passes_through():
    client = TestClient(_build_typed_id_app())
    good = f"agent_{uuid.uuid4()}"
    resp = client.post("/typed", json={"agent_id": good})
    assert resp.status_code == 200
    assert resp.json() == {"ok": good}
