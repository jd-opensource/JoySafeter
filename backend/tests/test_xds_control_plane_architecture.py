from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_ROOT = REPO_ROOT / "app/joysafeter_orchestrator_rs/src"


def test_xds_control_plane_has_owned_modules() -> None:
    assert not (RUST_ROOT / "network_policy.rs").exists()
    assert (RUST_ROOT / "kernel/network_policy.rs").is_file()
    assert (RUST_ROOT / "kernel/network_policy/application.rs").is_file()
    assert (RUST_ROOT / "kernel/network_policy/authority.rs").is_file()
    assert (RUST_ROOT / "kernel/network_policy/ports.rs").is_file()
    assert (RUST_ROOT / "kernel/network_policy/recovery.rs").is_file()
    assert (RUST_ROOT / "xds/mod.rs").is_file()
    assert (RUST_ROOT / "xds/authority.rs").is_file()
    assert (RUST_ROOT / "xds/authority_worker.rs").is_file()
    assert (RUST_ROOT / "xds/control_plane.rs").is_file()
    assert (RUST_ROOT / "xds/delta.rs").is_file()
    assert (RUST_ROOT / "xds/inventory.rs").is_file()
    assert (RUST_ROOT / "xds/leader.rs").is_file()
    assert (RUST_ROOT / "xds/model.rs").is_file()
    assert (RUST_ROOT / "xds/node_ownership.rs").is_file()
    assert (RUST_ROOT / "xds/resource_store.rs").is_file()
    assert not (RUST_ROOT / "sandbox/envoy_render.rs").exists()
    assert (RUST_ROOT / "sandbox/envoy_render/mod.rs").is_file()
    assert (RUST_ROOT / "sandbox/envoy_render/json.rs").is_file()
    assert (RUST_ROOT / "sandbox/envoy_render/proto.rs").is_file()
    assert (RUST_ROOT / "sandbox/envoy_delivery.rs").is_file()
    assert (RUST_ROOT / "sandbox/envoy_filesystem.rs").is_file()


def test_xds_authority_has_one_lifecycle_owner() -> None:
    authority = (RUST_ROOT / "xds/authority.rs").read_text(encoding="utf-8")
    legacy = RUST_ROOT / "kernel/xds_authority.rs"
    adapter = (RUST_ROOT / "sandbox/envoy_delivery.rs").read_text(encoding="utf-8")

    assert not legacy.exists()
    assert "pub enum AuthorityPhase" in authority
    assert "RecoveryServing" in authority
    assert "pub struct RecoveryAuthorityGuard" in authority
    assert "pub struct MutationAuthorityGuard" in authority
    assert "serving: watch::Sender<bool>" not in adapter
    assert "set_serving" not in adapter


def test_legacy_backend_is_removed_instead_of_kept_as_a_compatibility_facade() -> None:
    legacy = RUST_ROOT / "sandbox/lds_backend.rs"
    adapter = (RUST_ROOT / "sandbox/envoy_delivery.rs").read_text(encoding="utf-8")
    filesystem = (RUST_ROOT / "sandbox/envoy_filesystem.rs").read_text(encoding="utf-8")
    manager = (RUST_ROOT / "sandbox/envoy.rs").read_text(encoding="utf-8")

    assert not legacy.exists()
    assert "pub use super::envoy_render" not in adapter
    assert "pub use super::envoy_filesystem" not in adapter
    assert "pub trait EnvoyDelivery" in adapter
    assert "pub struct ControlPlaneEnvoyDelivery" in adapter
    assert "pub struct FilesystemEnvoyDelivery" in filesystem
    assert "delivery: Arc<dyn EnvoyDelivery>" in manager
    for obsolete_adapter in ("LdsBackend", "CdsBackend", "GrpcLds", "GrpcCds"):
        assert obsolete_adapter not in adapter
        assert obsolete_adapter not in manager
    for unused_operation in (
        "upsert_listeners",
        "upsert_clusters",
        "replace_sandbox_clusters",
    ):
        assert unused_operation not in adapter
        assert unused_operation not in filesystem
    for bypass in ("DeliverySubmission::Unsupported", "remove_clusters", "remove_listeners"):
        assert bypass not in adapter
        assert bypass not in manager


