"""Rename mission_comments to task_activities and update enums.

Revision ID: h1i2j3k4l5m6
Revises: g8h9i0j1k2l3
Create Date: 2026-04-22
"""

revision = "h1i2j3k4l5m6"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # 1. Rename table
    op.rename_table("mission_comments", "task_activities")

    # 2. Rename columns
    op.alter_column("task_activities", "parent_comment_id", new_column_name="parent_activity_id")
    op.alter_column("task_activities", "mission_id", new_column_name="task_id")

    # 3. Rename enum types
    op.execute("ALTER TYPE commentauthortype RENAME TO activityauthortype")
    op.execute("ALTER TYPE commenttype RENAME TO activitytype")

    # 4. Rename indexes
    op.execute("ALTER INDEX IF EXISTS mission_comments_mission_created_idx RENAME TO task_activities_task_created_idx")
    op.execute("ALTER INDEX IF EXISTS mission_comments_workspace_idx RENAME TO task_activities_workspace_idx")
    op.execute("ALTER INDEX IF EXISTS mission_comments_author_idx RENAME TO task_activities_author_idx")
    op.execute("ALTER INDEX IF EXISTS mission_comments_parent_idx RENAME TO task_activities_parent_idx")

    # 5. Rename foreign key constraints
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'task_activities'::regclass
                  AND conname LIKE 'mission_comments%'
            ) LOOP
                EXECUTE 'ALTER TABLE task_activities RENAME CONSTRAINT '
                    || quote_ident(r.conname)
                    || ' TO '
                    || quote_ident(REPLACE(r.conname, 'mission_comments', 'task_activities'));
            END LOOP;
        END $$;
    """)

    # 6. Rename self-referencing FK column name in constraint
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'task_activities'::regclass
                  AND conname LIKE '%parent_comment%'
            ) LOOP
                EXECUTE 'ALTER TABLE task_activities RENAME CONSTRAINT '
                    || quote_ident(r.conname)
                    || ' TO '
                    || quote_ident(REPLACE(r.conname, 'parent_comment', 'parent_activity'));
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # Reverse all renames
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'task_activities'::regclass
                  AND conname LIKE '%parent_activity%'
            ) LOOP
                EXECUTE 'ALTER TABLE task_activities RENAME CONSTRAINT '
                    || quote_ident(r.conname)
                    || ' TO '
                    || quote_ident(REPLACE(r.conname, 'parent_activity', 'parent_comment'));
            END LOOP;
        END $$;
    """)

    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'task_activities'::regclass
                  AND conname LIKE 'task_activities%'
            ) LOOP
                EXECUTE 'ALTER TABLE task_activities RENAME CONSTRAINT '
                    || quote_ident(r.conname)
                    || ' TO '
                    || quote_ident(REPLACE(r.conname, 'task_activities', 'mission_comments'));
            END LOOP;
        END $$;
    """)

    op.execute("ALTER INDEX IF EXISTS task_activities_parent_idx RENAME TO mission_comments_parent_idx")
    op.execute("ALTER INDEX IF EXISTS task_activities_author_idx RENAME TO mission_comments_author_idx")
    op.execute("ALTER INDEX IF EXISTS task_activities_workspace_idx RENAME TO mission_comments_workspace_idx")
    op.execute("ALTER INDEX IF EXISTS task_activities_task_created_idx RENAME TO mission_comments_mission_created_idx")

    op.execute("ALTER TYPE activitytype RENAME TO commenttype")
    op.execute("ALTER TYPE activityauthortype RENAME TO commentauthortype")

    op.alter_column("task_activities", "task_id", new_column_name="mission_id")
    op.alter_column("task_activities", "parent_activity_id", new_column_name="parent_comment_id")
    op.rename_table("task_activities", "mission_comments")
