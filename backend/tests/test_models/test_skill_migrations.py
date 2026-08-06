"""Alembic smoke tests for the pre-release initial schema.

These don't touch a real database — they exercise alembic's
``--sql`` mode (offline) to confirm:

  1. The migration directory contains one initial revision.
  2. ``base -> head`` creates the current schema directly.
  3. ``head -> base`` removes the current schema.

Running this in CI catches the most common alembic mistake — a new
revision file with the wrong ``down_revision`` — before it lands in a
deployed DB.

We don't shell out to ``alembic`` because alembic is importable; using
the Python API keeps the test self-contained and CI-friendly.
"""

from __future__ import annotations

import io
import uuid
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # alembic.ini's script_location is relative to backend/, so we need to
    # anchor it explicitly when pytest invokes from anywhere.
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.mark.no_db
def test_chain_is_single_initial_revision():
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["20260803_000001"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [revision.revision for revision in revisions] == ["20260803_000001"]
    assert revisions[0].down_revision is None


@pytest.mark.no_db
def test_upgrade_sql_creates_current_schema():
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.upgrade(cfg, "base:head", sql=True)
    sql = buf.getvalue()

    assert "CREATE SEQUENCE joysafeter_task_owner_epoch_seq" in sql
    assert "CREATE TABLE joysafeter_cluster_members" in sql
    assert "CREATE TABLE joysafeter_tasks" in sql
    assert "CREATE TABLE joysafeter_sessions" in sql
    assert "CREATE TABLE joysafeter_triggers" in sql
    assert "CREATE TABLE joysafeter_skills" in sql
    assert "CREATE TABLE joysafeter_skill_versions" in sql
    assert "CREATE TABLE joysafeter_skill_usage_log" in sql
    assert "org_version_id UUID" in sql
    assert "public_version_id UUID" in sql
    assert "review_target_visibility VARCHAR(16)" in sql
    assert "artifact_hash VARCHAR(64)" in sql
    assert "skill_usage_log_session_created_idx" in sql
    assert "skill_usage_log_skill_created_idx" in sql
    assert "skill_usage_log_project_artifact_created_idx" in sql
    assert "skill_usage_log_project_target_created_idx" in sql
    assert "skill_usage_log_project_scan_created_idx" in sql
    assert "uq_joysafeter_triggers_global_name" in sql
    assert "uq_joysafeter_triggers_project_name" in sql
    trigger_sql = sql.split("CREATE TABLE joysafeter_triggers", 1)[1].split(";", 1)[0]
    assert "system_prompt" not in trigger_sql
    assert "joysafeter_schedules" not in sql
    assert "root_path" not in sql
    assert "is_public" not in sql


@pytest.mark.no_db
def test_downgrade_sql_removes_current_schema():
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.downgrade(cfg, "head:base", sql=True)
    sql = buf.getvalue()

    assert "DROP TABLE joysafeter_skill_usage_log" in sql
    assert "DROP TABLE joysafeter_skill_versions" in sql
    assert "DROP TABLE joysafeter_skills" in sql
    assert "DROP TABLE joysafeter_triggers" in sql
    assert "DROP TABLE joysafeter_sessions" in sql
    assert "DROP TABLE joysafeter_tasks" in sql
    assert "DROP TABLE joysafeter_cluster_members" in sql
    assert "DROP SEQUENCE joysafeter_task_owner_epoch_seq" in sql


# ---------------------------------------------------------------------------
# Current Skill schema checks against the migrated Postgres fixture.
# ---------------------------------------------------------------------------


async def _columns(session: AsyncSession, table: str) -> set[str]:
    rows = await session.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_migration_adds_version_pointer_columns(db_session: AsyncSession):
    """org_version_id / public_version_id land on joysafeter_skills and
    review_target_visibility lands on joysafeter_skill_versions after
    upgrade head."""
    skill_cols = await _columns(db_session, "joysafeter_skills")
    assert "org_version_id" in skill_cols
    assert "public_version_id" in skill_cols

    version_cols = await _columns(db_session, "joysafeter_skill_versions")
    assert "review_target_visibility" in version_cols


@pytest.mark.asyncio
async def test_migration_drops_root_path(db_session: AsyncSession):
    """root_path was always NULL with no readers/writers; the migration
    removes it entirely."""
    skill_cols = await _columns(db_session, "joysafeter_skills")
    assert "root_path" not in skill_cols


@pytest.mark.asyncio
async def test_insert_skill_with_null_version_pointers(db_session: AsyncSession):
    """A skill row inserts fine with both version pointers left NULL — the
    columns are nullable FKs, not required."""
    user_id = f"u-{uuid.uuid4()}"
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_users (id, name, email, hashed_password, is_active, email_verified, is_super_user, failed_login_attempts, created_at, updated_at) "
            "VALUES (:id, :name, :email, 'x', true, false, false, 0, now(), now())"
        ),
        {"id": user_id, "name": "migration-test-user", "email": f"{user_id}@example.com"},
    )
    # project_id is NOT NULL (P4), so seed an org + project to satisfy the FK.
    org_id = f"org-{uuid.uuid4()}"
    project_id = f"proj-{uuid.uuid4()}"
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage, created_at, updated_at) "
            "VALUES (:id, 'mig-test-org', :slug, 0, 0, now(), now())"
        ),
        {"id": org_id, "slug": f"org-slug-{uuid.uuid4()}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default, created_at, updated_at) "
            "VALUES (:id, :org_id, 'mig-test-project', :slug, false, now(), now())"
        ),
        {"id": project_id, "org_id": org_id, "slug": f"proj-slug-{uuid.uuid4()}"},
    )
    skill_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_skills "
            "(id, name, description, content, tags, source_type, created_by_id, project_id, "
            " visibility, metadata, allowed_tools, security_status, "
            " security_issues_count, security_critical_count, security_high_count, "
            " security_medium_count, security_low_count, lifecycle_status, "
            " org_version_id, public_version_id, created_at, updated_at) "
            "VALUES (:id, 'n', 'd', 'c', '[]'::jsonb, 'local', :uid, :project_id, "
            " 'project', '{}'::jsonb, '[]'::jsonb, 'not_scanned', "
            " 0, 0, 0, 0, 0, 'draft', NULL, NULL, now(), now())"
        ),
        {"id": skill_id, "uid": user_id, "project_id": project_id},
    )
    await db_session.commit()

    got = await db_session.execute(
        text("SELECT org_version_id, public_version_id FROM joysafeter_skills WHERE id = :id"),
        {"id": skill_id},
    )
    row = got.one()
    assert row[0] is None
    assert row[1] is None
