use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn main_delegates_runtime_composition_to_bootstrap_application() {
    let main = source("src/main.rs");
    assert!(main.contains("OrchestratorApplication::build"));
    for forbidden in [
        "ProviderFactoryRegistry",
        "start_grpc_server",
        "start_xds_server",
        "SandboxResolver::new",
        "SandboxController::new",
        "spawn_scheduler",
        "SessionStateSubscriber",
        "NetworkPolicyAuthorityHandler",
        "RedisNetworkPolicyRequestSource",
    ] {
        assert!(
            !main.contains(forbidden),
            "main owns forbidden composition detail: {forbidden}"
        );
    }

    let application = source("src/bootstrap/application.rs");
    assert!(application.contains("pub struct OrchestratorApplication"));
    assert!(application.contains("ProviderFactoryRegistry"));
    assert!(application.contains("start_grpc_server"));
    assert!(application.contains("start_xds_server"));
}

#[test]
fn composition_root_builds_network_policy_material_behind_its_port() {
    let main = source("src/main.rs");
    assert!(!main.contains("build_network_policy_material_resolver"));
    assert!(!main.contains("PostgresNetworkPolicyMaterialResolver"));

    let application = source("src/bootstrap/application.rs");
    assert!(application.contains("build_network_policy_material_resolver"));

    let bootstrap = source("src/bootstrap/network_policy_material.rs");
    assert!(bootstrap.contains("NetworkPolicyMaterialResolver"));
    assert!(bootstrap.contains("PostgresNetworkPolicyMaterialResolver"));
    assert!(!bootstrap.contains("sandbox_resolver"));
    assert!(bootstrap.contains("credentials::runtime_projection"));

    let resolver = source("src/kernel/sandbox_resolver.rs");
    assert!(!resolver.contains("PostgresNetworkPolicyMaterialResolver"));
    assert!(resolver.contains("NetworkPolicyService"));
    assert!(!resolver.contains("fn rebuild_sandbox_credentials"));

    let projection = source("src/kernel/credentials/runtime_projection.rs");
    assert!(projection.contains("pub(crate) async fn rebuild_sandbox_credentials"));
    assert!(!projection.contains("sandbox_resolver"));

    let scheduler = source("src/kernel/scheduler.rs");
    assert!(scheduler.contains("NetworkPolicyService"));
    assert!(!scheduler.contains("NetworkPolicyMaterialResolver"));

    let command_listener = source("src/kernel/command_listener.rs");
    assert!(!command_listener.contains("llm_egress_allowed_hosts"));
}

#[test]
fn registry_is_confined_to_the_composition_root() {
    let registry = source("src/bootstrap/registry.rs");
    assert!(registry.contains("pub struct ProviderFactoryRegistry"));

    for application_module in [
        "src/kernel/sandbox_resolver.rs",
        "src/kernel/sandbox_controller.rs",
        "src/kernel/sandbox_lifecycle.rs",
        "src/grpc/server.rs",
    ] {
        assert!(!source(application_module).contains("ProviderFactoryRegistry"));
    }
}

#[test]
fn application_accepts_injected_provider_and_identity_factories() {
    let application = source("src/bootstrap/application.rs");
    assert!(application.contains("BootstrapDependencies"));
    assert!(application.contains("build_with_dependencies"));
    assert!(application.contains(".provider_registry"));
    assert!(application.contains(".identity_factory"));
    assert_eq!(
        application
            .matches("ProviderFactoryRegistry::with_defaults()")
            .count(),
        1,
        "production defaults belong only in BootstrapDependencies::production"
    );
    assert!(!application.contains("match identity_provider_kind"));
}

#[test]
fn provider_registry_owns_normalization_and_runtime_topology() {
    let registry = source("src/bootstrap/registry.rs");
    assert!(registry.contains("pub struct SandboxProviderKey"));
    assert!(registry.contains("pub struct SandboxRuntimeTopology"));
    assert!(registry.contains("pub struct ResolvedSandboxProvider"));
    assert!(registry.contains("pub fn resolve"));

    let application = source("src/bootstrap/application.rs");
    assert!(!application.contains("matches!(config.sandbox_provider.as_str()"));
    assert!(!application.contains("match config.sandbox_provider.as_str()"));
    assert!(!application.contains("config.sandbox_provider == \"k8s\""));
}

