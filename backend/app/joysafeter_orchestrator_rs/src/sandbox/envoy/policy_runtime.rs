use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use serde_json::json;
use tokio::sync::Mutex;
use tracing::{debug, info};

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::{
    validate_egress_policy, ListenerKind, ListenerSpec, SandboxEgressPolicy,
};
use crate::kernel::network_policy::ports::{
    NetworkPolicyApplyRequest, NetworkPolicyRecoveryEntry, NetworkPolicyRecoveryFailure,
    NetworkPolicyRecoveryReport, NetworkPolicyRuntime,
};
use crate::xds::authority::{RecoveryAuthorityGuard, XdsAuthority};
use crate::xds::delivery::DeliveryRequest;
use crate::xds::inventory::{RecoveredSandbox, RecoveryDeliveryState, RecoveryInventory};

use super::super::envoy_delivery::{
    delivery_generation, managed_cluster, managed_listener, network_policy_generation,
    DeliverySubmission, EnvoyDelivery,
};
use super::socket::EgressSocketProvisioner;

#[derive(Clone)]
pub struct EnvoyPolicyConfig {
    pub grpc_mode: bool,
    pub write_debug_entries: bool,
    pub reset_debug_directory: bool,
    pub config_dir: String,
    pub delivery_timeout: Duration,
}

pub struct EnvoyPolicyEngine {
    delivery: Arc<dyn EnvoyDelivery>,
    sockets: Arc<EgressSocketProvisioner>,
    config: EnvoyPolicyConfig,
    sandbox_apply_locks: Mutex<HashMap<SandboxId, Arc<Mutex<()>>>>,
}

impl EnvoyPolicyEngine {
    pub fn new(
        delivery: Arc<dyn EnvoyDelivery>,
        sockets: Arc<EgressSocketProvisioner>,
        config: EnvoyPolicyConfig,
    ) -> Self {
        Self {
            delivery,
            sockets,
            config,
            sandbox_apply_locks: Mutex::new(HashMap::new()),
        }
    }

    pub async fn initialize(&self) -> anyhow::Result<()> {
        if self.config.reset_debug_directory {
            let sandboxes = PathBuf::from(&self.config.config_dir).join("sandboxes");
            let _ = tokio::fs::remove_dir_all(&sandboxes).await;
            tokio::fs::create_dir_all(&sandboxes).await?;
        }
        self.delivery.prepare_for_startup().await
    }

    async fn sandbox_lock(&self, sandbox_id: SandboxId) -> Arc<Mutex<()>> {
        self.sandbox_apply_locks
            .lock()
            .await
            .entry(sandbox_id)
            .or_insert_with(|| Arc::new(Mutex::new(())))
            .clone()
    }

    async fn cleanup_lock(&self, sandbox_id: SandboxId, lock: &Arc<Mutex<()>>) {
        let mut locks = self.sandbox_apply_locks.lock().await;
        if locks
            .get(&sandbox_id)
            .is_some_and(|current| Arc::ptr_eq(current, lock))
            && Arc::strong_count(lock) <= 2
        {
            locks.remove(&sandbox_id);
        }
    }

