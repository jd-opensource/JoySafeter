from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.joysafeter_domain.models.joysafeter_secret import JoySafeterSecret
from app.joysafeter_domain.schemas.joysafeter_secret import (
    CreateSecretRequest,
    SecretKind,
    SecretListItem,
    TestSecretRequest as SecretConnectivityRequest,
    UpdateSecretRequest,
)
from app.joysafeter_shared.ids import SecretId

pytestmark = pytest.mark.no_db


def test_secret_create_requires_explicit_kind_and_llm_identity() -> None:
    with pytest.raises(ValidationError):
        CreateSecretRequest(name="missing-kind", data={})

    with pytest.raises(ValidationError, match="provider and protocol"):
        CreateSecretRequest(kind="llm", name="missing-provider", data={})

    request = CreateSecretRequest(
        kind="llm",
        name="openai-production",
        provider="openai",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": "  secret  "},
        is_default=True,
    )
    assert request.kind is SecretKind.LLM
    assert request.data == {"OPENAI_API_KEY": "secret"}


def test_generic_secret_rejects_llm_identity_and_default() -> None:
    request = CreateSecretRequest(kind="generic", name="github", data={"GITHUB_TOKEN": " token "})
    assert request.kind is SecretKind.GENERIC
    assert request.provider is None
    assert request.protocol is None
    assert request.is_default is False
    assert request.data == {"GITHUB_TOKEN": "token"}

    with pytest.raises(ValidationError, match="must not define provider or protocol"):
        CreateSecretRequest(
            kind="generic",
            name="invalid-provider",
            provider="openai",
            protocol="openai_responses",
            data={},
        )
    with pytest.raises(ValidationError, match="cannot be a default"):
        CreateSecretRequest(kind="generic", name="invalid-default", data={}, is_default=True)


def test_secret_identity_is_not_accepted_by_update_request() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UpdateSecretRequest(provider="openai", data={"OPENAI_API_KEY": "secret"})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UpdateSecretRequest(kind="llm", data={"OPENAI_API_KEY": "secret"})


def test_connectivity_request_requires_explicit_llm_identity() -> None:
    with pytest.raises(ValidationError):
        SecretConnectivityRequest(provider="openai", protocol="openai_responses", data={})
    with pytest.raises(ValidationError):
        SecretConnectivityRequest(kind="generic", provider="openai", protocol="openai_responses", data={})

    request = SecretConnectivityRequest(
        kind="llm",
        provider="openai",
        protocol="openai_responses",
        data={"OPENAI_API_KEY": " secret "},
    )
    assert request.kind is SecretKind.LLM
    assert request.data == {"OPENAI_API_KEY": "secret"}


def test_secret_response_identity_is_explicit_and_nullable_for_generic() -> None:
    item = SecretListItem(
        id=SecretId.new(),
        name="github",
        kind="generic",
        provider=None,
        protocol=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert item.kind is SecretKind.GENERIC
    assert item.provider is None
    assert item.protocol is None


def test_secret_model_contains_identity_constraint_and_protocol_default_indexes() -> None:
    table = JoySafeterSecret.__table__
    assert table.c.kind.nullable is False
    assert table.c.kind.server_default is None
    assert table.c.provider.nullable is True
    assert table.c.provider.server_default is None
    assert table.c.protocol.nullable is True
    assert table.c.protocol.server_default is None

    check_constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_joysafeter_secrets_kind_identity" in check_constraints
    assert "kind = 'llm'" in check_constraints["ck_joysafeter_secrets_kind_identity"]
    assert "kind = 'generic'" in check_constraints["ck_joysafeter_secrets_kind_identity"]

    index_names = {index.name for index in table.indexes}
    assert "uq_joysafeter_secrets_project_protocol_default" in index_names
    assert "uq_joysafeter_secrets_global_protocol_default" in index_names


def test_initial_schema_remains_the_only_alembic_head() -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260803_000001"]
