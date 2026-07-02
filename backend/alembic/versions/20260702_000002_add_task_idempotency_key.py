"""add task idempotency_key (Foundation 2 — effectively-once)

Adds a nullable ``idempotency_key`` to ``joysafeter_tasks`` with a unique
constraint so a retried submission (client or HA API replica) maps to exactly
one task instead of double-executing pentest tooling.

Revision ID: 20260702_000002
Revises: 20260627_000001
Create Date: 2026-07-02 00:00:00.000000+00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260702_000002"
down_revision: Union[str, None] = "20260627_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_tasks", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_joysafeter_tasks_idempotency_key", "joysafeter_tasks", ["idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_joysafeter_tasks_idempotency_key", "joysafeter_tasks", type_="unique"
    )
    op.drop_column("joysafeter_tasks", "idempotency_key")