    pub async fn recover(
        &self,
        authority: &RecoveryAuthorityGuard,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport> {
        authority.validate()?;
        if !self.config.grpc_mode {
            authority.begin_serving()?;
            let mut report = NetworkPolicyRecoveryReport::default();
            for entry in entries {
                let result = self
                    .apply_policy(
                        DeliveryRequest {
                            authority_epoch: authority.epoch(),
                            sandbox_id: entry.sandbox_id,
                            generation: delivery_generation(&entry.generation),
                        },
                        entry.policy,
                    )
                    .await;
                match result {
                    Ok(()) => report.ready.push((entry.sandbox_id, entry.generation)),
                    Err(error) => report.failed.push(NetworkPolicyRecoveryFailure {
                        sandbox_id: entry.sandbox_id,
                        generation: entry.generation,
                        reason: format!("recovered policy delivery failed: {error:#}"),
                    }),
                }
            }
            self.delivery.set_degraded_inventory(report.failed.len());
            return Ok(report);
        }

        let mut recovered = Vec::with_capacity(entries.len());
        for entry in entries {
            authority.validate()?;
            self.sockets.prepare_socket_dir(entry.sandbox_id).await?;
            let listener = ListenerSpec {
                sandbox_id: entry.sandbox_id,
                kind: ListenerKind::Http,
                allowed_hosts: entry.policy.allowlist_hosts.clone(),
                credentials: entry.policy.credential_routes.clone(),
                proxy_auth_token: entry.policy.proxy_auth_token.clone(),
            };
            let mut resources = entry
                .policy
                .clusters(&entry.sandbox_id)
                .iter()
                .map(managed_cluster)
                .collect::<anyhow::Result<Vec<_>>>()?;
            resources.push(managed_listener(&listener)?);
            recovered.push(RecoveredSandbox {
                sandbox_id: entry.sandbox_id,
                generation: delivery_generation(&entry.generation),
                resources,
            });
        }
        let installed = self
            .delivery
            .install_recovery_inventory(authority, RecoveryInventory::new(recovered, Vec::new())?)
            .await?;
        authority.begin_serving()?;

        let mut report = NetworkPolicyRecoveryReport::default();
        for installed_delivery in installed.deliveries {
            authority.validate()?;
            match installed_delivery.state {
                RecoveryDeliveryState::Deferred => {
                    report.deferred.push(installed_delivery.sandbox_id)
                }
                RecoveryDeliveryState::Await(attempt) => {
                    let result = self
                        .delivery
                        .wait_for_delivery(attempt, self.config.delivery_timeout)
                        .await;
                    let result = match result {
                        Ok(()) => {
                            self.sockets
                                .wait_for_socket_ready(installed_delivery.sandbox_id)
                                .await
                        }
                        Err(error) => Err(error),
                    };
                    match result {
                        Ok(()) => report.ready.push((
                            installed_delivery.sandbox_id,
                            network_policy_generation(installed_delivery.generation),
                        )),
                        Err(error) => report.failed.push(NetworkPolicyRecoveryFailure {
                            sandbox_id: installed_delivery.sandbox_id,
                            generation: network_policy_generation(installed_delivery.generation),
                            reason: format!("recovered policy delivery failed: {error:#}"),
                        }),
                    }
                }
            }
        }
        self.delivery
            .set_degraded_inventory(report.deferred.len() + report.failed.len());
        Ok(report)
    }

    pub async fn apply_policy(
        &self,
        request: DeliveryRequest,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        let sandbox_id = request.sandbox_id;
        validate_egress_policy(&sandbox_id, &policy)?;
        self.sockets.prepare_socket_dir(sandbox_id).await?;
        if self.config.write_debug_entries {
            self.write_debug_entry(sandbox_id, &policy).await?;
        }

        let delivery_attempt = {
            let lock = self.sandbox_lock(sandbox_id).await;
            let guard = tokio::time::timeout(Duration::from_secs(5), lock.lock())
                .await
                .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox apply lock"))?;
            let listener = ListenerSpec {
                sandbox_id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts.clone(),
                credentials: policy.credential_routes.clone(),
                proxy_auth_token: policy.proxy_auth_token.clone(),
            };
            let submission = tokio::time::timeout(
                Duration::from_secs(10),
                self.delivery.apply_sandbox_batch(
                    request,
                    policy.clusters(&sandbox_id),
                    vec![listener],
                ),
            )
            .await
            .map_err(|_| anyhow::anyhow!("timed out applying Envoy xDS update"))??;
            let attempt = match submission {
                DeliverySubmission::AlreadyCurrent => None,
                DeliverySubmission::Await(attempt) => Some(attempt),
            };
            drop(guard);
            self.cleanup_lock(sandbox_id, &lock).await;
            attempt
        };
        if let Some(attempt) = delivery_attempt {
            self.delivery
                .wait_for_delivery(attempt, self.config.delivery_timeout)
                .await?;
        }
        self.sockets.wait_for_socket_ready(sandbox_id).await?;
        info!(%sandbox_id, "Envoy policy delivered and socket ready");
        Ok(())
    }

    pub async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let lock = self.sandbox_lock(sandbox_id).await;
        let guard = tokio::time::timeout(Duration::from_secs(5), lock.lock())
            .await
            .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox apply lock"))?;
        let result = self.remove_unlocked(sandbox_id).await;
        drop(guard);
        self.cleanup_lock(sandbox_id, &lock).await;
        result
    }

    async fn remove_unlocked(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        match self.delivery.remove_sandbox_batch(sandbox_id).await? {
            DeliverySubmission::Await(attempt) => {
                self.delivery
                    .wait_for_delivery(attempt, self.config.delivery_timeout)
                    .await
                    .with_context(|| {
                        format!("Envoy did not ACK xDS removal for sandbox {sandbox_id}")
                    })?;
                self.delivery.retire_sandbox_delivery(sandbox_id).await;
            }
            DeliverySubmission::AlreadyCurrent => {
                self.delivery.retire_sandbox_delivery(sandbox_id).await;
            }
        }
        self.sockets.remove_socket_dir(sandbox_id).await;
        if self.config.write_debug_entries {
            let entry = PathBuf::from(&self.config.config_dir)
                .join("sandboxes")
                .join(format!("{}.json", sandbox_id.as_uuid()));
            let _ = tokio::fs::remove_file(entry).await;
        }
        debug!(%sandbox_id, "Removed sandbox Envoy policy");
        Ok(())
    }

    pub async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        let configured = self.delivery.configured_sandbox_ids().await;
        let mut stale: Vec<_> = configured.difference(live_sandbox_ids).copied().collect();
        stale.sort_by_key(|sandbox_id| sandbox_id.as_uuid());
        for sandbox_id in &stale {
            self.remove(*sandbox_id).await?;
        }
        Ok(stale.len())
    }

    async fn write_debug_entry(
        &self,
        sandbox_id: SandboxId,
        policy: &SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        let path = PathBuf::from(&self.config.config_dir)
            .join("sandboxes")
            .join(format!("{}.json", sandbox_id.as_uuid()));
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let content = serde_json::to_vec(&json!({
            "sandbox_id": sandbox_id.as_uuid().to_string(),
            "allowed_hosts": policy.allowlist_hosts,
        }))?;
        let temporary = path.with_extension("tmp");
        tokio::fs::write(&temporary, content).await?;
        tokio::fs::rename(temporary, path).await?;
        Ok(())
    }
}

