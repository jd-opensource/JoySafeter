"""Remove deprecated egress cookie injection fields from persisted JSONB.

Revision ID: 20260831_000001
Revises: 20260830_000004
Create Date: 2026-08-31 00:00:01.000000
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any, Optional, Union

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260831_000001"
down_revision: Union[str, None] = "20260830_000004"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def _fail(location: str, message: str) -> RuntimeError:
    return RuntimeError(f"{location}: {message}")


def _object(value: object, *, location: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(location, "expected JSON object")
    return copy.deepcopy(dict(value))


def _normalize_inject(value: object, *, location: str) -> dict[str, Any]:
    inject = _object(value, location=location)
    if "cookie_name" in inject:
        if inject["cookie_name"] is not None:
            raise _fail(f"{location}.cookie_name", "expected null deprecated value")
        inject.pop("cookie_name")
    if "cookies" in inject:
        if inject["cookies"] != {}:
            raise _fail(f"{location}.cookies", "expected empty deprecated mapping")
        inject.pop("cookies")
    return inject


def _restore_inject(value: object, *, location: str) -> dict[str, Any]:
    inject = _object(value, location=location)
    inject["cookie_name"] = None
    inject["cookies"] = {}
    return inject


def normalize_environment_config(value: object, *, location: str) -> dict[str, Any]:
    config = _object(value, location=location)
    services = config.get("egress_services")
    if services is None:
        return config
    if not isinstance(services, list):
        raise _fail(f"{location}.egress_services", "expected list or null")

    normalized_services: list[dict[str, Any]] = []
    for index, value_service in enumerate(services):
        service_location = f"{location}.egress_services[{index}]"
        service = _object(value_service, location=service_location)
        inject = service.get("inject")
        if inject is not None:
            service["inject"] = _normalize_inject(inject, location=f"{service_location}.inject")
        normalized_services.append(service)
    config["egress_services"] = normalized_services
    return config


def restore_environment_config(value: object, *, location: str) -> dict[str, Any]:
    config = _object(value, location=location)
    services = config.get("egress_services")
    if services is None:
        return config
    if not isinstance(services, list):
        raise _fail(f"{location}.egress_services", "expected list or null")

    restored_services: list[dict[str, Any]] = []
    for index, value_service in enumerate(services):
        service_location = f"{location}.egress_services[{index}]"
        service = _object(value_service, location=service_location)
        inject = service.get("inject")
        if inject is not None:
            service["inject"] = _restore_inject(inject, location=f"{service_location}.inject")
        restored_services.append(service)
    config["egress_services"] = restored_services
    return config


def normalize_snapshot(value: object, *, location: str) -> dict[str, Any]:
    snapshot = _object(value, location=location)
    environment = snapshot.get("environment")
    if environment is None:
        return snapshot

    environment_location = f"{location}.environment"
    normalized_environment = _object(environment, location=environment_location)
    config = normalized_environment.get("config")
    if config is not None:
        normalized_environment["config"] = normalize_environment_config(
            config,
            location=f"{environment_location}.config",
        )
    snapshot["environment"] = normalized_environment
    return snapshot


def restore_snapshot(value: object, *, location: str) -> dict[str, Any]:
    snapshot = _object(value, location=location)
    environment = snapshot.get("environment")
    if environment is None:
        return snapshot

    environment_location = f"{location}.environment"
    restored_environment = _object(environment, location=environment_location)
    config = restored_environment.get("config")
    if config is not None:
        restored_environment["config"] = restore_environment_config(
            config,
            location=f"{environment_location}.config",
        )
    snapshot["environment"] = restored_environment
    return snapshot


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
    if context.is_offline_mode():
        raise RuntimeError("deprecated egress cookie field migration is online-only")
    connection = op.get_bind()
    environments = [
        (row_id, normalize_environment_config(document, location=f"joysafeter_environments[{row_id}].config"))
        for row_id, document in _locked_documents(connection, "joysafeter_environments", "config")
    ]
    sessions = [
        (row_id, normalize_snapshot(document, location=f"joysafeter_sessions[{row_id}].agent_snapshot"))
        for row_id, document in _locked_documents(
            connection,
            "joysafeter_sessions",
            "agent_snapshot",
            skip_null=True,
        )
    ]
    agent_versions = [
        (row_id, normalize_snapshot(document, location=f"joysafeter_agent_versions[{row_id}].snapshot"))
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
    if context.is_offline_mode():
        raise RuntimeError("deprecated egress cookie field migration is online-only")
    connection = op.get_bind()
    environments = [
        (row_id, restore_environment_config(document, location=f"joysafeter_environments[{row_id}].config"))
        for row_id, document in _locked_documents(connection, "joysafeter_environments", "config")
    ]
    sessions = [
        (row_id, restore_snapshot(document, location=f"joysafeter_sessions[{row_id}].agent_snapshot"))
        for row_id, document in _locked_documents(
            connection,
            "joysafeter_sessions",
            "agent_snapshot",
            skip_null=True,
        )
    ]
    agent_versions = [
        (row_id, restore_snapshot(document, location=f"joysafeter_agent_versions[{row_id}].snapshot"))
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
