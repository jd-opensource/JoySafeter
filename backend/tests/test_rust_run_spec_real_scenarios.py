import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "backend" / "app" / "joysafeter_orchestrator_rs"


def _rust_database_url(postgres_url: str) -> str:
    return postgres_url.replace("postgresql+asyncpg://", "postgres://")


@pytest.mark.asyncio
async def test_rust_run_spec_snapshot_real_postgres_scenarios(postgres_url):
    env = os.environ.copy()
    env["DATABASE_URL"] = _rust_database_url(postgres_url)

    result = subprocess.run(
        [
            "cargo",
            "test",
            "--manifest-path",
            str(ORCHESTRATOR / "Cargo.toml"),
            "snapshot",
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
    assert "harness_input_uses_session_execution_snapshot_after_live_config_changes" in output
    assert "harness_input_snapshot_session_file_storage_missing_fails_build" in output
    assert "sandbox_resolver_snapshot_session_file_injection_storage_missing_fails_resolve" in output
    assert "sandbox_resolver_uses_session_snapshot_for_image_network_and_env" in output
    assert "scheduler_auto_session_snapshot_includes_environment_before_live_mutation" in output
    assert "test result: ok." in output
