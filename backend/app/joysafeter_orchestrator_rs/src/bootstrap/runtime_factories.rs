use std::sync::Arc;

use crate::config::JoySafeterConfig;
use crate::db::runner_auth_store::PostgresRunnerAuthStore;
use crate::db::task_identity_store::PostgresTaskIdentityStore;
use crate::kernel::agent_identity_provider::AgentIdentityProvider;
use crate::kernel::credentials::access::CredentialMaterialAccessService;
use crate::kernel::credentials::CredentialStore;
use crate::kernel::ha::BridgeStore;
use crate::kernel::harness_input_builder::HarnessInputBuilder;
use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
use crate::kernel::network_policy::reconciler::NetworkPolicyReconciler;
use crate::kernel::network_policy::service::NetworkPolicyService;
use crate::kernel::queue::TaskQueue;
use crate::kernel::redis_coordinator::RedisCoordinator;
use crate::kernel::repository_access::material::{
    RepositoryAccessMaterial, RepositoryAccessMaterialAdapter,
};
use crate::kernel::runner::{
    RunnerCleanupService, RunnerExecutionService, RunnerFlowSet, RunnerRecoveryService,
};
use crate::kernel::runtime_auth::RunnerAuthenticator;
use crate::kernel::sandbox_controller::SandboxController;
use crate::kernel::sandbox_resolver::{
    ResolveContextBuilder, SandboxIdentityPolicy, SandboxIdentityPolicyService,
    SandboxLifecycleService, SandboxNetworkingService, SandboxPoolService,
    SandboxProvisioningService, SandboxResolution, SandboxResolver,
};
use crate::kernel::task_identity::material::{TaskIdentityMaterial, TaskIdentityMaterialAdapter};
use crate::kernel::task_identity::TaskIdentityService;
use crate::runtime_config::RuntimeConfig;
use crate::sandbox;
use crate::sandbox::envoy::process::EnvoyProcessSupervisor;
use crate::sandbox::envoy::{EnvoyConfig, EnvoyRuntime};
use crate::sandbox::envoy_delivery::{ControlPlaneEnvoyDelivery, EnvoyDelivery};
use crate::sandbox::envoy_filesystem::FilesystemEnvoyDelivery;
use crate::sandbox::runtime::{PlacementEventSink, SandboxSocketProvisioner};
use crate::xds::placement::{PlacementReconciler, PlacementRetryPolicy};
use async_trait::async_trait;
use bollard::Docker;
use sqlx::PgPool;
use tokio::task::JoinHandle;

use super::registry::{
    ProviderFactory, ProviderFactoryRegistry, RuntimeComponents, RuntimeFactoryContext,
    SandboxRuntimeTopology,
};
use super::supervisor::ServiceCriticality;

pub(super) struct RuntimeTask {
    pub(super) name: &'static str,
    pub(super) criticality: ServiceCriticality,
    pub(super) handle: JoinHandle<()>,
}

fn unscoped_topology() -> SandboxRuntimeTopology {
    SandboxRuntimeTopology {
        node_visibility: crate::xds::control_plane::NodeVisibility::Unscoped,
        managed_xds_authority_in_multi: false,
        xds_leader_coordination_in_multi: false,
    }
}

pub(super) fn register_defaults(registry: &mut ProviderFactoryRegistry) {
    registry.register(["docker"], Arc::new(DockerFactory));
    registry.register(["k8s", "kubernetes"], Arc::new(KubernetesFactory));
    registry.register(["daytona"], Arc::new(DaytonaFactory));
    registry.register(["e2b"], Arc::new(E2bFactory));
}

pub(super) fn build_credential_access(pool: PgPool) -> CredentialMaterialAccessService {
    CredentialMaterialAccessService::new(pool)
}

pub(super) fn build_credential_store(pool: PgPool) -> CredentialStore {
    CredentialStore::new(pool)
}

fn build_repository_material() -> Arc<dyn RepositoryAccessMaterial> {
    Arc::new(RepositoryAccessMaterialAdapter::from_env())
}

fn build_task_identity_material() -> Arc<dyn TaskIdentityMaterial> {
    Arc::new(TaskIdentityMaterialAdapter::from_env())
}

