"""Alembic offline-SQL smoke tests for the P0+P1 skill migrations.

These don't touch a real database — they exercise alembic's
``--sql`` mode (offline) to confirm:

  1. The migration chain reaches a single head (no branched revisions).
  2. ``20260624_000001 -> head`` generates SQL for every expected step,
     in order.
  3. The downgrade path retraces the same chain.

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


def test_chain_has_single_head():
    """A branched alembic chain produces two heads; surface that early
    before someone discovers it via `alembic upgrade` blowing up on a
    real database."""
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected single head, got {heads}"


def test_chain_includes_expected_skill_revisions():
    """The chain ending at head must contain the current squashed schema and
    every follow-up Skill/managed-resource revision. If a future rebase drops
    one of them, this test catches it."""
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    # Walk backwards from head; collect into a set since the linear
    # chain order is already enforced by alembic itself.
    seen = set()
    for rev in script.walk_revisions(base="base", head=head):
        seen.add(rev.revision)
    expected = {
        "20260627_000001",  # squashed managed-agent schema
        "20260702_000002",  # task idempotency key
        "20260702_000003",  # task lease
        "20260702_000004",  # task owner epoch
        "20260703_000005",  # project task limit
        "20260703_000006",  # project resource limits
        "20260703_000007",  # task submitter identity
        "20260703_000008",  # session message idempotency index
        "20260703_000009",  # cluster members
        "20260703_000010",  # unique active default project
        "20260710_000011",  # schedules
        "20260716_000012",  # project-scoped vault names
        "20260716_000013",  # project-scoped agent/environment names
        "20260717_000014",  # normalize project member roles
        "20260717_000015",  # unique org member
        "20260717_000016",  # unified role vocabulary
        "20260718_000001",  # Skill version pointers / root_path removal
        "20260718_000002",  # single-axis Skill teardown
        "20260720_000001",  # Skill runtime usage audit fields/indexes
    }
    missing = expected - seen
    assert not missing, f"missing revisions: {sorted(missing)}"


def test_upgrade_sql_renders_current_skill_steps():
    """Offline SQL generation exercises every revision's ``upgrade()``
    function. A typo (or PG-only syntax that alembic can't render in
    offline mode) shows up here before hitting a real database."""
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.upgrade(cfg, "base:head", sql=True)
    sql = buf.getvalue()

    # Squashed schema still creates the Skill runtime/audit foundations.
    assert "CREATE TABLE joysafeter_skill_usage_log" in sql
    assert "skill_usage_log_session_created_idx" in sql
    assert "skill_usage_log_skill_created_idx" in sql

    # Skill version pointer + single-axis teardown revisions.
    assert "ADD COLUMN org_version_id" in sql
    assert "ADD COLUMN public_version_id" in sql
    assert "ADD COLUMN review_target_visibility" in sql
    assert "DROP COLUMN root_path" in sql
    assert "DROP TABLE joysafeter_skill_collaborators" in sql
    assert "DROP COLUMN is_public" in sql
    assert "ALTER COLUMN project_id SET NOT NULL" in sql

    # Runtime usage audit follow-up fields + security-response indexes.
    assert "ADD COLUMN skill_version_id" in sql
    assert "ADD COLUMN skill_name" in sql
    assert "ADD COLUMN skill_source_type" in sql
    assert "ADD COLUMN target" in sql
    assert "ADD COLUMN artifact_hash" in sql
    assert "skill_usage_log_project_artifact_created_idx" in sql
    assert "skill_usage_log_project_target_created_idx" in sql
    assert "skill_usage_log_project_scan_created_idx" in sql


def test_downgrade_sql_unwinds_current_skill_steps():
    """Round-trip safety net: every upgrade must have a working
    downgrade. Offline mode lets us verify the SQL is generated;
    actual data-level reversibility is a separate concern (the P1.4
    promote_legacy migration is intentionally one-way and pins that
    with a no-op downgrade)."""
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.downgrade(cfg, "head:base", sql=True)
    sql = buf.getvalue()

    # Each downgrade should be visible in the rendered SQL.
    assert "DROP INDEX skill_usage_log_project_scan_created_idx" in sql
    assert "DROP INDEX skill_usage_log_project_target_created_idx" in sql
    assert "DROP INDEX skill_usage_log_project_artifact_created_idx" in sql
    assert "DROP COLUMN artifact_hash" in sql
    assert "DROP COLUMN skill_name" in sql
    assert "ADD COLUMN root_path" in sql
    assert "ADD COLUMN is_public" in sql
    assert "CREATE TABLE joysafeter_skill_collaborators" in sql
    assert "DROP COLUMN org_version_id" in sql
    assert "DROP COLUMN public_version_id" in sql


# ---------------------------------------------------------------------------
# P1 (single-axis redesign): version pointers on skills + review target on
# versions, and removal of the always-NULL root_path column.
#
# These run against the real migrated Postgres (the ``db_session`` fixture
# spins up a testcontainer and applies ``alembic upgrade head``), so they
# validate the 20260718_000001 migration end-to-end rather than in offline
# SQL.
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
