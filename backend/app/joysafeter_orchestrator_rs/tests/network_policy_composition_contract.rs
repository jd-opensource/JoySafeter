use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn network_policy_service_is_the_only_application_facing_policy_capability() {
    let service = source("src/kernel/network_policy/service.rs");
    assert!(service.contains("pub struct NetworkPolicyService"));
    for capability in ["ensure_ready", "reconcile", "recover", "teardown"] {
        assert!(
            service.contains(&format!("fn {capability}")),
            "network policy service must own {capability}"
        );
    }

    for path in [
        "src/kernel/sandbox_resolver/networking.rs",
        "src/kernel/command_listener.rs",
        "src/kernel/network_policy/reconciler.rs",
    ] {
        let module = source(path);
        assert!(
            module.contains("NetworkPolicyService"),
            "{path} must depend on the network policy facade"
        );
        for leaked_dependency in [
            "network_policy_runtime:",
            "network_policy_material_resolver:",
            "network_policy_queue:",
            "xds_authority:",
        ] {
            assert!(
                !module.contains(leaked_dependency),
                "{path} leaks policy internals through {leaked_dependency}"
            );
        }
    }

    for path in [
        "src/kernel/sandbox_resolver.rs",
        "src/kernel/sandbox_controller.rs",
        "src/kernel/scheduler.rs",
    ] {
        assert!(
            !source(path).contains("NetworkPolicyService"),
            "{path} must depend on a narrower sandbox capability"
        );
    }
}

#[test]
fn production_composition_has_no_successful_noop_network_policy_runtime() {
    let ports = source("src/kernel/network_policy/ports.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");
    let registry = source("src/bootstrap/registry.rs");

    assert!(!ports.contains("pub struct NoopNetworkPolicyRuntime"));
    assert!(!factories.contains("NoopNetworkPolicyRuntime"));
    assert!(registry.contains("Option<Arc<dyn NetworkPolicyRuntime>>"));
}

#[test]
fn composition_root_constructs_policy_service_once_and_injects_it() {
    let application = source("src/bootstrap/application.rs");

    assert!(application.contains("NetworkPolicyService::managed"));
    assert!(application.contains("NetworkPolicyService::unsupported"));
    assert!(!application.contains("with_network_policy_runtime"));
    assert!(!application.contains("with_network_policy_material_resolver"));
    assert!(!application.contains("with_network_policy_control"));
}
