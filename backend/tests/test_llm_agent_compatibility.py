from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from credential_test_helpers import encrypted_secret_data
from error_contract_helpers import handled_app_error_payload

from app.joysafeter_api.api.v1.agents import _model_from_secret_data, create_agent, update_agent
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("engine_kind", "provider", "protocol", "data", "expected_model"),
    [
        (
            "claude",
            "anthropic",
            "anthropic_messages",
            {"ANTHROPIC_API_KEY": "key", "ANTHROPIC_MODEL": "claude-model"},
            "claude-model",
        ),
        (
            "codex",
            "openai",
            "openai_responses",
            {"OPENAI_API_KEY": "key", "OPENAI_MODEL": "responses-model"},
            "responses-model",
        ),
        (
            "native",
            "deepseek",
            "chat_completions",
            {"OPENAI_API_KEY": "key", "OPENAI_MODEL": "deepseek-chat"},
            "deepseek-chat",
        ),
        (
            "pi",
            "openai",
            "chat_completions",
            {"OPENAI_API_KEY": "key", "OPENAI_MODEL": "chat-model"},
            "chat-model",
        ),
    ],
)
async def test_agent_accepts_catalog_compatible_secret_and_resolves_profile_model(
    db_session,
    engine_kind: str,
    provider: str,
    protocol: str,
    data: dict[str, str],
    expected_model: str,
) -> None:
    secret = JoySafeterSecret(
        name=f"compatible-{uuid.uuid4()}",
        kind="llm",
        provider=provider,
        protocol=protocol,
        data=encrypted_secret_data(data),
    )
    db_session.add(secret)
    await db_session.commit()

    response = await create_agent(
        JoySafeterCreateAgentRequest(
            name=f"agent-{uuid.uuid4()}",
            engine_kind=engine_kind,
            secret_ref=secret.name,
        ),
        db_session,
        _auth_ctx(),
    )

    assert response.engine_kind == engine_kind
    assert response.model is not None
    assert response.model.id == expected_model


@pytest.mark.asyncio
async def test_codex_rejects_chat_completions_even_from_openai(db_session) -> None:
    secret = JoySafeterSecret(
        name=f"codex-chat-{uuid.uuid4()}",
        kind="llm",
        provider="openai",
        protocol="chat_completions",
        data=encrypted_secret_data({"OPENAI_API_KEY": "key"}),
    )
    db_session.add(secret)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_agent(
            JoySafeterCreateAgentRequest(
                name=f"agent-{uuid.uuid4()}",
                engine_kind="codex",
                secret_ref=secret.name,
            ),
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "AGENT_SECRET_INCOMPATIBLE"
    assert payload["data"] == {
        "secret_ref": secret.name,
        "engine_kind": "codex",
        "kind": "llm",
        "provider": "openai",
        "protocol": "chat_completions",
    }


@pytest.mark.asyncio
async def test_agent_rejects_generic_secret(db_session) -> None:
    secret = JoySafeterSecret(
        name=f"generic-{uuid.uuid4()}",
        kind="generic",
        provider=None,
        protocol=None,
        data=encrypted_secret_data({"TOKEN": "value"}),
    )
    db_session.add(secret)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_agent(
            JoySafeterCreateAgentRequest(
                name=f"agent-{uuid.uuid4()}",
                engine_kind="claude",
                secret_ref=secret.name,
            ),
            db_session,
            _auth_ctx(),
        )

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload["code"] == "AGENT_SECRET_INCOMPATIBLE"
    assert payload["data"] == {
        "secret_ref": secret.name,
        "engine_kind": "claude",
        "kind": "generic",
        "provider": None,
        "protocol": None,
    }


@pytest.mark.asyncio
async def test_agent_clear_normalizes_secret_ref_to_null(db_session) -> None:
    secret = JoySafeterSecret(
        name=f"clearable-{uuid.uuid4()}",
        kind="llm",
        provider="anthropic",
        protocol="anthropic_messages",
        data=encrypted_secret_data({"ANTHROPIC_API_KEY": "key"}),
    )
    db_session.add(secret)
    await db_session.commit()

    created = await create_agent(
        JoySafeterCreateAgentRequest(
            name=f"agent-{uuid.uuid4()}",
            engine_kind="claude",
            secret_ref=secret.name,
        ),
        db_session,
        _auth_ctx(),
    )

    updated = await update_agent(
        JoySafeterUpdateAgentRequest(version=created.version, secret_ref=None),
        created.id,
        db_session,
        _auth_ctx(),
    )

    assert updated.secret_ref is None


@pytest.mark.no_db
def test_model_from_secret_data_tolerates_incompatible_provider():
    """A secret whose provider is no longer valid (e.g. legacy data where the
    provider equals an engine id like 'pi') must NOT raise — listing agents
    would otherwise 400 on a single misconfigured agent. It degrades to None.
    """
    bad_secret = SimpleNamespace(
        name="pi",
        kind="llm",
        provider="pi",  # 'pi' is an engine id, never a valid LLM provider
        protocol="chat_completions",
    )

    result = _model_from_secret_data(bad_secret, {"OPENAI_MODEL": "whatever"})

    assert result is None


@pytest.mark.no_db
def test_model_from_secret_data_resolves_valid_provider():
    good_secret = SimpleNamespace(
        name="ds",
        kind="llm",
        provider="deepseek",
        protocol="chat_completions",
    )

    result = _model_from_secret_data(good_secret, {"OPENAI_MODEL": "deepseek-chat"})

    assert result == {"id": "deepseek-chat"}
