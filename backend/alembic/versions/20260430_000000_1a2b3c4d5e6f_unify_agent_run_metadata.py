"""unify_agent_run_metadata

Revision ID: 1a2b3c4d5e6f
Revises:
Create Date: 2026-04-30 18:32:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "1a2b3c4d5e6f"
down_revision = "ff6aa7bb8cc9"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add new columns
    op.add_column("agent_runs", sa.Column("trigger_medium", sa.String(length=20), nullable=True))
    op.add_column("agent_runs", sa.Column("run_purpose", sa.String(length=20), nullable=True))

    # 2. Data Migration: single-pass CASE to map old trigger_source → new axes
    op.execute("""
        UPDATE agent_runs SET
            trigger_medium = CASE trigger_source
                WHEN 'task' THEN 'system'
                WHEN 'chat' THEN 'api'
                WHEN 'api' THEN 'api'
                WHEN 'scheduler' THEN 'scheduler'
                WHEN 'draft_test' THEN 'ui'
                WHEN 'draft_copilot' THEN 'ui'
                WHEN 'copilot' THEN 'ui'
                WHEN 'debug' THEN 'ui'
                ELSE 'api'
            END,
            run_purpose = CASE trigger_source
                WHEN 'task' THEN 'production'
                WHEN 'chat' THEN 'production'
                WHEN 'api' THEN 'production'
                WHEN 'scheduler' THEN 'production'
                WHEN 'draft_test' THEN 'draft_test'
                WHEN 'draft_copilot' THEN 'internal_builder'
                WHEN 'copilot' THEN 'internal_builder'
                WHEN 'debug' THEN 'debug'
                ELSE 'production'
            END
    """)

    # 3. Make new columns non-nullable
    op.alter_column("agent_runs", "trigger_medium", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("agent_runs", "run_purpose", existing_type=sa.String(length=20), nullable=False)

    # 4. Drop old column
    op.drop_column("agent_runs", "trigger_source")

    # 5. Clean up old executor kinds and definition kinds
    op.execute("UPDATE executions SET executor_kind = 'build_copilot' WHERE executor_kind = 'copilot'")
    op.execute(
        "UPDATE agent_versions SET definition_kind = 'sandbox_cli' WHERE definition_kind IN ('claude_code', 'codex', 'openclaw')"
    )


def downgrade():
    # 1. Add old column
    op.add_column("agent_runs", sa.Column("trigger_source", sa.String(length=20), nullable=True))

    # 2. Revert Data Migration: single-pass CASE
    op.execute("""
        UPDATE agent_runs SET
            trigger_source = CASE
                WHEN trigger_medium = 'system' AND run_purpose = 'production' THEN 'task'
                WHEN trigger_medium = 'api' AND run_purpose = 'production' THEN 'chat'
                WHEN trigger_medium = 'scheduler' AND run_purpose = 'production' THEN 'scheduler'
                WHEN trigger_medium = 'ui' AND run_purpose = 'draft_test' THEN 'draft_test'
                WHEN trigger_medium = 'ui' AND run_purpose = 'internal_builder' THEN 'draft_copilot'
                WHEN trigger_medium = 'ui' AND run_purpose = 'debug' THEN 'debug'
                ELSE 'api'
            END
    """)

    # 3. Make old column non-nullable
    op.alter_column("agent_runs", "trigger_source", existing_type=sa.String(length=20), nullable=False)

    # 4. Drop new columns
    op.drop_column("agent_runs", "run_purpose")
    op.drop_column("agent_runs", "trigger_medium")
