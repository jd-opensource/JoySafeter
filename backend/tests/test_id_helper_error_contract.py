import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1.files import _parse_session_scope
from app.joysafeter_api.api.v1.network_policies import NetworkPolicyStatusResponse
from app.joysafeter_domain.schemas.analytics import AgentMetricsResponse, AgentRankingItem, AlertItem, CallRecord
from app.joysafeter_domain.schemas.joysafeter_file import FileResponse
from app.joysafeter_domain.schemas.joysafeter_sandbox import SandboxResponse
from app.joysafeter_domain.schemas.joysafeter_session import SessionAgent, SessionResponse
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import (
    AgentId,
    MemoryId,
    MemoryStoreId,
    MemoryVersionId,
    SandboxId,
    SessionId,
    TaskId,
)

pytestmark = pytest.mark.no_db


def test_analytics_call_record_serializes_canonical_resource_ids():
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    payload = CallRecord(
        id=TaskId(task_id),
        trace_id=TaskId(task_id),
        session_id=SessionId(session_id),
        agent_id=AgentId(agent_id),
        status="completed",
    ).model_dump()

    assert payload["id"] == f"task_{task_id}"
    assert payload["trace_id"] == f"task_{task_id}"
    assert payload["session_id"] == f"sess_{session_id}"
    assert payload["agent_id"] == f"agent_{agent_id}"


def test_analytics_agent_responses_serialize_typed_identity():
    agent_id = AgentId.new()

    metrics = AgentMetricsResponse(agent_id=agent_id, agent_name="Agent").model_dump()
    alert = AlertItem(type="slow_agent", severity="warning", agent_id=agent_id).model_dump()
    ranking = AgentRankingItem(
        agent_id=agent_id,
        agent_name="Agent",
        total_tasks=0,
        success_rate=0,
        failed_count=0,
        avg_duration_ms=0,
        total_tokens=0,
        activity_status="unused",
    ).model_dump()

    assert metrics["agent_id"] == str(agent_id)
    assert alert["agent_id"] == str(agent_id)
    assert ranking["agent_id"] == str(agent_id)


def test_task_references_in_operational_responses_use_canonical_prefix():
    task_id = uuid.uuid4()
    sandbox_id = SandboxId.new()
    now = datetime.now(UTC)

    sandbox_payload = SandboxResponse(
        id=sandbox_id,
        provider="kubernetes",
        status="idle",
        image="sandbox:latest",
        last_task_id=task_id,
        last_used_at=now,
        created_at=now,
    ).model_dump(mode="json")
    policy_payload = NetworkPolicyStatusResponse(
        sandbox_id=sandbox_id,
        task_id=task_id,
        sandbox_status="idle",
        networking_status="ready",
        sandbox_updated_at=now,
    ).model_dump(mode="json")

    assert sandbox_payload["last_task_id"] == f"task_{task_id}"
    assert sandbox_payload["id"] == str(sandbox_id)
    assert policy_payload["sandbox_id"] == str(sandbox_id)
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
            session_id=SessionId(session_id),
            created_at=datetime.now(UTC),
        )
    )

    assert response.session_id == SessionId(session_id)


def test_file_scope_rejects_removed_session_prefix():
    with pytest.raises(AppError):
        _parse_session_scope(f"sesn_{uuid.uuid4()}")


def test_file_scope_rejects_bare_session_uuid():
    with pytest.raises(AppError):
        _parse_session_scope(str(uuid.uuid4()))


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


def test_memory_ids_require_their_canonical_public_prefix():
    store_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    version_id = uuid.uuid4()

    assert MemoryStoreId.from_public(f"memstore_{store_id}") == MemoryStoreId(store_id)
    assert MemoryId.from_public(f"mem_{memory_id}") == MemoryId(memory_id)
    assert MemoryVersionId.from_public(f"memver_{version_id}") == MemoryVersionId(version_id)
    with pytest.raises(ValueError):
        MemoryStoreId.from_public(str(store_id))
    with pytest.raises(ValueError):
        MemoryId.from_public(f"memver_{memory_id}")
