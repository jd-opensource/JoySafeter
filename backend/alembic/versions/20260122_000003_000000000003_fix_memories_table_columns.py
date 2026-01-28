"""fix_memories_table_columns

Revision ID: 000000000003
Revises: 000000000002
Create Date: 2026-01-22 00:00:03.000000+00:00

修复 memories 表缺失的列：
- 添加 memory 列（JSON，NOT NULL）
- 添加 topics 列（JSON，nullable）
如果列已存在则跳过
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000000000003"
down_revision: Union[str, None] = "000000000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加缺失的 memory 和 topics 列到 memories 表"""
    # 使用 DO 块安全地检查并添加列
    op.execute("""
        DO $$
        BEGIN
            -- 检查并添加 memory 列
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'memory'
            ) THEN
                -- 如果表中有数据，先添加为可空列，然后设置默认值
                ALTER TABLE memories ADD COLUMN memory JSON;
                -- 为现有记录设置默认值（空 JSON 对象）
                UPDATE memories SET memory = '{}'::json WHERE memory IS NULL;
                -- 设置为 NOT NULL
                ALTER TABLE memories ALTER COLUMN memory SET NOT NULL;
            END IF;

            -- 检查并添加 topics 列
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'topics'
            ) THEN
                ALTER TABLE memories ADD COLUMN topics JSON;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """移除 memory 和 topics 列（仅在存在时）"""
    op.execute("""
        DO $$
        BEGIN
            -- 移除 topics 列（如果存在）
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'topics'
            ) THEN
                ALTER TABLE memories DROP COLUMN topics;
            END IF;

            -- 移除 memory 列（如果存在）
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'memories' AND column_name = 'memory'
            ) THEN
                ALTER TABLE memories DROP COLUMN memory;
            END IF;
        END $$;
    """)
