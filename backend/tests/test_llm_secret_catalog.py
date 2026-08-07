from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.joysafeter_domain.services.joysafeter_secret_service as secret_service_module
from app.joysafeter_api.api.v1.secrets import list_secrets
from app.joysafeter_domain.llm.compatibility import LlmCompatibilityError
from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.schemas.joysafeter_secret import CreateSecretRequest, SecretKind, UpdateSecretRequest
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


@pytest.mark.asyncio
async def test_create_secret_persists_explicit_llm_and_generic_identity(db_session) -> None:
    service = SecretService(db_session)

    llm_secret = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("openai"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5"},
        )
    )
    generic_secret = await service.create_secret(
        CreateSecretRequest(kind="generic", name=_name("github"), data={"GITHUB_TOKEN": "token"})
    )

    assert (llm_secret.kind, llm_secret.provider, llm_secret.protocol) == (
        "llm",
        "openai",
        "openai_responses",
    )
    assert service.get_secret_data(llm_secret)["OPENAI_API_KEY"] == "secret"
    assert llm_secret.data["OPENAI_API_KEY"] != "secret"
    assert (generic_secret.kind, generic_secret.provider, generic_secret.protocol) == (
        "generic",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_secret_list_keeps_catalog_orphan_visible_as_incompatible(db_session) -> None:
    orphan = JoySafeterSecret(
        name=_name("catalog-orphan"),
        kind="llm",
        provider="removed-provider",
        protocol="removed-protocol",
        data={},
    )
    db_session.add(orphan)
    await db_session.commit()

    response = await list_secrets(
        limit=10,
        after_id=None,
        kind=SecretKind.LLM,
        name=orphan.name,
        provider=None,
        protocol=None,
        compatible_engine=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    assert response["data"][0]["name"] == orphan.name
    assert response["data"][0]["compatible_engine_ids"] == []
    assert response["data"][0]["model"] is None


@pytest.mark.asyncio
async def test_merging_secret_refs_does_not_create_provider_alias_keys(db_session) -> None:
    service = SecretService(db_session)
    secret = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("anthropic-token"),
            provider="anthropic",
            protocol="anthropic_messages",
            data={"ANTHROPIC_AUTH_TOKEN": "secret"},
        )
    )

    merged = await service.merge_secret_refs_into_env({}, [secret.name])

    assert merged == {"ANTHROPIC_AUTH_TOKEN": "secret"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["claude", "codex", "native", "pi"])
async def test_create_secret_rejects_engine_names_as_provider(db_session, provider: str) -> None:
    service = SecretService(db_session)

    with pytest.raises(LlmCompatibilityError) as exc_info:
        await service.create_secret(
            CreateSecretRequest(
                kind="llm",
                name=_name(provider),
                provider=provider,
                protocol="openai_responses",
                data={"OPENAI_API_KEY": "secret"},
            )
        )

    assert exc_info.value.code == "LLM_SECRET_PROVIDER_RESERVED"
    assert exc_info.value.data == {"provider": provider}


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_create_secret_uses_catalog_engine_ids_as_reserved_provider_names(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        secret_service_module,
        "get_llm_catalog",
        lambda: SimpleNamespace(engines=[SimpleNamespace(id="future-engine")]),
    )
    service = object.__new__(SecretService)
    service.db = SimpleNamespace()

    with pytest.raises(LlmCompatibilityError) as exc_info:
        await service.create_secret(
            CreateSecretRequest(
                kind="llm",
                name=_name("future-engine"),
                provider="future-engine",
                protocol="openai_responses",
                data={"OPENAI_API_KEY": "secret"},
            )
        )

    assert exc_info.value.code == "LLM_SECRET_PROVIDER_RESERVED"


@pytest.mark.asyncio
async def test_create_secret_rejects_invalid_provider_protocol_binding(db_session) -> None:
    service = SecretService(db_session)

    with pytest.raises(LlmCompatibilityError) as exc_info:
        await service.create_secret(
            CreateSecretRequest(
                kind="llm",
                name=_name("deepseek-responses"),
                provider="deepseek",
                protocol="openai_responses",
                data={"OPENAI_API_KEY": "secret"},
            )
        )

    assert exc_info.value.code == "LLM_PROVIDER_PROTOCOL_UNSUPPORTED"


