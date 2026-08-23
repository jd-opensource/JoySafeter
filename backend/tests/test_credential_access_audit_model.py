from __future__ import annotations

import pytest

from app.joysafeter_domain.models.joysafeter_credential_access_audit import (
    JoySafeterCredentialAccessAudit,
)


@pytest.mark.no_db
def test_credential_access_audit_schema_contains_only_non_secret_evidence() -> None:
    columns = set(JoySafeterCredentialAccessAudit.__table__.columns.keys())

    assert {
        "id",
        "project_id",
        "credential_id",
        "credential_kind",
        "usage",
        "consumer_type",
        "consumer_id",
        "principal_type",
        "principal_id",
        "user_id",
        "org_id",
        "role",
        "ip_address",
        "user_agent",
        "session_id",
        "task_id",
        "generation",
        "field_names",
        "result",
        "error_code",
        "created_at",
    } <= columns
    assert {"value", "data", "payload", "ciphertext", "secret", "updated_at"}.isdisjoint(columns)


@pytest.mark.no_db
def test_credential_access_audit_preserves_credential_identity_without_foreign_key() -> None:
    table = JoySafeterCredentialAccessAudit.__table__

    assert table.c.credential_id.nullable is False
    assert table.c.credential_id.foreign_keys == set()
    assert "credential_public_id" not in table.c


@pytest.mark.no_db
def test_runtime_success_dedupe_index_treats_null_consumer_as_equal() -> None:
    index = next(
        index
        for index in JoySafeterCredentialAccessAudit.__table__.indexes
        if index.name == "uq_credential_access_audits_runtime_success"
    )

    assert index.unique is True
    assert index.dialect_options["postgresql"]["nulls_not_distinct"] is True
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert "result = 'success'" in predicate
    assert "session_id IS NOT NULL" in predicate
    assert "generation IS NOT NULL" in predicate


@pytest.mark.no_db
def test_access_audit_has_principal_lookup_index() -> None:
    indexes = {index.name: index for index in JoySafeterCredentialAccessAudit.__table__.indexes}

    index = indexes["ix_credential_access_audits_principal_created"]
    assert [column.name for column in index.columns] == ["principal_type", "principal_id", "created_at"]
