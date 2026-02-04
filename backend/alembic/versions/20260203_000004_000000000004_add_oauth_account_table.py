"""add_oauth_account_table

Revision ID: 000000000004
Revises: 000000000003
Create Date: 2026-02-03 00:00:00.000000+00:00

添加 OAuth 账户关联表，支持 GitHub、Google 及自定义 OIDC 提供商登录。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000004"
down_revision: Union[str, None] = "000000000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 oauth_account 表
    op.create_table(
        "oauth_account",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_account_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_userinfo", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # 创建唯一索引：确保同一提供商的同一账户只能绑定一个用户
    op.create_index(
        "ix_oauth_account_provider_account",
        "oauth_account",
        ["provider", "provider_account_id"],
        unique=True,
    )

    # 创建用户索引：加速按用户查询
    op.create_index(
        "ix_oauth_account_user_id",
        "oauth_account",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_account_user_id", table_name="oauth_account")
    op.drop_index("ix_oauth_account_provider_account", table_name="oauth_account")
    op.drop_table("oauth_account")