pub(super) fn build_runner_flows(
    pool: PgPool,
    envoy_enabled: bool,
    max_executions: usize,
) -> RunnerFlowSet {
    let credential_access = build_credential_access(pool.clone());
    RunnerFlowSet::new(
        RunnerExecutionService::new(max_executions),
        RunnerRecoveryService::new(),
        RunnerCleanupService::new(),
        HarnessInputBuilder::with_services(
            pool,
            credential_access,
            build_repository_material(),
            envoy_enabled,
        ),
    )
}

pub(super) fn build_runner_authenticator(pool: PgPool) -> RunnerAuthenticator {
    RunnerAuthenticator::new(Arc::new(PostgresRunnerAuthStore::new(pool)))
}

pub(super) struct SandboxRuntimeServices {
    pub(super) controller: Arc<SandboxController>,
    pub(super) resolution: Arc<dyn SandboxResolution>,
    pub(super) identity_policy: Arc<dyn SandboxIdentityPolicy>,
    pub(super) network_policy_reconciler: Option<Arc<NetworkPolicyReconciler>>,
}

pub(super) fn build_sandbox_runtime_services(
    pool: PgPool,
    queue: TaskQueue,
    bridge_store: Arc<dyn BridgeStore>,
    provider: Arc<dyn crate::sandbox::provider::SandboxProvider>,
    redis_coordinator: Option<Arc<RedisCoordinator>>,
    config: JoySafeterConfig,
    runtime_config: Arc<RuntimeConfig>,
    network_policy: NetworkPolicyService,
    identity_provider: Arc<dyn AgentIdentityProvider>,
) -> SandboxRuntimeServices {
    let networking = SandboxNetworkingService::new(pool.clone(), network_policy.clone());
    let lifecycle =
        SandboxLifecycleService::new(pool.clone(), provider.clone(), networking.clone());
    let pool_service = SandboxPoolService::new(
        pool.clone(),
        provider.clone(),
        config.clone(),
        networking.clone(),
        lifecycle.clone(),
    );
    let provisioning = SandboxProvisioningService::new(
        pool.clone(),
        provider.clone(),
        config.clone(),
        networking.clone(),
        lifecycle.clone(),
    );
    let identity = TaskIdentityService::new(
        Arc::new(PostgresTaskIdentityStore::new(pool.clone())),
        build_task_identity_material(),
        config.agent_identity_allowed_hosts.clone(),
    )
    .with_provider(identity_provider);
    let context_builder = ResolveContextBuilder::new(
        pool.clone(),
        config.clone(),
        networking.clone(),
        identity,
        build_credential_access(pool.clone()),
        build_repository_material(),
    );
    let identity_policy: Arc<dyn SandboxIdentityPolicy> =
        Arc::new(SandboxIdentityPolicyService::new(
            pool.clone(),
            networking.clone(),
            lifecycle.clone(),
            context_builder.clone(),
        ));
    let pool_replenish_notify = Arc::new(tokio::sync::Notify::new());
    let controller = Arc::new(SandboxController::new_with_components(
        pool.clone(),
        queue,
        bridge_store,
        provider.clone(),
        redis_coordinator,
        config,
        runtime_config,
        networking.clone(),
        lifecycle.clone(),
        Arc::new(pool_service.clone()),
        pool_replenish_notify.clone(),
    ));
    let resolution: Arc<dyn SandboxResolution> = Arc::new(
        SandboxResolver::new_with_services(
            pool.clone(),
            networking,
            lifecycle,
            pool_service,
            provisioning,
            context_builder,
        )
        .with_pool_replenish_notify(pool_replenish_notify),
    );
    let network_policy_reconciler = provider
        .capabilities()
        .has_egress_management
        .then(|| Arc::new(NetworkPolicyReconciler::new(pool, network_policy)));

    SandboxRuntimeServices {
        controller,
        resolution,
        identity_policy,
        network_policy_reconciler,
    }
}

