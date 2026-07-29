"""skill usage artifact audit fields

Revision ID: 20260720_000001
Revises: 20260718_000002
Create Date: 2026-07-20 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_000001"
down_revision: Union[str, None] = "20260718_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_skill_usage_log", sa.Column("skill_version_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("skill_name", sa.String(length=64), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("skill_source_type", sa.String(length=50), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("target", sa.String(length=255), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("security_scan_id", sa.UUID(), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("target_hash", sa.String(length=64), nullable=True))
    op.add_column("joysafeter_skill_usage_log", sa.Column("artifact_hash", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_joysafeter_skill_usage_log_skill_version_id_joysafeter_skill_versions"),
        "joysafeter_skill_usage_log",
        "joysafeter_skill_versions",
        ["skill_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "skill_usage_log_artifact_hash_idx",
        "joysafeter_skill_usage_log",
        ["artifact_hash"],
        unique=False,
    )
    op.create_index(
        "skill_usage_log_target_hash_idx",
        "joysafeter_skill_usage_log",
        ["target_hash"],
        unique=False,
    )
    op.create_index(
        "skill_usage_log_security_scan_idx",
        "joysafeter_skill_usage_log",
        ["security_scan_id"],
        unique=False,
    )
    op.create_index(
        "skill_usage_log_project_artifact_created_idx",
        "joysafeter_skill_usage_log",
        ["project_id", "artifact_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        "skill_usage_log_project_target_created_idx",
        "joysafeter_skill_usage_log",
        ["project_id", "target_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        "skill_usage_log_project_scan_created_idx",
        "joysafeter_skill_usage_log",
        ["project_id", "security_scan_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("skill_usage_log_project_scan_created_idx", table_name="joysafeter_skill_usage_log")
    op.drop_index("skill_usage_log_project_target_created_idx", table_name="joysafeter_skill_usage_log")
    op.drop_index("skill_usage_log_project_artifact_created_idx", table_name="joysafeter_skill_usage_log")
    op.drop_index("skill_usage_log_security_scan_idx", table_name="joysafeter_skill_usage_log")
    op.drop_index("skill_usage_log_target_hash_idx", table_name="joysafeter_skill_usage_log")
    op.drop_index("skill_usage_log_artifact_hash_idx", table_name="joysafeter_skill_usage_log")
    op.drop_constraint(
        op.f("fk_joysafeter_skill_usage_log_skill_version_id_joysafeter_skill_versions"),
        "joysafeter_skill_usage_log",
        type_="foreignkey",
    )
    op.drop_column("joysafeter_skill_usage_log", "artifact_hash")
    op.drop_column("joysafeter_skill_usage_log", "target_hash")
    op.drop_column("joysafeter_skill_usage_log", "security_scan_id")
    op.drop_column("joysafeter_skill_usage_log", "target")
    op.drop_column("joysafeter_skill_usage_log", "skill_source_type")
    op.drop_column("joysafeter_skill_usage_log", "skill_name")
    op.drop_column("joysafeter_skill_usage_log", "skill_version_id")
