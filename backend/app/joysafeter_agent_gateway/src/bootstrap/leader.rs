//! Kubernetes Lease fencing for the stateful ADS/management projection.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use k8s_openapi::api::coordination::v1::{Lease, LeaseSpec};
use k8s_openapi::api::core::v1::Pod;
use k8s_openapi::apimachinery::pkg::apis::meta::v1::MicroTime;
use kube::api::{Api, ObjectMeta, Patch, PatchParams, PostParams};
use kube::Client;
use serde_json::json;
use tokio::task::JoinHandle;
use tracing::{info, warn};

use crate::application::PolicyProjectionRegistry;
use crate::replication::{ReplicaProjector, ReplicationCoordinator};
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::XdsControlPlane;
use crate::xds::inventory::RecoveryInventory;

pub const LEADER_LABEL: &str = "joysafeter-agent-gateway-leader";

#[derive(Clone)]
pub struct LeaderConfig {
    pub namespace: String,
    pub pod_name: String,
    pub lease_name: String,
    pub identity: String,
    pub lease_duration: Duration,
    pub renew_interval: Duration,
}

struct Coordinator {
    client: Client,
    config: LeaderConfig,
    authority: XdsAuthority,
    control_plane: XdsControlPlane,
    projections: PolicyProjectionRegistry,
    replication: ReplicationCoordinator,
    replica_projector: ReplicaProjector,
    leading: AtomicBool,
    stopped: AtomicBool,
}

pub struct LeaderHandle {
    inner: Arc<Coordinator>,
    task: JoinHandle<()>,
}

#[derive(Clone)]
pub struct LeaderReplication {
    pub coordinator: ReplicationCoordinator,
    pub projector: ReplicaProjector,
}

impl LeaderHandle {
    pub async fn shutdown(&self) {
        self.inner.stopped.store(true, Ordering::Release);
        self.inner.demote().await;
        self.inner.release().await;
        self.task.abort();
    }
}

pub fn spawn(
    client: Client,
    config: LeaderConfig,
    authority: XdsAuthority,
    control_plane: XdsControlPlane,
    projections: PolicyProjectionRegistry,
    replication: LeaderReplication,
) -> LeaderHandle {
    let inner = Arc::new(Coordinator {
        client,
        config,
        authority,
        control_plane,
        projections,
        replication: replication.coordinator,
        replica_projector: replication.projector,
        leading: AtomicBool::new(false),
        stopped: AtomicBool::new(false),
    });
    let runner = inner.clone();
    let task = tokio::spawn(async move { runner.run().await });
    LeaderHandle { inner, task }
}

impl Coordinator {
    async fn run(self: Arc<Self>) {
        while !self.stopped.load(Ordering::Acquire) {
            let held = if self.leading.load(Ordering::Acquire) {
                self.try_renew().await
            } else {
                self.try_acquire().await
            };
            match held {
                Ok(Some(epoch)) if !self.leading.swap(true, Ordering::AcqRel) => {
                    if let Err(error) = self.promote(epoch).await {
                        warn!(%error, "failed to promote Agent Gateway leader");
                        self.leading.store(false, Ordering::Release);
                        self.demote().await;
                        self.release().await;
                    }
                }
                Ok(None) | Err(_) if self.leading.swap(false, Ordering::AcqRel) => {
                    self.demote().await;
                }
                Err(error) => warn!(%error, "Agent Gateway Lease operation failed"),
                _ => {}
            }
            tokio::time::sleep(self.config.renew_interval).await;
        }
    }

