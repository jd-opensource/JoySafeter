"""cleanup legacy schema after squash

Revision ID: 20260803_000001
Revises: 20260731_000003
Create Date: 2026-08-03 00:00:00.000000

Run this once on databases that were deployed before the squashed baseline.
It removes known legacy objects and adds objects/indexes present in the new
single init schema.
"""

from __future__ import annotations

from typing import Iterable, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260803_000001"
down_revision: Union[str, None] = "20260731_000003"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def _exec(sql: str) -> None:
    op.execute(sa.text(sql))


def _create_index_if_missing(
    name: str,
    table: str,
    columns: Iterable[str],
    *,
    where: str | None = None,
    unique: bool = False,
) -> None:
    unique_sql = "UNIQUE " if unique else ""
    cols = ", ".join(columns)
    where_sql = f" WHERE {where}" if where else ""
    _exec(f"CREATE {unique_sql}INDEX IF NOT EXISTS {name} ON {table} ({cols}){where_sql}")


def upgrade() -> None:
    # Legacy schedule table/column from the pre-unified trigger design.
    _exec("DROP TABLE IF EXISTS joysafeter_schedules CASCADE")
    _exec("DROP INDEX IF EXISTS idx_ct_schedule")
    _exec("ALTER TABLE IF EXISTS joysafeter_tasks DROP COLUMN IF EXISTS schedule_id")

    # Runtime task fencing sequence used by task state transitions.
    _exec("CREATE SEQUENCE IF NOT EXISTS joysafeter_task_owner_epoch_seq")

    # Runtime membership mirror. Kept outside ORM but required by health checks.
    _exec(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_cluster_members (
            instance_id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    _create_index_if_missing(
        "idx_joysafeter_cluster_members_role_expires_at",
        "joysafeter_cluster_members",
        ["role", "expires_at"],
    )

    # Time/query indexes added to the squashed baseline for high-growth tables.
    _create_index_if_missing("idx_joysafeter_auth_sessions_expires", "joysafeter_auth_sessions", ["expires_at"])
    _create_index_if_missing(
        "idx_joysafeter_auth_sessions_last_activity",
        "joysafeter_auth_sessions",
        ["last_activity_at"],
    )
    _create_index_if_missing("idx_joysafeter_files_deleted", "joysafeter_files", ["deleted_at"])
    _create_index_if_missing(
        "idx_joysafeter_memory_versions_store_created",
        "joysafeter_memory_versions",
        ["store_id", "created_at"],
    )
    _create_index_if_missing(
        "idx_joysafeter_memory_versions_session_created",
        "joysafeter_memory_versions",
        ["session_id", "created_at"],
    )
    _create_index_if_missing(
        "idx_joysafeter_session_memory_stores_created",
        "joysafeter_session_memory_stores",
        ["created_at"],
    )
    _create_index_if_missing("idx_jsnp_created_at", "joysafeter_sandbox_network_policies", ["created_at"])
    _create_index_if_missing("idx_jsnp_pushed_at", "joysafeter_sandbox_network_policies", ["pushed_at"])
    _create_index_if_missing("idx_jsnp_acked_at", "joysafeter_sandbox_network_policies", ["acked_at"])
    _create_index_if_missing("idx_csb_last_used", "joysafeter_sandboxes", ["last_used_at"])
    _create_index_if_missing("idx_csb_updated", "joysafeter_sandboxes", ["updated_at"])
    _create_index_if_missing("idx_csb_destroyed", "joysafeter_sandboxes", ["destroyed_at"])
    _create_index_if_missing("idx_csess_updated", "joysafeter_sessions", ["updated_at"])
    _create_index_if_missing("idx_csess_archived", "joysafeter_sessions", ["archived_at"])
    _create_index_if_missing("idx_session_files_created", "joysafeter_session_files", ["created_at"])
    _create_index_if_missing(
        "idx_joysafeter_session_storage_mounts_created",
        "joysafeter_session_storage_mounts",
        ["created_at"],
    )
    _create_index_if_missing(
        "idx_joysafeter_session_storage_mounts_detached",
        "joysafeter_session_storage_mounts",
        ["detached_at"],
    )
    _create_index_if_missing("skill_usage_log_created_idx", "joysafeter_skill_usage_log", ["created_at"])
    _create_index_if_missing(
        "idx_joysafeter_storage_audit_created",
        "joysafeter_storage_mount_audit",
        ["created_at"],
    )
    _create_index_if_missing(
        "idx_joysafeter_storage_audit_result_created",
        "joysafeter_storage_mount_audit",
        ["result", "created_at"],
    )
    _create_index_if_missing("idx_ct_status_next_schedule", "joysafeter_tasks", ["status", "next_schedule_at"])
    _create_index_if_missing("idx_ct_started", "joysafeter_tasks", ["started_at"])
    _create_index_if_missing("idx_ct_completed", "joysafeter_tasks", ["completed_at"])
    _create_index_if_missing(
        "idx_joysafeter_triggers_project_created",
        "joysafeter_triggers",
        ["project_id", "created_at"],
    )
    _create_index_if_missing("idx_joysafeter_triggers_updated", "joysafeter_triggers", ["updated_at"])
    _create_index_if_missing("idx_joysafeter_triggers_last_attempt", "joysafeter_triggers", ["last_attempt_at"])
    _create_index_if_missing("idx_joysafeter_triggers_deleted", "joysafeter_triggers", ["deleted_at"])


def downgrade() -> None:
    # This migration is a one-way compatibility repair for already-deployed DBs.
    # Do not recreate removed legacy schedule objects on downgrade.
    pass