pub(super) fn build_sandbox_controller_tasks(
    controller: Arc<SandboxController>,
    network_policy_reconciler: Option<Arc<NetworkPolicyReconciler>>,
) -> Vec<RuntimeTask> {
    let mut tasks = vec![
        RuntimeTask {
            name: "sandbox-idle-sweep",
            criticality: ServiceCriticality::Critical,
            handle: {
                let controller = controller.clone();
                tokio::spawn(async move { controller.idle_sweep_loop().await })
            },
        },
        RuntimeTask {
            name: "sandbox-provisioning-monitor",
            criticality: ServiceCriticality::Critical,
            handle: {
                let controller = controller.clone();
                tokio::spawn(async move { controller.provisioning_poll_loop().await })
            },
        },
        RuntimeTask {
            name: "sandbox-pool-orphan-maintenance",
            criticality: ServiceCriticality::Degradable,
            handle: {
                let controller = controller.clone();
                tokio::spawn(async move { controller.cleanup_loop().await })
            },
        },
    ];
    if let Some(reconciler) = network_policy_reconciler {
        tasks.push(RuntimeTask {
            name: "sandbox-networking-reconcile",
            criticality: ServiceCriticality::Critical,
            handle: tokio::spawn(async move { reconciler.run().await }),
        });
    }
    tasks
}

fn build_delivery(
    config: &JoySafeterConfig,
    context: &RuntimeFactoryContext,
) -> anyhow::Result<Option<Arc<dyn EnvoyDelivery>>> {
    if !config.envoy_enabled {
        return Ok(None);
    }
    if config.envoy_xds_mode == "grpc" {
        let control_plane = context
            .xds_control_plane
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("gRPC xDS control plane is not configured"))?;
        Ok(Some(Arc::new(ControlPlaneEnvoyDelivery::new(
            control_plane.clone(),
        ))))
    } else {
        Ok(Some(Arc::new(FilesystemEnvoyDelivery::new(
            config.envoy_config_dir.clone(),
        ))))
    }
}

struct EnvoyCapabilities {
    network_policy_runtime: Arc<dyn NetworkPolicyRuntime>,
    socket_provisioner: Arc<dyn SandboxSocketProvisioner>,
    envoy_process: Arc<EnvoyProcessSupervisor>,
}

fn build_envoy_capabilities(
    config: &JoySafeterConfig,
    context: &RuntimeFactoryContext,
    docker: Option<Arc<Docker>>,
    skip_socket_dir_prep: bool,
    node_id: &str,
) -> anyhow::Result<Option<EnvoyCapabilities>> {
    let Some(delivery) = build_delivery(config, context)? else {
        return Ok(None);
    };
    let runtime = EnvoyRuntime::new(
        docker,
        EnvoyConfig {
            envoy_image: config.envoy_image.clone(),
            socket_volume: config.envoy_socket_volume.clone(),
            socket_host_dir: config.envoy_socket_host_dir.clone(),
            config_dir: config.envoy_config_dir.clone(),
            grpc_target_host: config.envoy_grpc_host.clone(),
            grpc_target_port: config.xds_port,
            xds_auth_token: config
                .grpc_xds_enabled()
                .then(|| config.xds_auth_token.clone())
                .flatten(),
            container_name: config.envoy_container_name.clone(),
            xds_mode: config.envoy_xds_mode.clone(),
            write_debug_entries: config.envoy_write_debug_entries,
            socket_ready_timeout_ms: config.envoy_socket_ready_timeout_ms,
            health_check_interval_sec: config.envoy_health_check_interval_sec,
            health_failure_threshold: config.envoy_health_failure_threshold,
            manage_bootstrap: !skip_socket_dir_prep,
            skip_socket_dir_prep,
            node_id: node_id.to_string(),
        },
        delivery,
    );
    Ok(Some(EnvoyCapabilities {
        network_policy_runtime: runtime.network_policy_runtime(context.xds_authority.clone()),
        socket_provisioner: runtime.socket_provisioner(),
        envoy_process: runtime.process_supervisor(),
    }))
}

