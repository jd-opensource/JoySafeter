"""drop legacy graph tables"""
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f6a7b8c9d0e1"


def upgrade():
    for table in ["graph_node_secrets", "graph_executions", "graph_edges", "graph_nodes", "graphs"]:
        try:
            op.drop_table(table)
        except Exception:
            pass


def downgrade():
    pass
