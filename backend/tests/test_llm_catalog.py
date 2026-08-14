from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import app.joysafeter_domain.llm.compatibility as compatibility
from app.joysafeter_domain.llm.catalog import LlmCatalogError, get_llm_catalog, load_llm_catalog
from app.joysafeter_domain.llm.compatibility import (
    LlmCompatibilityError,
    compatible_engine_ids,
    compatible_protocol_ids,
    compatible_provider_protocol_pairs,
    validate_credential_data,
    validate_engine_protocol,
    validate_provider_protocol,
)

pytestmark = pytest.mark.no_db


def _valid_catalog_data() -> dict:
    return {
        "version": "test.1",
        "protocols": [
            {
                "id": "anthropic_messages",
                "display_name": "Anthropic Messages API",
                "description": "Anthropic Messages contract",
            },
            {
                "id": "openai_responses",
                "display_name": "OpenAI Responses API",
                "description": "OpenAI Responses contract",
            },
        ],
        "engines": [
            {
                "id": "claude",
                "display_name": "Claude Code",
                "supported_protocol_ids": ["anthropic_messages"],
                "preferred_protocol_ids": ["anthropic_messages"],
            }
        ],
        "credential_profiles": [
            {
                "id": "anthropic_standard",
                "fields": [
                    {
                        "key": "ANTHROPIC_API_KEY",
                        "label": "API Key",
                        "type": "secret",
                    },
                    {
                        "key": "ANTHROPIC_AUTH_TOKEN",
                        "label": "Auth Token",
                        "type": "secret",
                    },
                    {
                        "key": "ANTHROPIC_BASE_URL",
                        "label": "Base URL",
                        "type": "url",
                        "advanced": True,
                    },
                    {
                        "key": "ANTHROPIC_MODEL",
                        "label": "Model",
                        "type": "text",
                    },
                ],
                "required_any_of": [["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]],
                "base_url_key": "ANTHROPIC_BASE_URL",
                "model_key": "ANTHROPIC_MODEL",
            }
        ],
        "providers": [
            {
                "id": "anthropic",
                "display_name": "Anthropic",
                "protocol_bindings": [
                    {
                        "protocol_id": "anthropic_messages",
                        "credential_profile_id": "anthropic_standard",
                        "default_base_url": "https://api.anthropic.com",
                        "model_suggestions": ["claude-sonnet-4-5"],
                    }
                ],
            }
        ],
    }


def _write_catalog(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "llm_catalog.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_catalog_loads_initial_engine_and_provider_matrix() -> None:
    catalog = get_llm_catalog()

    assert catalog.engine("claude").supported_protocol_ids == ["anthropic_messages"]
    assert catalog.engine("codex").supported_protocol_ids == ["openai_responses"]
    assert catalog.engine("native").supported_protocol_ids == [
        "anthropic_messages",
        "openai_responses",
        "chat_completions",
    ]
    assert catalog.engine("pi").supported_protocol_ids == [
        "anthropic_messages",
        "openai_responses",
        "chat_completions",
    ]

    assert [binding.protocol_id for binding in catalog.provider("anthropic").protocol_bindings] == [
        "anthropic_messages"
    ]
    assert [binding.protocol_id for binding in catalog.provider("openai").protocol_bindings] == [
        "openai_responses",
        "chat_completions",
    ]
    assert [binding.protocol_id for binding in catalog.provider("deepseek").protocol_bindings] == [
        "chat_completions"
    ]
    assert [binding.protocol_id for binding in catalog.provider("custom").protocol_bindings] == [
        "anthropic_messages",
        "openai_responses",
        "chat_completions",
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["protocols"].append(deepcopy(data["protocols"][0])),
            "duplicate protocol id",
        ),
        (
            lambda data: data["engines"][0]["supported_protocol_ids"].append("missing_protocol"),
            "unknown protocol",
        ),
        (
            lambda data: data["providers"][0]["protocol_bindings"][0].update(
                {"credential_profile_id": "missing_profile"}
            ),
            "unknown credential profile",
        ),
        (
            lambda data: data["providers"][0]["protocol_bindings"].append(
                deepcopy(data["providers"][0]["protocol_bindings"][0])
            ),
            "duplicate protocol binding",
        ),
        (
            lambda data: data["engines"][0]["preferred_protocol_ids"].append("openai_responses"),
            "preferred protocol",
        ),
        (
            lambda data: data["providers"][0].update({"id": data["engines"][0]["id"]}),
            "engine and provider ids overlap",
        ),
    ],
)
def test_catalog_rejects_broken_cross_references(tmp_path: Path, mutate, message: str) -> None:
    data = _valid_catalog_data()
    mutate(data)

    with pytest.raises(LlmCatalogError, match=message):
        load_llm_catalog(_write_catalog(tmp_path, data))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url_key", "MISSING_BASE_URL"),
        ("model_key", "MISSING_MODEL"),
        ("required_any_of", [["MISSING_KEY"]]),
    ],
)
def test_catalog_rejects_profile_references_to_unknown_fields(tmp_path: Path, field: str, value: object) -> None:
    data = _valid_catalog_data()
    data["credential_profiles"][0][field] = value

    with pytest.raises(LlmCatalogError, match="unknown field"):
        load_llm_catalog(_write_catalog(tmp_path, data))


