"""add skill_collaborators, skill_versions, skill_version_files, platform_tokens tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-21 00:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- 1. collaborator_role enum type --
    collaborator_role = postgresql.ENUM(
        "viewer", "editor", "publisher", "admin",
        name="collaborator_role",
        create_type=False,
    )
    collaborator_role.create(op.get_bind(), checkfirst=True)

    # -- 2. skill_collaborators --
    op.create_table(
        "skill_collaborators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", collaborator_role, nullable=False),
        sa.Column("invited_by", sa.String(255),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "user_id",
                            name="skill_collaborators_skill_user_unique"),
    )
    op.create_index("skill_collaborators_user_skill_idx",
                     "skill_collaborators", ["user_id", "skill_id"])

    # -- 3. skill_versions --
    op.create_table(
        "skill_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("release_notes", sa.Text, nullable=True),
        sa.Column("skill_name", sa.String(64), nullable=False),
        sa.Column("skill_description", sa.String(1024), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("allowed_tools", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("compatibility", sa.String(500), nullable=True),
        sa.Column("license", sa.String(100), nullable=True),
        sa.Column("published_by_id", sa.String(255),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "version",
                            name="skill_versions_skill_version_unique"),
    )
    op.create_index("skill_versions_skill_idx",
                     "skill_versions", ["skill_id"])
    op.create_index("skill_versions_published_at_idx",
                     "skill_versions", ["published_at"])

    # -- 4. skill_version_files --
    op.create_table(
        "skill_version_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("storage_type", sa.String(20), nullable=False, server_default="database"),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("skill_version_files_version_idx",
                     "skill_version_files", ["version_id"])

    # -- 5. platform_tokens --
    op.create_table(
        "platform_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("platform_tokens_user_idx",
                     "platform_tokens", ["user_id"])
    op.create_index("platform_tokens_hash_idx",
                     "platform_tokens", ["token_hash"])
    op.create_index("platform_tokens_active_idx",
                     "platform_tokens", ["is_active"])


def downgrade() -> None:
    op.drop_table("platform_tokens")
    op.drop_table("skill_version_files")
    op.drop_table("skill_versions")
    op.drop_table("skill_collaborators")
    sa.Enum(name="collaborator_role").drop(op.get_bind(), checkfirst=True)
