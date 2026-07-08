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
from contextlib import redirect_stdout
from pathlib import Path

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
