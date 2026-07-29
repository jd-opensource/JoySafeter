"""repair project members schema for pre-squash local databases

Revision ID: 20260707_000003
Revises: 20260707_000002
Create Date: 2026-07-07 00:00:03.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260707_000003"
down_revision: Union[str, None] = "20260707_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Local DBs created before the project-scoped ACL migration can be stamped
    # at the squashed revision while missing this table. Skill listing joins it
    # for project-level visibility, so repair it without dropping existing data.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_project_members (
            id VARCHAR(255) NOT NULL PRIMARY KEY,
            project_id VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'member',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS id VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS project_id VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS user_id VARCHAR(255)")
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS role VARCHAR(50)")
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
    op.execute("ALTER TABLE joysafeter_project_members ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

    op.execute("UPDATE joysafeter_project_members SET role = 'member' WHERE role IS NULL")
    op.execute("UPDATE joysafeter_project_members SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE joysafeter_project_members SET updated_at = now() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE joysafeter_project_members ALTER COLUMN role SET DEFAULT 'member'")
    op.execute("ALTER TABLE joysafeter_project_members ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE joysafeter_project_members ALTER COLUMN updated_at SET DEFAULT now()")

    op.execute(
        """
        INSERT INTO joysafeter_project_members (
            id,
            project_id,
            user_id,
            role,
            created_at,
            updated_at
        )
        SELECT
            'pm_' || md5(projects.id || ':' || members.user_id),
            projects.id,
            members.user_id,
            'member',
            now(),
            now()
        FROM joysafeter_organization_projects AS projects
        JOIN joysafeter_organization_members AS members
          ON members.organization_id = projects.org_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM joysafeter_project_members AS existing
            WHERE existing.project_id = projects.id
              AND existing.user_id = members.user_id
        )
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_joysafeter_project_members_project_user'
            ) THEN
                ALTER TABLE joysafeter_project_members
                ADD CONSTRAINT uq_joysafeter_project_members_project_user
                UNIQUE (project_id, user_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_project_members_project_id_joysafeter_organization_projects'
            ) THEN
                ALTER TABLE joysafeter_project_members
                ADD CONSTRAINT fk_joysafeter_project_members_project_id_joysafeter_organization_projects
                FOREIGN KEY (project_id)
                REFERENCES joysafeter_organization_projects(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_joysafeter_project_members_user_id_joysafeter_users'
            ) THEN
                ALTER TABLE joysafeter_project_members
                ADD CONSTRAINT fk_joysafeter_project_members_user_id_joysafeter_users
                FOREIGN KEY (user_id)
                REFERENCES joysafeter_users(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_joysafeter_project_members_project_id "
        "ON joysafeter_project_members (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_joysafeter_project_members_user_id "
        "ON joysafeter_project_members (user_id)"
    )


def downgrade() -> None:
    # Forward-only local schema repair.
    pass
