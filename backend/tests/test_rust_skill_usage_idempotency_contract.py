from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_INPUT_BUILDER = REPO_ROOT / Path("backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs")


def test_rust_skill_usage_insert_is_idempotent_per_session_artifact():
    source = HARNESS_INPUT_BUILDER.read_text()
    record_fn = source[source.index("async fn record_skill_usage") : source.index("/// Return the highest published")]

    assert "WHERE NOT EXISTS" in record_fn
    assert "existing.skill_id = $2" in record_fn
    assert "existing.skill_version IS NOT DISTINCT FROM $5" in record_fn
    assert "existing.target IS NOT DISTINCT FROM $7" in record_fn
    assert "existing.artifact_hash IS NOT DISTINCT FROM $10" in record_fn
    assert "existing.session_id IS NOT DISTINCT FROM $11" in record_fn
