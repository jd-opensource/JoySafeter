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
        "JoySafeterAgent",
        "crate::db::models",
        "PgPool",
        "sqlx::",
        "SandboxProvider",
        "NetworkPolicyService",
        "crate::xds",
        "identity_lease_metadata",
        "identity_lease_matches",
        "identity_lease_refresh_after_seconds",
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
    let identity = source("src/kernel/task_identity/service.rs");
    let task_identity = source("src/kernel/task_identity/mod.rs");
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let context = source("src/kernel/sandbox_resolver/context.rs");
    let network_identity = source("src/kernel/network_policy/identity.rs");
    let store = source("src/kernel/task_identity/store.rs");
    let postgres_store = source("src/db/task_identity_store.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");

    for required in [
        "struct TaskIdentityService",
        "resolve_injection",
        "validate_provider_injection",
    ] {
        assert!(
            identity.contains(required),
            "identity service misses {required}"
        );
    }

    assert!(
        task_identity.contains("mod service;")
            && task_identity.contains("pub(crate) use service::{")
            && task_identity.contains("TaskIdentityService")
            && task_identity.contains("TaskIdentitySubject"),
        "task_identity must expose its application service contract"
    );
    assert!(
        !resolver.contains("mod identity;")
            && !resolver.contains("self::identity::TaskIdentityService"),
        "sandbox resolver must not own or re-export task identity implementation"
    );
    assert!(
        context.contains("crate::kernel::task_identity::{")
            && !context.contains("super::identity")
            && !context.contains("pub fn with_identity_provider"),
        "sandbox resolver context must consume the task identity domain contract"
    );

    for forbidden in [
        "PgPool",
        "sqlx::",
        "PostgresTaskIdentityStore",
        "SELECT ",
        "UPDATE ",
        "SandboxProvider",
        "NetworkPolicyService",
        "EgressCredentialRoute",
        "network_policy::",
        "crate::xds",
    ] {
        assert!(
            !identity.contains(forbidden),
            "identity service depends on {forbidden}"
        );
    }

    for required in [
        "trait TaskIdentityStore",
        "claim_material",
        "complete_claim",
        "release_claim",
        "load_task_actor",
    ] {
        assert!(store.contains(required), "identity store misses {required}");
    }
    for forbidden in [
        "PgPool",
        "sqlx::",
        "PostgresTaskIdentityStore",
        "SELECT ",
        "UPDATE ",
        "AgentIdentityProvider",
        "SandboxProvider",
        "NetworkPolicyService",
        "crate::xds",
    ] {
        assert!(
            !store.contains(forbidden),
            "identity store crosses into {forbidden}"
        );
    }

    for required in [
        "struct PostgresTaskIdentityStore",
        "impl TaskIdentityStore for PostgresTaskIdentityStore",
        "SELECT project_id, user_id, user_name, credential_kind",
        "UPDATE joysafeter_task_identity_contexts",
    ] {
        assert!(
            postgres_store.contains(required),
            "PostgreSQL identity adapter misses {required}"
        );
    }
    for forbidden in [
        "AgentIdentityProvider",
        "SandboxProvider",
        "NetworkPolicyService",
        "crate::xds",
    ] {
        assert!(
            !postgres_store.contains(forbidden),
            "PostgreSQL identity adapter crosses into {forbidden}"
        );
    }
    assert!(
        factories.contains("db::task_identity_store::PostgresTaskIdentityStore"),
        "composition root must select the PostgreSQL identity adapter"
    );

    for required in [
        "merge_identity_injection",
        "EgressCredentialRoute",
        "AgentIdentityInjection",
    ] {
        assert!(
            network_identity.contains(required),
            "network-policy identity projection misses {required}"
        );
    }
    for forbidden in [
        "TaskIdentityStore",
        "AgentIdentityProvider",
        "TaskIdentityMaterialAdapter",
        "sqlx::",
        "PgPool",
    ] {
        assert!(
            !network_identity.contains(forbidden),
            "network-policy identity projection owns forbidden concern {forbidden}"
        );
    }

    let identity_policy = source("src/kernel/sandbox_resolver/identity_policy.rs");
    for required in [
        "identity_lease_metadata",
        "identity_lease_matches",
        "identity_lease_refresh_after_seconds",
    ] {
        assert!(
            identity_policy.contains(required),
            "identity policy does not own lease concern {required}"
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
    assert!(
        scheduler_production.contains("credential_store: CredentialStore")
            && !scheduler_production.contains("CredentialStore::new"),
        "scheduler must receive credential persistence instead of constructing it"
    );
    assert!(
        application.contains("build_credential_store"),
        "bootstrap must construct scheduler credential persistence"
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
fn sandbox_runtime_is_staged_before_provider_start_and_activated_after_create() {
    for path in [
        "src/kernel/sandbox_resolver/provisioning.rs",
        "src/kernel/sandbox_resolver/pool.rs",
    ] {
        let implementation = source(path);
        let stage = implementation
            .find("stage_sandbox")
            .unwrap_or_else(|| panic!("{path} does not persist runner admission before create"));
        let create = implementation
            .find("provider.create")
            .unwrap_or_else(|| panic!("{path} does not create a provider runtime"));
        let activate = implementation
            .find("activate_staged_sandbox")
            .unwrap_or_else(|| panic!("{path} does not bind the provider runtime after create"));

        assert!(
            stage < create,
            "{path} starts the provider before durable runner admission exists"
        );
        assert!(
            create < activate,
            "{path} activates the sandbox before the provider external id exists"
        );
    }
}

#[test]
fn runtime_credentials_cross_only_the_typed_provider_boundary() {
    let provider = source("src/sandbox/provider.rs");

    for required in [
        "struct SandboxRuntimeCredentials",
        "runtime_credentials: SandboxRuntimeCredentials",
        "fn provider_environment",
        "apply_to_environment",
    ] {
        assert!(
            provider.contains(required),
            "sandbox provider contract misses {required}"
        );
    }

    for path in [
        "src/kernel/sandbox_resolver/provisioning.rs",
        "src/kernel/sandbox_resolver/pool.rs",
    ] {
        let orchestration = source(path);
        for forbidden in [
            "env.insert(\"JOYSAFETER_RUNNER_TOKEN\"",
            "env.insert(\"JOYSAFETER_EGRESS_PROXY_TOKEN\"",
        ] {
            assert!(
                !orchestration.contains(forbidden),
                "{path} leaks runtime credentials into generic environment assembly"
            );
        }
        assert!(
            orchestration.contains("SandboxRuntimeCredentials::new"),
            "{path} must pass runtime credentials through the typed provider contract"
        );
    }

    for path in [
        "src/sandbox/docker.rs",
        "src/sandbox/k8s.rs",
        "src/sandbox/e2b.rs",
        "src/sandbox/daytona.rs",
    ] {
        assert!(
            source(path).contains("provider_environment()"),
            "{path} must project runtime credentials only at the provider boundary"
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

#[test]
fn runtime_auth_owns_persisted_egress_proxy_token_parsing() {
    let runtime_auth = source("src/kernel/runtime_auth.rs");
    let credential_projection = source("src/kernel/credentials/runtime_projection.rs");
    let resolver = source("src/kernel/sandbox_resolver.rs");
    let identity_policy = source("src/kernel/sandbox_resolver/identity_policy.rs");

    assert!(runtime_auth.contains("pub(crate) fn egress_proxy_token"));
    assert!(!runtime_auth.contains("JoySafeterSandbox"));
    assert!(!credential_projection.contains("fn sandbox_egress_proxy_token"));
    assert!(resolver.contains("runtime_auth::egress_proxy_token"));
    assert!(identity_policy.contains("runtime_auth::egress_proxy_token"));
}

#[test]
fn credential_runtime_projection_is_split_by_capability() {
    let facade = source("src/kernel/credentials/runtime_projection.rs");
    let environment = source("src/kernel/credentials/runtime_projection/environment.rs");
    let external_egress = source("src/kernel/credentials/runtime_projection/external_egress.rs");
    let git_egress = source("src/kernel/credentials/runtime_projection/git_egress.rs");
    let llm_egress = source("src/kernel/credentials/runtime_projection/llm_egress.rs");
    let recovery = source("src/kernel/credentials/runtime_projection/recovery.rs");

    for module in [
        "mod environment;",
        "mod external_egress;",
        "mod git_egress;",
        "mod llm_egress;",
        "mod recovery;",
    ] {
        assert!(
            facade.contains(module),
            "runtime projection misses {module}"
        );
    }
    for forbidden in [
        "sqlx::",
        "fn resolve_agent_env_from",
        "fn extract_llm_egress",
        "fn build_git_egress",
        "fn build_external_egress",
        "fn rebuild_sandbox_credentials",
    ] {
        assert!(
            !facade.contains(forbidden),
            "runtime projection facade still owns {forbidden}"
        );
    }

    for forbidden in ["sqlx::", "PgPool", "EgressCredentialRoute", "runtime_auth"] {
        assert!(
            !environment.contains(forbidden),
            "environment projection crosses into {forbidden}"
        );
    }
    for forbidden in ["sqlx::", "PgPool", "JoySafeterAgent", "runtime_auth"] {
        assert!(
            !external_egress.contains(forbidden),
            "external egress projection crosses into {forbidden}"
        );
        assert!(
            !llm_egress.contains(forbidden),
            "LLM egress projection crosses into {forbidden}"
        );
    }
    assert!(git_egress.contains("RepositoryAccessMaterial"));
    assert!(!git_egress.contains("RepositoryAccessMaterialAdapter"));
    assert!(recovery.contains("rebuild_sandbox_credentials"));
    assert!(recovery.contains("runtime_auth::egress_proxy_token"));
}

#[test]
fn sensitive_material_adapters_are_injected_from_bootstrap() {
    let identity = source("src/kernel/task_identity/service.rs");
    let git_egress = source("src/kernel/credentials/runtime_projection/git_egress.rs");
    let harness = source("src/kernel/harness_input_builder.rs");
    let context = source("src/kernel/sandbox_resolver/context.rs");
    let factories = source("src/bootstrap/runtime_factories.rs");
    let material_factory = source("src/bootstrap/network_policy_material.rs");

    for forbidden in ["TaskIdentityMaterialAdapter::from_env", "std::env::var"] {
        assert!(
            !identity.contains(forbidden),
            "task identity service constructs configuration dependency {forbidden}"
        );
    }
    assert!(identity.contains("material: Arc<dyn TaskIdentityMaterial>"));
    assert!(identity.contains("allowed_hosts: Vec<String>"));

    assert!(
        !git_egress.contains("RepositoryAccessMaterialAdapter::from_env"),
        "Git egress constructs its own material adapter"
    );
    assert!(
        git_egress.contains("material: &dyn RepositoryAccessMaterial"),
        "Git egress does not declare its material dependency"
    );

    assert!(harness.contains("repository_material: Arc<dyn RepositoryAccessMaterial>"));
    assert!(context.contains("repository_material: Arc<dyn RepositoryAccessMaterial>"));
    assert!(factories.contains("TaskIdentityMaterialAdapter::from_env"));
    assert!(factories.contains("RepositoryAccessMaterialAdapter::from_env"));
    assert!(material_factory.contains("RepositoryAccessMaterialAdapter::from_env"));
}
