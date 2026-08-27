"""Model-level smoke tests for skill usage-log and version schema.

Verifies SQLAlchemy mapping for the two new shapes:

  - ``SkillUsageLog`` (joysafeter_skill_usage_log table)
  - ``SkillVersion`` new fields (security_scan_id, target_hash,
    lifecycle_status, approved_by_id, approved_at)

These tests pin the column types and nullability so an accidental
``Optional`` flip in a future model edit fails the suite. They do not
exercise inserts (the migration tests cover that the table is created
correctly; CRUD round-trip belongs to integration suites).
"""

from __future__ import annotations

import pytest

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog as SkillUsageLog
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillVersion as SkillVersion

pytestmark = pytest.mark.no_db

# ── SkillUsageLog ─────────────────────────────────────────────


def test_usage_log_table_name():
    assert SkillUsageLog.__tablename__ == "joysafeter_skill_usage_log"


def test_usage_log_columns_and_nullability():
    """Every audit row identifies the concrete published version loaded.

    Request context ids remain nullable because not every execution has a
    user-facing session or actor.
    """
    cols = {c.name: c for c in SkillUsageLog.__table__.columns}
    expected_nullable = {
        "id": False,
        "created_at": False,
        "updated_at": False,
        "skill_id": True,
        "skill_version": False,
        "session_id": True,
        "agent_id": True,
        "project_id": True,
        "user_id": True,
    }
    for name, expected in expected_nullable.items():
        assert cols[name].nullable is expected, (name, cols[name].nullable)


def test_usage_log_indexes_cover_hot_queries():
    """Three hot queries each get a composite index that allows a cheap
    range scan: by-session, by-skill, by-project — each paired with
    created_at for time-window slicing."""
    names = {i.name for i in SkillUsageLog.__table__.indexes}
    assert "skill_usage_log_session_created_idx" in names
    assert "skill_usage_log_skill_created_idx" in names
    assert "skill_usage_log_project_created_idx" in names


# ── SkillVersion lifecycle and security fields ────────────────


def test_skill_version_has_lifecycle_and_security_fields():
    cols = {c.name for c in SkillVersion.__table__.columns}
    for field in (
        "security_scan_id",
        "target_hash",
        "lifecycle_status",
        "approved_by_id",
        "approved_at",
    ):
        assert field in cols, f"missing field: {field}"


def test_skill_version_lifecycle_default_is_approved():
    """Versions are always created from an approved publish action;
    the default needs to be ``approved`` so existing publish flows
    keep working without explicitly setting the field."""
    col = SkillVersion.__table__.c.lifecycle_status
    assert col.nullable is False
    assert col.default is not None
    assert col.default.arg == "approved"


def test_skill_version_security_fields_are_nullable():
    """The four security/approval fields stay NULL until a version is
    associated with a scan or reviewed — gradual rollout requires it."""
    cols = SkillVersion.__table__.c
    assert cols.security_scan_id.nullable is True
    assert cols.target_hash.nullable is True
    assert cols.approved_by_id.nullable is True
    assert cols.approved_at.nullable is True