pub struct EnvoyNetworkPolicyRuntime {
    engine: Arc<EnvoyPolicyEngine>,
    authority: XdsAuthority,
}

impl EnvoyNetworkPolicyRuntime {
    pub fn new(engine: Arc<EnvoyPolicyEngine>, authority: XdsAuthority) -> Self {
        Self { engine, authority }
    }
}

#[async_trait::async_trait]
impl NetworkPolicyRuntime for EnvoyNetworkPolicyRuntime {
    async fn initialize(&self) -> anyhow::Result<()> {
        self.engine.initialize().await
    }

    async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        self.engine.prune(live_sandbox_ids).await
    }

    async fn recover(
        &self,
        authority_epoch: u64,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport> {
        let guard = self
            .authority
            .recovery_guard()
            .filter(|guard| guard.epoch() == authority_epoch)
            .ok_or_else(|| anyhow::anyhow!("xDS recovery authority changed"))?;
        self.engine.recover(&guard, entries).await
    }

    async fn apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.engine
            .apply_policy(
                DeliveryRequest {
                    authority_epoch: request.authority_epoch,
                    sandbox_id: request.sandbox_id,
                    generation: delivery_generation(&request.generation),
                },
                policy,
            )
            .await
    }

    async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.engine.remove(sandbox_id).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::network_policy::NetworkPolicyGeneration;
    use crate::sandbox::envoy::socket::EgressSocketConfig;
    use crate::sandbox::envoy_filesystem::FilesystemEnvoyDelivery;
    use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
    use crate::xds::model::DeliveryGeneration;

    fn sockets() -> Arc<EgressSocketProvisioner> {
        Arc::new(EgressSocketProvisioner::new(
            None,
            EgressSocketConfig {
                envoy_image: "unused".to_string(),
                socket_volume: "unused".to_string(),
                socket_host_dir: None,
                container_name: "unused".to_string(),
                socket_ready_timeout_ms: 10,
                externally_provisioned: true,
            },
        ))
    }

    fn config(config_dir: String, grpc_mode: bool) -> EnvoyPolicyConfig {
        EnvoyPolicyConfig {
            grpc_mode,
            write_debug_entries: false,
            reset_debug_directory: false,
            config_dir,
            delivery_timeout: Duration::from_millis(10),
        }
    }

    fn request(sandbox_id: SandboxId, version: i64) -> DeliveryRequest {
        DeliveryRequest {
            authority_epoch: 1,
            sandbox_id,
            generation: DeliveryGeneration {
                policy_hash: format!("policy-{version}"),
                policy_version: version,
            },
        }
    }

    #[tokio::test]
    async fn authoritative_prune_removes_only_stale_delivery_inventory() {
        let directory = tempfile::tempdir().expect("tempdir");
        let delivery = Arc::new(FilesystemEnvoyDelivery::new(
            directory.path().to_string_lossy().into_owned(),
        ));
        let engine = EnvoyPolicyEngine::new(
            delivery.clone(),
            sockets(),
            config(directory.path().to_string_lossy().into_owned(), false),
        );
        let live = SandboxId::new();
        let stale = SandboxId::new();
        engine
            .apply_policy(request(live, 1), SandboxEgressPolicy::default())
            .await
            .expect("apply live policy");
        engine
            .apply_policy(request(stale, 1), SandboxEgressPolicy::default())
            .await
            .expect("apply stale policy");

        let removed = engine
            .prune(&HashSet::from([live]))
            .await
            .expect("prune stale policy");

        assert_eq!(removed, 1);
        assert_eq!(
            delivery.configured_sandbox_ids().await,
            HashSet::from([live])
        );
    }

    #[tokio::test]
    async fn deferred_recovery_preserves_the_persisted_generation() {
        let authority = XdsAuthority::managed();
        let recovery = authority.begin_staging().expect("begin staging");
        let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::NodeScoped);
        let engine = Arc::new(EnvoyPolicyEngine::new(
            Arc::new(crate::sandbox::envoy_delivery::ControlPlaneEnvoyDelivery::new(control_plane)),
            sockets(),
            config("unused".to_string(), true),
        ));
        let runtime = EnvoyNetworkPolicyRuntime::new(engine, authority);
        let sandbox_id = SandboxId::new();
        let generation = NetworkPolicyGeneration {
            policy_hash: "deferred-policy".to_string(),
            policy_version: 7,
        };

        let report = runtime
            .recover(
                recovery.epoch(),
                vec![NetworkPolicyRecoveryEntry {
                    sandbox_id,
                    generation: generation.clone(),
                    policy: SandboxEgressPolicy::default(),
                }],
            )
            .await
            .expect("recover deferred inventory");

        assert!(report.ready.is_empty());
        assert_eq!(report.deferred, vec![sandbox_id]);
        assert!(report.failed.is_empty());
    }
}
