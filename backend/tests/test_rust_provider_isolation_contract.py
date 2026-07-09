from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_provider_isolation_minimum_is_configured_and_enforced_at_startup():
    config = _read("backend/app/joysafeter_orchestrator_rs/src/config.rs")
    main = _read("backend/app/joysafeter_orchestrator_rs/src/main.rs")

    assert "sandbox_min_isolation_class" in config
    assert "JOYSAFETER_SANDBOX_MIN_ISOLATION_CLASS" in config
    assert "provider_isolation_rank" in config
    assert '"" | "docker" => Some(1)' in config
    assert '"daytona" => Some(2)' in config
    assert '"e2b" => Some(3)' in config
    assert "validate_provider_isolation" in config
    assert "does not satisfy JOYSAFETER_SANDBOX_MIN_ISOLATION_CLASS" in config

    assert "config.validate_provider_isolation()?" in main
    assert "sandbox_min_isolation_class" in main


def test_python_settings_and_env_example_expose_provider_isolation_minimum():
    settings = _read("backend/app/joysafeter_shared/config/settings.py")
    env_example = _read("backend/env.example")

    assert 'sandbox_min_isolation_class: str = "shared_container"' in settings
    assert "JOYSAFETER_SANDBOX_MIN_ISOLATION_CLASS=shared_container" in env_example
    assert "shared_container | remote_workspace | isolated_vm" in env_example

