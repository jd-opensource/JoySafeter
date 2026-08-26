"""Replace polymorphic environment references with native UUID links.

Revision ID: 20260825_000004
Revises: 20260825_000003
Create Date: 2026-08-25 00:00:04.000000
"""

from __future__ import annotations

from typing import Optional, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_000004"
down_revision: Union[str, None] = "20260825_000003"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

ENVIRONMENT_LINK_TABLES = (
    "joysafeter_agents",
    "joysafeter_sessions",
    "joysafeter_triggers",
)

ENVIRONMENT_FOREIGN_KEYS = {
    "joysafeter_agents": "fk_joysafeter_agents_environment_id",
    "joysafeter_sessions": "fk_joysafeter_sessions_environment_id",
    "joysafeter_triggers": "fk_joysafeter_triggers_environment_id",
}

ENVIRONMENT_INDEXES = {
    "joysafeter_agents": "ix_joysafeter_agents_environment_id",
    "joysafeter_sessions": "ix_joysafeter_sessions_environment_id",
    "joysafeter_triggers": "ix_joysafeter_triggers_environment_id",
}


def resolve_reference_sql(reference_expression: str, project_expression: str) -> str:
    normalized_reference = f"NULLIF(btrim({reference_expression}), '')"
    return f"""
        SELECT environment.id
        FROM joysafeter_environments AS environment
        WHERE environment.project_id IS NOT DISTINCT FROM {project_expression}
          AND environment.deleted_at IS NULL
          AND (
              environment.name = {normalized_reference}
              OR 'env_' || environment.id::text = {normalized_reference}
          )
    """.strip()


def raise_for_resolution_failures(failures: list[tuple[str, int]]) -> None:
    if not failures:
        return
    details = "; ".join(f"{table}: {count} unresolved environment references" for table, count in failures)
    raise RuntimeError(f"environment ID migration preflight failed: {details}")


def snapshot_rewrite_sql(*, table: str, json_column: str, environment_id_expression: str = "environment_id") -> str:
    return f"""
        UPDATE {table}
        SET {json_column} = ({json_column} - 'environment_ref') ||
            CASE
                WHEN {environment_id_expression} IS NULL THEN '{{}}'::jsonb
                ELSE jsonb_build_object('environment_id', 'env_' || {environment_id_expression}::text)
            END
        WHERE {json_column} IS NOT NULL
    """.strip()


def _non_empty(expression: str) -> str:
    return f"NULLIF(btrim({expression}), '')"


def _resolution_failure_count_sql(*, source_sql: str, reference_expression: str, project_expression: str) -> str:
    resolution_sql = resolve_reference_sql(reference_expression, project_expression)
    return f"""
        SELECT count(*)
        FROM {source_sql}
        WHERE {_non_empty(reference_expression)} IS NOT NULL
          AND (SELECT count(*) FROM ({resolution_sql}) AS matches) <> 1
    """.strip()


def _resolved_environment_id(reference_expression: str, project_expression: str) -> str:
    return f"({resolve_reference_sql(reference_expression, project_expression)})"


