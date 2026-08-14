from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_envoy_recovery_does_not_ignore_socket_directory_failures() -> None:
    source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs").read_text()

    assert "let _ = self.prepare_socket_dir(sb.id).await;" not in source
    assert "self.prepare_socket_dir(sb.id).await?;" in source


def test_provider_startup_failure_aborts_orchestrator_readiness() -> None:
    main_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/main.rs").read_text()
    docker_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/docker.rs").read_text()

    assert "sandbox_provider.on_startup(&db_pool).await?;" in main_source
    assert "manager.init().await?;" in docker_source
    assert ".recover_from_db(pool, &self.config.llm_egress_allowed_hosts)\n                .await?;" in docker_source
