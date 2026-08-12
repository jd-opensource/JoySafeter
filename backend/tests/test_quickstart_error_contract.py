"""Error-contract tests for the quickstart chat route after the 9e consumer
sweep: the request references a model credential by ``model_credential_id``
(CredentialId) and resolves it via ``CredentialService`` (was the name-based
``secret_ref`` + ``SecretService``).

The upstream-event helpers are pure functions; the resolution-path tests use
conftest's real ``db_session`` (the full app is un-loadable mid-cutover, so we
call the route function directly).
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.quickstart import (
    QuickstartChatRequest,
    QuickstartMessage,
    _upstream_connection_error_event,
    _upstream_error_event,
    _upstream_stream_error_event,
    quickstart_chat,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


def _auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _chat_req(*, model_credential_id: CredentialId, engine_kind: str = "codex") -> QuickstartChatRequest:
    return QuickstartChatRequest(
        model_credential_id=model_credential_id,
        engine_kind=engine_kind,
        messages=[QuickstartMessage(role="user", content="help me configure an agent")],
    )


async def _make_model_credential(db_session, project_id: str, data: dict[str, str]) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider="openai",
            protocol="openai_responses",
            data=data,
        ),
        project_id=project_id,
    )
    return cred.id


def test_quickstart_schema_uses_model_credential_id_not_secret_ref():
    fields = QuickstartChatRequest.model_fields
    assert "model_credential_id" in fields
    assert "secret_ref" not in fields


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
async def test_quickstart_chat_missing_credential_returns_structured_error(db_session, project_id):
    missing_id = CredentialId.new()

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(
            _chat_req(model_credential_id=missing_id), db_session, _auth_ctx(project_id)
        )

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "CREDENTIAL_NOT_FOUND",
        "message": "Credential not found",
        "data": {"credential_id": str(missing_id), "engine_kind": "codex"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_missing_provider_key_returns_structured_error(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id, {"OPENAI_MODEL": "gpt-5.3-codex"})

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(
            _chat_req(model_credential_id=cred_id), db_session, _auth_ctx(project_id)
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "LLM_SECRET_CREDENTIALS_INCOMPLETE",
        "message": "Required LLM credential fields are missing",
        "data": {
            "provider": "openai",
            "protocol": "openai_responses",
            "required_fields": ["OPENAI_API_KEY"],
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_invalid_base_url_returns_structured_error(db_session, project_id):
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "http://169.254.169.254/latest"},
    )

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(
            _chat_req(model_credential_id=cred_id), db_session, _auth_ctx(project_id)
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_INVALID",
        "message": "Invalid OPENAI_BASE_URL",
        "data": {
            "provider": "openai",
            "key": "OPENAI_BASE_URL",
            "base_url": "http://169.254.169.254/latest",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_rejects_unallowlisted_openai_base_url(db_session, project_id, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://evil.example.com/v1"},
    )

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(
            _chat_req(model_credential_id=cred_id), db_session, _auth_ctx(project_id)
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_NOT_ALLOWED",
        "message": "OPENAI_BASE_URL host is not allowlisted.",
        "data": {
            "provider": "openai",
            "key": "OPENAI_BASE_URL",
            "base_url": "https://evil.example.com/v1",
            "host": "evil.example.com",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