@pytest.mark.asyncio
async def test_compatible_engine_filter_is_applied_before_pagination(db_session) -> None:
    service = SecretService(db_session)
    await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("codex-compatible"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        )
    )
    await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("claude-default"),
            provider="anthropic",
            protocol="anthropic_messages",
            data={"ANTHROPIC_API_KEY": "secret"},
            is_default=True,
        )
    )

    secrets, has_more = await service.list_secrets(limit=1, compatible_engine="codex")

    assert len(secrets) == 1
    assert secrets[0].protocol == "openai_responses"
    assert has_more is False


@pytest.mark.asyncio
async def test_secret_name_filter_returns_only_the_exact_project_secret(db_session) -> None:
    service = SecretService(db_session)
    target = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("target"),
            provider="anthropic",
            protocol="anthropic_messages",
            data={"ANTHROPIC_API_KEY": "secret"},
        )
    )
    await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("other"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        )
    )

    secrets, has_more = await service.list_secrets(limit=1, name=target.name)

    assert [secret.id for secret in secrets] == [target.id]
    assert has_more is False


@pytest.mark.asyncio
async def test_secret_list_api_exposes_catalog_identity_and_compatible_engines(db_session) -> None:
    service = SecretService(db_session)
    secret = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("openai-list"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5"},
            is_default=True,
        )
    )

    page = await list_secrets(
        limit=10,
        after_id=None,
        kind=SecretKind.LLM,
        provider=None,
        protocol=None,
        compatible_engine="codex",
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    assert page["data"] == [
        {
            "id": str(secret.id),
            "name": secret.name,
            "kind": "llm",
            "provider": "openai",
            "protocol": "openai_responses",
            "model": "gpt-5",
            "compatible_engine_ids": ["codex", "native", "pi"],
            "is_default": True,
            "keys": ["OPENAI_API_KEY", "OPENAI_MODEL"],
            "created_at": secret.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": secret.updated_at.isoformat().replace("+00:00", "Z"),
        }
    ]


@pytest.mark.asyncio
async def test_defaults_are_cleared_only_within_the_same_protocol(db_session) -> None:
    service = SecretService(db_session)
    anthropic = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("anthropic-default"),
            provider="anthropic",
            protocol="anthropic_messages",
            data={"ANTHROPIC_API_KEY": "secret"},
            is_default=True,
        )
    )
    first_openai = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("openai-default-1"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
            is_default=True,
        )
    )
    second_openai = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("openai-default-2"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
            is_default=True,
        )
    )

    await db_session.refresh(anthropic)
    await db_session.refresh(first_openai)
    assert anthropic.is_default is True
    assert first_openai.is_default is False
    assert second_openai.is_default is True
    assert await service.get_default_secret(project_id=None, protocol="anthropic_messages") == anthropic
    assert await service.get_default_secret(project_id=None, protocol="openai_responses") == second_openai


@pytest.mark.asyncio
async def test_llm_update_validates_the_final_merged_plaintext(db_session) -> None:
    service = SecretService(db_session)
    secret = await service.create_secret(
        CreateSecretRequest(
            kind="llm",
            name=_name("openai-update"),
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5"},
        )
    )

    with pytest.raises(LlmCompatibilityError) as exc_info:
        await service.update_secret(secret.id, UpdateSecretRequest(data={"OPENAI_MODEL": "gpt-5"}))
    assert exc_info.value.code == "LLM_SECRET_CREDENTIALS_INCOMPLETE"

    masked = service.get_masked_secret_data(secret)
    updated = await service.update_secret(
        secret.id,
        UpdateSecretRequest(data={"OPENAI_API_KEY": masked["OPENAI_API_KEY"], "OPENAI_MODEL": "gpt-5-mini"}),
    )
    assert updated is not None
    assert service.get_secret_data(updated) == {
        "OPENAI_API_KEY": "secret",
        "OPENAI_MODEL": "gpt-5-mini",
    }
