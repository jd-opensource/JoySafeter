"""drop legacy graph tables"""
from alembic import op

revision = "z1a2b3c4d5e6"
down_revision = "f6a7b8c9d0e1"


def upgrade():
    for table in ["graph_node_secrets", "graph_executions", "graph_edges", "graph_nodes", "graphs"]:
        try:
            op.drop_table(table)
        except Exception:
            pass


def downgrade():
    pass
