"""add per-project concurrent-task limit override (Foundation 3 — tenancy)

Adds a nullable ``max_concurrent_tasks`` to ``joysafeter_organization_projects``.
The project is the tenant boundary; admission control caps a project's live
(non-terminal) task count so one tenant cannot starve the shared HA fleet. NULL
means "use the global default" (settings.max_concurrent_per_project); a value
overrides it for that project (e.g. a paid/trusted tenant).

Revision ID: 20260703_000005
Revises: 20260702_000004
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260703_000005"
down_revision: Union[str, None] = "20260702_000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_organization_projects",
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("joysafeter_organization_projects", "max_concurrent_tasks")
