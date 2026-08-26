"""Validate the persisted MCP transport/authentication matrix.

Revision ID: 20260825_000005
Revises: 20260825_000004
Create Date: 2026-08-25 00:00:05.000000
"""

from __future__ import annotations

import json
from typing import Any, Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_000005"
down_revision: Union[str, None] = "20260825_000004"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def _json_value(value: Any, *, location: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{location} is not valid JSON") from exc
    return value


def validate_mcp_servers(value: Any, *, location: str) -> None:
    servers = _json_value(value, location=location)
    if servers is None:
        return
    if not isinstance(servers, list):
        raise RuntimeError(f"{location} must be a JSON array")
    for index, server in enumerate(servers):
        item_location = f"{location}[{index}]"
        if not isinstance(server, dict):
            raise RuntimeError(f"{item_location} must be a JSON object")
        if server.get("type") != "sse":
            continue
        requirement = server.get("auth_requirement")
        if requirement != "none":
            raise RuntimeError(
                f"{item_location} is an SSE MCP server with auth_requirement={requirement!r}; "
                "SSE MCP servers require auth_requirement='none'"
            )


def validate_snapshot(value: Any, *, location: str) -> None:
    snapshot = _json_value(value, location=location)
    if not isinstance(snapshot, dict):
        raise RuntimeError(f"{location} must be a JSON object")
    validate_mcp_servers(snapshot.get("mcp_servers", []), location=f"{location}.mcp_servers")


def _validate_rows(*, table: str, key: str, column: str, validator, where: str = "") -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT {key}, {column} FROM {table} {where} ORDER BY {key} FOR UPDATE")
    ).mappings()
    for row in rows:
        validator(row[column], location=f"{table}.{row[key]}.{column}")


def upgrade() -> None:
    _validate_rows(
        table="joysafeter_agents",
        key="id",
        column="mcp_servers",
        validator=validate_mcp_servers,
    )
    _validate_rows(
        table="joysafeter_agent_versions",
        key="id",
        column="snapshot",
        validator=validate_snapshot,
    )
    _validate_rows(
        table="joysafeter_sessions",
        key="id",
        column="agent_snapshot",
        validator=validate_snapshot,
        where="WHERE agent_snapshot IS NOT NULL",
    )


def downgrade() -> None:
    pass
