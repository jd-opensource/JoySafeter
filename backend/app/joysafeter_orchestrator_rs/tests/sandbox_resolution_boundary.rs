use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn runtime_plan_is_pure_and_infrastructure_independent() {
    let model = source("src/kernel/sandbox_resolver/model.rs");
    let plan = source("src/kernel/sandbox_resolver/runtime_plan.rs");

    for required in [
        "struct ResolveContext",
        "struct ResolvedSandbox",
        "struct ExpectedFingerprint",
    ] {
        assert!(
            model.contains(required),
            "resolution model misses {required}"
        );
    }

    for required in [
        "runtime_fingerprint_matches",
        "effective_networking_config",
        "provisioning_config",
    ] {
        assert!(plan.contains(required), "runtime plan misses {required}");
    }

    for forbidden in [
        "PgPool",
        "sqlx::",
        "SandboxProvider",
        "NetworkPolicyService",
        "crate::xds",
    ] {
        assert!(!model.contains(forbidden), "model depends on {forbidden}");
        assert!(
            !plan.contains(forbidden),
            "runtime plan depends on {forbidden}"
        );
    }
}

#[test]
fn task_identity_owns_secret_lifecycle_without_network_runtime_access() {
    let identity = source("src/kernel/sandbox_resolver/identity.rs");

    for required in [
        "struct TaskIdentityService",
        "resolve_injection",
        "load_context_for_update",
        "consume_locked_context",
        "merge_into_routes",
    ] {
        assert!(
            identity.contains(required),
            "identity service misses {required}"
        );
    }

    for forbidden in ["SandboxProvider", "NetworkPolicyService", "crate::xds"] {
        assert!(
            !identity.contains(forbidden),
            "identity service depends on {forbidden}"
        );
    }
}

#[test]
fn networking_service_owns_policy_readiness_without_provider_access() {
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let networking = source("src/kernel/sandbox_resolver/networking.rs");

    for required in [
        "struct SandboxNetworkingService",
        "apply_prepared",
        "refresh_reused",
        "setup_pool_claim",
        "teardown",
    ] {
        assert!(
            networking.contains(required),
            "networking service misses {required}"
        );
    }

    for forbidden in ["NetworkPolicyService", "network_policy_ready"] {
        assert!(
            !resolver.contains(forbidden),
            "resolver still owns networking detail {forbidden}"
        );
    }

    for forbidden in ["SandboxProvider", "crate::xds"] {
        assert!(
            !networking.contains(forbidden),
            "networking service crosses into {forbidden}"
        );
    }
}

#[test]
fn scheduler_consumes_bootstrap_assembled_resolver() {
    let scheduler = source("src/kernel/scheduler.rs");
    let scheduler_production = scheduler.split("#[cfg(test)]").next().unwrap_or(&scheduler);
    let application = source("src/bootstrap/application.rs");

    assert!(
        !scheduler_production.contains("SandboxResolver::new"),
        "scheduler must not assemble the sandbox resolver"
    );
    assert!(
        scheduler_production.contains("resolver: Arc<dyn SandboxResolution>"),
        "scheduler must receive the sandbox resolution port"
    );
    assert!(
        application.contains("sandbox_runtime.resolution"),
        "bootstrap must pass its assembled resolution port to the scheduler"
    );
}

#[test]
fn sandbox_controller_only_orchestrates_narrow_maintenance_flows() {
    let controller = source("src/kernel/sandbox_controller.rs");
    let controller_fields = controller
        .split_once("pub struct SandboxController {")
        .and_then(|(_, rest)| rest.split_once("}\n\nimpl SandboxController"))
        .map(|(fields, _)| fields)
        .expect("SandboxController fields");

    for required in [
        "IdleSandboxMaintenance",
        "ProvisioningSandboxMaintenance",
        "SandboxPoolMaintenance",
        "SandboxOrphanMaintenance",
        "SandboxTaskRecovery",
    ] {
        assert!(
            controller.contains(&format!("struct {required}")),
            "sandbox maintenance capability is missing: {required}"
        );
    }

    for forbidden in ["PgPool", "SandboxProvider", "BridgeStore", "TaskQueue"] {
        assert!(
            !controller_fields.contains(forbidden),
            "SandboxController retains child-flow dependency {forbidden}"
        );
    }
}

