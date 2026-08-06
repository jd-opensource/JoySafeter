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
    parse_trigger_id,
    parse_vault_id,
)
from app.joysafeter_domain.schemas.joysafeter_file import FileResponse
from app.joysafeter_shared.common.app_errors import AppError

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

    assert parse_session_id(f"sess_{session_id}") == session_id


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
