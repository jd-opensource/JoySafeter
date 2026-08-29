from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def test_envoy_recovery_does_not_ignore_socket_directory_failures() -> None:
    source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs").read_text()

    assert "let _ = self.prepare_socket_dir(sandbox_id).await;" not in source
    assert "self.prepare_socket_dir(sandbox_id).await?;" in source


def test_network_policy_startup_failure_aborts_orchestrator_readiness() -> None:
    application_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/bootstrap/application.rs").read_text()
    envoy_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs").read_text()

    assert "self.manager.init().await?;" in envoy_source
    assert "self.manager.verify_socket_storage_consistency().await" in envoy_source
    assert "network_policy_runtime.initialize().await?;" in application_source
    assert "kernel::network_policy::recovery::recover_as_authority(" in application_source
    assert "ready_flag.store(true, Ordering::Release);" in application_source
    assert application_source.index("network_policy_runtime.initialize().await?;") < application_source.index(
        "ready_flag.store(true, Ordering::Release);"
    )
    assert application_source.index(
        "kernel::network_policy::recovery::recover_as_authority("
    ) < application_source.index("ready_flag.store(true, Ordering::Release);")


def test_multi_k8s_xds_coordination_failure_aborts_startup() -> None:
    application_source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/bootstrap/application.rs").read_text()

    assert "multi+k8s xDS leader requested but POD_NAME unset; skipping" not in application_source
    assert "xDS leader: K8s client init failed" not in application_source
    assert 'std::env::var("POD_NAME").map_err' in application_source
    assert "kube::Client::try_default().await.map_err" in application_source
    assert "multi+k8s gRPC xDS requires POD_NAME" in application_source
    assert "multi+k8s gRPC xDS requires K8s leader coordination" in application_source


def test_xds_shutdown_stops_reacquisition_and_reconciles_stale_labels() -> None:
    source = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/xds/leader.rs").read_text()

    assert "self.coordinator_task.abort();" in source
    assert "self.election_task.abort();" in source
    assert "let lease_held = coordinator_election.is_leader();" in source
    assert "coordinator_xds_service.set_serving(false);" in source
    assert "coordinator_authority.revoke();" in source
    assert "let desired_serving = should_serve_xds(lease_held, coordinator_authority.is_ready());" in source
    assert "&coordinator_client," in source
    assert "&coordinator_namespace," in source
    assert "&coordinator_pod_name," in source
    assert "desired_serving," in source
