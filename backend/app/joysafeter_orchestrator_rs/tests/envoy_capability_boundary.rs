use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn process_supervisor_owns_only_container_lifecycle_and_health() {
    let process = source("src/sandbox/envoy/process.rs");
    assert!(process.contains("pub struct EnvoyProcessSupervisor"));
    assert!(process.contains("spawn_health_monitor"));
    assert!(process.contains("restart"));
    for forbidden in [
        "EnvoyDelivery",
        "NetworkPolicyRuntime",
        "SandboxEgressPolicy",
        "sandbox_apply_locks",
    ] {
        assert!(!process.contains(forbidden), "process owns {forbidden}");
    }
}

#[test]
fn socket_provisioner_owns_socket_storage_without_policy_delivery() {
    let socket = source("src/sandbox/envoy/socket.rs");
    assert!(socket.contains("pub struct EgressSocketProvisioner"));
    assert!(socket.contains("impl SandboxSocketProvisioner"));
    assert!(socket.contains("wait_for_socket_ready"));
    for forbidden in [
        "EnvoyDelivery",
        "NetworkPolicyRuntime",
        "SandboxEgressPolicy",
        "RestartContainerOptions",
        "spawn_health_monitor",
    ] {
        assert!(!socket.contains(forbidden), "socket owns {forbidden}");
    }
}

#[test]
fn policy_runtime_owns_delivery_and_per_sandbox_serialization_only() {
    let policy = source("src/sandbox/envoy/policy_runtime.rs");
    assert!(policy.contains("pub struct EnvoyNetworkPolicyRuntime"));
    assert!(policy.contains("sandbox_apply_locks"));
    assert!(policy.contains("EnvoyDelivery"));
    for forbidden in [
        "CreateContainerOptions",
        "RestartContainerOptions",
        "inspect_container",
        "start_container",
    ] {
        assert!(!policy.contains(forbidden), "policy owns {forbidden}");
    }
}

#[test]
fn runtime_components_expose_capabilities_not_envoy_manager() {
    let registry = source("src/bootstrap/registry.rs");
    assert!(!registry.contains("EnvoyManager"));
    assert!(registry.contains("EnvoyProcessSupervisor"));
    assert!(registry.contains("SandboxSocketProvisioner"));
    assert!(registry.contains("NetworkPolicyRuntime"));
}
