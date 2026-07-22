import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "backend" / "app" / "joysafeter_orchestrator_rs"


def _rust_database_url(postgres_url: str) -> str:
    return postgres_url.replace("postgresql+asyncpg://", "postgres://")


@pytest.mark.asyncio
async def test_rust_session_status_real_postgres_scenarios(postgres_url):
    env = os.environ.copy()
    env["DATABASE_URL"] = _rust_database_url(postgres_url)

    result = subprocess.run(
        [
            "cargo",
            "test",
            "--manifest-path",
            str(ORCHESTRATOR / "Cargo.toml"),
            "db::queries::tests::",
            "--",
            "--nocapture",
            "--test-threads=1",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "test result: ok." in output
    assert "event_persister_redelivered_event_id_does_not_consume_next_db_seq" in output
    assert "atomic_session_status_helper_writes_status_event_and_canonical_seq" in output
