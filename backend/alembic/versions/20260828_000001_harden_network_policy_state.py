"""Harden sandbox network-policy generation invariants.

Revision ID: 20260828_000001
Revises: 20260825_000005
Create Date: 2026-08-28 00:00:01.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_000001"
down_revision: Union[str, None] = "20260825_000005"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

NETWORKING_STATUS_CONSTRAINT = "ck_sandbox_networking_status"
DESIRED_GENERATION_CONSTRAINT = "ck_sandbox_desired_network_policy_generation"
APPLIED_GENERATION_CONSTRAINT = "ck_sandbox_applied_network_policy_generation"
READY_GENERATION_CONSTRAINT = "ck_sandbox_ready_network_policy_generation"

KNOWN_STATUSES = ("disabled", "pending", "ready", "nacked", "failed")


def _invalid_state_counts(connection) -> dict[str, int]:
    row = connection.execute(
        sa.text(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE networking_status NOT IN ('disabled', 'pending', 'ready', 'nacked', 'failed')
              ) AS unknown_status,
              COUNT(*) FILTER (
                WHERE NOT (
                  (networking_policy_hash IS NULL AND networking_policy_version = 0)
                  OR (
                    networking_policy_hash IS NOT NULL
                    AND length(btrim(networking_policy_hash)) > 0
                    AND networking_policy_version > 0
                  )
                )
              ) AS invalid_desired_generation,
              COUNT(*) FILTER (
                WHERE NOT (
                  (networking_applied_hash IS NULL AND networking_applied_version IS NULL)
                  OR (
                    networking_applied_hash IS NOT NULL
                    AND length(btrim(networking_applied_hash)) > 0
                    AND networking_applied_version > 0
                  )
                )
              ) AS invalid_applied_generation,
              COUNT(*) FILTER (
                WHERE networking_status = 'ready'
                  AND NOT (
                    networking_policy_hash IS NOT NULL
                    AND networking_applied_hash IS NOT NULL
                    AND networking_policy_version > 0
                    AND networking_applied_version > 0
                    AND networking_policy_hash = networking_applied_hash
                    AND networking_policy_version = networking_applied_version
                  )
              ) AS invalid_ready_generation
            FROM joysafeter_sandboxes
            """
        )
    ).mappings().one()
    return {name: int(value or 0) for name, value in row.items()}


def upgrade() -> None:
    connection = op.get_bind()
    invalid_counts = _invalid_state_counts(connection)
    violations = {name: count for name, count in invalid_counts.items() if count}
    if violations:
        summary = ", ".join(f"{name}={count}" for name, count in sorted(violations.items()))
        raise RuntimeError(
            "invalid sandbox network-policy state; run "
            "scripts/audit_network_policy_generations.py --repair before migration: "
            f"{summary}"
        )

    op.drop_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.create_check_constraint(
        NETWORKING_STATUS_CONSTRAINT,
        "joysafeter_sandboxes",
        "networking_status IN ('disabled', 'pending', 'ready', 'nacked', 'failed')",
    )
    op.create_check_constraint(
        DESIRED_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        "(networking_policy_hash IS NULL AND networking_policy_version = 0) OR "
        "(networking_policy_hash IS NOT NULL AND length(btrim(networking_policy_hash)) > 0 "
        "AND networking_policy_version > 0)",
    )
    op.create_check_constraint(
        APPLIED_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        "(networking_applied_hash IS NULL AND networking_applied_version IS NULL) OR "
        "(networking_applied_hash IS NOT NULL AND length(btrim(networking_applied_hash)) > 0 "
        "AND networking_applied_version > 0)",
    )
    op.create_check_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        "networking_status <> 'ready' OR "
        "(networking_policy_hash IS NOT NULL AND networking_applied_hash IS NOT NULL "
        "AND networking_policy_version > 0 AND networking_applied_version > 0 "
        "AND networking_policy_hash = networking_applied_hash "
        "AND networking_policy_version = networking_applied_version)",
    )


def downgrade() -> None:
    op.drop_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.drop_constraint(
        APPLIED_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.drop_constraint(
        DESIRED_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.drop_constraint(
        NETWORKING_STATUS_CONSTRAINT,
        "joysafeter_sandboxes",
        type_="check",
    )
    op.create_check_constraint(
        READY_GENERATION_CONSTRAINT,
        "joysafeter_sandboxes",
        "networking_status <> 'ready' OR "
        "(networking_applied_hash IS NOT DISTINCT FROM networking_policy_hash "
        "AND networking_applied_version IS NOT DISTINCT FROM networking_policy_version)",
    )
