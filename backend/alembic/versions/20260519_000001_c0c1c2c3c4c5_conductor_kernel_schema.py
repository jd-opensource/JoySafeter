"""conductor kernel schema

Revision ID: c0c1c2c3c4c5
Revises: a9a8a7a6a5a4
Create Date: 2026-05-19 00:00:01.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0c1c2c3c4c5"
down_revision: Union[str, None] = "a9a8a7a6a5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Agents ===
    op.create_table(
        "conductor_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("engine_kind", sa.Text(), nullable=False, server_default="claude"),
        sa.Column("model", postgresql.JSONB(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("env", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("mcp_configs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("skills", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("permission_mode", sa.Text(), nullable=False, server_default="bypassPermissions"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("multiagent", postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("environment_ref", sa.Text(), nullable=True),
        sa.Column("secret_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_ca_name_unique", "conductor_agents", ["name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_ca_created_at", "conductor_agents", [sa.text("created_at DESC")])

    op.create_table(
        "conductor_agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "version"),
    )

    # === Secrets ===
    op.create_table(
        "conductor_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_cs_name_unique", "conductor_secrets", ["name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))

    # === Environments ===
    op.create_table(
        "conductor_environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("image_tag", sa.Text(), nullable=True),
        sa.Column("image_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    # === Sessions ===
    op.create_table(
        "conductor_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_agents.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="idle"),
        sa.Column("stop_reason", postgresql.JSONB(), nullable=True),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default='{"input_tokens":0,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}'),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("vault_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("agent_version", sa.Integer(), nullable=True),
        sa.Column("agent_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("environment_ref", sa.Text(), nullable=True),
        sa.Column("last_harness_session_id", sa.Text(), nullable=True),
        sa.Column("last_work_dir", sa.Text(), nullable=True),
        sa.Column("last_sandbox_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_csess_agent", "conductor_sessions", ["agent_id"])
    op.create_index("idx_csess_created", "conductor_sessions", [sa.text("created_at DESC")])

    op.create_table(
        "conductor_session_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_sessions.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "seq"),
    )
    op.create_index("idx_cse_session_seq", "conductor_session_events", ["session_id", "seq"])

    # === Tasks ===
    op.create_table(
        "conductor_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_agents.id"), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_sessions.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("sandbox_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", postgresql.JSONB(), nullable=True),
        sa.Column("timeout_sec", sa.Integer(), nullable=False, server_default="7200"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_ct_status", "conductor_tasks", ["status"])
    op.create_index("idx_ct_agent", "conductor_tasks", ["agent_id"])
    op.create_index("idx_ct_created", "conductor_tasks", [sa.text("created_at DESC")])

    # === Sandboxes ===
    op.create_table(
        "conductor_sandboxes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider", sa.Text(), nullable=False, server_default="docker"),
        sa.Column("status", sa.Text(), nullable=False, server_default="creating"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("last_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_path", sa.Text(), nullable=True),
    )
    op.create_index("idx_csb_pool", "conductor_sandboxes", [sa.text("created_at ASC")], postgresql_where=sa.text("status = 'pooled'"))
    op.create_index("idx_csb_status", "conductor_sandboxes", ["status"])
    op.create_index("idx_csb_session", "conductor_sandboxes", ["chat_session_id"], postgresql_where=sa.text("chat_session_id IS NOT NULL"))

    # === Memory Stores ===
    op.create_table(
        "conductor_memory_stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "conductor_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_memory_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.Text(), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "path"),
    )

    op.create_table(
        "conductor_memory_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_memory_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=True),
        sa.Column("content_size_bytes", sa.Integer(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_by", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "conductor_session_memory_stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_sessions.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_memory_stores.id"), nullable=False),
        sa.Column("access", sa.Text(), nullable=False, server_default="read_write"),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("mount_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "store_id"),
    )

    # === Vaults ===
    op.create_table(
        "conductor_vaults",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_cv_name", "conductor_vaults", ["name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "conductor_vault_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vault_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conductor_vaults.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("credential_type", sa.Text(), nullable=False, server_default="static_bearer"),
        sa.Column("mcp_server_url", sa.Text(), nullable=False),
        sa.Column("token_value", sa.Text(), nullable=False),
        sa.Column("oauth_config", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_cvc_url", "conductor_vault_credentials", ["vault_id", "mcp_server_url"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_table("conductor_vault_credentials")
    op.drop_table("conductor_vaults")
    op.drop_table("conductor_session_memory_stores")
    op.drop_table("conductor_memory_versions")
    op.drop_table("conductor_memories")
    op.drop_table("conductor_memory_stores")
    op.drop_table("conductor_sandboxes")
    op.drop_table("conductor_tasks")
    op.drop_table("conductor_session_events")
    op.drop_table("conductor_sessions")
    op.drop_table("conductor_environments")
    op.drop_table("conductor_secrets")
    op.drop_table("conductor_agent_versions")
    op.drop_table("conductor_agents")
