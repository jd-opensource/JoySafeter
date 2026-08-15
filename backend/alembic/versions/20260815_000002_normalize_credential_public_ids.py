"""Normalize persisted credential references to canonical public IDs.

Revision ID: 20260815_000002
Revises: 20260815_000001
Create Date: 2026-08-15 00:00:01.000000

This migration is online-only and irreversible. It validates every credential
reference before updating any JSONB row so PostgreSQL can roll the whole
revision back if one reference is malformed or no longer resolves safely.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any, NamedTuple, Optional, Union

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260815_000002"
down_revision: Union[str, None] = "20260815_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

_CREDENTIAL_PREFIX = "cred_"


class _CredentialRecord(NamedTuple):
    id: str
    project_id: str | None
    kind: str
    name: str
    archived: bool
    deleted: bool

    @property
    def public_id(self) -> str:
        return f"{_CREDENTIAL_PREFIX}{self.id}"


class _CredentialCatalog(NamedTuple):
    by_id: dict[str, _CredentialRecord]
    all_by_name: dict[tuple[str | None, str, str], tuple[_CredentialRecord, ...]]
    live_by_name: dict[tuple[str | None, str, str], tuple[_CredentialRecord, ...]]


def _text_id(value: object) -> str | None:
    return None if value is None else str(value)


def _load_catalog(connection: sa.engine.Connection) -> _CredentialCatalog:
    rows = connection.execute(
        sa.text(
            "SELECT id, project_id, kind, name, archived_at, deleted_at "
            "FROM joysafeter_credentials ORDER BY id FOR SHARE"
        )
    ).mappings()
    by_id: dict[str, _CredentialRecord] = {}
    all_names: dict[tuple[str | None, str, str], list[_CredentialRecord]] = {}
    live_names: dict[tuple[str | None, str, str], list[_CredentialRecord]] = {}
    for row in rows:
        record = _CredentialRecord(
            id=str(row["id"]),
            project_id=_text_id(row["project_id"]),
            kind=str(row["kind"]),
            name=str(row["name"]),
            archived=row["archived_at"] is not None,
            deleted=row["deleted_at"] is not None,
        )
        by_id[record.id] = record
        key = (record.project_id, record.kind, record.name)
        all_names.setdefault(key, []).append(record)
        if not record.archived and not record.deleted:
            live_names.setdefault(key, []).append(record)
    return _CredentialCatalog(
        by_id=by_id,
        all_by_name={key: tuple(value) for key, value in all_names.items()},
        live_by_name={key: tuple(value) for key, value in live_names.items()},
    )


def _reference_uuid(value: str) -> str | None:
    raw = value[len(_CREDENTIAL_PREFIX) :] if value.startswith(_CREDENTIAL_PREFIX) else value
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError):
        return None


def _validate_record(
    record: _CredentialRecord,
    *,
    project_id: str | None,
    expected_kind: str,
    location: str,
    require_live: bool,
) -> str:
    if project_id is None or record.project_id != project_id:
        raise RuntimeError(f"Credential reference at {location} is not in the same project")
    if record.kind != expected_kind:
        raise RuntimeError(f"Credential reference at {location} must point to kind={expected_kind}, got {record.kind}")
    if require_live:
        if record.deleted:
            raise RuntimeError(f"Credential reference at {location} points to a deleted credential")
        if record.archived:
            raise RuntimeError(f"Credential reference at {location} points to an archived credential")
    return record.public_id


def _normalize_reference(
    value: object,
    *,
    project_id: str | None,
    expected_kind: str,
    location: str,
    catalog: _CredentialCatalog,
    allow_legacy_name: bool = False,
    require_live: bool = True,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Credential reference at {location} must be a non-empty string")
    normalized = value.strip()
    reference_id = _reference_uuid(normalized)
    if reference_id is not None:
        record = catalog.by_id.get(reference_id)
        if record is None:
            raise RuntimeError(f"Credential reference at {location} does not exist: {normalized}")
        return _validate_record(
            record,
            project_id=project_id,
            expected_kind=expected_kind,
            location=location,
            require_live=require_live,
        )

    if normalized.startswith(_CREDENTIAL_PREFIX):
        raise RuntimeError(f"Credential reference at {location} has an invalid public ID: {normalized}")
    if not allow_legacy_name:
        raise RuntimeError(f"Credential reference at {location} is not a credential public ID: {normalized}")

    key = (project_id, expected_kind, normalized)
    matches = catalog.live_by_name.get(key, ()) if require_live else catalog.all_by_name.get(key, ())
    if require_live and not matches:
        historical_matches = catalog.all_by_name.get(key, ())
        if len(historical_matches) == 1:
            return _validate_record(
                historical_matches[0],
                project_id=project_id,
                expected_kind=expected_kind,
                location=location,
                require_live=True,
            )
    if len(matches) != 1:
        raise RuntimeError(
            f"Legacy credential name at {location} must resolve exactly once, got {len(matches)}: {normalized}"
        )
    return _validate_record(
        matches[0],
        project_id=project_id,
        expected_kind=expected_kind,
        location=location,
        require_live=require_live,
    )


def _normalize_environment_config(
    value: object,
    *,
    project_id: str | None,
    location: str,
    catalog: _CredentialCatalog,
    require_live_credentials: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Environment config at {location} must be a JSON object")
    normalized = copy.deepcopy(value)

    if "secret_refs" in normalized:
        refs = normalized["secret_refs"]
        if not isinstance(refs, list):
            raise RuntimeError(f"Credential references at {location}.secret_refs must be a JSON array")
        normalized["secret_refs"] = [
            _normalize_reference(
                reference,
                project_id=project_id,
                expected_kind="service",
                location=f"{location}.secret_refs[{index}]",
                catalog=catalog,
                allow_legacy_name=True,
                require_live=require_live_credentials,
            )
            for index, reference in enumerate(refs)
        ]

    if "egress_services" in normalized:
        services = normalized["egress_services"]
        if not isinstance(services, list):
            raise RuntimeError(f"Egress services at {location}.egress_services must be a JSON array")
        for index, service in enumerate(services):
            service_location = f"{location}.egress_services[{index}]"
            if not isinstance(service, dict):
                raise RuntimeError(f"Egress service at {service_location} must be a JSON object")
            if service.get("service_credential_id") not in (None, ""):
                reference = service["service_credential_id"]
                allow_legacy_name = False
            elif service.get("credential_ref") not in (None, ""):
                reference = service["credential_ref"]
                allow_legacy_name = True
            else:
                raise RuntimeError(f"Egress service at {service_location} is missing a credential reference")
            service["service_credential_id"] = _normalize_reference(
                reference,
                project_id=project_id,
                expected_kind="service",
                location=f"{service_location}.service_credential_id",
                catalog=catalog,
                allow_legacy_name=allow_legacy_name,
                require_live=require_live_credentials,
            )
            service.pop("credential_ref", None)

    return normalized


def _normalize_snapshot(
    value: object,
    *,
    project_id: str | None,
    location: str,
    catalog: _CredentialCatalog,
    require_live_credentials: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Snapshot at {location} must be a JSON object")
    normalized = copy.deepcopy(value)
    model_value = normalized.get("model_credential_id")
    legacy_value = normalized.get("secret_ref")
    if isinstance(model_value, str) and model_value.strip():
        normalized["model_credential_id"] = _normalize_reference(
            model_value,
            project_id=project_id,
            expected_kind="model",
            location=f"{location}.model_credential_id",
            catalog=catalog,
            require_live=require_live_credentials,
        )
    elif isinstance(legacy_value, str) and legacy_value.strip():
        normalized["model_credential_id"] = _normalize_reference(
            legacy_value,
            project_id=project_id,
            expected_kind="model",
            location=f"{location}.secret_ref",
            catalog=catalog,
            allow_legacy_name=True,
            require_live=require_live_credentials,
        )
    elif model_value not in (None, ""):
        raise RuntimeError(f"Credential reference at {location}.model_credential_id must be a string or null")
    elif legacy_value not in (None, ""):
        raise RuntimeError(f"Credential reference at {location}.secret_ref must be a string or null")
    normalized.pop("secret_ref", None)

    environment = normalized.get("environment")
    if isinstance(environment, dict) and "config" in environment:
        environment["config"] = _normalize_environment_config(
            environment["config"],
            project_id=project_id,
            location=f"{location}.environment.config",
            catalog=catalog,
            require_live_credentials=require_live_credentials,
        )
    return normalized


def _prepare_updates(
    connection: sa.engine.Connection,
    catalog: _CredentialCatalog,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    environment_updates: list[dict[str, object]] = []
    environment_rows = connection.execute(
        sa.text(
            "SELECT id, project_id, config FROM joysafeter_environments WHERE config IS NOT NULL ORDER BY id FOR UPDATE"
        )
    ).mappings()
    for row in environment_rows:
        normalized = _normalize_environment_config(
            row["config"],
            project_id=_text_id(row["project_id"]),
            location=f"joysafeter_environments.{row['id']}.config",
            catalog=catalog,
        )
        if normalized != row["config"]:
            environment_updates.append({"id": row["id"], "value": normalized})

    session_updates: list[dict[str, object]] = []
    session_rows = connection.execute(
        sa.text(
            "SELECT id, project_id, status, archived_at, agent_snapshot FROM joysafeter_sessions "
            "WHERE agent_snapshot IS NOT NULL ORDER BY id FOR UPDATE"
        )
    ).mappings()
    for row in session_rows:
        normalized = _normalize_snapshot(
            row["agent_snapshot"],
            project_id=_text_id(row["project_id"]),
            location=f"joysafeter_sessions.{row['id']}.agent_snapshot",
            catalog=catalog,
            require_live_credentials=(row["archived_at"] is None and str(row["status"]) != "terminated"),
        )
        if normalized != row["agent_snapshot"]:
            session_updates.append({"id": row["id"], "value": normalized})

    version_updates: list[dict[str, object]] = []
    version_rows = connection.execute(
        sa.text(
            "SELECT v.id, a.project_id, v.snapshot "
            "FROM joysafeter_agent_versions v "
            "JOIN joysafeter_agents a ON a.id = v.agent_id "
            "ORDER BY v.id FOR UPDATE OF v"
        )
    ).mappings()
    for row in version_rows:
        normalized = _normalize_snapshot(
            row["snapshot"],
            project_id=_text_id(row["project_id"]),
            location=f"joysafeter_agent_versions.{row['id']}.snapshot",
            catalog=catalog,
        )
        if normalized != row["snapshot"]:
            version_updates.append({"id": row["id"], "value": normalized})

    return environment_updates, session_updates, version_updates


def _apply_updates(
    connection: sa.engine.Connection,
    *,
    table: str,
    column: str,
    updates: list[dict[str, object]],
) -> None:
    statement = sa.text(f"UPDATE {table} SET {column} = CAST(:value AS JSONB) WHERE id = :id")
    for update in updates:
        connection.execute(
            statement,
            {"id": update["id"], "value": json.dumps(update["value"])},
        )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Migration 20260815_000002 is online-only because it validates live credential references.")

    connection = op.get_bind()
    catalog = _load_catalog(connection)
    environment_updates, session_updates, version_updates = _prepare_updates(connection, catalog)

    _apply_updates(
        connection,
        table="joysafeter_environments",
        column="config",
        updates=environment_updates,
    )
    _apply_updates(
        connection,
        table="joysafeter_sessions",
        column="agent_snapshot",
        updates=session_updates,
    )
    _apply_updates(
        connection,
        table="joysafeter_agent_versions",
        column="snapshot",
        updates=version_updates,
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade of 20260815_000002_normalize_credential_public_ids is not supported; "
        "restore the database backup taken before normalization."
    )
