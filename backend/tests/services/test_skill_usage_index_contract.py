from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


MIGRATION = Path("alembic/versions/20260720_000001_skill_usage_artifact_audit.py")


def test_skill_usage_security_response_indexes_are_migrated():
    sql_source = MIGRATION.read_text()
    expected = {
        "skill_usage_log_artifact_hash_idx",
        "skill_usage_log_target_hash_idx",
        "skill_usage_log_security_scan_idx",
        "skill_usage_log_project_artifact_created_idx",
        "skill_usage_log_project_target_created_idx",
        "skill_usage_log_project_scan_created_idx",
    }

    missing = [name for name in sorted(expected) if name not in sql_source]
    assert not missing, f"missing usage-log indexes in migration: {missing}"

    for name in expected:
        assert sql_source.count(name) >= 2, f"{name} must be present in upgrade and downgrade"