#[test]
fn pool_provisioning_is_a_narrow_injected_capability() {
    let pool = source("src/kernel/sandbox_resolver/pool.rs");
    let controller = source("src/kernel/sandbox_controller.rs");

    for required in [
        "trait PoolSandboxProvisioner",
        "struct SandboxPoolService",
        "async fn provision",
    ] {
        assert!(pool.contains(required), "pool capability misses {required}");
    }

    assert!(
        controller.contains("pool_provisioner: Arc<dyn PoolSandboxProvisioner>"),
        "controller must depend on the pool provisioning port"
    );
    assert!(
        !controller.contains("SandboxResolver::new_with"),
        "controller must not construct the resolver"
    );

    for forbidden in ["TaskIdentityService", "crate::xds"] {
        assert!(
            !pool.contains(forbidden),
            "pool capability depends on {forbidden}"
        );
    }
}

#[test]
fn resolver_does_not_reexport_pool_provisioning() {
    let resolver = source("src/kernel/sandbox_resolver.rs");

    assert!(
        !resolver.contains("provision_pool_sandbox"),
        "pool provisioning belongs to PoolSandboxProvisioner, not SandboxResolver"
    );
}

#[test]
fn degraded_network_recovery_belongs_to_network_policy_domain() {
    let controller = source("src/kernel/sandbox_controller.rs");
    let reconciler = source("src/kernel/network_policy/reconciler.rs");

    assert!(reconciler.contains("struct NetworkPolicyReconciler"));
    assert!(reconciler.contains("reconcile_batch"));
    assert!(reconciler.contains("pub(crate) async fn run"));
    assert!(!controller.contains("reconcile_degraded_networking"));
    assert!(!controller.contains("networking_reconcile_loop"));

    for forbidden in ["SandboxProvider", "crate::xds"] {
        assert!(
            !reconciler.contains(forbidden),
            "network-policy reconciler depends on {forbidden}"
        );
    }
}

#[test]
fn resolver_lifecycle_owns_restart_and_cleanup_protocols() {
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let lifecycle = source("src/kernel/sandbox_resolver/lifecycle.rs");

    for required in [
        "struct SandboxLifecycleService",
        "cleanup_rejected_create",
        "destroy_observed",
        "restart_stopped",
        "active_status",
    ] {
        assert!(
            lifecycle.contains(required),
            "lifecycle service misses {required}"
        );
    }

    for forbidden in [
        "fn cleanup_rejected_new_sandbox",
        "fn destroy_observed_sandbox",
        "fn restart_stopped_sandbox",
        "fn compensate_failed_stopped_restart",
        "fn active_sandbox_status",
    ] {
        assert!(
            !resolver.contains(forbidden),
            "resolver still implements lifecycle detail {forbidden}"
        );
    }
}

#[test]
fn new_sandbox_provisioning_owns_provider_creation_protocol() {
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let provisioning = source("src/kernel/sandbox_resolver/provisioning.rs");
    let resolver_fields = resolver
        .split_once("pub struct SandboxResolver {")
        .and_then(|(_, rest)| rest.split_once("\n}"))
        .map(|(fields, _)| fields)
        .expect("resolver struct");

    for required in [
        "struct SandboxProvisioningService",
        "pub(crate) async fn create",
        "provider.create",
        "provider.start",
        "cleanup_rejected_create",
        "transition_sandbox_cas",
    ] {
        assert!(
            provisioning.contains(required),
            "provisioning service misses {required}"
        );
    }

    assert!(
        !resolver_fields.contains("SandboxProvider"),
        "resolver stores the provider instead of a provisioning capability"
    );
    for forbidden in [
        "async fn create_new_sandbox",
        "self.provider.create",
        "self.provider.start",
    ] {
        assert!(
            !resolver.contains(forbidden),
            "resolver still owns provider provisioning detail {forbidden}"
        );
    }
}

