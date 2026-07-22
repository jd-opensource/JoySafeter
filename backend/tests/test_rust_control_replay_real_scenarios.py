import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "backend" / "app" / "joysafeter_orchestrator_rs"


def _rust_database_url(postgres_url: str) -> str:
    return postgres_url.replace("postgresql+asyncpg://", "postgres://")


@pytest.mark.asyncio
async def test_rust_control_replay_real_postgres_scenarios(postgres_url):
    env = os.environ.copy()
    env["DATABASE_URL"] = _rust_database_url(postgres_url)

    result = subprocess.run(
        [
            "cargo",
            "test",
            "--manifest-path",
            str(ORCHESTRATOR / "Cargo.toml"),
            "grpc::server::tests::",
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

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "pending_control_replay_marks_processed_only_after_send_succeeds" in output
    assert "send_setup_waits_for_late_session_link_before_marking_done" in output
    assert "test result: ok." in output
