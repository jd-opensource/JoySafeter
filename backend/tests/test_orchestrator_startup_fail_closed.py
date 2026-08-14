from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


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


def test_multi_k8s_xds_coordination_failure_aborts_startup() -> None:
    main_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/main.rs").read_text()

    assert "multi+k8s xDS leader requested but POD_NAME unset; skipping" not in main_source
    assert "xDS leader: K8s client init failed" not in main_source
    assert 'std::env::var("POD_NAME").map_err' in main_source
    assert "kube::Client::try_default().await.map_err" in main_source


def test_xds_shutdown_stops_reacquisition_and_reconciles_stale_labels() -> None:
    source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/kernel/xds_leader.rs").read_text()

    assert "self.coordinator_task.abort();" in source
    assert "self.election_task.abort();" in source
    assert "let desired_leader = coordinator_election.is_leader();" in source
    assert "&coordinator_client," in source
    assert "&coordinator_namespace," in source
    assert "&coordinator_pod_name," in source
    assert "desired_leader," in source
