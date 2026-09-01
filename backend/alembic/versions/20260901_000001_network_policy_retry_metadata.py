"""Add typed network-policy failure and retry metadata.

Revision ID: 20260901_000001
Revises: 20260831_000001
Create Date: 2026-09-01 00:00:01.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_000001"
down_revision: Union[str, None] = "20260831_000001"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_last_error_code", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column(
            "networking_retryable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column(
            "networking_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "joysafeter_sandboxes",
        sa.Column("networking_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "joysafeter_sandbox_network_policies",
        sa.Column("error_code", sa.Text(), nullable=True),
    )
    op.add_column(
        "joysafeter_sandbox_network_policies",
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sandboxes
            SET networking_status = CASE
                    WHEN networking_last_error ILIKE '%NACK%' THEN 'nacked'
                    ELSE 'failed'
                END,
                networking_last_error_code = CASE
                    WHEN networking_last_error ILIKE '%NACK%' THEN 'legacy_nack'
                    ELSE 'legacy_unclassified'
                END,
                networking_retryable = CASE
                    WHEN networking_last_error ILIKE '%NACK%' THEN FALSE
                    ELSE TRUE
                END,
                networking_next_retry_at = CASE
                    WHEN networking_last_error ILIKE '%NACK%' THEN NULL
                    ELSE NOW()
                END
            WHERE networking_status = 'nacked'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE joysafeter_sandbox_network_policies
            SET status = CASE
                    WHEN last_error ILIKE '%NACK%' THEN 'nacked'
                    ELSE 'failed'
                END,
                error_code = CASE
                    WHEN last_error ILIKE '%NACK%' THEN 'legacy_nack'
                    ELSE 'legacy_unclassified'
                END,
                retryable = CASE
                    WHEN last_error ILIKE '%NACK%' THEN FALSE
                    ELSE TRUE
                END,
                last_nack_reason = CASE
                    WHEN last_error ILIKE '%NACK%' THEN COALESCE(last_nack_reason, last_error)
                    ELSE NULL
                END
            WHERE status = 'nacked'
            """
        )
    )
    op.create_index(
        "idx_sandbox_networking_retry_due",
        "joysafeter_sandboxes",
        ["networking_next_retry_at"],
        unique=False,
        postgresql_where=sa.text("destroyed_at IS NULL AND networking_status = 'failed' AND networking_retryable"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_sandbox_networking_retry_due",
        table_name="joysafeter_sandboxes",
    )
    op.drop_column("joysafeter_sandbox_network_policies", "retryable")
    op.drop_column("joysafeter_sandbox_network_policies", "error_code")
    op.drop_column("joysafeter_sandboxes", "networking_next_retry_at")
    op.drop_column("joysafeter_sandboxes", "networking_retry_count")
    op.drop_column("joysafeter_sandboxes", "networking_retryable")
    op.drop_column("joysafeter_sandboxes", "networking_last_error_code")
