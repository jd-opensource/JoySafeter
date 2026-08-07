import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.joysafeter_api.id_validation_error import app_error_for_id_validation
from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialId,
    EnvironmentId,
    FileId,
    SecretId,
    SessionId,
    SessionResourceId,
    TaskId,
    VaultId,
)

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

    @app.get("/typed/{agent_id}")
    async def _read(agent_id: AgentId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(agent_id)}

    @app.get("/typed-session/{session_id}")
    async def _read_session(session_id: SessionId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(session_id)}

    @app.get("/typed-task/{task_id}")
    async def _read_task(task_id: TaskId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(task_id)}

    @app.get("/typed-tasks")
    async def _list_tasks(after_id: TaskId | None = None) -> dict:  # pragma: no cover - exercised via client
        return {"after_id": str(after_id) if after_id is not None else None}

    @app.get("/typed-environment/{env_id}")
    async def _read_environment(env_id: EnvironmentId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(env_id)}

    @app.get("/typed-file/{file_id}")
    async def _read_file(file_id: FileId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(file_id)}

    @app.get("/typed-resource/{resource_id}")
    async def _read_resource(resource_id: SessionResourceId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(resource_id)}

    @app.get("/typed-secret/{secret_id}")
    async def _read_secret(secret_id: SecretId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(secret_id)}

    @app.get("/typed-vault/{vault_id}")
    async def _read_vault(vault_id: VaultId) -> dict:  # pragma: no cover - exercised via client
        return {"ok": str(vault_id)}

    @app.get("/typed-vault/{vault_id}/credentials/{cred_id}")
    async def _read_credential(
        vault_id: VaultId,
        cred_id: CredentialId,
    ) -> dict:  # pragma: no cover - exercised via client
        return {"vault_id": str(vault_id), "cred_id": str(cred_id)}

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


def test_integration_invalid_agent_path_id_yields_canonical_400():
    client = TestClient(_build_typed_id_app())
    resp = client.get("/typed/agent_not-a-uuid")

    assert resp.status_code == 400
    assert resp.json()["data"] == {
        "field": "agent_id",
        "agent_id": "agent_not-a-uuid",
        "expected_prefix": "agent_",
    }


@pytest.mark.parametrize(
    ("path", "field", "prefix"),
    [
        (f"/typed-session/{uuid.uuid4()}", "session_id", "sess_"),
        (f"/typed-task/{uuid.uuid4()}", "task_id", "task_"),
        (f"/typed-tasks?after_id={uuid.uuid4()}", "after_id", "task_"),
        (f"/typed-environment/{uuid.uuid4()}", "env_id", "env_"),
        (f"/typed-file/{uuid.uuid4()}", "file_id", "file_"),
        (f"/typed-resource/{uuid.uuid4()}", "resource_id", "sesrsc_"),
        (f"/typed-secret/{uuid.uuid4()}", "secret_id", "secret_"),
        (f"/typed-vault/{uuid.uuid4()}", "vault_id", "vault_"),
        (
            f"/typed-vault/vault_{uuid.uuid4()}/credentials/{uuid.uuid4()}",
            "cred_id",
            "cred_",
        ),
    ],
)
def test_integration_bare_core_ids_are_rejected_at_public_boundaries(path: str, field: str, prefix: str):
    client = TestClient(_build_typed_id_app())
    resp = client.get(path)

    assert resp.status_code == 400
    assert resp.json()["code"] == f"{field.upper()}_INVALID"
    assert resp.json()["data"]["expected_prefix"] == prefix
