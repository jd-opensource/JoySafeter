"""Error-contract tests for the Task 7 Skill AI Authoring model consumer.

The request references a model credential by ``model_credential_id`` and the
endpoint resolves it through canonical ModelInferenceBinding policy/material
ports rather than the CredentialService compatibility facade.

The full app is un-loadable mid-cutover, so the route functions are called
directly against conftest's real ``db_session``.
"""

import uuid

import pytest
import pytest_asyncio
from error_contract_helpers import handled_app_error_payload
from sqlalchemy.exc import IntegrityError

from app.joysafeter_api.api.v1.skills_ai_authoring import (
    AuthoringChatRequest,
    AuthoringMessage,
    SaveDraftRequest,
    authoring_chat,
    authoring_save_draft,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.common.app_errors import AppError, ResourceConflictError
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


def _auth_ctx(project_id: str | None = "proj-a") -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


def _chat_req(cred_id: CredentialId) -> AuthoringChatRequest:
    return AuthoringChatRequest(
        model_credential_id=cred_id,
        messages=[AuthoringMessage(role="user", content="Draft a skill")],
    )


async def _make_model_credential(
    db_session,
    project_id: str,
    data: dict[str, str],
    *,
    provider: str = "openai",
    protocol: str = "openai_responses",
) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider=provider,
            protocol=protocol,
            data=data,
        ),
        project_id=project_id,
    )
    return cred.id


def test_authoring_schema_uses_model_credential_id_not_secret_ref():
    fields = AuthoringChatRequest.model_fields
    assert "model_credential_id" in fields
    assert "secret_ref" not in fields


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
async def test_authoring_chat_missing_credential_returns_structured_error(db_session, project_id):
    missing_id = CredentialId.new()

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(missing_id), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "CREDENTIAL_NOT_FOUND",
        "message": "Credential not found",
        "data": {"credential_id": str(missing_id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.parametrize("data", [{}, {"UNRELATED_SECRET": "must-not-leak"}])
@pytest.mark.asyncio
async def test_authoring_chat_missing_openai_key_returns_structured_error(
    db_session,
    project_id,
    data,
):
    cred_id = await _make_model_credential(db_session, project_id, data)

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(cred_id), db_session, _auth_ctx(project_id))

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload == {
        "code": "SKILL_AUTHORING_SECRET_MISSING_KEY",
        "message": "Credential missing OPENAI_API_KEY.",
        "data": {"credential_id": str(cred_id), "required_key": "OPENAI_API_KEY"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert "must-not-leak" not in str(payload)


@pytest.mark.asyncio
async def test_authoring_chat_rejects_wrong_protocol_credential(db_session, project_id):
    # A model credential on a non-Responses protocol is incompatible with authoring.
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value"},
        protocol="chat_completions",
    )

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(cred_id), db_session, _auth_ctx(project_id))

    assert exc_info.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_authoring_chat_invalid_openai_base_url_returns_structured_error(db_session, project_id):
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "http://169.254.169.254/latest"},
    )

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(cred_id), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SKILL_AUTHORING_BASE_URL_INVALID",
        "message": "Invalid OPENAI_BASE_URL.",
        "data": {
            "credential_id": str(cred_id),
            "key": "OPENAI_BASE_URL",
            "base_url": "http://169.254.169.254/latest",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_authoring_chat_rejects_unallowlisted_openai_base_url(db_session, project_id, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://evil.example.com/v1"},
    )

    with pytest.raises(AppError) as exc_info:
        await authoring_chat(_chat_req(cred_id), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SKILL_AUTHORING_BASE_URL_NOT_ALLOWED",
        "message": "OPENAI_BASE_URL host is not allowlisted.",
        "data": {
            "credential_id": str(cred_id),
            "key": "OPENAI_BASE_URL",
            "base_url": "https://evil.example.com/v1",
            "host": "evil.example.com",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
