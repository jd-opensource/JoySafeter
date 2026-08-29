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
