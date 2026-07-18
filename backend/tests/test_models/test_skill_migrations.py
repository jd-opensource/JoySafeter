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
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command

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


def test_chain_includes_expected_p0_p1_revisions():
    """The chain ending at head must contain every revision we shipped
    in P0 + P1 + P2 in order. If a future rebase drops one of them,
    this test catches it."""
    cfg = _config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    # Walk backwards from head; collect into a set since the linear
    # chain order is already enforced by alembic itself.
    seen = set()
    for rev in script.walk_revisions(base="base", head=head):
        seen.add(rev.revision)
    expected = {
        "20260625_000001",  # P0: ruleset_version
        "20260625_000002",  # P0: lifecycle_status
        "20260625_000003",  # P1: visibility
        "20260625_000004",  # P1: promote legacy
        "20260625_000005",  # P2: skill_usage_log
        "20260625_000006",  # P2: skill_version security fields
        "20260625_000007",  # P2.8: project_members table
    }
    missing = expected - seen
    assert not missing, f"missing revisions: {sorted(missing)}"


def test_upgrade_sql_renders_each_p0_p1_step():
    """Offline SQL generation exercises every revision's ``upgrade()``
    function. A typo (or PG-only syntax that alembic can't render in
    offline mode) shows up here before hitting a real database."""
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.upgrade(cfg, "20260624_000001:head", sql=True)
    sql = buf.getvalue()

    # Each migration's upgrade() should emit a recognizable DDL signature.
    # The list is the same chain as above; we check the SQL is the right
    # SQL, not just that the migration ran.
    assert "ADD COLUMN ruleset_version" in sql
    assert "skill_security_scans_ruleset_version_idx" in sql
    assert "ADD COLUMN lifecycle_status" in sql
    assert "skills_lifecycle_status_idx" in sql
    assert "ADD COLUMN visibility" in sql
    assert "skills_visibility_idx" in sql
    # Backfill statements
    assert "UPDATE joysafeter_skills SET visibility = 'public'" in sql
    assert "UPDATE joysafeter_skills SET visibility = 'project'" in sql
    assert "UPDATE joysafeter_skills SET lifecycle_status = 'approved'" in sql

    # P2 — usage log table + version security fields
    assert "CREATE TABLE joysafeter_skill_usage_log" in sql
    assert "skill_usage_log_session_created_idx" in sql
    assert "skill_usage_log_skill_created_idx" in sql
    assert "ADD COLUMN security_scan_id" in sql  # on skill_versions
    assert "ADD COLUMN target_hash" in sql
    assert "ADD COLUMN lifecycle_status" in sql  # on skill_versions (also matches P0 — both expected)
    assert "ADD COLUMN approved_by_id" in sql
    assert "ADD COLUMN approved_at" in sql

    # P2.8 — project_members table + org-member backfill
    assert "CREATE TABLE joysafeter_project_members" in sql
    assert "ix_joysafeter_project_members_project_id" in sql
    assert "INSERT INTO joysafeter_project_members" in sql


def test_downgrade_sql_unwinds_back_to_p0_baseline():
    """Round-trip safety net: every upgrade must have a working
    downgrade. Offline mode lets us verify the SQL is generated;
    actual data-level reversibility is a separate concern (the P1.4
    promote_legacy migration is intentionally one-way and pins that
    with a no-op downgrade)."""
    cfg = _config()
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.downgrade(cfg, "20260625_000007:20260624_000001", sql=True)
    sql = buf.getvalue()

    # Each downgrade should be visible in the rendered SQL
    assert "DROP COLUMN visibility" in sql
    assert "DROP COLUMN lifecycle_status" in sql
    assert "DROP COLUMN ruleset_version" in sql
    assert "DROP TABLE joysafeter_skill_usage_log" in sql
    assert "DROP COLUMN security_scan_id" in sql
    assert "DROP COLUMN target_hash" in sql
    assert "DROP COLUMN approved_by_id" in sql
    assert "DROP COLUMN approved_at" in sql
    assert "DROP TABLE joysafeter_project_members" in sql


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
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t"
        ),
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
    skill_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO joysafeter_skills "
            "(id, name, description, content, tags, source_type, created_by_id, "
            " is_public, visibility, metadata, allowed_tools, security_status, "
            " security_issues_count, security_critical_count, security_high_count, "
            " security_medium_count, security_low_count, lifecycle_status, "
            " org_version_id, public_version_id, created_at, updated_at) "
            "VALUES (:id, 'n', 'd', 'c', '[]'::jsonb, 'local', :uid, "
            " false, 'private', '{}'::jsonb, '[]'::jsonb, 'not_scanned', "
            " 0, 0, 0, 0, 0, 'draft', NULL, NULL, now(), now())"
        ),
        {"id": skill_id, "uid": user_id},
    )
    await db_session.commit()

    got = await db_session.execute(
        text(
            "SELECT org_version_id, public_version_id FROM joysafeter_skills WHERE id = :id"
        ),
        {"id": skill_id},
    )
    row = got.one()
    assert row[0] is None
    assert row[1] is None
