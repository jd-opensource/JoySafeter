use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use serde_json::json;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::{
    validate_egress_policy, ListenerKind, ListenerSpec, SandboxEgressPolicy,
};
use crate::kernel::network_policy::error::NetworkPolicyApplyError;
use crate::kernel::network_policy::ports::{
    NetworkPolicyApplyRequest, NetworkPolicyApplyTicket, NetworkPolicyPruneTicket,
    NetworkPolicyRecoveryEntry, NetworkPolicyRecoveryFailure, NetworkPolicyRecoveryReport,
    NetworkPolicyRemoveTicket, NetworkPolicyRuntime,
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
                        error,
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
                    let result: Result<(), NetworkPolicyApplyError> = match result {
                        Ok(()) => self
                            .sockets
                            .wait_for_socket_ready(installed_delivery.sandbox_id)
                            .await
                            .map_err(|error| {
                                NetworkPolicyApplyError::SocketNotReady(format!("{error:#}"))
                            }),
                        Err(error) => Err(error.into()),
                    };
                    match result {
                        Ok(()) => report.ready.push((
                            installed_delivery.sandbox_id,
                            network_policy_generation(installed_delivery.generation),
                        )),
                        Err(error) => report.failed.push(NetworkPolicyRecoveryFailure {
                            sandbox_id: installed_delivery.sandbox_id,
                            generation: network_policy_generation(installed_delivery.generation),
                            error,
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
    ) -> Result<(), NetworkPolicyApplyError> {
        self.prepare_policy(request.sandbox_id, &policy).await?;
        let ticket = self.publish_policy(request, policy).await?;
        self.settle_policy(ticket).await
    }

    pub async fn prepare_policy(
        &self,
        sandbox_id: SandboxId,
        policy: &SandboxEgressPolicy,
    ) -> Result<(), NetworkPolicyApplyError> {
        validate_egress_policy(&sandbox_id, policy)
            .map_err(|error| NetworkPolicyApplyError::InvalidPolicy(format!("{error:#}")))?;
        self.sockets
            .prepare_socket_dir(sandbox_id)
            .await
            .map_err(|error| {
                NetworkPolicyApplyError::SocketPreparationFailed(format!("{error:#}"))
            })?;
        if self.config.write_debug_entries {
            self.write_debug_entry(sandbox_id, policy)
                .await
                .map_err(|error| {
                    NetworkPolicyApplyError::RuntimePreparationFailed(format!("{error:#}"))
                })?;
        }
        Ok(())
    }

    pub(crate) async fn publish_policy(
        &self,
        request: DeliveryRequest,
        policy: SandboxEgressPolicy,
    ) -> Result<NetworkPolicyApplyTicket, NetworkPolicyApplyError> {
        let sandbox_id = request.sandbox_id;
        validate_egress_policy(&sandbox_id, &policy)
            .map_err(|error| NetworkPolicyApplyError::InvalidPolicy(format!("{error:#}")))?;
        let delivery_attempt = {
            let lock = self.sandbox_lock(sandbox_id).await;
            let guard = tokio::time::timeout(Duration::from_secs(5), lock.lock())
                .await
                .map_err(|_| {
                    NetworkPolicyApplyError::PublicationUnavailable(
                        "timed out acquiring Envoy sandbox apply lock".to_string(),
                    )
                })?;
            let listener = ListenerSpec {
                sandbox_id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts.clone(),
                credentials: policy.credential_routes.clone(),
                proxy_auth_token: policy.proxy_auth_token.clone(),
            };
            let clusters = policy.clusters(&sandbox_id);
            let submission = tokio::time::timeout(
                Duration::from_secs(10),
                self.delivery
                    .apply_sandbox_batch(request, clusters, vec![listener]),
            )
            .await
            .map_err(|_| {
                NetworkPolicyApplyError::PublicationUnavailable(
                    "timed out applying Envoy xDS update".to_string(),
                )
            })?
            .map_err(|error| {
                NetworkPolicyApplyError::PublicationUnavailable(format!("{error:#}"))
            })?;
            let attempt = match submission {
                DeliverySubmission::AlreadyCurrent => None,
                DeliverySubmission::Await(attempt) => Some(attempt),
            };
            drop(guard);
            self.cleanup_lock(sandbox_id, &lock).await;
            attempt
        };
        Ok(match delivery_attempt {
            Some(attempt) => {
                NetworkPolicyApplyTicket::pending(sandbox_id, attempt.attempt_id.as_u64())
            }
            None => NetworkPolicyApplyTicket::completed(sandbox_id),
        })
    }

    pub(crate) async fn settle_policy(
        &self,
        ticket: NetworkPolicyApplyTicket,
    ) -> Result<(), NetworkPolicyApplyError> {
        if let Some(attempt_id) = ticket.delivery_attempt_id() {
            self.delivery
                .wait_for_delivery(
                    crate::xds::delivery::DeliveryAttempt {
                        sandbox_id: ticket.sandbox_id(),
                        attempt_id: crate::xds::delivery::DeliveryAttemptId::from_raw(attempt_id),
                    },
                    self.config.delivery_timeout,
                )
                .await
                .map_err(NetworkPolicyApplyError::from)?;
        }
        self.sockets
            .wait_for_socket_ready(ticket.sandbox_id())
            .await
            .map_err(|error| NetworkPolicyApplyError::SocketNotReady(format!("{error:#}")))?;
        info!(sandbox_id = %ticket.sandbox_id(), "Envoy policy delivered and socket ready");
        Ok(())
    }

    pub(crate) async fn publish_remove(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<NetworkPolicyRemoveTicket> {
        let lock = self.sandbox_lock(sandbox_id).await;
        let guard = tokio::time::timeout(Duration::from_secs(5), lock.lock())
            .await
            .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox apply lock"))?;
        let submission = self.delivery.remove_sandbox_batch(sandbox_id).await;
        drop(guard);
        self.cleanup_lock(sandbox_id, &lock).await;
        Ok(match submission? {
            DeliverySubmission::Await(attempt) => {
                NetworkPolicyRemoveTicket::pending(sandbox_id, attempt.attempt_id.as_u64())
            }
            DeliverySubmission::AlreadyCurrent => NetworkPolicyRemoveTicket::completed(sandbox_id),
        })
    }

    pub(crate) async fn settle_remove(
        &self,
        ticket: NetworkPolicyRemoveTicket,
    ) -> anyhow::Result<()> {
        if let Some(attempt_id) = ticket.delivery_attempt_id() {
            self.delivery
                .wait_for_delivery(
                    crate::xds::delivery::DeliveryAttempt {
                        sandbox_id: ticket.sandbox_id(),
                        attempt_id: crate::xds::delivery::DeliveryAttemptId::from_raw(attempt_id),
                    },
                    self.config.delivery_timeout,
                )
                .await
                .with_context(|| {
                    format!(
                        "Envoy did not ACK xDS removal for sandbox {}",
                        ticket.sandbox_id()
                    )
                })?;
        }
        self.delivery
            .retire_sandbox_delivery(ticket.sandbox_id())
            .await;
        self.sockets.remove_socket_dir(ticket.sandbox_id()).await;
        if self.config.write_debug_entries {
            let entry = PathBuf::from(&self.config.config_dir)
                .join("sandboxes")
                .join(format!("{}.json", ticket.sandbox_id().as_uuid()));
            let _ = tokio::fs::remove_file(entry).await;
        }
        debug!(sandbox_id = %ticket.sandbox_id(), "Removed sandbox Envoy policy");
        Ok(())
    }

    pub async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let ticket = self.publish_remove(sandbox_id).await?;
        self.settle_remove(ticket).await
    }

    pub(crate) async fn publish_prune(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<NetworkPolicyPruneTicket> {
        let configured = self.delivery.configured_sandbox_ids().await;
        let mut stale: Vec<_> = configured.difference(live_sandbox_ids).copied().collect();
        stale.sort_by_key(|sandbox_id| sandbox_id.as_uuid());
        let mut cleanup_sandbox_ids = Vec::with_capacity(stale.len());
        let mut failures = Vec::new();
        for sandbox_id in &stale {
            let lock = self.sandbox_lock(*sandbox_id).await;
            let guard = tokio::time::timeout(Duration::from_secs(5), lock.lock())
                .await
                .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox prune lock"))?;
            let result = self.delivery.remove_sandbox_batch(*sandbox_id).await;
            if result.is_ok() {
                self.delivery.retire_sandbox_delivery(*sandbox_id).await;
            }
            drop(guard);
            self.cleanup_lock(*sandbox_id, &lock).await;
            match result {
                Ok(_) => cleanup_sandbox_ids.push(*sandbox_id),
                Err(error) => {
                    warn!(sandbox_id = %sandbox_id, %error, "Failed to prune stale xDS sandbox inventory");
                    failures.push(format!("{sandbox_id}: {error:#}"));
                }
            }
        }
        Ok(NetworkPolicyPruneTicket::published(
            stale.len(),
            cleanup_sandbox_ids,
            failures,
        ))
    }

    pub(crate) async fn settle_prune(
        &self,
        ticket: NetworkPolicyPruneTicket,
    ) -> anyhow::Result<usize> {
        for sandbox_id in ticket.cleanup_sandbox_ids() {
            self.sockets.remove_socket_dir(*sandbox_id).await;
            if self.config.write_debug_entries {
                let entry = PathBuf::from(&self.config.config_dir)
                    .join("sandboxes")
                    .join(format!("{}.json", sandbox_id.as_uuid()));
                let _ = tokio::fs::remove_file(entry).await;
            }
            debug!(%sandbox_id, "Removed stale sandbox Envoy policy artifacts");
        }
        if !ticket.publication_failures().is_empty() {
            anyhow::bail!(
                "failed to prune {} of {} stale xDS sandboxes: {}",
                ticket.publication_failures().len(),
                ticket.stale(),
                ticket.publication_failures().join("; ")
            );
        }
        Ok(ticket.removed())
    }

    pub async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        let ticket = self.publish_prune(live_sandbox_ids).await?;
        self.settle_prune(ticket).await
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

    async fn publish_prune(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<NetworkPolicyPruneTicket> {
        self.engine.publish_prune(live_sandbox_ids).await
    }

    async fn settle_prune(&self, ticket: NetworkPolicyPruneTicket) -> anyhow::Result<usize> {
        self.engine.settle_prune(ticket).await
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

    async fn prepare_apply(
        &self,
        request: &NetworkPolicyApplyRequest,
        policy: &SandboxEgressPolicy,
    ) -> Result<(), NetworkPolicyApplyError> {
        self.engine.prepare_policy(request.sandbox_id, policy).await
    }

    async fn publish_apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> Result<NetworkPolicyApplyTicket, NetworkPolicyApplyError> {
        self.engine
            .publish_policy(
                DeliveryRequest {
                    authority_epoch: request.authority_epoch,
                    sandbox_id: request.sandbox_id,
                    generation: delivery_generation(&request.generation),
                },
                policy,
            )
            .await
    }

    async fn settle_apply(
        &self,
        ticket: NetworkPolicyApplyTicket,
    ) -> Result<(), NetworkPolicyApplyError> {
        self.engine.settle_policy(ticket).await
    }

    async fn apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> Result<(), NetworkPolicyApplyError> {
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

    async fn publish_remove(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<NetworkPolicyRemoveTicket> {
        self.engine.publish_remove(sandbox_id).await
    }

    async fn settle_remove(&self, ticket: NetworkPolicyRemoveTicket) -> anyhow::Result<()> {
        self.engine.settle_remove(ticket).await
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;
    use crate::kernel::network_policy::envoy_model::{ClusterSpec, ListenerSpec};
    use crate::kernel::network_policy::NetworkPolicyGeneration;
    use crate::sandbox::envoy::socket::EgressSocketConfig;
    use crate::sandbox::envoy_delivery::{DeliverySubmission, EnvoyDelivery};
    use crate::sandbox::envoy_filesystem::FilesystemEnvoyDelivery;
    use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
    use crate::xds::delivery::{DeliveryAttempt, DeliveryAttemptId};
    use crate::xds::model::DeliveryGeneration;
    use tokio::sync::Notify;

    struct NonAckingRemovalDelivery {
        configured: Mutex<HashSet<SandboxId>>,
        wait_calls: AtomicUsize,
        retired: Mutex<HashSet<SandboxId>>,
        removal_attempts: Mutex<Vec<SandboxId>>,
        remove_errors: HashSet<SandboxId>,
    }

    struct BlockingApplyDelivery {
        apply_calls: AtomicUsize,
        wait_started: Notify,
        release_wait: Notify,
    }

    #[async_trait::async_trait]
    impl EnvoyDelivery for BlockingApplyDelivery {
        async fn prepare_for_startup(&self) -> anyhow::Result<()> {
            Ok(())
        }

        async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
            HashSet::new()
        }

        async fn apply_sandbox_batch(
            &self,
            delivery: DeliveryRequest,
            _clusters: Vec<ClusterSpec>,
            _listeners: Vec<ListenerSpec>,
        ) -> anyhow::Result<DeliverySubmission> {
            let attempt_id = self.apply_calls.fetch_add(1, Ordering::SeqCst) + 1;
            Ok(DeliverySubmission::Await(DeliveryAttempt {
                sandbox_id: delivery.sandbox_id,
                attempt_id: DeliveryAttemptId::from_raw(attempt_id as u64),
            }))
        }

        async fn remove_sandbox_batch(
            &self,
            _sandbox_id: SandboxId,
        ) -> anyhow::Result<DeliverySubmission> {
            anyhow::bail!("remove is not part of this test")
        }

        async fn wait_for_delivery(
            &self,
            attempt: DeliveryAttempt,
            _timeout: Duration,
        ) -> Result<(), crate::xds::delivery::DeliveryWaitError> {
            if attempt.attempt_id.as_u64() == 1 {
                self.wait_started.notify_one();
                self.release_wait.notified().await;
            }
            Ok(())
        }
    }

    #[async_trait::async_trait]
    impl EnvoyDelivery for NonAckingRemovalDelivery {
        async fn prepare_for_startup(&self) -> anyhow::Result<()> {
            Ok(())
        }

        async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
            self.configured.lock().await.clone()
        }

        async fn apply_sandbox_batch(
            &self,
            _delivery: DeliveryRequest,
            _clusters: Vec<ClusterSpec>,
            _listeners: Vec<ListenerSpec>,
        ) -> anyhow::Result<DeliverySubmission> {
            anyhow::bail!("apply is not part of this test")
        }

        async fn remove_sandbox_batch(
            &self,
            sandbox_id: SandboxId,
        ) -> anyhow::Result<DeliverySubmission> {
            self.removal_attempts.lock().await.push(sandbox_id);
            if self.remove_errors.contains(&sandbox_id) {
                anyhow::bail!("synthetic removal publication failure");
            }
            self.configured.lock().await.remove(&sandbox_id);
            Ok(DeliverySubmission::Await(DeliveryAttempt {
                sandbox_id,
                attempt_id: DeliveryAttemptId::from_raw(1),
            }))
        }

        async fn wait_for_delivery(
            &self,
            attempt: DeliveryAttempt,
            _timeout: Duration,
        ) -> Result<(), crate::xds::delivery::DeliveryWaitError> {
            self.wait_calls.fetch_add(1, Ordering::SeqCst);
            Err(crate::xds::delivery::DeliveryWaitError::TimedOut {
                sandbox_id: attempt.sandbox_id,
            })
        }

        async fn retire_sandbox_delivery(&self, sandbox_id: SandboxId) {
            self.retired.lock().await.insert(sandbox_id);
        }
    }

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
    async fn slow_delivery_settlement_does_not_block_another_sandbox_publication() {
        let delivery = Arc::new(BlockingApplyDelivery {
            apply_calls: AtomicUsize::new(0),
            wait_started: Notify::new(),
            release_wait: Notify::new(),
        });
        let engine = Arc::new(EnvoyPolicyEngine::new(
            delivery.clone(),
            sockets(),
            config("unused".to_string(), true),
        ));
        let first = SandboxId::new();
        let second = SandboxId::new();
        let first_ticket = engine
            .publish_policy(request(first, 1), SandboxEgressPolicy::default())
            .await
            .expect("publish first policy");
        let settling_engine = engine.clone();
        let settling = tokio::spawn(async move {
            settling_engine
                .settle_policy(first_ticket)
                .await
                .expect("settle first policy")
        });
        tokio::time::timeout(Duration::from_millis(100), delivery.wait_started.notified())
            .await
            .expect("first settlement should wait for ACK");

        tokio::time::timeout(
            Duration::from_millis(100),
            engine.publish_policy(request(second, 1), SandboxEgressPolicy::default()),
        )
        .await
        .expect("second publication must not wait for first ACK")
        .expect("publish second policy");

        delivery.release_wait.notify_one();
        settling.await.expect("join first settlement");
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
    async fn authoritative_prune_does_not_wait_for_stale_removal_ack() {
        let directory = tempfile::tempdir().expect("tempdir");
        let stale = SandboxId::new();
        let delivery = Arc::new(NonAckingRemovalDelivery {
            configured: Mutex::new(HashSet::from([stale])),
            wait_calls: AtomicUsize::new(0),
            retired: Mutex::new(HashSet::new()),
            removal_attempts: Mutex::new(Vec::new()),
            remove_errors: HashSet::new(),
        });
        let engine = EnvoyPolicyEngine::new(
            delivery.clone(),
            sockets(),
            config(directory.path().to_string_lossy().into_owned(), true),
        );

        let removed = engine
            .prune(&HashSet::new())
            .await
            .expect("stale inventory should be retired without waiting for Envoy");

        assert_eq!(removed, 1);
        assert_eq!(delivery.wait_calls.load(Ordering::SeqCst), 0);
        assert!(delivery.retired.lock().await.contains(&stale));
    }

    #[tokio::test]
    async fn authoritative_prune_continues_after_one_stale_removal_fails() {
        let directory = tempfile::tempdir().expect("tempdir");
        let first = SandboxId::from_uuid(
            uuid::Uuid::parse_str("00000000-0000-7000-8000-000000000001").expect("uuid"),
        );
        let second = SandboxId::from_uuid(
            uuid::Uuid::parse_str("00000000-0000-7000-8000-000000000002").expect("uuid"),
        );
        let delivery = Arc::new(NonAckingRemovalDelivery {
            configured: Mutex::new(HashSet::from([first, second])),
            wait_calls: AtomicUsize::new(0),
            retired: Mutex::new(HashSet::new()),
            removal_attempts: Mutex::new(Vec::new()),
            remove_errors: HashSet::from([first]),
        });
        let engine = EnvoyPolicyEngine::new(
            delivery.clone(),
            sockets(),
            config(directory.path().to_string_lossy().into_owned(), true),
        );

        let error = engine
            .prune(&HashSet::new())
            .await
            .expect_err("failed stale publications remain observable");

        assert!(error.to_string().contains("1 of 2"));
        assert_eq!(*delivery.removal_attempts.lock().await, vec![first, second]);
        assert_eq!(*delivery.configured.lock().await, HashSet::from([first]));
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
