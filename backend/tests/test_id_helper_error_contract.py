import uuid

import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.id_helpers import parse_agent_id, parse_session_id, parse_vault_id
from app.joysafeter_shared.common.app_errors import AppError


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
