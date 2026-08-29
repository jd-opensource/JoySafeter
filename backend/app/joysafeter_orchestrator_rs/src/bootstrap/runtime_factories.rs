use std::sync::Arc;

use async_trait::async_trait;
use bollard::Docker;

use crate::config::JoySafeterConfig;
use crate::kernel::network_policy::ports::NoopNetworkPolicyRuntime;
use crate::sandbox;
use crate::sandbox::envoy::{EnvoyConfig, EnvoyManager, EnvoyNetworkPolicyRuntime};
use crate::sandbox::envoy_delivery::{EnvoyPublishers, FilesystemCds, FilesystemLds};
use crate::sandbox::runtime::{PlacementEvent, PlacementEventHandler};
use crate::xds::publisher::{GrpcCds, GrpcLds};
use crate::xds::transport::DeltaXdsServer;

use super::registry::{ProviderFactory, ProviderFactoryRegistry, RuntimeComponents};

pub(super) fn register_defaults(registry: &mut ProviderFactoryRegistry) {
    registry.register(["docker"], Arc::new(DockerFactory));
    registry.register(["k8s", "kubernetes"], Arc::new(KubernetesFactory));
    registry.register(["daytona"], Arc::new(DaytonaFactory));
    registry.register(["e2b"], Arc::new(E2bFactory));
}

struct DockerFactory;

fn build_envoy_publishers(
    config: &JoySafeterConfig,
) -> anyhow::Result<(Option<EnvoyPublishers>, Option<Arc<DeltaXdsServer>>)> {
    if !config.envoy_enabled {
        return Ok((None, None));
    }
    if config.envoy_xds_mode == "grpc" {
        let server = DeltaXdsServer::with_static_token(&config.xds_auth_token)?;
        Ok((
            Some(EnvoyPublishers {
                lds: Arc::new(GrpcLds::new(server.clone())),
                cds: Arc::new(GrpcCds::new(server.clone())),
            }),
            Some(server),
        ))
    } else {
        Ok((
            Some(EnvoyPublishers {
                lds: Arc::new(FilesystemLds::new(config.envoy_config_dir.clone())),
                cds: Arc::new(FilesystemCds::new(config.envoy_config_dir.clone())),
            }),
            None,
        ))
    }
}

