"""unify_agent_run_metadata

Revision ID: 1a2b3c4d5e6f
Revises: 
Create Date: 2026-04-30 18:32:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = 'ff6aa7bb8cc9'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Add new columns
    op.add_column('agent_runs', sa.Column('trigger_medium', sa.String(length=20), nullable=True))
    op.add_column('agent_runs', sa.Column('run_purpose', sa.String(length=20), nullable=True))

    # 2. Data Migration: Map old trigger_source to new medium and purpose
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'system', run_purpose = 'production' 
        WHERE trigger_source = 'task'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'api', run_purpose = 'production' 
        WHERE trigger_source IN ('chat', 'api')
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'scheduler', run_purpose = 'production' 
        WHERE trigger_source = 'scheduler'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'ui', run_purpose = 'draft_test' 
        WHERE trigger_source = 'draft_test'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'ui', run_purpose = 'internal_builder' 
        WHERE trigger_source IN ('draft_copilot', 'copilot')
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_medium = 'ui', run_purpose = 'debug' 
        WHERE trigger_source = 'debug'
    """)
    
    # Set default for any remaining nulls (safety catch)
    op.execute("UPDATE agent_runs SET trigger_medium = 'api', run_purpose = 'production' WHERE trigger_medium IS NULL")

    # 3. Make new columns non-nullable
    op.alter_column('agent_runs', 'trigger_medium', existing_type=sa.String(length=20), nullable=False)
    op.alter_column('agent_runs', 'run_purpose', existing_type=sa.String(length=20), nullable=False)

    # 4. Drop old column
    op.drop_column('agent_runs', 'trigger_source')

    # 5. Clean up old executor kinds and definition kinds
    op.execute("UPDATE executions SET executor_kind = 'build_copilot' WHERE executor_kind = 'copilot'")
    op.execute("UPDATE agent_versions SET definition_kind = 'sandbox_cli' WHERE definition_kind IN ('claude_code', 'codex', 'openclaw')")


def downgrade():
    # 1. Add old column
    op.add_column('agent_runs', sa.Column('trigger_source', sa.String(length=20), nullable=True))

    # 2. Revert Data Migration
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'task' 
        WHERE trigger_medium = 'system' AND run_purpose = 'production'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'chat' 
        WHERE trigger_medium = 'api' AND run_purpose = 'production'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'scheduler' 
        WHERE trigger_medium = 'scheduler' AND run_purpose = 'production'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'draft_test' 
        WHERE trigger_medium = 'ui' AND run_purpose = 'draft_test'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'draft_copilot' 
        WHERE trigger_medium = 'ui' AND run_purpose = 'internal_builder'
    """)
    op.execute("""
        UPDATE agent_runs 
        SET trigger_source = 'debug' 
        WHERE trigger_medium = 'ui' AND run_purpose = 'debug'
    """)

    # 3. Make old column non-nullable
    op.alter_column('agent_runs', 'trigger_source', existing_type=sa.String(length=20), nullable=False)

    # 4. Drop new columns
    op.drop_column('agent_runs', 'run_purpose')
    op.drop_column('agent_runs', 'trigger_medium')