def test_bootstrap_constructs_one_independent_xds_control_plane() -> None:
    main = (RUST_ROOT / "main.rs").read_text(encoding="utf-8")
    application = (RUST_ROOT / "bootstrap/application.rs").read_text(encoding="utf-8")
    control_plane = (RUST_ROOT / "xds/control_plane.rs").read_text(encoding="utf-8")
    transport = (RUST_ROOT / "xds/transport.rs").read_text(encoding="utf-8")

    assert "OrchestratorApplication::build" in main
    assert "XdsControlPlane::new" not in main
    assert application.count("XdsControlPlane::new") == 1
    assert "pub struct XdsControlPlane" in control_plane
    assert "XdsResourceStore" in control_plane
    assert "NodeOwnershipRegistry" in control_plane
    assert "DeltaXdsServer" in control_plane
    assert "service: XdsControlPlane" in transport
    assert "service: Arc<DeltaXdsServer>" not in transport
    assert "pub fn resources(&self)" not in control_plane
    assert "pub fn node_ownership(&self)" not in control_plane
    for bypass in (
        "pub async fn upsert_resources",
        "pub async fn replace_type",
        "pub async fn replace_sandbox_type",
        "pub async fn remove_sandbox_type",
    ):
        assert bypass not in control_plane
        assert bypass not in (RUST_ROOT / "xds/delta.rs").read_text(encoding="utf-8")

    resource_store = (RUST_ROOT / "xds/resource_store.rs").read_text(encoding="utf-8")
    assert "async fn replace_type" not in resource_store


def test_sandbox_adapters_depend_on_control_plane_not_delta_transport() -> None:
    adapter = (RUST_ROOT / "sandbox/envoy_delivery.rs").read_text(encoding="utf-8")
    docker = (RUST_ROOT / "sandbox/docker.rs").read_text(encoding="utf-8")
    kubernetes = (RUST_ROOT / "sandbox/k8s.rs").read_text(encoding="utf-8")

    assert "XdsControlPlane" in adapter
    assert "DeltaXdsServer" not in adapter
    assert "async fn prepare_for_startup" in adapter
    assert "replace_all_listeners" not in adapter
    assert "replace_all_clusters" not in adapter
    assert ".delta_service()" not in docker
    assert ".delta_service()" not in kubernetes


def test_kubernetes_xds_delivery_uses_initialized_pod_boundary() -> None:
    kubernetes = (RUST_ROOT / "sandbox/k8s.rs").read_text(encoding="utf-8")
    watcher = (RUST_ROOT / "sandbox/pod_watcher.rs").read_text(encoding="utf-8")
    placement = (RUST_ROOT / "xds/placement.rs").read_text(encoding="utf-8")
    factories = (RUST_ROOT / "bootstrap/runtime_factories.rs").read_text(
        encoding="utf-8"
    )

    assert "PlacementEventSink" in kubernetes
    assert "XdsControlPlane" not in kubernetes
    assert "PlacementEvent::Assigned" in watcher
    assert "PlacementEvent::Removed" in watcher
    assert "PlacementEvent::Reconciled" in watcher
    assert "PlacementReconciler" in factories
    assert "assign_sandbox_node" in placement
    assert "remove_sandbox_node" in placement
    assert "replace_node_assignments" in placement
    assert "pub async fn node_assignments" not in watcher
    assert "condition.type_ == \"Initialized\"" in watcher


