use std::sync::Arc;

use async_trait::async_trait;
use bollard::Docker;
use tracing::warn;

use crate::config::JoySafeterConfig;
use crate::kernel::network_policy::ports::{NetworkPolicyRuntime, NoopNetworkPolicyRuntime};
use crate::sandbox;
use crate::sandbox::envoy::{EnvoyConfig, EnvoyManager, EnvoyNetworkPolicyRuntime};
use crate::sandbox::envoy_delivery::{ControlPlaneEnvoyDelivery, EnvoyDelivery};
use crate::sandbox::envoy_filesystem::FilesystemEnvoyDelivery;
use crate::sandbox::runtime::{PlacementEvent, PlacementEventHandler, SandboxSocketProvisioner};

use super::registry::{
    ProviderFactory, ProviderFactoryRegistry, RuntimeComponents, RuntimeFactoryContext,
};

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

fn build_envoy_manager(
    config: &JoySafeterConfig,
    context: &RuntimeFactoryContext,
    docker: Option<Arc<Docker>>,
    skip_socket_dir_prep: bool,
    node_id: &str,
) -> anyhow::Result<Option<Arc<EnvoyManager>>> {
    let Some(delivery) = build_delivery(config, context)? else {
        return Ok(None);
    };
    Ok(Some(Arc::new(EnvoyManager::new(
        docker,
        EnvoyConfig {
            envoy_image: config.envoy_image.clone(),
            socket_volume: config.envoy_socket_volume.clone(),
            socket_host_dir: config.envoy_socket_host_dir.clone(),
            config_dir: config.envoy_config_dir.clone(),
            envoy_network: config.envoy_network.clone(),
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
            health_check_interval_sec: if skip_socket_dir_prep {
                0
            } else {
                config.envoy_health_check_interval_sec
            },
            health_failure_threshold: if skip_socket_dir_prep {
                0
            } else {
                config.envoy_health_failure_threshold
            },
            skip_socket_dir_prep,
            node_id: node_id.to_string(),
        },
        delivery,
    ))))
}

fn runtime_components(
    sandbox_provider: Arc<dyn sandbox::provider::SandboxProvider>,
    envoy_manager: Option<Arc<EnvoyManager>>,
    authority: crate::xds::authority::XdsAuthority,
) -> RuntimeComponents {
    let network_policy_runtime: Arc<dyn NetworkPolicyRuntime> = match envoy_manager.as_ref() {
        Some(manager) => Arc::new(EnvoyNetworkPolicyRuntime::new(manager.clone(), authority)),
        None => Arc::new(NoopNetworkPolicyRuntime),
    };
    RuntimeComponents {
        sandbox_provider,
        network_policy_runtime,
        envoy_manager,
    }
}

fn placement_handler(context: &RuntimeFactoryContext) -> Option<PlacementEventHandler> {
    context.xds_control_plane.clone().map(|control_plane| {
        Arc::new(move |event| {
            let control_plane = control_plane.clone();
            Box::pin(async move {
                let result = match event {
                    PlacementEvent::Assigned {
                        sandbox_id,
                        node_name,
                    } => control_plane
                        .assign_sandbox_node(sandbox_id, node_name)
                        .await
                        .map(|_| ()),
                    PlacementEvent::Removed { sandbox_id } => {
                        control_plane.remove_sandbox_node(sandbox_id).await;
                        Ok(())
                    }
                    PlacementEvent::Reconciled { assignments } => control_plane
                        .replace_node_assignments(assignments)
                        .await
                        .map(|_| ()),
                };
                if let Err(error) = result {
                    warn!(%error, "failed to apply xDS node ownership observation");
                }
            }) as futures::future::BoxFuture<'static, ()>
        }) as PlacementEventHandler
    })
}

struct DockerFactory;

#[async_trait]
impl ProviderFactory for DockerFactory {
    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        let docker = config
            .envoy_enabled
            .then(|| Docker::connect_with_local_defaults().map(Arc::new))
            .transpose()?;
        let envoy_manager =
            build_envoy_manager(config, context, docker, false, "joysafeter-envoy")?;
        let socket: Option<Arc<dyn SandboxSocketProvisioner>> = envoy_manager
            .as_ref()
            .map(|manager| manager.clone() as Arc<dyn SandboxSocketProvisioner>);
        let provider = Arc::new(sandbox::docker::DockerProvider::new(config, socket).await?);
        Ok(runtime_components(
            provider,
            envoy_manager,
            context.xds_authority.clone(),
        ))
    }
}

struct KubernetesFactory;

#[async_trait]
impl ProviderFactory for KubernetesFactory {
    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
    ) -> anyhow::Result<RuntimeComponents> {
        let envoy_manager = build_envoy_manager(config, context, None, true, "k8s-envoy")?;
        let socket: Option<Arc<dyn SandboxSocketProvisioner>> = envoy_manager
            .as_ref()
            .map(|manager| manager.clone() as Arc<dyn SandboxSocketProvisioner>);
        let provider = Arc::new(
            sandbox::k8s::K8sProvider::new(config, socket, placement_handler(context)).await?,
        );
        Ok(runtime_components(
            provider,
            envoy_manager,
            context.xds_authority.clone(),
        ))
    }
}

struct DaytonaFactory;

#[async_trait]
impl ProviderFactory for DaytonaFactory {
    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
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
            context.xds_authority.clone(),
        ))
    }
}

struct E2bFactory;

#[async_trait]
impl ProviderFactory for E2bFactory {
    async fn build(
        &self,
        config: &JoySafeterConfig,
        context: &RuntimeFactoryContext,
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
            context.xds_authority.clone(),
        ))
    }
}