fn runtime_components(
    sandbox_provider: Arc<dyn sandbox::provider::SandboxProvider>,
    envoy: Option<EnvoyCapabilities>,
    placement_reconciler: Option<tokio::task::JoinHandle<()>>,
) -> RuntimeComponents {
    let (network_policy_runtime, socket_provisioner, envoy_process) =
        envoy.map_or((None, None, None), |capabilities| {
            (
                Some(capabilities.network_policy_runtime),
                Some(capabilities.socket_provisioner),
                Some(capabilities.envoy_process),
            )
        });
    RuntimeComponents {
        sandbox_provider,
        network_policy_runtime,
        socket_provisioner,
        envoy_process,
        placement_reconciler,
    }
}

fn build_placement_runtime(
    context: &RuntimeFactoryContext,
) -> (Option<PlacementEventSink>, Option<PlacementReconciler>) {
    context
        .xds_control_plane
        .clone()
        .map_or((None, None), |control_plane| {
            let (sink, reconciler) = PlacementReconciler::new(
                Arc::new(control_plane),
                256,
                PlacementRetryPolicy::default(),
            );
            (Some(sink), Some(reconciler))
        })
}

struct DockerFactory;

#[async_trait]
impl ProviderFactory for DockerFactory {
    fn topology(&self) -> SandboxRuntimeTopology {
        unscoped_topology()
    }

    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        let docker = config
            .envoy_enabled
            .then(|| Docker::connect_with_local_defaults().map(Arc::new))
            .transpose()?;
        let envoy = build_envoy_capabilities(config, context, docker, false, "joysafeter-envoy")?;
        let socket = envoy
            .as_ref()
            .map(|capabilities| capabilities.socket_provisioner.clone());
        let provider = Arc::new(sandbox::docker::DockerProvider::new(config, socket).await?);
        Ok(runtime_components(provider, envoy, None))
    }
}

struct KubernetesFactory;

#[async_trait]
impl ProviderFactory for KubernetesFactory {
    fn topology(&self) -> SandboxRuntimeTopology {
        SandboxRuntimeTopology {
            node_visibility: crate::xds::control_plane::NodeVisibility::NodeScoped,
            managed_xds_authority_in_multi: true,
            xds_leader_coordination_in_multi: true,
        }
    }

    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        let envoy = build_envoy_capabilities(config, context, None, true, "k8s-envoy")?;
        let socket = envoy
            .as_ref()
            .map(|capabilities| capabilities.socket_provisioner.clone());
        let (placement_events, placement_reconciler) = build_placement_runtime(context);
        let provider =
            Arc::new(sandbox::k8s::K8sProvider::new(config, socket, placement_events).await?);
        Ok(runtime_components(
            provider,
            envoy,
            placement_reconciler.map(|reconciler| tokio::spawn(reconciler.run())),
        ))
    }
}

struct DaytonaFactory;

#[async_trait]
impl ProviderFactory for DaytonaFactory {
    fn topology(&self) -> SandboxRuntimeTopology {
        unscoped_topology()
    }

    async fn build(
        &self,
        config: &JoySafeterConfig,
        _context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        if config.daytona_api_url.is_empty() || config.daytona_api_key.is_empty() {
            anyhow::bail!("JOYSAFETER_DAYTONA_API_URL and JOYSAFETER_DAYTONA_API_KEY required");
        }
        Ok(runtime_components(
            Arc::new(sandbox::daytona::DaytonaProvider::new(
                &config.daytona_api_url,
                &config.daytona_api_key,
                config.daytona_target.as_deref().unwrap_or("us"),
                &config.daytona_snapshot,
            )),
            None,
            None,
        ))
    }
}

struct E2bFactory;

#[async_trait]
impl ProviderFactory for E2bFactory {
    fn topology(&self) -> SandboxRuntimeTopology {
        unscoped_topology()
    }

    async fn build(
        &self,
        config: &JoySafeterConfig,
        _context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        if config.e2b_api_key.is_empty() || config.e2b_template_id.is_empty() {
            anyhow::bail!("JOYSAFETER_E2B_API_KEY and JOYSAFETER_E2B_TEMPLATE_ID required");
        }
        Ok(runtime_components(
            Arc::new(sandbox::e2b::E2bProvider::new(
                config
                    .e2b_api_url
                    .as_deref()
                    .unwrap_or("https://api.e2b.app"),
                &config.e2b_api_key,
                &config.e2b_template_id,
            )),
            None,
            None,
        ))
    }
}
