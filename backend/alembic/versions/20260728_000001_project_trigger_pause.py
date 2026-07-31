"""repair project columns for duplicate 20260728 revision databases

Revision ID: 20260731_000001
Revises: 20260729_000001
Create Date: 2026-07-31 18:20:00.000000

The revision id 20260728_000001 was used by two historical migrations. Some
long-lived databases advanced along the network-policy branch and never applied
the project trigger pause migration, leaving the ORM model ahead of the schema.
This forward-only repair migration idempotently adds the project columns the
current model expects.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import context, op

revision: str = "20260731_000001"
down_revision: Union[str, None] = "20260729_000001"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None

TABLE_NAME = "joysafeter_organization_projects"


def _has_column(column_name: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    columns = inspect(bind).get_columns(TABLE_NAME)
    return any(column["name"] == column_name for column in columns)


def _add_column_if_missing(column: sa.Column) -> None:
    if not _has_column(column.name):
        op.add_column(TABLE_NAME, column)


def upgrade() -> None:
    _add_column_if_missing(
        sa.Column(
            "triggers_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        )
    )
    _add_column_if_missing(sa.Column("max_concurrent_tasks", sa.Integer(), nullable=True))
    _add_column_if_missing(sa.Column("max_cpu", sa.Float(), nullable=True))
    _add_column_if_missing(sa.Column("max_memory_mb", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Forward-only repair migration. These columns are owned by their original
    # migrations in normal downgrade flows; dropping them here could remove data
    # on databases that already applied the original migrations.
    pass
