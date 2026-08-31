use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn xds_owns_its_delivery_generation_contract() {
    let model = source("src/xds/model.rs");
    assert!(model.contains("pub struct DeliveryGeneration"));

    for path in [
        "src/xds/model.rs",
        "src/xds/delivery.rs",
        "src/xds/inventory.rs",
    ] {
        let module = source(path);
        assert!(
            !module.contains("kernel::network_policy::NetworkPolicyGeneration"),
            "{path} depends on the network-policy domain generation"
        );
    }
}

#[test]
fn bootstrap_and_runner_internals_are_not_public_library_modules() {
    let bootstrap = source("src/bootstrap/mod.rs");
    for internal in [
        "pub mod application;",
        "pub mod registry;",
        "pub mod runtime_factories;",
        "pub mod supervisor;",
    ] {
        assert!(!bootstrap.contains(internal), "bootstrap leaks {internal}");
    }
    assert!(bootstrap.contains("pub use application::OrchestratorApplication"));

    let kernel = source("src/kernel/mod.rs");
    assert!(kernel.contains("pub(crate) mod runner;"));
    let grpc = source("src/grpc/mod.rs");
    assert!(grpc.contains("pub(crate) mod transport;"));
}

#[test]
fn bridge_store_is_the_only_runner_ownership_authority() {
    let coordinator = source("src/kernel/redis_coordinator.rs");
    assert!(!coordinator.contains("joysafeter:sandbox_owner:"));
    for legacy_api in [
        "pub async fn register_sandbox(",
        "pub async fn refresh_sandbox(",
        "pub async fn remove_sandbox(",
        "pub async fn get_sandbox_owner(",
    ] {
        assert!(
            !coordinator.contains(legacy_api),
            "RedisCoordinator still exposes duplicate ownership API {legacy_api}"
        );
    }

    let session = source("src/kernel/runner/session.rs");
    let execution = source("src/kernel/runner/execution.rs");
    let cleanup = source("src/kernel/runner/cleanup.rs");
    let failure = source("src/kernel/runner/failure.rs");
    let command_listener = source("src/kernel/command_listener.rs");
    let controller = source("src/kernel/sandbox_controller.rs");

    assert!(!session.contains("coord.register_sandbox("));
    assert!(!execution.contains("coord.refresh_sandbox("));
    assert!(!cleanup.contains("coord.remove_sandbox("));
    assert!(!failure.contains("coordinator.remove_sandbox("));
    assert!(!command_listener.contains("coord.remove_sandbox("));
    assert!(controller.contains("bridge_store.get_owner_instance(sandbox_id)"));
    assert!(!controller.contains("coord.get_sandbox_owner(sandbox_id)"));
}