#[test]
fn resolve_context_builder_owns_material_projection() {
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let context = source("src/kernel/sandbox_resolver/context.rs");

    for required in [
        "struct ResolveContextBuilder",
        "pub(crate) async fn build",
        "resolve_live_environment_binding",
        "resolve_agent_env_from",
        "resolve_mcp_runtime_plan_with_access",
        "resolve_mount_resources",
        "load_storage_volume_catalog",
    ] {
        assert!(
            context.contains(required),
            "context builder misses {required}"
        );
    }

    for forbidden in [
        "async fn build_resolve_context",
        "CredentialMaterialAccessService",
        "resolve_mount_resources",
        "environment_binding::",
    ] {
        assert!(
            !resolver.contains(forbidden),
            "resolver still owns context materialization detail {forbidden}"
        );
    }
}

#[test]
fn identity_policy_is_a_separate_injected_capability() {
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let identity_policy = source("src/kernel/sandbox_resolver/identity_policy.rs");
    let execution = source("src/kernel/runner/execution.rs");
    let recovery = source("src/kernel/runner/recovery.rs");

    for required in [
        "trait SandboxIdentityPolicy",
        "struct SandboxIdentityPolicyService",
        "refresh_delay",
        "refresh_policy",
        "clear_policy",
    ] {
        assert!(
            identity_policy.contains(required),
            "identity policy capability misses {required}"
        );
    }

    for forbidden in [
        "fn task_identity_refresh_delay",
        "fn refresh_task_agent_identity_policy",
        "fn clear_task_agent_identity_policy",
    ] {
        assert!(
            !resolver.contains(forbidden),
            "resolver still exposes identity policy operation {forbidden}"
        );
    }

    assert!(!execution.contains("sandbox_resolver::SandboxResolver"));
    assert!(!recovery.contains("sandbox_resolver::SandboxResolver"));
}

#[test]
fn scheduler_depends_on_resolution_port_not_concrete_resolver() {
    let ports = source("src/kernel/sandbox_resolver/ports.rs");
    let scheduler = source("src/kernel/scheduler.rs");

    assert!(ports.contains("trait SandboxResolution"));
    assert!(ports.contains("async fn resolve"));
    assert!(scheduler.contains("Arc<dyn SandboxResolution>"));
    assert!(!scheduler.contains("Arc<SandboxResolver>"));
    assert!(!scheduler.contains("resolver: &SandboxResolver"));
}

#[test]
fn sandbox_controller_uses_lifecycle_and_networking_capabilities() {
    let controller = source("src/kernel/sandbox_controller.rs");

    for required in [
        "networking: SandboxNetworkingService",
        "lifecycle: SandboxLifecycleService",
    ] {
        assert!(
            controller.contains(required),
            "controller misses {required}"
        );
    }
    for forbidden in ["network_policy: NetworkPolicyService"] {
        assert!(
            !controller.contains(forbidden),
            "controller crosses network-policy/xDS boundary through {forbidden}"
        );
    }
}

#[test]
fn bootstrap_factory_assembles_sandbox_capability_graph() {
    let application = source("src/bootstrap/application.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");

    assert!(factories.contains("struct SandboxRuntimeServices"));
    assert!(factories.contains("build_sandbox_runtime_services"));
    for capability in [
        "SandboxNetworkingService::new",
        "SandboxLifecycleService::new",
        "SandboxProvisioningService::new",
        "ResolveContextBuilder::new",
        "SandboxIdentityPolicyService::new",
        "SandboxResolver::new_with_services",
    ] {
        assert!(
            factories.contains(capability),
            "runtime factory does not assemble {capability}"
        );
        assert!(
            !application.contains(capability),
            "application hard-codes sandbox child construction via {capability}"
        );
    }
}
