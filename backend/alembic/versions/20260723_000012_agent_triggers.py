"""add agent trigger/webhook support and schedule runtime fields

Revision ID: 20260723_000012
Revises: 20260710_000011
Create Date: 2026-07-23 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260723_000012"
down_revision: Union[str, None] = "20260720_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_schedules",
        sa.Column("session_mode", sa.String(length=16), nullable=False, server_default="fresh"),
    )
    op.add_column("joysafeter_schedules", sa.Column("pinned_session_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_schedules", sa.Column("reusable_session_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_schedules", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("joysafeter_schedules", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("joysafeter_schedules", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "joysafeter_schedules",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("joysafeter_schedules", sa.Column("last_task_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_schedules", sa.Column("last_session_id", sa.UUID(), nullable=True))
    op.add_column(
        "joysafeter_schedules",
        sa.Column("last_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_schedules_pinned_session_id_joysafeter_sessions"),
        "joysafeter_schedules",
        "joysafeter_sessions",
        ["pinned_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_schedules_reusable_session_id_joysafeter_sessions"),
        "joysafeter_schedules",
        "joysafeter_sessions",
        ["reusable_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_schedules_last_task_id_joysafeter_tasks"),
        "joysafeter_schedules",
        "joysafeter_tasks",
        ["last_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_joysafeter_schedules_last_session_id_joysafeter_sessions"),
        "joysafeter_schedules",
        "joysafeter_sessions",
        ["last_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_joysafeter_schedules_session_mode", "joysafeter_schedules", ["session_mode"])

    op.create_table(
        "joysafeter_triggers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("environment_ref", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("session_mode", sa.String(length=16), nullable=False, server_default="fresh"),
        sa.Column("pinned_session_id", sa.UUID(), nullable=True),
        sa.Column("reusable_session_id", sa.UUID(), nullable=True),
        sa.Column("secret", sa.String(length=255), nullable=True),
        sa.Column("filter", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("timeout_sec", sa.Integer(), nullable=False, server_default="7200"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("project_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.String(length=255), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_task_id", sa.UUID(), nullable=True),
        sa.Column("last_session_id", sa.UUID(), nullable=True),
        sa.Column("last_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["joysafeter_agents.id"], name=op.f("fk_joysafeter_triggers_agent_id_joysafeter_agents")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["joysafeter_organization_projects.id"],
            name=op.f("fk_joysafeter_triggers_project_id_joysafeter_organization_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["pinned_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_triggers_pinned_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reusable_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_triggers_reusable_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_task_id"],
            ["joysafeter_tasks.id"],
            name=op.f("fk_joysafeter_triggers_last_task_id_joysafeter_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_session_id"],
            ["joysafeter_sessions.id"],
            name=op.f("fk_joysafeter_triggers_last_session_id_joysafeter_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_joysafeter_triggers")),
        sa.UniqueConstraint("project_id", "name", name="uq_joysafeter_triggers_project_name"),
    )
    op.create_index("idx_joysafeter_triggers_project", "joysafeter_triggers", ["project_id"])
    op.create_index("idx_joysafeter_triggers_type_enabled", "joysafeter_triggers", ["type", "enabled"])


def downgrade() -> None:
    op.drop_index("idx_joysafeter_triggers_type_enabled", table_name="joysafeter_triggers")
    op.drop_index("idx_joysafeter_triggers_project", table_name="joysafeter_triggers")
    op.drop_table("joysafeter_triggers")

    op.drop_index("idx_joysafeter_schedules_session_mode", table_name="joysafeter_schedules")
    op.drop_constraint(
        op.f("fk_joysafeter_schedules_last_session_id_joysafeter_sessions"), "joysafeter_schedules", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_joysafeter_schedules_last_task_id_joysafeter_tasks"), "joysafeter_schedules", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_joysafeter_schedules_reusable_session_id_joysafeter_sessions"),
        "joysafeter_schedules",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_joysafeter_schedules_pinned_session_id_joysafeter_sessions"),
        "joysafeter_schedules",
        type_="foreignkey",
    )
    for column in (
        "last_payload",
        "last_session_id",
        "last_task_id",
        "consecutive_failures",
        "last_error",
        "last_success_at",
        "last_attempt_at",
        "reusable_session_id",
        "pinned_session_id",
        "session_mode",
    ):
        op.drop_column("joysafeter_schedules", column)
