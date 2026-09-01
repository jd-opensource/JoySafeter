use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn command_listener_delegates_destroy_and_never_calls_envoy_directly() {
    let listener = source("src/kernel/command_listener.rs");

    assert!(listener.contains("finalize_claimed_sandbox_destroy"));
    assert!(listener.contains("destroy_unpersisted_sandbox"));
    assert!(!listener.contains("EnvoyManager"));
    assert!(!listener.contains("envoy.remove_sandbox"));
    assert!(!listener.contains("envoy_manager"));
}

#[test]
fn shared_destroy_protocol_finalizes_postgres_before_policy_teardown() {
    let lifecycle = source("src/kernel/sandbox_lifecycle.rs");
    let finalize = lifecycle
        .find("destroy_sandbox_if_status_and_external_id")
        .expect("durable destroy finalization");
    let teardown = lifecycle[finalize..]
        .find("network_cleanup.teardown_networking")
        .map(|offset| finalize + offset)
        .expect("network-policy teardown");

    assert!(
        finalize < teardown,
        "PostgreSQL finalization must precede authoritative policy removal"
    );
}

#[test]
fn shared_destroy_protocol_distinguishes_runtime_deletion_from_residual_cleanup() {
    let provider = source("src/sandbox/provider.rs");
    let lifecycle = source("src/kernel/sandbox_lifecycle.rs");
    let k8s = source("src/sandbox/k8s.rs");

    assert!(provider.contains("SandboxDestroyOutcome"));
    assert!(provider.contains("SandboxRuntimeDeletion"));
    assert!(lifecycle.contains("destroy_with_outcome"));
    assert!(lifecycle.contains("residual cleanup pending"));
    assert!(k8s.contains("get_opt(external_id)"));
    assert!(k8s.contains("spec.nodeName="));
    assert!(k8s.contains("SandboxDestroyOutcome::deleted_with_residual"));
}

#[test]
fn bridge_health_destroy_is_fenced_by_exact_connection_generation() {
    let controller = source("src/kernel/sandbox_controller.rs");
    let bridge_store = source("src/kernel/ha/traits.rs");

    assert!(bridge_store.contains("async fn owns_connection"));
    assert!(controller.matches("owns_connection(&bridge)").count() >= 3);
    assert!(controller.contains("remove_if_current(ext_id, &bridge)"));
}
