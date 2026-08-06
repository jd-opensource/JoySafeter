import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.files import _parse_session_scope
from app.joysafeter_api.api.v1.id_helpers import (
    parse_agent_id,
    parse_memory_id,
    parse_memory_store_id,
    parse_memory_version_id,
    parse_session_id,
    parse_task_after_id,
    parse_task_id,
    parse_trigger_id,
    parse_vault_id,
)
from app.joysafeter_api.api.v1.network_policies import NetworkPolicyStatusResponse
from app.joysafeter_domain.schemas.analytics import CallRecord
from app.joysafeter_domain.schemas.joysafeter_file import FileResponse
from app.joysafeter_domain.schemas.joysafeter_sandbox import SandboxResponse
from app.joysafeter_domain.schemas.joysafeter_session import SessionAgent, SessionResponse
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import AgentId, SessionId, TaskId

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_parse_agent_id_invalid_value_returns_structured_error():
    with pytest.raises(AppError) as exc_info:
        parse_agent_id("agent_not-a-uuid")

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "AGENT_ID_INVALID",
        "message": "Invalid agent_id: agent_not-a-uuid",
        "data": {
            "field": "agent_id",
            "agent_id": "agent_not-a-uuid",
            "expected_prefix": "agent_",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


def test_parse_session_id_accepts_prefixed_uuid():
    session_id = uuid.uuid4()

    assert parse_session_id(f"sess_{session_id}") == SessionId(session_id)


def test_parse_task_id_accepts_prefixed_uuid():
    task_id = uuid.uuid4()

    assert parse_task_id(f"task_{task_id}") == TaskId(task_id)


def test_parse_task_after_id_accepts_public_cursor_and_bare_uuid():
    task_id = uuid.uuid4()

    assert parse_task_after_id(f"task_{task_id}") == task_id
    assert parse_task_after_id(str(task_id)) == task_id
    assert parse_task_after_id(None) is None


def test_analytics_call_record_serializes_canonical_resource_ids():
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    payload = CallRecord(
        id=str(task_id),
        trace_id=str(task_id),
        session_id=str(session_id),
        agent_id=str(agent_id),
        status="completed",
    ).model_dump()

    assert payload["id"] == f"task_{task_id}"
    assert payload["trace_id"] == f"task_{task_id}"
    assert payload["session_id"] == f"sess_{session_id}"
    assert payload["agent_id"] == f"agent_{agent_id}"


def test_task_references_in_operational_responses_use_canonical_prefix():
    task_id = uuid.uuid4()
    now = datetime.now(UTC)

    sandbox_payload = SandboxResponse(
        id=uuid.uuid4(),
        provider="kubernetes",
        status="idle",
        image="sandbox:latest",
        last_task_id=task_id,
        last_used_at=now,
        created_at=now,
    ).model_dump(mode="json")
    policy_payload = NetworkPolicyStatusResponse(
        sandbox_id=uuid.uuid4(),
        task_id=task_id,
        sandbox_status="idle",
        networking_status="ready",
        sandbox_updated_at=now,
    ).model_dump(mode="json")

    assert sandbox_payload["last_task_id"] == f"task_{task_id}"
    assert policy_payload["task_id"] == f"task_{task_id}"


def test_file_response_uses_canonical_session_prefix():
    session_id = uuid.uuid4()
    response = FileResponse.from_model(
        SimpleNamespace(
            id=uuid.uuid4(),
            filename="report.txt",
            purpose="assistants",
            content_type="text/plain",
            size_bytes=6,
            sha256="abc123",
            downloadable=True,
            session_id=session_id,
            created_at=datetime.now(UTC),
        )
    )

    assert response.session_id == f"sess_{session_id}"


def test_file_scope_rejects_removed_session_prefix():
    with pytest.raises(AppError):
        _parse_session_scope(f"sesn_{uuid.uuid4()}")


def test_session_response_serializes_canonical_session_prefix():
    session_id = uuid.uuid4()
    response = SessionResponse(
        id=SessionId(session_id),
        agent=SessionAgent(id=AgentId(uuid.uuid4()), version=1, name="a"),
        status="idle",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert response.model_dump(mode="json")["id"] == f"sess_{session_id}"
    assert str(response.model_dump()["id"]) == f"sess_{session_id}"


def test_parse_trigger_id_accepts_prefixed_uuid():
    trigger_id = uuid.uuid4()

    assert parse_trigger_id(f"trig_{trigger_id}") == trigger_id


def test_parse_memory_ids_accept_prefixed_uuid():
    store_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    version_id = uuid.uuid4()

    assert parse_memory_store_id(f"memstore_{store_id}") == store_id
    assert parse_memory_id(f"mem_{memory_id}") == memory_id
    assert parse_memory_version_id(f"memver_{version_id}") == version_id


@pytest.mark.asyncio
async def test_parse_vault_id_invalid_value_returns_structured_error():
    with pytest.raises(AppError) as exc_info:
        parse_vault_id("vault_not-a-uuid")

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "VAULT_ID_INVALID",
        "message": "Invalid vault_id: vault_not-a-uuid",
        "data": {
            "field": "vault_id",
            "vault_id": "vault_not-a-uuid",
            "expected_prefix": "vault_",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
