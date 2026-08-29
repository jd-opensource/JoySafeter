fn source(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn production_network_policy_has_one_generation_state_machine() {
    assert!(!std::path::Path::new("src/kernel/network_policy/model.rs").exists());
    assert!(!std::path::Path::new("src/kernel/network_policy/service.rs").exists());

    let module = source("src/kernel/network_policy.rs");
    assert!(!module.contains("pub mod model"));
    assert!(!module.contains("pub mod service"));

    let ports = source("src/kernel/network_policy/ports.rs");
    assert!(!ports.contains("NetworkPolicyRepository"));
    assert!(!ports.contains("NetworkPolicyPublisher"));
    assert!(ports.contains("trait NetworkPolicyRuntime"));

    let application = source("src/kernel/network_policy/application.rs");
    assert!(application.contains("prepare_desired_network_policy"));
    assert!(application.contains("mark_sandbox_network_policy_acked"));
    assert!(application.contains("record_network_policy_failure_detail"));

    let authority = source("src/kernel/network_policy/authority.rs");
    assert!(authority.contains("pub struct NetworkPolicyAuthorityHandler"));
    assert!(authority.contains("apply_generation_as_authority"));
    assert!(authority.contains("network_policy_removal_is_current"));
    assert!(authority.contains("list_live_sandboxes_for_recovery"));

    let request = source("src/kernel/network_policy/request.rs");
    assert!(request.contains("pub struct NetworkPolicyRequest"));
    assert!(request.contains("pub enum NetworkPolicyAction"));
    assert!(!request.contains("crate::db"));
}

#[test]
fn redis_adapter_only_transports_network_policy_requests() {
    let redis = source("src/kernel/ha/redis_impl.rs");
    for forbidden in [
        "recover_as_authority",
        "apply_generation_as_authority",
        "network_policy_removal_is_current",
        "list_live_sandboxes_for_recovery",
        "mark_ready",
        "ready_guard",
        "lock_application",
    ] {
        assert!(
            !redis.contains(forbidden),
            "Redis adapter owns forbidden authority/application concern: {forbidden}"
        );
    }

    let worker = source("src/xds/authority_worker.rs");
    assert!(worker.contains("pub async fn run_authority_worker"));
    assert!(worker.contains("mark_ready"));
    assert!(worker.contains("ready_guard"));
}

#[test]
fn generation_value_is_domain_owned_and_cas_is_postgres_owned() {
    let policy = source("src/kernel/network_policy.rs");
    assert!(policy.contains("pub struct NetworkPolicyGeneration"));

    let queries = source("src/db/queries/sandbox.rs");
    assert!(!queries.contains("pub struct NetworkPolicyGeneration"));
    assert!(queries.contains("use crate::kernel::network_policy::NetworkPolicyGeneration"));
    assert!(queries.contains("pub enum NetworkPolicyPrepareOutcome"));
    assert!(queries.contains("pub enum NetworkPolicyAckOutcome"));
    assert!(queries.contains("pub enum NetworkPolicyFailureOutcome"));
    assert!(queries.contains("prepare_desired_network_policy"));
    assert!(queries.contains("mark_sandbox_network_policy_acked"));
    assert!(queries.contains("record_network_policy_failure_detail"));
}
