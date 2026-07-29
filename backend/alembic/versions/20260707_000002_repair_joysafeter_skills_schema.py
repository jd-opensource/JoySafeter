"""repair joysafeter skill schema for pre-squash local databases

Revision ID: 20260707_000002
Revises: 20260707_000001
Create Date: 2026-07-07 00:00:02.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260707_000002"
down_revision: Union[str, None] = "20260707_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_skill_tables_if_missing() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skills (
            name VARCHAR(64) NOT NULL,
            description VARCHAR(1024) NOT NULL,
            content TEXT NOT NULL,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_type VARCHAR(50) NOT NULL DEFAULT 'local',
            source_url VARCHAR(1024),
            root_path VARCHAR(512),
            owner_id VARCHAR(255),
            created_by_id VARCHAR(255) NOT NULL,
            is_public BOOLEAN NOT NULL DEFAULT false,
            visibility VARCHAR(16) NOT NULL DEFAULT 'private',
            project_id VARCHAR(255),
            license VARCHAR(100),
            compatibility VARCHAR(500),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
            security_status VARCHAR(32) NOT NULL DEFAULT 'not_scanned',
            security_score INTEGER,
            security_severity VARCHAR(32),
            security_recommendation VARCHAR(32),
            security_scanned_at TIMESTAMPTZ,
            security_scan_id UUID,
            security_scan_hash VARCHAR(64),
            security_issues_count INTEGER NOT NULL DEFAULT 0,
            security_critical_count INTEGER NOT NULL DEFAULT 0,
            security_high_count INTEGER NOT NULL DEFAULT 0,
            security_medium_count INTEGER NOT NULL DEFAULT 0,
            security_low_count INTEGER NOT NULL DEFAULT 0,
            lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'draft',
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_files (
            skill_id UUID NOT NULL,
            path VARCHAR(512) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            content TEXT,
            storage_type VARCHAR(20) NOT NULL DEFAULT 'database',
            storage_key VARCHAR(512),
            size INTEGER NOT NULL DEFAULT 0,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_collaborators (
            skill_id UUID NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            role VARCHAR(32) NOT NULL,
            invited_by VARCHAR(255) NOT NULL,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_security_scans (
            skill_id UUID,
            project_id VARCHAR(255),
            owner_id VARCHAR(255),
            created_by_id VARCHAR(255) NOT NULL,
            trigger VARCHAR(32) NOT NULL,
            target_name VARCHAR(128),
            target_hash VARCHAR(64) NOT NULL,
            scanner VARCHAR(64) NOT NULL DEFAULT 'skillspector',
            scanner_version VARCHAR(64),
            ruleset_version VARCHAR(64),
            status VARCHAR(32) NOT NULL,
            score INTEGER,
            severity VARCHAR(32),
            recommendation VARCHAR(32),
            issues_count INTEGER NOT NULL DEFAULT 0,
            critical_count INTEGER NOT NULL DEFAULT 0,
            high_count INTEGER NOT NULL DEFAULT 0,
            medium_count INTEGER NOT NULL DEFAULT 0,
            low_count INTEGER NOT NULL DEFAULT 0,
            report JSONB,
            error_message TEXT,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_versions (
            skill_id UUID NOT NULL,
            version VARCHAR(20) NOT NULL,
            release_notes TEXT,
            skill_name VARCHAR(64) NOT NULL,
            skill_description VARCHAR(1024) NOT NULL,
            content TEXT NOT NULL,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
            compatibility VARCHAR(500),
            license VARCHAR(100),
            published_by_id VARCHAR(255) NOT NULL,
            published_at TIMESTAMPTZ NOT NULL,
            security_scan_id UUID,
            target_hash VARCHAR(64),
            lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'approved',
            approved_by_id VARCHAR(255),
            approved_at TIMESTAMPTZ,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_version_files (
            version_id UUID NOT NULL,
            path VARCHAR(512) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            content TEXT,
            storage_type VARCHAR(20) NOT NULL DEFAULT 'database',
            storage_key VARCHAR(512),
            size INTEGER NOT NULL DEFAULT 0,
            id UUID NOT NULL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS joysafeter_skill_usage_log (
            id UUID NOT NULL PRIMARY KEY,
            skill_id UUID,
            skill_version VARCHAR(64),
            session_id VARCHAR(255),
            agent_id VARCHAR(255),
            project_id VARCHAR(255),
            user_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _repair_skills_columns() -> None:
    columns = [
        ("name", "VARCHAR(64)"),
        ("description", "VARCHAR(1024)"),
        ("content", "TEXT"),
        ("tags", "JSONB"),
        ("source_type", "VARCHAR(50)"),
        ("source_url", "VARCHAR(1024)"),
        ("root_path", "VARCHAR(512)"),
        ("owner_id", "VARCHAR(255)"),
        ("created_by_id", "VARCHAR(255)"),
        ("is_public", "BOOLEAN"),
        ("visibility", "VARCHAR(16)"),
        ("project_id", "VARCHAR(255)"),
        ("license", "VARCHAR(100)"),
        ("compatibility", "VARCHAR(500)"),
        ("metadata", "JSONB"),
        ("allowed_tools", "JSONB"),
        ("security_status", "VARCHAR(32)"),
        ("security_score", "INTEGER"),
        ("security_severity", "VARCHAR(32)"),
        ("security_recommendation", "VARCHAR(32)"),
        ("security_scanned_at", "TIMESTAMPTZ"),
        ("security_scan_id", "UUID"),
        ("security_scan_hash", "VARCHAR(64)"),
        ("security_issues_count", "INTEGER"),
        ("security_critical_count", "INTEGER"),
        ("security_high_count", "INTEGER"),
        ("security_medium_count", "INTEGER"),
        ("security_low_count", "INTEGER"),
        ("lifecycle_status", "VARCHAR(16)"),
        ("created_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ"),
    ]
    for name, sql_type in columns:
        op.execute(f"ALTER TABLE joysafeter_skills ADD COLUMN IF NOT EXISTS {name} {sql_type}")

    op.execute("UPDATE joysafeter_skills SET description = '' WHERE description IS NULL")
    op.execute("UPDATE joysafeter_skills SET content = '' WHERE content IS NULL")
    op.execute("UPDATE joysafeter_skills SET tags = '[]'::jsonb WHERE tags IS NULL")
    op.execute("UPDATE joysafeter_skills SET source_type = 'local' WHERE source_type IS NULL")
    op.execute("UPDATE joysafeter_skills SET is_public = false WHERE is_public IS NULL")
    op.execute(
        """
        UPDATE joysafeter_skills
        SET visibility = CASE WHEN is_public IS TRUE THEN 'public' ELSE 'private' END
        WHERE visibility IS NULL
        """
    )
    op.execute("UPDATE joysafeter_skills SET metadata = '{}'::jsonb WHERE metadata IS NULL")
    op.execute("UPDATE joysafeter_skills SET allowed_tools = '[]'::jsonb WHERE allowed_tools IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_status = 'not_scanned' WHERE security_status IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_issues_count = 0 WHERE security_issues_count IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_critical_count = 0 WHERE security_critical_count IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_high_count = 0 WHERE security_high_count IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_medium_count = 0 WHERE security_medium_count IS NULL")
    op.execute("UPDATE joysafeter_skills SET security_low_count = 0 WHERE security_low_count IS NULL")
    op.execute("UPDATE joysafeter_skills SET lifecycle_status = 'approved' WHERE lifecycle_status IS NULL")
    op.execute("UPDATE joysafeter_skills SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE joysafeter_skills SET updated_at = now() WHERE updated_at IS NULL")

    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN tags SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN source_type SET DEFAULT 'local'")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN is_public SET DEFAULT false")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN visibility SET DEFAULT 'private'")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN metadata SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN allowed_tools SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_status SET DEFAULT 'not_scanned'")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_issues_count SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_critical_count SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_high_count SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_medium_count SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN security_low_count SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN lifecycle_status SET DEFAULT 'draft'")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE joysafeter_skills ALTER COLUMN updated_at SET DEFAULT now()")


def _repair_skill_file_columns() -> None:
    for table, parent_column in (
        ("joysafeter_skill_files", "skill_id"),
        ("joysafeter_skill_version_files", "version_id"),
    ):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {parent_column} UUID")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS path VARCHAR(512)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS file_type VARCHAR(50)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS content TEXT")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS storage_type VARCHAR(20)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS storage_key VARCHAR(512)")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS size INTEGER")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")

        op.execute(f"UPDATE {table} SET storage_type = 'database' WHERE storage_type IS NULL")
        op.execute(f"UPDATE {table} SET size = 0 WHERE size IS NULL")
        op.execute(f"UPDATE {table} SET created_at = now() WHERE created_at IS NULL")
        op.execute(f"UPDATE {table} SET updated_at = now() WHERE updated_at IS NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN storage_type SET DEFAULT 'database'")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN size SET DEFAULT 0")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")


def _repair_auxiliary_columns() -> None:
    scan_columns = [
        ("skill_id", "UUID"),
        ("project_id", "VARCHAR(255)"),
        ("owner_id", "VARCHAR(255)"),
        ("created_by_id", "VARCHAR(255)"),
        ("trigger", "VARCHAR(32)"),
        ("target_name", "VARCHAR(128)"),
        ("target_hash", "VARCHAR(64)"),
        ("scanner", "VARCHAR(64)"),
        ("scanner_version", "VARCHAR(64)"),
        ("ruleset_version", "VARCHAR(64)"),
        ("status", "VARCHAR(32)"),
        ("score", "INTEGER"),
        ("severity", "VARCHAR(32)"),
        ("recommendation", "VARCHAR(32)"),
        ("issues_count", "INTEGER"),
        ("critical_count", "INTEGER"),
        ("high_count", "INTEGER"),
        ("medium_count", "INTEGER"),
        ("low_count", "INTEGER"),
        ("report", "JSONB"),
        ("error_message", "TEXT"),
        ("created_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ"),
    ]
    for name, sql_type in scan_columns:
        op.execute(f"ALTER TABLE joysafeter_skill_security_scans ADD COLUMN IF NOT EXISTS {name} {sql_type}")
    op.execute("UPDATE joysafeter_skill_security_scans SET scanner = 'skillspector' WHERE scanner IS NULL")
    for column in ("issues_count", "critical_count", "high_count", "medium_count", "low_count"):
        op.execute(f"UPDATE joysafeter_skill_security_scans SET {column} = 0 WHERE {column} IS NULL")
        op.execute(f"ALTER TABLE joysafeter_skill_security_scans ALTER COLUMN {column} SET DEFAULT 0")
    op.execute("ALTER TABLE joysafeter_skill_security_scans ALTER COLUMN scanner SET DEFAULT 'skillspector'")

    collaborator_columns = [
        ("skill_id", "UUID"),
        ("user_id", "VARCHAR(255)"),
        ("role", "VARCHAR(32)"),
        ("invited_by", "VARCHAR(255)"),
        ("created_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ"),
    ]
    for name, sql_type in collaborator_columns:
        op.execute(f"ALTER TABLE joysafeter_skill_collaborators ADD COLUMN IF NOT EXISTS {name} {sql_type}")

    version_columns = [
        ("skill_id", "UUID"),
        ("version", "VARCHAR(20)"),
        ("release_notes", "TEXT"),
        ("skill_name", "VARCHAR(64)"),
        ("skill_description", "VARCHAR(1024)"),
        ("content", "TEXT"),
        ("tags", "JSONB"),
        ("metadata", "JSONB"),
        ("allowed_tools", "JSONB"),
        ("compatibility", "VARCHAR(500)"),
        ("license", "VARCHAR(100)"),
        ("published_by_id", "VARCHAR(255)"),
        ("published_at", "TIMESTAMPTZ"),
        ("security_scan_id", "UUID"),
        ("target_hash", "VARCHAR(64)"),
        ("lifecycle_status", "VARCHAR(16)"),
        ("approved_by_id", "VARCHAR(255)"),
        ("approved_at", "TIMESTAMPTZ"),
        ("created_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ"),
    ]
    for name, sql_type in version_columns:
        op.execute(f"ALTER TABLE joysafeter_skill_versions ADD COLUMN IF NOT EXISTS {name} {sql_type}")
    op.execute("UPDATE joysafeter_skill_versions SET tags = '[]'::jsonb WHERE tags IS NULL")
    op.execute("UPDATE joysafeter_skill_versions SET metadata = '{}'::jsonb WHERE metadata IS NULL")
    op.execute("UPDATE joysafeter_skill_versions SET allowed_tools = '[]'::jsonb WHERE allowed_tools IS NULL")
    op.execute("UPDATE joysafeter_skill_versions SET lifecycle_status = 'approved' WHERE lifecycle_status IS NULL")
    op.execute("ALTER TABLE joysafeter_skill_versions ALTER COLUMN tags SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE joysafeter_skill_versions ALTER COLUMN metadata SET DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE joysafeter_skill_versions ALTER COLUMN allowed_tools SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE joysafeter_skill_versions ALTER COLUMN lifecycle_status SET DEFAULT 'approved'")

    usage_columns = [
        ("skill_id", "UUID"),
        ("skill_version", "VARCHAR(64)"),
        ("session_id", "VARCHAR(255)"),
        ("agent_id", "VARCHAR(255)"),
        ("project_id", "VARCHAR(255)"),
        ("user_id", "VARCHAR(255)"),
        ("created_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ"),
    ]
    for name, sql_type in usage_columns:
        op.execute(f"ALTER TABLE joysafeter_skill_usage_log ADD COLUMN IF NOT EXISTS {name} {sql_type}")

    for table in (
        "joysafeter_skill_security_scans",
        "joysafeter_skill_collaborators",
        "joysafeter_skill_versions",
        "joysafeter_skill_usage_log",
    ):
        op.execute(f"UPDATE {table} SET created_at = now() WHERE created_at IS NULL")
        op.execute(f"UPDATE {table} SET updated_at = now() WHERE updated_at IS NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")


def _create_indexes() -> None:
    indexes = [
        "CREATE INDEX IF NOT EXISTS skills_created_by_idx ON joysafeter_skills (created_by_id)",
        "CREATE INDEX IF NOT EXISTS skills_lifecycle_status_idx ON joysafeter_skills (lifecycle_status)",
        "CREATE INDEX IF NOT EXISTS skills_owner_idx ON joysafeter_skills (owner_id)",
        "CREATE INDEX IF NOT EXISTS skills_project_idx ON joysafeter_skills (project_id)",
        "CREATE INDEX IF NOT EXISTS skills_public_idx ON joysafeter_skills (is_public)",
        "CREATE INDEX IF NOT EXISTS skills_security_recommendation_idx ON joysafeter_skills (security_recommendation)",
        "CREATE INDEX IF NOT EXISTS skills_security_severity_idx ON joysafeter_skills (security_severity)",
        "CREATE INDEX IF NOT EXISTS skills_security_status_idx ON joysafeter_skills (security_status)",
        "CREATE INDEX IF NOT EXISTS skills_tags_idx ON joysafeter_skills USING gin (tags)",
        "CREATE INDEX IF NOT EXISTS skills_visibility_idx ON joysafeter_skills (visibility)",
        "CREATE INDEX IF NOT EXISTS skill_files_path_idx ON joysafeter_skill_files (skill_id, path)",
        "CREATE INDEX IF NOT EXISTS skill_files_skill_idx ON joysafeter_skill_files (skill_id)",
        "CREATE INDEX IF NOT EXISTS skill_collaborators_user_skill_idx ON joysafeter_skill_collaborators (user_id, skill_id)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_owner_created_idx ON joysafeter_skill_security_scans (owner_id, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_project_created_idx ON joysafeter_skill_security_scans (project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_recommendation_created_idx ON joysafeter_skill_security_scans (recommendation, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_severity_created_idx ON joysafeter_skill_security_scans (severity, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_skill_created_idx ON joysafeter_skill_security_scans (skill_id, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_status_created_idx ON joysafeter_skill_security_scans (status, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_security_scans_target_hash_idx ON joysafeter_skill_security_scans (target_hash)",
        "CREATE INDEX IF NOT EXISTS skill_versions_lifecycle_status_idx ON joysafeter_skill_versions (lifecycle_status)",
        "CREATE INDEX IF NOT EXISTS skill_versions_published_at_idx ON joysafeter_skill_versions (published_at)",
        "CREATE INDEX IF NOT EXISTS skill_versions_security_scan_idx ON joysafeter_skill_versions (security_scan_id)",
        "CREATE INDEX IF NOT EXISTS skill_versions_skill_idx ON joysafeter_skill_versions (skill_id)",
        "CREATE INDEX IF NOT EXISTS skill_version_files_version_idx ON joysafeter_skill_version_files (version_id)",
        "CREATE INDEX IF NOT EXISTS skill_usage_log_project_created_idx ON joysafeter_skill_usage_log (project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_usage_log_session_created_idx ON joysafeter_skill_usage_log (session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS skill_usage_log_skill_created_idx ON joysafeter_skill_usage_log (skill_id, created_at)",
    ]
    for statement in indexes:
        op.execute(statement)


def upgrade() -> None:
    # Older local databases can be stamped at the squashed initial revision
    # while still carrying pre-P1/P2 skill tables. Repair them forward without
    # deleting data.
    _create_skill_tables_if_missing()
    _repair_skills_columns()
    _repair_skill_file_columns()
    _repair_auxiliary_columns()
    _create_indexes()


def downgrade() -> None:
    # Forward-only local schema repair.
    pass
