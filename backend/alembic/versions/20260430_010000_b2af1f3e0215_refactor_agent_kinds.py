"""refactor_agent_kinds

Revision ID: b2af1f3e0215
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-30

Renames definition_kind->engine_kind, executor_kind->engine_kind.
Remaps values: graph->langgraph_visual, code->langgraph_code,
sandbox_cli->(split by runtime_binding), graph/code runtime->server.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2af1f3e0215'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    # 1. agent_versions: rename column + remap values
    op.alter_column('agent_versions', 'definition_kind', new_column_name='engine_kind')
    op.execute("UPDATE agent_versions SET engine_kind = 'langgraph_visual' WHERE engine_kind = 'graph'")
    op.execute("UPDATE agent_versions SET engine_kind = 'langgraph_code' WHERE engine_kind = 'code'")
    # sandbox_cli -> split by runtime_binding from linked releases
    op.execute("""
        UPDATE agent_versions av
        SET engine_kind = COALESCE(
            (SELECT ar.runtime_binding->>'runtime_type'
             FROM agent_releases ar
             WHERE ar.agent_version_id = av.id
             LIMIT 1),
            'claude_code'
        )
        WHERE av.engine_kind = 'sandbox_cli'
    """)

    # 2. agent_releases: remap runtime_kind values
    op.execute("UPDATE agent_releases SET runtime_kind = 'server' WHERE runtime_kind IN ('graph', 'code')")

    # 3. executions: rename column (values already correct: claude_code, codex, openclaw, build_copilot)
    op.alter_column('executions', 'executor_kind', new_column_name='engine_kind')


def downgrade():
    # 3. executions: restore column name
    op.alter_column('executions', 'engine_kind', new_column_name='executor_kind')

    # 2. agent_releases: restore runtime_kind values (best-effort)
    # Cannot distinguish graph vs code from runtime_kind alone, default to graph
    op.execute("UPDATE agent_releases SET runtime_kind = 'graph' WHERE runtime_kind = 'server'")

    # 1. agent_versions: restore column name + remap values
    op.execute("UPDATE agent_versions SET engine_kind = 'graph' WHERE engine_kind = 'langgraph_visual'")
    op.execute("UPDATE agent_versions SET engine_kind = 'code' WHERE engine_kind = 'langgraph_code'")
    op.execute("""
        UPDATE agent_versions SET engine_kind = 'sandbox_cli'
        WHERE engine_kind IN ('claude_code', 'codex', 'openclaw')
    """)
    op.alter_column('agent_versions', 'engine_kind', new_column_name='definition_kind')
