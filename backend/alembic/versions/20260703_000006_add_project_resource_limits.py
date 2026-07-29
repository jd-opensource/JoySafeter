"""add per-project sandbox resource-limit overrides (Foundation 3 — tenancy)

Adds nullable ``max_cpu`` (cores) and ``max_memory_mb`` (MiB) to
``joysafeter_organization_projects``. NULL for a field means "use the global
default" (settings.sandbox_cpu / sandbox_memory_mb); a value overrides that
field for the project. Enforced per-sandbox via the Docker provider so one
tenant cannot exhaust host CPU/RAM on the shared fleet.

Revision ID: 20260703_000006
Revises: 20260703_000005
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260703_000006"
down_revision: Union[str, None] = "20260703_000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_organization_projects", sa.Column("max_cpu", sa.Float(), nullable=True))
    op.add_column("joysafeter_organization_projects", sa.Column("max_memory_mb", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("joysafeter_organization_projects", "max_memory_mb")
    op.drop_column("joysafeter_organization_projects", "max_cpu")
