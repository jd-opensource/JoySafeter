from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "backend/alembic/versions/20260901_000001_network_policy_retry_metadata.py"


def test_network_policy_retry_metadata_migration_is_complete() -> None:
    source = MIGRATION.read_text()

    assert 'revision: str = "20260901_000001"' in source
    assert 'down_revision: Union[str, None] = "20260831_000001"' in source
    for column in [
        "networking_last_error_code",
        "networking_retryable",
        "networking_retry_count",
        "networking_next_retry_at",
        "error_code",
        "retryable",
    ]:
        assert column in source
    assert "idx_sandbox_networking_retry_due" in source
    assert "ILIKE '%NACK%'" in source
    assert "legacy_unclassified" in source
