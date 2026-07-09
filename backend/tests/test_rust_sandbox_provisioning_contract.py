from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_sandbox_create_config_carries_resource_and_ownership_labels():
    resolver = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs")

    assert "cpu_limit: self.config.sandbox_cpu" in resolver
    assert "memory_limit_mb: self.config.sandbox_memory_mb" in resolver
    assert '"joysafeter.owner_instance_id"' in resolver
    assert "self.config.instance_id.clone()" in resolver
    assert '"joysafeter.created_at_unix"' in resolver
    assert "chrono::Utc::now().timestamp().to_string()" in resolver
    assert '"joysafeter.project_id"' in resolver


def test_orphan_cleanup_has_db_insert_grace_for_recent_provider_sandboxes():
    controller = _read("backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_controller.rs")

    assert "ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS" in controller
    assert "is_recent_uncommitted_provider_sandbox" in controller
    assert '"joysafeter.created_at_unix"' in controller
    assert "Skipping recent provider sandbox with no DB row" in controller
    assert "now_unix - created_at < ORPHAN_PROVIDER_DB_INSERT_GRACE_SECS" in controller