def test_catalog_lookup_rejects_unknown_ids(tmp_path: Path) -> None:
    catalog = load_llm_catalog(_write_catalog(tmp_path, _valid_catalog_data()))

    with pytest.raises(LlmCatalogError, match="unknown engine"):
        catalog.engine("missing")
    with pytest.raises(LlmCatalogError, match="unknown protocol"):
        catalog.protocol("missing")
    with pytest.raises(LlmCatalogError, match="unknown provider"):
        catalog.provider("missing")
    with pytest.raises(LlmCatalogError, match="unknown credential profile"):
        catalog.credential_profile("missing")


def test_compatibility_helpers_preserve_catalog_order() -> None:
    assert compatible_protocol_ids("codex") == ["openai_responses"]
    assert compatible_protocol_ids("native", "openai") == [
        "openai_responses",
        "chat_completions",
    ]
    assert compatible_provider_protocol_pairs("claude") == [
        ("anthropic", "anthropic_messages"),
        ("custom", "anthropic_messages"),
    ]
    assert compatible_engine_ids("deepseek", "chat_completions") == ["native", "pi"]


def test_disabled_engine_and_provider_are_not_usable(tmp_path: Path, monkeypatch) -> None:
    data = _valid_catalog_data()
    data["engines"][0]["enabled"] = False
    data["providers"][0]["enabled"] = False
    catalog = load_llm_catalog(_write_catalog(tmp_path, data))
    monkeypatch.setattr(compatibility, "get_llm_catalog", lambda: catalog)

    with pytest.raises(LlmCompatibilityError) as engine_error:
        compatibility.validate_engine_protocol("claude", "anthropic_messages")
    assert engine_error.value.code == "LLM_ENGINE_DISABLED"

    with pytest.raises(LlmCompatibilityError) as provider_error:
        compatibility.validate_provider_protocol("anthropic", "anthropic_messages")
    assert provider_error.value.code == "LLM_PROVIDER_DISABLED"

    with pytest.raises(LlmCompatibilityError) as compatibility_error:
        compatibility.compatible_provider_protocol_pairs("claude")
    assert compatibility_error.value.code == "LLM_ENGINE_DISABLED"


def test_compatibility_validation_returns_binding_and_structured_errors() -> None:
    binding = validate_provider_protocol("openai", "openai_responses")
    assert binding.credential_profile_id == "openai_bearer"

    with pytest.raises(LlmCompatibilityError) as provider_error:
        validate_provider_protocol("deepseek", "openai_responses")
    assert provider_error.value.code == "LLM_PROVIDER_PROTOCOL_UNSUPPORTED"
    assert provider_error.value.data == {"provider": "deepseek", "protocol": "openai_responses"}

    with pytest.raises(LlmCompatibilityError) as engine_error:
        validate_engine_protocol("codex", "chat_completions")
    assert engine_error.value.code == "LLM_PROTOCOL_NOT_SUPPORTED_BY_ENGINE"
    assert engine_error.value.data == {"engine_kind": "codex", "protocol": "chat_completions"}


def test_credential_validation_uses_selected_profile_without_identity_detection() -> None:
    with pytest.raises(LlmCompatibilityError) as anthropic_error:
        validate_credential_data("anthropic", "anthropic_messages", {})
    assert anthropic_error.value.code == "LLM_SECRET_CREDENTIALS_INCOMPLETE"
    assert anthropic_error.value.data == {
        "provider": "anthropic",
        "protocol": "anthropic_messages",
        "required_any_of": [["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]],
    }

    validate_credential_data(
        "anthropic",
        "anthropic_messages",
        {"ANTHROPIC_AUTH_TOKEN": "token"},
    )

    with pytest.raises(LlmCompatibilityError) as openai_error:
        validate_credential_data(
            "openai",
            "openai_responses",
            {"ANTHROPIC_API_KEY": "not-an-openai-key"},
        )
    assert openai_error.value.code == "LLM_SECRET_CREDENTIALS_INCOMPLETE"
    assert openai_error.value.data == {
        "provider": "openai",
        "protocol": "openai_responses",
        "required_fields": ["OPENAI_API_KEY"],
    }
