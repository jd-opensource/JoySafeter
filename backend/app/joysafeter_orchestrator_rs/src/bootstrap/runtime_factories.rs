use std::sync::Arc;

use crate::config::JoySafeterConfig;
use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
use crate::sandbox;
use crate::sandbox::envoy::process::EnvoyProcessSupervisor;
use crate::sandbox::envoy::{EnvoyConfig, EnvoyRuntime};
use crate::sandbox::envoy_delivery::{ControlPlaneEnvoyDelivery, EnvoyDelivery};
use crate::sandbox::envoy_filesystem::FilesystemEnvoyDelivery;
use crate::sandbox::runtime::{PlacementEventSink, SandboxSocketProvisioner};
use crate::xds::placement::{PlacementReconciler, PlacementRetryPolicy};
use async_trait::async_trait;
use bollard::Docker;

use super::registry::{
    ProviderFactory, ProviderFactoryRegistry, RuntimeComponents, RuntimeFactoryContext,
    SandboxRuntimeTopology,
};

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