#[test]
fn runtime_adapters_do_not_construct_or_retain_xds_services() {
    for path in ["src/sandbox/docker.rs", "src/sandbox/k8s.rs"] {
        let module = source(path);
        for forbidden in [
            "DeltaXdsServer",
            "GrpcLds",
            "GrpcCds",
            "xds_service",
            "set_sandbox_node",
            "EnvoyManager",
            "NetworkPolicyRuntime",
            "SandboxCredentials",
            "PgPool",
            "XdsAuthorityGuard",
        ] {
            assert!(
                !module.contains(forbidden),
                "{path} owns forbidden xDS capability: {forbidden}"
            );
        }
    }
}

#[test]
fn network_policy_runtime_port_is_infrastructure_agnostic() {
    let port = source("src/kernel/network_policy/ports.rs");
    for forbidden in [
        "sqlx::PgPool",
        "XdsAuthorityGuard",
        "serde_json::Value",
        "SandboxCredentials",
    ] {
        assert!(
            !port.contains(forbidden),
            "network-policy port leaks infrastructure type: {}",
            forbidden
        );
    }
}

#[test]
fn network_policy_domain_does_not_depend_on_sandbox_or_sandbox_resolver() {
    for path in [
        "src/kernel/network_policy.rs",
        "src/kernel/network_policy/application.rs",
        "src/kernel/network_policy/envoy_model.rs",
        "src/kernel/network_policy/material.rs",
        "src/kernel/network_policy/ports.rs",
        "src/kernel/network_policy/recovery.rs",
    ] {
        let module = source(path);
        for forbidden in ["crate::sandbox::", "sandbox_resolver"] {
            assert!(
                !module.contains(forbidden),
                "{path} depends on forbidden lower-level module: {forbidden}"
            );
        }
    }

    let material = source("src/kernel/network_policy/material.rs");
    assert!(material.contains("trait NetworkPolicyMaterialResolver"));
    assert!(!material.contains("sqlx::"));
    assert!(!material.contains("JoySafeterSandbox"));
    assert!(!material.contains("sandbox_resolver"));
}

#[test]
fn envoy_adapter_does_not_own_postgres_recovery_or_status_transitions() {
    let adapter = source("src/sandbox/envoy.rs");
    for forbidden in [
        "sqlx::PgPool",
        "crate::db::queries",
        "recover_from_db",
        "reopen_network_policy_for_authority_recovery",
        "mark_sandbox_network_policy_acked",
        "update_sandbox_networking_status",
        "rebuild_sandbox_credentials",
    ] {
        assert!(
            !adapter.contains(forbidden),
            "Envoy adapter owns forbidden durable-state concern: {}",
            forbidden
        );
    }
}

#[test]
fn sandbox_provider_does_not_own_network_policy_operations() {
    let provider = source("src/sandbox/provider.rs");
    for forbidden in [
        "on_startup",
        "recover_networking",
        "prune_networking",
        "setup_networking",
        "refresh_networking",
        "teardown_networking",
    ] {
        assert!(
            !provider.contains(forbidden),
            "SandboxProvider leaks network-policy operation: {forbidden}"
        );
    }

    for path in [
        "src/kernel/command_listener.rs",
        "src/kernel/ha/redis_impl.rs",
        "src/kernel/sandbox_controller.rs",
        "src/kernel/sandbox_lifecycle.rs",
        "src/kernel/sandbox_resolver.rs",
    ] {
        let module = source(path);
        for forbidden in [
            "provider.recover_networking",
            "provider.prune_networking",
            "provider.setup_networking",
            "provider.refresh_networking",
            "provider.teardown_networking",
            "self.provider.recover_networking",
            "self.provider.prune_networking",
            "self.provider.setup_networking",
            "self.provider.refresh_networking",
            "self.provider.teardown_networking",
        ] {
            assert!(
                !module.contains(forbidden),
                "{path} invokes forbidden SandboxProvider capability: {forbidden}"
            );
        }
    }
}
