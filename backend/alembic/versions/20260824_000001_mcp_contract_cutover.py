"""Cut MCP persistence over to the canonical runtime contract.

Revision ID: 20260824_000001
Revises: 20260823_000005
Create Date: 2026-08-24 00:00:01.000000
"""

from __future__ import annotations

import copy
import json
from typing import Any, Optional, Union

import sqlalchemy as sa

revision: str = "20260824_000001"
down_revision: Union[str, None] = "20260823_000005"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

_REMOTE_TRANSPORTS = frozenset({"streamable_http", "sse"})
_TRANSPORT_ALIASES = {
    "": "streamable_http",
    "url": "streamable_http",
    "http": "streamable_http",
    "streamable-http": "streamable_http",
    "stdio": "local_stdio",
}
_AUTH_SCHEME_ALIASES = {
    "bearer": "static_bearer",
    "api_key": "header_api_key",
}
_CANONICAL_AUTH_SCHEMES = frozenset({"static_bearer", "header_api_key", "custom_header"})
_DISABLED_AUTH_SCHEMES = frozenset({"oauth", "mcp_oauth"})
_REMOTE_SERVER_FIELDS = frozenset({"type", "name", "url", "auth_requirement"})
_LOCAL_SERVER_FIELDS = frozenset({"type", "name", "command", "args", "env"})


