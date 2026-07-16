import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy.exc import IntegrityError

from app.joysafeter_api.api.v1.skills_ai_authoring import (
    AuthoringChatRequest,
    AuthoringMessage,
    SaveDraftRequest,
    authoring_chat,
    authoring_save_draft,
)
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import AppError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


def _chat_req(secret_ref: str) -> AuthoringChatRequest:
    return AuthoringChatRequest(
        secret_ref=secret_ref, messages=[AuthoringMessage(role="user", content="Draft a skill")]
    )


@pytest.mark.asyncio
async def test_authoring_save_draft_duplicate_name_raises_conflict(db_session, monkeypatch):
    async def create_conflict(self, **kwargs):
        raise IntegrityError("insert skill", {}, Exception("duplicate skill name"))

    monkeypatch.setattr(SkillService, "create_skill", create_conflict)

    req = SaveDraftRequest(
        name=f"duplicate-skill-{uuid.uuid4()}",
        description="",
        content="# Skill",
        tags=[],
        files=[],
    )

    with pytest.raises(ResourceConflictError) as exc_info:
        await authoring_save_draft(req, db_session, _auth_ctx())

    assert exc_info.value.code == "SKILL_NAME_ALREADY_EXISTS"
    assert "已存在" in exc_info.value.message


@pytest.mark.asyncio
async def test_authoring_chat_missing_secret_returns_structured_error(db_session):
    missing_ref = f"missing-secret-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(missing_ref), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SKILL_AUTHORING_SECRET_NOT_FOUND",
        "message": "Secret not found.",
        "data": {"secret_ref": missing_ref},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_authoring_chat_missing_openai_key_returns_structured_error(db_session):
    secret = JoySafeterSecret(
        name=f"authoring-missing-key-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_MODEL": "gpt-5.5"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SKILL_AUTHORING_SECRET_MISSING_KEY",
        "message": "Secret missing OPENAI_API_KEY.",
        "data": {"secret_ref": secret.name, "required_key": "OPENAI_API_KEY"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_authoring_chat_invalid_openai_base_url_returns_structured_error(db_session):
    secret = JoySafeterSecret(
        name=f"authoring-invalid-url-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "http://169.254.169.254/latest"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SKILL_AUTHORING_BASE_URL_INVALID",
        "message": "Invalid OPENAI_BASE_URL.",
        "data": {
            "secret_ref": secret.name,
            "key": "OPENAI_BASE_URL",
            "base_url": "http://169.254.169.254/latest",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_authoring_chat_rejects_unallowlisted_openai_base_url(db_session, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    secret = JoySafeterSecret(
        name=f"authoring-unallowlisted-url-{uuid.uuid4()}",
        provider="codex",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://evil.example.com/v1"},
    )
    db_session.add(secret)
    await db_session.commit()
    await db_session.refresh(secret)

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(secret.name), db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SKILL_AUTHORING_BASE_URL_NOT_ALLOWED",
        "message": "OPENAI_BASE_URL host is not allowlisted.",
        "data": {
            "secret_ref": secret.name,
            "key": "OPENAI_BASE_URL",
            "base_url": "https://evil.example.com/v1",
            "host": "evil.example.com",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
