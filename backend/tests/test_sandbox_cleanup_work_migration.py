from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "backend/alembic/versions/20260901_000002_sandbox_cleanup_work.py"


def test_sandbox_cleanup_work_migration_is_complete() -> None:
    source = MIGRATION.read_text()

    assert 'revision: str = "20260901_000002"' in source
    assert 'down_revision: Union[str, None] = "20260901_000001"' in source
    assert "joysafeter_sandbox_cleanup_work" in source
    assert "uq_sandbox_cleanup_resource" in source
    assert "idx_sandbox_cleanup_due" in source
    assert "claim_expires_at" in source
    assert "next_attempt_at" in source
