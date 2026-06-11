"""add provider and protocol to secrets

Revision ID: 20260611_000002
Revises: 20260608_000001
Create Date: 2026-06-11 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260611_000002"
down_revision: Union[str, tuple[str, str], None] = "20260608_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("joysafeter_secrets", sa.Column("provider", sa.String(length=64), nullable=False, server_default="custom"))
    op.add_column("joysafeter_secrets", sa.Column("protocol", sa.String(length=64), nullable=False, server_default="custom"))
    op.create_index("idx_cs_provider_protocol", "joysafeter_secrets", ["provider", "protocol"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_cs_provider_protocol", table_name="joysafeter_secrets")
    op.drop_column("joysafeter_secrets", "protocol")
    op.drop_column("joysafeter_secrets", "provider")
