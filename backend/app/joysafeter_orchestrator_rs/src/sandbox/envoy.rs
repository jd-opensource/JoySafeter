//! Envoy runtime composition facade.
//!
//! Mutable state is owned by three disjoint capabilities:
//! process lifecycle, socket provisioning, and policy delivery.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use bollard::Docker;

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::SandboxEgressPolicy;
use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
use crate::sandbox::envoy_delivery::EnvoyDelivery;
use crate::sandbox::runtime::SandboxSocketProvisioner;
use crate::xds::authority::XdsAuthority;
use crate::xds::delivery::DeliveryRequest;

pub mod policy_runtime;
pub mod process;
pub mod socket;

use policy_runtime::{EnvoyNetworkPolicyRuntime, EnvoyPolicyConfig, EnvoyPolicyEngine};
use process::{EnvoyProcessConfig, EnvoyProcessSupervisor};
use socket::{EgressSocketConfig, EgressSocketProvisioner};

#[derive(Clone)]
pub struct EnvoyConfig {
    pub envoy_image: String,
    pub socket_volume: String,
    pub socket_host_dir: Option<String>,
    pub config_dir: String,
    pub grpc_target_host: String,
    pub grpc_target_port: u16,
    pub xds_auth_token: Option<String>,
    pub container_name: String,
    pub xds_mode: String,
    pub write_debug_entries: bool,
    pub socket_ready_timeout_ms: u64,
    pub health_check_interval_sec: u64,
    pub health_failure_threshold: u64,
    pub manage_bootstrap: bool,
    pub skip_socket_dir_prep: bool,
    pub node_id: String,
}

pub struct EnvoyRuntime {
    process: Arc<EnvoyProcessSupervisor>,
    sockets: Arc<EgressSocketProvisioner>,
    policy: Arc<EnvoyPolicyEngine>,
}

impl EnvoyRuntime {
    pub fn new(
        docker: Option<Arc<Docker>>,
        config: EnvoyConfig,
        delivery: Arc<dyn EnvoyDelivery>,
    ) -> Self {
        let sockets = Arc::new(EgressSocketProvisioner::new(
            docker.clone(),
            EgressSocketConfig {
                envoy_image: config.envoy_image,
                socket_volume: config.socket_volume,
                socket_host_dir: config.socket_host_dir,
                container_name: config.container_name.clone(),
                socket_ready_timeout_ms: config.socket_ready_timeout_ms,
                externally_provisioned: config.skip_socket_dir_prep,
            },
        ));
        let process = Arc::new(EnvoyProcessSupervisor::new(
            docker,
            EnvoyProcessConfig {
                container_name: config.container_name,
                health_check_interval: Duration::from_secs(if config.skip_socket_dir_prep {
                    0
                } else {
                    config.health_check_interval_sec
                }),
                health_failure_threshold: config.health_failure_threshold,
                manage_bootstrap: config.manage_bootstrap,
                config_dir: config.config_dir.clone(),
                grpc_mode: config.xds_mode == "grpc",
                grpc_target_host: config.grpc_target_host,
                grpc_target_port: config.grpc_target_port,
                xds_auth_token: config.xds_auth_token,
                node_id: config.node_id,
            },
        ));
        let policy = Arc::new(EnvoyPolicyEngine::new(
            delivery,
            sockets.clone(),
            EnvoyPolicyConfig {
                grpc_mode: config.xds_mode == "grpc",
                write_debug_entries: config.write_debug_entries,
                reset_debug_directory: !config.skip_socket_dir_prep,
                config_dir: config.config_dir,
                delivery_timeout: Duration::from_millis(config.socket_ready_timeout_ms.max(1_000)),
            },
        ));
        Self {
            process,
            sockets,
            policy,
        }
    }

    pub fn process_supervisor(&self) -> Arc<EnvoyProcessSupervisor> {
        self.process.clone()
    }

    pub fn socket_provisioner(&self) -> Arc<dyn SandboxSocketProvisioner> {
        self.sockets.clone()
    }

    pub fn network_policy_runtime(&self, authority: XdsAuthority) -> Arc<dyn NetworkPolicyRuntime> {
        Arc::new(EnvoyNetworkPolicyRuntime::new(
            self.policy.clone(),
            authority,
        ))
    }

    pub async fn initialize(&self) -> anyhow::Result<()> {
        self.process.initialize().await?;
        self.policy.initialize().await?;
        self.process
            .wait_until_ready(Duration::from_secs(15))
            .await?;
        self.sockets.verify_socket_storage_consistency().await
    }

    pub async fn add_sandbox_policy(
        &self,
        request: DeliveryRequest,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.policy.apply_policy(request, policy).await
    }

    pub async fn remove_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.policy.remove(sandbox_id).await
    }

    pub async fn prune_networking_except(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<usize> {
        self.policy.prune(live_sandbox_ids).await
    }
}
