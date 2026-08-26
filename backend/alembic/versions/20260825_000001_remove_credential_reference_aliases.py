"""Remove legacy credential-reference aliases from persisted JSONB documents.

Revision ID: 20260825_000001
Revises: 20260824_000002
Create Date: 2026-08-25 00:00:01.000000
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from typing import Any, Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_000001"
down_revision: Union[str, None] = "20260824_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

_SNAPSHOT_SCHEMA_V1 = "joysafeter.agent_execution_snapshot.v1"
_SNAPSHOT_SCHEMA_V2 = "joysafeter.agent_execution_snapshot.v2"
_CREDENTIAL_ID = re.compile(r"^cred_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CREDENTIAL_GROUP_ID = re.compile(r"^credgrp_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _fail(location: str, message: str) -> RuntimeError:
    return RuntimeError(f"{location}: {message}")


def _object(value: object, *, location: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(location, "expected JSON object")
    return copy.deepcopy(dict(value))


def _canonical_id(value: object, *, pattern: re.Pattern[str], location: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _fail(location, "invalid canonical ID")
    return value


def _id_list(
    value: object,
    *,
    pattern: re.Pattern[str],
    location: str,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _fail(location, "expected ID list or null")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        canonical = _canonical_id(item, pattern=pattern, location=f"{location}[{index}]")
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _merge_list_alias(
    document: dict[str, Any],
    *,
    canonical_key: str,
    legacy_key: str,
    pattern: re.Pattern[str],
    location: str,
) -> list[str] | None:
    canonical_present = canonical_key in document
    legacy_present = legacy_key in document
    canonical = (
        _id_list(document[canonical_key], pattern=pattern, location=f"{location}.{canonical_key}")
        if canonical_present
        else None
    )
    legacy = (
        _id_list(document[legacy_key], pattern=pattern, location=f"{location}.{legacy_key}") if legacy_present else None
    )
    if canonical is not None and legacy is not None and canonical != legacy:
        raise _fail(location, f"conflicting {canonical_key}/{legacy_key} values")
    document.pop(legacy_key, None)
    return canonical if canonical is not None else legacy


def _merge_scalar_alias(
    document: dict[str, Any],
    *,
    canonical_key: str,
    legacy_key: str,
    pattern: re.Pattern[str],
    location: str,
) -> str | None:
    values: list[str] = []
    for key in (canonical_key, legacy_key):
        if key not in document or document[key] is None:
            continue
        values.append(_canonical_id(document[key], pattern=pattern, location=f"{location}.{key}"))
    if len(set(values)) > 1:
        raise _fail(location, f"conflicting {canonical_key}/{legacy_key} values")
    document.pop(legacy_key, None)
    return values[0] if values else None


def _merge_text_alias(
    document: dict[str, Any],
    *,
    canonical_key: str,
    legacy_key: str,
    location: str,
) -> str | None:
    values: list[str] = []
    for key in (canonical_key, legacy_key):
        if key not in document or document[key] is None:
            continue
        value = document[key]
        if not isinstance(value, str) or not value.strip():
            raise _fail(f"{location}.{key}", "expected non-empty string")
        values.append(value.strip())
    if len(set(values)) > 1:
        raise _fail(location, f"conflicting {canonical_key}/{legacy_key} values")
    document.pop(legacy_key, None)
    return values[0] if values else None


def canonicalize_environment_config(value: object, *, location: str) -> dict[str, Any]:
    document = _object(value, location=location)
    direct_ids = _merge_list_alias(
        document,
        canonical_key="environment_credential_ids",
        legacy_key="secret_refs",
        pattern=_CREDENTIAL_ID,
        location=location,
    )
    root_service_id = document.pop("service_credential_id", None)
    if root_service_id is not None:
        root_service_id = _canonical_id(
            root_service_id,
            pattern=_CREDENTIAL_ID,
            location=f"{location}.service_credential_id",
        )
        if direct_ids is None:
            direct_ids = []
        if root_service_id not in direct_ids:
            direct_ids.append(root_service_id)
    if direct_ids is not None:
        document["environment_credential_ids"] = direct_ids

    services = document.get("egress_services")
    if services is not None:
        if not isinstance(services, list):
            raise _fail(f"{location}.egress_services", "expected list or null")
        canonical_services: list[dict[str, Any]] = []
        for index, value_service in enumerate(services):
            service_location = f"{location}.egress_services[{index}]"
            service = _object(value_service, location=service_location)
            credential_ref = _merge_scalar_alias(
                service,
                canonical_key="credential_ref",
                legacy_key="service_credential_id",
                pattern=_CREDENTIAL_ID,
                location=service_location,
            )
            if credential_ref is not None:
                service["credential_ref"] = credential_ref
            if "inject" in service and service["inject"] is not None:
                inject_location = f"{service_location}.inject"
                inject = _object(service["inject"], location=inject_location)
                credential_field = _merge_text_alias(
                    inject,
                    canonical_key="credential_field",
                    legacy_key="secret_key",
                    location=inject_location,
                )
                if credential_field is not None:
                    inject["credential_field"] = credential_field
                service["inject"] = inject
            canonical_services.append(service)
        document["egress_services"] = canonical_services
    return document


def canonicalize_snapshot(value: object, *, location: str) -> dict[str, Any]:
    document = _object(value, location=location)
    schema = document.get("schema")
    if schema not in {None, _SNAPSHOT_SCHEMA_V1, _SNAPSHOT_SCHEMA_V2}:
        raise _fail(f"{location}.schema", "unsupported snapshot schema")

    model_credential_id = _merge_scalar_alias(
        document,
        canonical_key="model_credential_id",
        legacy_key="secret_ref",
        pattern=_CREDENTIAL_ID,
        location=location,
    )
    if model_credential_id is not None:
        document["model_credential_id"] = model_credential_id

    environment_ids = _merge_list_alias(
        document,
        canonical_key="environment_credential_ids",
        legacy_key="secret_refs",
        pattern=_CREDENTIAL_ID,
        location=location,
    )
    if environment_ids is not None:
        document["environment_credential_ids"] = environment_ids

    group_ids = _merge_list_alias(
        document,
        canonical_key="credential_group_ids",
        legacy_key="vault_ids",
        pattern=_CREDENTIAL_GROUP_ID,
        location=location,
    )
    if group_ids is not None:
        document["credential_group_ids"] = group_ids

    if "environment" in document and document["environment"] is not None:
        environment_location = f"{location}.environment"
        environment = _object(document["environment"], location=environment_location)
        if "config" in environment and environment["config"] is not None:
            environment["config"] = canonicalize_environment_config(
                environment["config"],
                location=f"{environment_location}.config",
            )
        document["environment"] = environment

    document["schema"] = _SNAPSHOT_SCHEMA_V2
    return document


def _locked_documents(
    connection: Any,
    table: str,
    column: str,
    *,
    skip_null: bool = False,
) -> list[tuple[object, object]]:
    predicate = f" WHERE {column} IS NOT NULL" if skip_null else ""
    rows = connection.execute(sa.text(f"SELECT id, {column} FROM {table}{predicate} ORDER BY id FOR UPDATE"))
    return [(row[0], row[1]) for row in rows]


def _update_documents(
    connection: Any,
    *,
    table: str,
    column: str,
    documents: list[tuple[object, dict[str, Any]]],
) -> None:
    statement = sa.text(f"UPDATE {table} SET {column} = CAST(:document AS jsonb) WHERE id = :id")
    for row_id, document in documents:
        connection.execute(statement, {"id": row_id, "document": json.dumps(document, separators=(",", ":"))})


def upgrade() -> None:
    connection = op.get_bind()
    environments = [
        (row_id, canonicalize_environment_config(document, location=f"joysafeter_environments[{row_id}].config"))
        for row_id, document in _locked_documents(connection, "joysafeter_environments", "config")
    ]
    sessions = [
        (row_id, canonicalize_snapshot(document, location=f"joysafeter_sessions[{row_id}].agent_snapshot"))
        for row_id, document in _locked_documents(
            connection,
            "joysafeter_sessions",
            "agent_snapshot",
            skip_null=True,
        )
    ]
    agent_versions = [
        (row_id, canonicalize_snapshot(document, location=f"joysafeter_agent_versions[{row_id}].snapshot"))
        for row_id, document in _locked_documents(connection, "joysafeter_agent_versions", "snapshot")
    ]

    _update_documents(
        connection,
        table="joysafeter_environments",
        column="config",
        documents=environments,
    )
    _update_documents(
        connection,
        table="joysafeter_sessions",
        column="agent_snapshot",
        documents=sessions,
    )
    _update_documents(
        connection,
        table="joysafeter_agent_versions",
        column="snapshot",
        documents=agent_versions,
    )


def downgrade() -> None:
    raise RuntimeError("credential-reference alias removal is irreversible")
