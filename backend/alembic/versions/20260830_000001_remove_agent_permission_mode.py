"""Remove the provider-specific agent permission_mode projection.

Revision ID: 20260830_000001
Revises: 20260829_000001
Create Date: 2026-08-30 00:00:01.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260830_000001"
down_revision: Union[str, None] = "20260829_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def _legacy_permission_mode_sql(tools_sql: str) -> str:
    tools = (
        "CASE WHEN jsonb_typeof(COALESCE("
        f"{tools_sql}, '[]'::jsonb)) = 'array' "
        f"THEN COALESCE({tools_sql}, '[]'::jsonb) ELSE '[]'::jsonb END"
    )
    ask_config = (
        "EXISTS ("
        "SELECT 1 FROM jsonb_array_elements("
        "CASE WHEN jsonb_typeof(tool->'configs') = 'array' "
        "THEN tool->'configs' ELSE '[]'::jsonb END"
        ") AS config "
        "WHERE config #>> '{permission_policy,type}' = 'always_ask'"
        ")"
    )
    return (
        "CASE WHEN EXISTS ("
        f"SELECT 1 FROM jsonb_array_elements({tools}) AS tool WHERE "
        "(tool->>'type' = 'agent_toolset_20260401' AND ("
        "tool #>> '{default_config,permission_policy,type}' = 'always_ask' OR "
        f"{ask_config}"
        ")) OR "
        "(tool->>'type' = 'mcp_toolset' AND ("
        "NOT (tool ? 'default_config') OR tool->'default_config' IS NULL OR "
        "tool #>> '{default_config,permission_policy,type}' = 'always_ask' OR "
        f"{ask_config}"
        "))"
        ") THEN 'default' ELSE 'bypassPermissions' END"
    )


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sessions
            SET agent_snapshot = agent_snapshot - 'permission_mode'
            WHERE jsonb_typeof(agent_snapshot) = 'object'
              AND agent_snapshot ? 'permission_mode'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE joysafeter_agent_versions
            SET snapshot = snapshot - 'permission_mode'
            WHERE jsonb_typeof(snapshot) = 'object'
              AND snapshot ? 'permission_mode'
            """
        )
    )
    op.drop_column("joysafeter_agents", "permission_mode")


def downgrade() -> None:
    op.add_column(
        "joysafeter_agents",
        sa.Column(
            "permission_mode",
            sa.Text(),
            nullable=False,
            server_default="bypassPermissions",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE joysafeter_agents SET permission_mode = "
            + _legacy_permission_mode_sql("tools")
        )
    )
    op.execute(
        sa.text(
            "UPDATE joysafeter_sessions SET agent_snapshot = "
            "jsonb_set(agent_snapshot, '{permission_mode}', "
            "to_jsonb(("
            + _legacy_permission_mode_sql("agent_snapshot->'tools'")
            + ")::text), true) "
            "WHERE jsonb_typeof(agent_snapshot) = 'object'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE joysafeter_agent_versions SET snapshot = "
            "jsonb_set(snapshot, '{permission_mode}', "
            "to_jsonb(("
            + _legacy_permission_mode_sql("snapshot->'tools'")
            + ")::text), true) "
            "WHERE jsonb_typeof(snapshot) = 'object'"
        )
    )