fn build_envoy_manager(
    config: &JoySafeterConfig,
    docker: Option<Arc<Docker>>,
    publishers: Option<EnvoyPublishers>,
    skip_socket_dir_prep: bool,
    node_id: &str,
) -> anyhow::Result<Option<Arc<EnvoyManager>>> {
    if !config.envoy_enabled {
        return Ok(None);
    }
    let publishers =
        publishers.ok_or_else(|| anyhow::anyhow!("Envoy publishers were not configured"))?;
    Ok(Some(Arc::new(EnvoyManager::new(
        docker,
        EnvoyConfig {
            envoy_image: config.envoy_image.clone(),
            socket_volume: config.envoy_socket_volume.clone(),
            socket_host_dir: config.envoy_socket_host_dir.clone(),
            config_dir: config.envoy_config_dir.clone(),
            envoy_network: config.envoy_network.clone(),
            grpc_target_host: config.envoy_grpc_host.clone(),
            grpc_target_port: config.envoy_grpc_port,
            xds_auth_token: config.xds_auth_token.clone(),
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
        publishers.lds,
        publishers.cds,
    ))))
}

#[async_trait]
impl ProviderFactory for DockerFactory {
    async fn build(&self, config: &JoySafeterConfig) -> anyhow::Result<RuntimeComponents> {
        let (publishers, xds_service) = build_envoy_publishers(config)?;
        let envoy_manager = build_envoy_manager(
            config,
            config
                .envoy_enabled
                .then(|| Docker::connect_with_local_defaults().map(Arc::new))
                .transpose()?,
            publishers,
            false,
            "joysafeter-envoy",
        )?;
        let provider = Arc::new(
            sandbox::docker::DockerProvider::new(
                config,
                envoy_manager
                    .clone()
                    .map(|manager| manager as Arc<dyn sandbox::runtime::SandboxSocketProvisioner>),
            )
            .await?,
        );
        let network_policy_runtime = envoy_manager
            .map(|manager| {
                Arc::new(EnvoyNetworkPolicyRuntime::new(manager))
                    as Arc<dyn crate::kernel::network_policy::ports::NetworkPolicyRuntime>
            })
            .unwrap_or_else(|| Arc::new(NoopNetworkPolicyRuntime));
        Ok(RuntimeComponents {
            sandbox_provider: provider,
            network_policy_runtime,
            xds_service,
        })
    }
}

struct KubernetesFactory;

#[async_trait]
impl ProviderFactory for KubernetesFactory {
    async fn build(&self, config: &JoySafeterConfig) -> anyhow::Result<RuntimeComponents> {
        let (publishers, xds_service) = build_envoy_publishers(config)?;
        if let Some(xds_service) = &xds_service {
            xds_service.enable_node_aware();
        }
        let envoy_manager = build_envoy_manager(config, None, publishers, true, "k8s-envoy")?;
        let placement_events: Option<PlacementEventHandler> = xds_service.clone().map(|xds| {
            Arc::new(move |event| match event {
                PlacementEvent::Assigned {
                    sandbox_id,
                    node_name,
                } => xds.set_sandbox_node(sandbox_id, node_name),
                PlacementEvent::Removed { sandbox_id } => xds.remove_sandbox_node(sandbox_id),
            }) as PlacementEventHandler
        });
        let provider = Arc::new(
            sandbox::k8s::K8sProvider::new(
                config,
                envoy_manager
                    .clone()
                    .map(|manager| manager as Arc<dyn sandbox::runtime::SandboxSocketProvisioner>),
                placement_events,
            )
            .await?,
        );
        let network_policy_runtime = envoy_manager
            .map(|manager| {
                Arc::new(EnvoyNetworkPolicyRuntime::new(manager))
                    as Arc<dyn crate::kernel::network_policy::ports::NetworkPolicyRuntime>
            })
            .unwrap_or_else(|| Arc::new(NoopNetworkPolicyRuntime));
        Ok(RuntimeComponents {
            sandbox_provider: provider,
            network_policy_runtime,
            xds_service,
        })
    }
}

struct DaytonaFactory;

#[async_trait]
impl ProviderFactory for DaytonaFactory {
    async fn build(&self, config: &JoySafeterConfig) -> anyhow::Result<RuntimeComponents> {
        if config.daytona_api_url.is_empty() || config.daytona_api_key.is_empty() {
            anyhow::bail!("JOYSAFETER_DAYTONA_API_URL and JOYSAFETER_DAYTONA_API_KEY required");
        }
        Ok(RuntimeComponents {
            sandbox_provider: Arc::new(sandbox::daytona::DaytonaProvider::new(
                &config.daytona_api_url,
                &config.daytona_api_key,
                config.daytona_target.as_deref().unwrap_or("us"),
                &config.daytona_snapshot,
            )),
            network_policy_runtime: Arc::new(NoopNetworkPolicyRuntime),
            xds_service: None,
        })
    }
}

struct E2bFactory;

#[async_trait]
impl ProviderFactory for E2bFactory {
    async fn build(&self, config: &JoySafeterConfig) -> anyhow::Result<RuntimeComponents> {
        if config.e2b_api_key.is_empty() || config.e2b_template_id.is_empty() {
            anyhow::bail!("JOYSAFETER_E2B_API_KEY and JOYSAFETER_E2B_TEMPLATE_ID required");
        }
        Ok(RuntimeComponents {
            sandbox_provider: Arc::new(sandbox::e2b::E2bProvider::new(
                config
                    .e2b_api_url
                    .as_deref()
                    .unwrap_or("https://api.e2b.app"),
                &config.e2b_api_key,
                &config.e2b_template_id,
            )),
            network_policy_runtime: Arc::new(NoopNetworkPolicyRuntime),
            xds_service: None,
        })
    }
}