def _preflight_and_populate_links() -> None:
    connection = op.get_bind()
    failures: list[tuple[str, int]] = []

    agent_failures = connection.execute(
        sa.text(
            _resolution_failure_count_sql(
                source_sql="joysafeter_agents AS source",
                reference_expression="source.environment_ref",
                project_expression="source.project_id",
            )
        )
    ).scalar_one()
    if agent_failures:
        failures.append(("joysafeter_agents", agent_failures))

    connection.execute(
        sa.text(
            f"""
            UPDATE joysafeter_agents AS source
            SET environment_id = {_resolved_environment_id("source.environment_ref", "source.project_id")}
            WHERE {_non_empty("source.environment_ref")} IS NOT NULL
            """
        )
    )

    trigger_reference = (
        "COALESCE(NULLIF(btrim(source.environment_ref), ''), "
        "CASE WHEN agent.environment_id IS NULL THEN NULL ELSE 'env_' || agent.environment_id::text END)"
    )
    trigger_source = "joysafeter_triggers AS source JOIN joysafeter_agents AS agent ON agent.id = source.agent_id"
    trigger_failures = connection.execute(
        sa.text(
            _resolution_failure_count_sql(
                source_sql=trigger_source,
                reference_expression=trigger_reference,
                project_expression="source.project_id",
            )
        )
    ).scalar_one()
    if trigger_failures:
        failures.append(("joysafeter_triggers", trigger_failures))

    connection.execute(
        sa.text(
            f"""
            UPDATE joysafeter_triggers AS source
            SET environment_id = {_resolved_environment_id(trigger_reference, "source.project_id")}
            FROM joysafeter_agents AS agent
            WHERE agent.id = source.agent_id
              AND {_non_empty(trigger_reference)} IS NOT NULL
            """
        )
    )

    session_reference = (
        "COALESCE(NULLIF(btrim(source.environment_ref), ''), "
        "NULLIF(btrim(source.agent_snapshot->>'environment_ref'), ''), "
        "CASE WHEN agent.environment_id IS NULL THEN NULL ELSE 'env_' || agent.environment_id::text END)"
    )
    session_source = "joysafeter_sessions AS source JOIN joysafeter_agents AS agent ON agent.id = source.agent_id"
    session_failures = connection.execute(
        sa.text(
            _resolution_failure_count_sql(
                source_sql=session_source,
                reference_expression=session_reference,
                project_expression="source.project_id",
            )
        )
    ).scalar_one()
    if session_failures:
        failures.append(("joysafeter_sessions", session_failures))

    connection.execute(
        sa.text(
            f"""
            UPDATE joysafeter_sessions AS source
            SET environment_id = {_resolved_environment_id(session_reference, "source.project_id")}
            FROM joysafeter_agents AS agent
            WHERE agent.id = source.agent_id
              AND {_non_empty(session_reference)} IS NOT NULL
            """
        )
    )

    version_reference = "source.snapshot->>'environment_ref'"
    version_source = "joysafeter_agent_versions AS source JOIN joysafeter_agents AS agent ON agent.id = source.agent_id"
    version_failures = connection.execute(
        sa.text(
            _resolution_failure_count_sql(
                source_sql=version_source,
                reference_expression=version_reference,
                project_expression="agent.project_id",
            )
        )
    ).scalar_one()
    if version_failures:
        failures.append(("joysafeter_agent_versions.snapshot", version_failures))

    raise_for_resolution_failures(failures)


def _rewrite_snapshots() -> None:
    op.execute(
        snapshot_rewrite_sql(
            table="joysafeter_sessions",
            json_column="agent_snapshot",
        )
    )
    op.execute(
        f"""
        UPDATE joysafeter_agent_versions AS source
        SET snapshot = (source.snapshot - 'environment_ref') ||
            CASE
                WHEN {_non_empty("source.snapshot->>'environment_ref'")} IS NULL THEN '{{}}'::jsonb
                ELSE jsonb_build_object(
                    'environment_id',
                    'env_' || {_resolved_environment_id("source.snapshot->>'environment_ref'", "agent.project_id")}::text
                )
            END
        FROM joysafeter_agents AS agent
        WHERE agent.id = source.agent_id
        """
    )


def upgrade() -> None:
    for table in ENVIRONMENT_LINK_TABLES:
        op.add_column(table, sa.Column("environment_id", sa.Uuid(), nullable=True))

    _preflight_and_populate_links()
    _rewrite_snapshots()

    for table in ENVIRONMENT_LINK_TABLES:
        op.create_foreign_key(
            ENVIRONMENT_FOREIGN_KEYS[table],
            table,
            "joysafeter_environments",
            ["environment_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(ENVIRONMENT_INDEXES[table], table, ["environment_id"])
        op.drop_column(table, "environment_ref")


def downgrade() -> None:
    for table in ENVIRONMENT_LINK_TABLES:
        op.add_column(table, sa.Column("environment_ref", sa.Text(), nullable=True))
        op.execute(
            f"""
            UPDATE {table}
            SET environment_ref = CASE
                WHEN environment_id IS NULL THEN NULL
                ELSE 'env_' || environment_id::text
            END
            """
        )

    op.execute(
        """
        UPDATE joysafeter_sessions
        SET agent_snapshot = (agent_snapshot - 'environment_id') ||
            CASE
                WHEN environment_id IS NULL THEN '{}'::jsonb
                ELSE jsonb_build_object('environment_ref', 'env_' || environment_id::text)
            END
        WHERE agent_snapshot IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE joysafeter_agent_versions
        SET snapshot = (snapshot - 'environment_id') ||
            CASE
                WHEN snapshot->>'environment_id' IS NULL THEN '{}'::jsonb
                ELSE jsonb_build_object('environment_ref', snapshot->>'environment_id')
            END
        """
    )

    for table in reversed(ENVIRONMENT_LINK_TABLES):
        op.drop_index(ENVIRONMENT_INDEXES[table], table_name=table)
        op.drop_constraint(ENVIRONMENT_FOREIGN_KEYS[table], table, type_="foreignkey")
        op.drop_column(table, "environment_id")