def _json_value(value: Any, *, location: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{location} is not valid JSON") from exc
    return value


def canonicalize_mcp_servers(value: Any, *, location: str) -> list[dict[str, Any]]:
    servers = _json_value(value, location=location)
    if servers is None:
        return []
    if not isinstance(servers, list):
        raise RuntimeError(f"{location} must be a JSON array")

    canonical: list[dict[str, Any]] = []
    for index, raw_server in enumerate(servers):
        item_location = f"{location}[{index}]"
        if not isinstance(raw_server, dict):
            raise RuntimeError(f"{item_location} must be a JSON object")
        server = copy.deepcopy(raw_server)
        raw_transport = server.get("type", "")
        if not isinstance(raw_transport, str):
            raise RuntimeError(f"{item_location}.type must be a string")
        transport = _TRANSPORT_ALIASES.get(raw_transport, raw_transport)
        if transport not in {*_REMOTE_TRANSPORTS, "local_stdio"}:
            raise RuntimeError(f"{item_location} has unsupported MCP transport: {raw_transport!r}")
        server["type"] = transport
        if transport in _REMOTE_TRANSPORTS:
            unexpected = sorted(set(server) - _REMOTE_SERVER_FIELDS)
            if unexpected:
                raise RuntimeError(f"{item_location} contains noncanonical MCP field(s): {', '.join(unexpected)}")
            if not isinstance(server.get("url"), str) or not server["url"].strip():
                raise RuntimeError(f"{item_location}.url must be a non-empty string")
            requirement = server.get("auth_requirement", "optional")
            if requirement not in {"required", "optional", "none"}:
                raise RuntimeError(f"{item_location} has unsupported MCP auth requirement: {requirement!r}")
            server["auth_requirement"] = requirement
        else:
            unexpected = sorted(set(server) - _LOCAL_SERVER_FIELDS)
            if unexpected:
                raise RuntimeError(f"{item_location} contains noncanonical MCP field(s): {', '.join(unexpected)}")
            if not isinstance(server.get("command"), str) or not server["command"].strip():
                raise RuntimeError(f"{item_location}.command must be a non-empty string")
            args = server.get("args", [])
            if not isinstance(args, list) or not all(isinstance(argument, str) for argument in args):
                raise RuntimeError(f"{item_location}.args must be an array of strings")
            environment = server.get("env", {})
            if not isinstance(environment, dict) or not all(
                isinstance(key, str) and isinstance(item, str) for key, item in environment.items()
            ):
                raise RuntimeError(f"{item_location}.env must be an object of string values")
        canonical.append(server)
    return canonical


def canonicalize_snapshot(value: Any, *, location: str) -> dict[str, Any]:
    snapshot = _json_value(value, location=location)
    if not isinstance(snapshot, dict):
        raise RuntimeError(f"{location} must be a JSON object")
    canonical = copy.deepcopy(snapshot)
    if "mcp_servers" in canonical:
        canonical["mcp_servers"] = canonicalize_mcp_servers(
            canonical["mcp_servers"], location=f"{location}.mcp_servers"
        )
    environment = canonical.get("environment")
    if isinstance(environment, dict) and isinstance(environment.get("config"), dict):
        environment["config"] = canonicalize_environment_config(
            environment["config"], location=f"{location}.environment.config"
        )
    return canonical


def canonicalize_environment_config(value: Any, *, location: str) -> dict[str, Any]:
    config = _json_value(value, location=location)
    if not isinstance(config, dict):
        raise RuntimeError(f"{location} must be a JSON object")
    canonical = copy.deepcopy(config)
    networking = canonical.get("networking")
    if isinstance(networking, dict):
        legacy_type = networking.pop("net_type", None)
        if legacy_type is not None:
            if "type" in networking and networking["type"] != legacy_type:
                raise RuntimeError(f"{location}.networking contains conflicting type and net_type")
            networking["type"] = legacy_type
        networking.pop("allow_mcp_servers", None)
    return canonical


def canonicalize_mcp_auth_scheme(value: Any, *, location: str) -> str:
    if value is None:
        return "static_bearer"
    if not isinstance(value, str):
        raise RuntimeError(f"{location} must be a string")
    canonical = _AUTH_SCHEME_ALIASES.get(value, value)
    if canonical not in _CANONICAL_AUTH_SCHEMES | _DISABLED_AUTH_SCHEMES:
        raise RuntimeError(f"{location} has unsupported MCP auth scheme: {value!r}")
    return canonical


def _update_json_rows(
    connection,
    *,
    table: str,
    key: str,
    column: str,
    transform,
    where: str = "",
) -> None:
    rows = connection.execute(
        sa.text(f"SELECT {key}, {column} FROM {table} {where} ORDER BY {key} FOR UPDATE")
    ).mappings()
    for row in rows:
        location = f"{table}.{row[key]}.{column}"
        current = _json_value(row[column], location=location)
        updated = transform(current, location=location)
        if updated != current:
            connection.execute(
                sa.text(f"UPDATE {table} SET {column} = CAST(:value AS JSONB) WHERE {key} = :key"),
                {"value": json.dumps(updated), "key": row[key]},
            )


def upgrade() -> None:
    from alembic import op

    connection = op.get_bind()
    _update_json_rows(
        connection,
        table="joysafeter_agents",
        key="id",
        column="mcp_servers",
        transform=canonicalize_mcp_servers,
    )
    _update_json_rows(
        connection,
        table="joysafeter_agent_versions",
        key="id",
        column="snapshot",
        transform=canonicalize_snapshot,
    )
    _update_json_rows(
        connection,
        table="joysafeter_sessions",
        key="id",
        column="agent_snapshot",
        transform=canonicalize_snapshot,
        where="WHERE agent_snapshot IS NOT NULL",
    )
    _update_json_rows(
        connection,
        table="joysafeter_environments",
        key="id",
        column="config",
        transform=canonicalize_environment_config,
    )

    rows = connection.execute(
        sa.text("SELECT id, credential_type FROM joysafeter_credentials WHERE kind = 'mcp' ORDER BY id FOR UPDATE")
    ).mappings()
    for row in rows:
        location = f"joysafeter_credentials.{row['id']}.credential_type"
        canonical = canonicalize_mcp_auth_scheme(row["credential_type"], location=location)
        if canonical != row["credential_type"]:
            connection.execute(
                sa.text("UPDATE joysafeter_credentials SET credential_type = :value WHERE id = :id"),
                {"value": canonical, "id": row["id"]},
            )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade of 20260824_000001_mcp_contract_cutover is not supported; "
        "restore the database from a backup taken before the canonical MCP cutover."
    )
