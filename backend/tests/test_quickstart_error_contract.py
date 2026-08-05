import uuid

import httpx
import pytest
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.quickstart import (
    QuickstartChatRequest,
    QuickstartMessage,
    _upstream_connection_error_event,
    _upstream_error_event,
    _upstream_stream_error_event,
    quickstart_chat,
)
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


def _chat_req(*, secret_ref: str, provider: str = "codex") -> QuickstartChatRequest:
    return QuickstartChatRequest(
        secret_ref=secret_ref,
        provider=provider,
        messages=[QuickstartMessage(role="user", content="help me configure an agent")],
    )


def test_quickstart_upstream_status_error_event_is_structured():
    assert _upstream_error_event(429) == {
        "type": "error",
        "code": "UPSTREAM_RATE_LIMITED",
        "message": "Rate limited by upstream API. Please try again later.",
        "data": None,
        "source": "upstream",
        "retryable": True,
        "status": 429,
    }


def test_quickstart_upstream_connection_error_event_is_retryable():
    assert _upstream_connection_error_event(httpx.ConnectError("connection refused")) == {
        "type": "error",
        "code": "UPSTREAM_CONNECTION_FAILED",
        "message": "Failed to connect to upstream API (ConnectError).",
        "data": None,
        "source": "upstream",
        "retryable": True,
    }


def test_quickstart_upstream_stream_error_event_is_structured():
    assert _upstream_stream_error_event("model refused the request") == {
        "type": "error",
        "code": "UPSTREAM_STREAM_ERROR",
        "message": "model refused the request",
        "data": None,
        "source": "upstream",
        "retryable": False,
    }


@pytest.mark.asyncio
async def test_quickstart_chat_missing_secret_returns_structured_error(db_session):
    missing_ref = f"missing-secret-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(secret_ref=missing_ref), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "QUICKSTART_SECRET_NOT_FOUND",
        "message": "Secret not found or missing required keys",
        "data": {"secret_ref": missing_ref, "provider": "codex"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_missing_provider_key_returns_structured_error(db_session):
    secret = JoySafeterSecret(
        name=f"quickstart-missing-key-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_MODEL": "gpt-5.3-codex"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(secret_ref=secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_SECRET_MISSING_KEY",
        "message": "Secret not found or missing required keys",
        "data": {"secret_ref": secret.name, "provider": "codex", "required_key": "OPENAI_API_KEY"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_invalid_base_url_returns_structured_error(db_session):
    secret = JoySafeterSecret(
        name=f"quickstart-invalid-url-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "http://169.254.169.254/latest"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(secret_ref=secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_INVALID",
        "message": "Invalid OPENAI_BASE_URL",
        "data": {
            "provider": "codex",
            "key": "OPENAI_BASE_URL",
            "base_url": "http://169.254.169.254/latest",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_rejects_unallowlisted_openai_base_url(db_session, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    secret = JoySafeterSecret(
        name=f"quickstart-unallowlisted-url-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://evil.example.com/v1"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(secret_ref=secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_NOT_ALLOWED",
        "message": "OPENAI_BASE_URL host is not allowlisted.",
        "data": {
            "provider": "codex",
            "key": "OPENAI_BASE_URL",
            "base_url": "https://evil.example.com/v1",
            "host": "evil.example.com",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