def test_exact_delivery_coordinator_is_the_only_xds_ack_state_machine() -> None:
    delta = (RUST_ROOT / "xds/delta.rs").read_text(encoding="utf-8")
    adapter = (RUST_ROOT / "sandbox/envoy_delivery.rs").read_text(encoding="utf-8")
    envoy = (RUST_ROOT / "sandbox/envoy.rs").read_text(encoding="utf-8")
    policy_runtime = (RUST_ROOT / "sandbox/envoy/policy_runtime.rs").read_text(
        encoding="utf-8"
    )

    for obsolete_symbol in (
        "XdsApplyStatus",
        "apply_status",
        "record_pending",
        "XdsStatusHandle",
        "wait_for_sandbox_ack",
    ):
        assert obsolete_symbol not in delta
        assert obsolete_symbol not in adapter
        assert obsolete_symbol not in envoy

    assert "DeliveryCoordinator" in delta
    assert "NodeSessionId" in delta
    assert "DeliveredResource" in delta
    assert "wait_for_delivery" in adapter
    assert "wait_for_delivery" in policy_runtime
    assert "wait_for_delivery" not in envoy


def test_xds_model_expresses_resource_and_sandbox_ownership() -> None:
    model = (RUST_ROOT / "xds/model.rs").read_text(encoding="utf-8")
    domain = (RUST_ROOT / "kernel/network_policy.rs").read_text(encoding="utf-8")
    repository = (RUST_ROOT / "db/queries/network_policy.rs").read_text(encoding="utf-8")

    assert "crate::db" not in model
    assert "pub struct NetworkPolicyGeneration" not in model
    assert "pub struct NetworkPolicyGeneration" in domain
    assert "crate::kernel::network_policy::NetworkPolicyGeneration" in repository
    assert "crate::xds" not in repository
    assert "pub enum ResourceType" in model
    assert "pub enum ResourceOwner" in model
    assert "pub struct ManagedXdsResource" in model
    assert "pub struct SandboxResourceBundle" in model


def test_network_policy_persistence_has_a_dedicated_typed_repository() -> None:
    repository = RUST_ROOT / "db/queries/network_policy.rs"
    sandbox_repository = (RUST_ROOT / "db/queries/sandbox.rs").read_text(encoding="utf-8")

    assert repository.is_file()
    source = repository.read_text(encoding="utf-8")
    assert "pub enum NetworkPolicyStatus" in source
    assert "pub async fn prepare_generation" in source
    assert "pub async fn retry_generation" in source
    assert "pub async fn mark_generation_applied" in source
    assert "pub async fn record_generation_failure" in source
    assert "pub async fn quarantine_recovery_generation" in source
    assert "pub async fn prepare_recovery_generation" in source
    assert "update_sandbox_networking_status" not in source
    assert "update_sandbox_networking_status" not in sandbox_repository


def test_recovery_builds_and_installs_inventory_before_ads_serving() -> None:
    envoy = (RUST_ROOT / "sandbox/envoy.rs").read_text(encoding="utf-8")
    policy_runtime = (RUST_ROOT / "sandbox/envoy/policy_runtime.rs").read_text(
        encoding="utf-8"
    )
    application = (RUST_ROOT / "bootstrap/application.rs").read_text(encoding="utf-8")
    worker = (RUST_ROOT / "xds/authority_worker.rs").read_text(encoding="utf-8")
    recovery = (RUST_ROOT / "kernel/network_policy/recovery.rs").read_text(
        encoding="utf-8"
    )
    ha = (RUST_ROOT / "kernel/ha/redis_impl.rs").read_text(encoding="utf-8")
    kubernetes = (RUST_ROOT / "sandbox/k8s.rs").read_text(encoding="utf-8")

    assert "install_recovery_inventory" in policy_runtime
    grpc_recovery = policy_runtime[policy_runtime.index("let installed =") :]
    assert grpc_recovery.index("install_recovery_inventory") < grpc_recovery.index(
        "authority.begin_serving()"
    )
    assert "crate::db" not in envoy
    assert "crate::db" not in policy_runtime
    assert "load_recovery_inventory" in recovery
    assert "runtime.recover(" in recovery
    assert recovery.index("runtime.recover(") < recovery.index("mark_generation_applied")
    assert "quarantine_recovery_generation" in recovery
    assert worker.index("work.recover(&guard)") < worker.index("authority.mark_ready(&guard)")
    assert "recover_as_authority" not in ha
    assert "mark_ready" not in ha
    assert "recover_networking" not in kubernetes
    assert "network_policy.recover(&recovery)" in application
