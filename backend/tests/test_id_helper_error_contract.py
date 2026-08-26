import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger, DateTime, Text

from app.joysafeter_api.api.v1.files import _parse_session_scope
from app.joysafeter_api.api.v1.network_policies import NetworkPolicyStatusResponse
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.analytics import AgentMetricsResponse, AgentRankingItem, AlertItem, CallRecord
from app.joysafeter_domain.schemas.joysafeter_file import FileResponse
from app.joysafeter_domain.schemas.joysafeter_sandbox import SandboxResponse
from app.joysafeter_domain.schemas.joysafeter_session import SessionAgent, SessionResponse
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import (
    AgentId,
    FileId,
    MemoryId,
    MemoryStoreId,
    MemoryVersionId,
    SandboxId,
    SessionId,
    TaskId,
)

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_analytics_call_record_serializes_canonical_resource_ids():
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    record = CallRecord(
        id=TaskId(task_id),
        trace_id=TaskId(task_id),
        session_id=SessionId(session_id),
        agent_id=AgentId(agent_id),
        status="completed",
    )
    payload = record.model_dump()
    json_payload = record.model_dump(mode="json")

    assert payload["id"] == TaskId(task_id)
    assert payload["trace_id"] == TaskId(task_id)
    assert payload["session_id"] == SessionId(session_id)
    assert payload["agent_id"] == AgentId(agent_id)
    assert json_payload["id"] == f"task_{task_id}"
    assert json_payload["trace_id"] == f"task_{task_id}"
    assert json_payload["session_id"] == f"sess_{session_id}"
    assert json_payload["agent_id"] == f"agent_{agent_id}"


def test_analytics_agent_responses_serialize_typed_identity():
    agent_id = AgentId.new()

    metrics_model = AgentMetricsResponse(agent_id=agent_id, agent_name="Agent")
    alert_model = AlertItem(type="slow_agent", severity="warning", agent_id=agent_id)
    ranking_model = AgentRankingItem(
        agent_id=agent_id,
        agent_name="Agent",
        total_tasks=0,
        success_rate=0,
        failed_count=0,
        avg_duration_ms=0,
        total_tokens=0,
        activity_status="unused",
    )

    assert metrics_model.model_dump()["agent_id"] is agent_id
    assert alert_model.model_dump()["agent_id"] is agent_id
    assert ranking_model.model_dump()["agent_id"] is agent_id
    assert metrics_model.model_dump(mode="json")["agent_id"] == str(agent_id)
    assert alert_model.model_dump(mode="json")["agent_id"] == str(agent_id)
    assert ranking_model.model_dump(mode="json")["agent_id"] == str(agent_id)


def test_task_references_in_operational_responses_use_canonical_prefix():
    task_id = TaskId.new()
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

    assert sandbox_payload["last_task_id"] == str(task_id)
    assert sandbox_payload["id"] == str(sandbox_id)
    assert policy_payload["sandbox_id"] == str(sandbox_id)
    assert policy_payload["task_id"] == str(task_id)


def test_sandbox_response_exposes_runtime_config_freshness():
    now = datetime.now(UTC)

    payload = SandboxResponse(
        id=SandboxId.new(),
        provider="kubernetes",
        status="idle",
        image="sandbox:latest",
        last_used_at=now,
        created_at=now,
        runtime_config_status="restart_required",
        runtime_config_last_reason="credential_updated",
        runtime_config_required_at=now,
    ).model_dump()

    assert payload["runtime_config_status"] == "restart_required"
    assert payload["runtime_config_last_reason"] == "credential_updated"
    assert payload["runtime_config_required_at"] == now


def test_runtime_config_generation_model_contracts():
    session_columns = JoySafeterSession.__table__.columns
    sandbox_columns = JoySafeterSandbox.__table__.columns

    session_generation = session_columns["runtime_config_generation"]
    session_reason = session_columns["runtime_config_generation_reason"]
    session_updated_at = session_columns["runtime_config_generation_updated_at"]
    sandbox_generation = sandbox_columns["runtime_config_applied_generation"]

    assert isinstance(session_generation.type, BigInteger)
    assert session_generation.nullable is False
    assert session_generation.default.arg == 0
    assert str(session_generation.server_default.arg) == "0"
    assert isinstance(session_reason.type, Text)
    assert session_reason.nullable is True
    assert isinstance(session_updated_at.type, DateTime)
    assert session_updated_at.type.timezone is True
    assert session_updated_at.nullable is True
    assert isinstance(sandbox_generation.type, BigInteger)
    assert sandbox_generation.nullable is False
    assert sandbox_generation.default.arg == 0
    assert str(sandbox_generation.server_default.arg) == "0"

    rust_models = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/models.rs").read_text()
    assert "pub runtime_config_generation: i64," in rust_models
    assert "pub runtime_config_generation_reason: Option<String>," in rust_models
    assert "pub runtime_config_generation_updated_at: Option<chrono::DateTime<chrono::Utc>>," in rust_models
    assert "pub runtime_config_applied_generation: i64," in rust_models


def test_file_response_uses_canonical_session_prefix():
    session_id = uuid.uuid4()
    file_id = FileId.new()
    response = FileResponse.from_model(
        SimpleNamespace(
            id=file_id,
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

    assert response.id is file_id
    assert response.session_id == SessionId(session_id)
    assert response.model_dump(mode="json")["id"] == str(file_id)
    assert response.model_dump(mode="json")["session_id"] == f"sess_{session_id}"


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
