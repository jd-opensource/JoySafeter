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