    async fn promote(&self, lease_epoch: u64) -> anyhow::Result<()> {
        let mutation_gate = self.replica_projector.mutation_gate();
        let _gate = mutation_gate.lock().await;
        let hot_snapshot = self.replication.begin_leader_term(lease_epoch).await?;
        let recovery = self.authority.begin_staging_at(lease_epoch)?;
        let inventory = if let Some(snapshot) = hot_snapshot {
            info!(
                policies = snapshot.policies.len(),
                placements = snapshot.placements.len(),
                "promoting hot standby snapshot"
            );
            self.replica_projector.recovery_inventory(&snapshot).await?
        } else {
            self.projections.clear();
            RecoveryInventory::new(Vec::new())?
        };
        self.control_plane
            .install_recovery_inventory(&recovery, inventory)
            .await?;
        recovery.validate()?;
        self.authority.begin_recovery_serving(&recovery)?;
        if !set_leader_label(
            &self.client,
            &self.config.namespace,
            &self.config.pod_name,
            true,
        )
        .await
        {
            anyhow::bail!("failed to publish Agent Gateway leader endpoint");
        }
        let replicated_policies = self.replication.current_snapshot().await.policies.len();
        info!(
            pod = %self.config.pod_name,
            epoch = recovery.epoch(),
            replicated_policies,
            "Agent Gateway Lease acquired; awaiting Orchestrator authority validation"
        );
        Ok(())
    }

    async fn demote(&self) {
        let _ = self.authority.revoke();
        set_leader_label(
            &self.client,
            &self.config.namespace,
            &self.config.pod_name,
            false,
        )
        .await;
        self.replication.demote().await;
    }

    async fn leases(&self) -> Api<Lease> {
        Api::namespaced(self.client.clone(), &self.config.namespace)
    }

    async fn try_acquire(&self) -> anyhow::Result<Option<u64>> {
        let leases = self.leases().await;
        match leases.get(&self.config.lease_name).await {
            Ok(existing) => {
                let default_spec = LeaseSpec::default();
                let spec = existing.spec.as_ref().unwrap_or(&default_spec);
                match acquire_step(
                    spec,
                    &self.config.identity,
                    self.config.lease_duration,
                    Utc::now(),
                ) {
                    AcquireStep::Renew => self.try_renew().await,
                    AcquireStep::Yield => Ok(None),
                    AcquireStep::Takeover => self.takeover(existing).await,
                }
            }
            Err(kube::Error::Api(error)) if error.code == 404 => self.create().await,
            Err(error) => Err(error.into()),
        }
    }

