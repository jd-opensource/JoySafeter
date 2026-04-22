"""drop legacy graph tables"""
from alembic import op

revision = "z1a2b3c4d5e6"
down_revision = "ff66aa77bb88"


def upgrade():
    for table in ["graph_node_secrets", "graph_executions", "graph_edges", "graph_nodes", "graphs"]:
        try:
            op.drop_table(table)
        except Exception:
            pass


def downgrade():
    pass