    async fn create(&self) -> anyhow::Result<Option<u64>> {
        let now = Utc::now();
        let lease = Lease {
            metadata: ObjectMeta {
                name: Some(self.config.lease_name.clone()),
                namespace: Some(self.config.namespace.clone()),
                ..Default::default()
            },
            spec: Some(LeaseSpec {
                holder_identity: Some(self.config.identity.clone()),
                lease_duration_seconds: Some(self.config.lease_duration.as_secs() as i32),
                acquire_time: Some(MicroTime(now)),
                renew_time: Some(MicroTime(now)),
                lease_transitions: Some(1),
                ..Default::default()
            }),
        };
        match self
            .leases()
            .await
            .create(&PostParams::default(), &lease)
            .await
        {
            Ok(_) => Ok(Some(1)),
            Err(kube::Error::Api(error)) if error.code == 409 => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    async fn takeover(&self, mut lease: Lease) -> anyhow::Result<Option<u64>> {
        let spec = lease.spec.get_or_insert_with(LeaseSpec::default);
        let now = Utc::now();
        spec.holder_identity = Some(self.config.identity.clone());
        spec.acquire_time = Some(MicroTime(now));
        spec.renew_time = Some(MicroTime(now));
        spec.lease_duration_seconds = Some(self.config.lease_duration.as_secs() as i32);
        let epoch = next_takeover_epoch(spec.lease_transitions);
        spec.lease_transitions = Some(epoch);
        match self
            .leases()
            .await
            .replace(&self.config.lease_name, &PostParams::default(), &lease)
            .await
        {
            Ok(_) => Ok(Some(epoch as u64)),
            Err(kube::Error::Api(error)) if error.code == 409 => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    async fn try_renew(&self) -> anyhow::Result<Option<u64>> {
        let leases = self.leases().await;
        let mut lease = leases.get(&self.config.lease_name).await?;
        let Some(spec) = lease.spec.as_mut() else {
            return Ok(None);
        };
        if spec.holder_identity.as_deref() != Some(&self.config.identity) {
            return Ok(None);
        }
        spec.renew_time = Some(MicroTime(Utc::now()));
        let epoch = spec.lease_transitions.unwrap_or(1).max(1) as u64;
        match leases
            .replace(&self.config.lease_name, &PostParams::default(), &lease)
            .await
        {
            Ok(_) => Ok(Some(epoch)),
            Err(kube::Error::Api(error)) if error.code == 409 => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    async fn release(&self) {
        let leases = self.leases().await;
        let Ok(mut lease) = leases.get(&self.config.lease_name).await else {
            return;
        };
        let Some(spec) = lease.spec.as_mut() else {
            return;
        };
        if spec.holder_identity.as_deref() != Some(&self.config.identity) {
            return;
        }
        spec.holder_identity = None;
        spec.renew_time = Some(MicroTime(Utc::now()));
        let _ = leases
            .replace(&self.config.lease_name, &PostParams::default(), &lease)
            .await;
    }
}

/// The next step when acquiring a Lease that already exists, decided purely from
/// its observed state. This is the split-brain guard: takeover happens only when
/// the Lease is unheld or expired; a live Lease held by a different identity is
/// yielded to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AcquireStep {
    /// We already hold it; refresh the renewal timestamp.
    Renew,
    /// A different identity holds a live Lease; stand by.
    Yield,
    /// The Lease is unheld or expired; contend for it.
    Takeover,
}

fn acquire_step(
    spec: &LeaseSpec,
    identity: &str,
    lease_duration: Duration,
    now: DateTime<Utc>,
) -> AcquireStep {
    let holder = spec.holder_identity.as_deref().unwrap_or("");
    if holder == identity {
        AcquireStep::Renew
    } else if !holder.is_empty() && !lease_expired(spec.renew_time.as_ref(), lease_duration, now) {
        AcquireStep::Yield
    } else {
        AcquireStep::Takeover
    }
}

/// Whether a Lease last renewed at `renew_time` has expired by `now` given
/// `lease_duration`. A missing renewal timestamp is treated as expired, and an
/// out-of-range `lease_duration` falls back to 15s (matching Kubernetes' own
/// default lease duration) so a bogus configuration can never make a stale
/// Lease look live — which would risk two concurrent leaders.
fn lease_expired(
    renew_time: Option<&MicroTime>,
    lease_duration: Duration,
    now: DateTime<Utc>,
) -> bool {
    let Some(renewed) = renew_time else {
        return true;
    };
    now > renewed.0
        + chrono::Duration::from_std(lease_duration)
            .unwrap_or_else(|_| chrono::Duration::seconds(15))
}

/// The monotonic fencing epoch to stamp when taking over a Lease: strictly
/// greater than the observed transition count and always at least 1. This value
/// becomes the xDS authority epoch, so it must never regress — a regression
/// would let a superseded leader's guards validate against a new authority.
fn next_takeover_epoch(current_transitions: Option<i32>) -> i32 {
    current_transitions.unwrap_or(0).saturating_add(1).max(1)
}

async fn set_leader_label(client: &Client, namespace: &str, pod_name: &str, leader: bool) -> bool {
    let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
    let value = if leader { json!("true") } else { json!(null) };
    let patch = json!({ "metadata": { "labels": { LEADER_LABEL: value } } });
    for attempt in 1..=3 {
        match pods
            .patch(pod_name, &PatchParams::default(), &Patch::Merge(&patch))
            .await
        {
            Ok(_) => return true,
            Err(error) => {
                warn!(attempt, %error, "failed to update Agent Gateway leader label");
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
        }
    }
    false
}

#[cfg(test)]
#[path = "../../tests/unit/leader_test.rs"]
mod tests;
