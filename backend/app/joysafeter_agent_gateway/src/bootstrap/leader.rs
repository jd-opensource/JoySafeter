//! Kubernetes Lease fencing for the stateful ADS/management projection.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

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
    /// Local monotonic instant of the last confirmed lease renewal (or promotion).
    /// Renewal failures only demote the leader once this exceeds `lease_duration`,
    /// so a transient kube-apiserver hiccup no longer flaps leadership. (Bug 1)
    last_renew_ok: Mutex<Instant>,
    /// Client-go style liveness tracking for a *foreign* Lease holder: the last
    /// `renewTime` we observed and the local instant we first saw it. Expiry is
    /// measured from the local monotonic instant, never by comparing the holder's
    /// wall-clock timestamp against ours — immune to cross-node clock skew. (Bug 2)
    observed_renew: Mutex<Option<(MicroTime, Instant)>>,
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
        last_renew_ok: Mutex::new(Instant::now()),
        observed_renew: Mutex::new(None),
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
                Ok(Some(epoch)) => {
                    if !self.leading.swap(true, Ordering::AcqRel) {
                        // Transition standby → leader.
                        if let Err(error) = self.promote(epoch).await {
                            warn!(%error, "failed to promote Agent Gateway leader");
                            self.leading.store(false, Ordering::Release);
                            self.demote().await;
                            self.release().await;
                        } else {
                            self.mark_renewed();
                        }
                    } else {
                        // Renewal succeeded while already leading.
                        self.mark_renewed();
                    }
                }
                // No lease held, or a transient Lease API failure.
                other => {
                    let err_msg = match &other {
                        Err(error) => Some(error.to_string()),
                        _ => None,
                    };
                    if self.leading.load(Ordering::Acquire) {
                        // Bug 1: only demote once we have genuinely failed to renew
                        // for a full lease_duration. A single kube-apiserver blip or
                        // 409 conflict must not flap leadership (which would empty the
                        // leader-only Service endpoint and break orchestrator → gateway).
                        let elapsed = { *self.last_renew_ok.lock().unwrap() }.elapsed();
                        if elapsed >= self.config.lease_duration {
                            warn!(
                                elapsed_ms = elapsed.as_millis(),
                                err = ?err_msg,
                                "Agent Gateway Lease renewal deadline exceeded; demoting leader"
                            );
                            self.leading.store(false, Ordering::Release);
                            self.demote().await;
                        } else {
                            warn!(
                                elapsed_ms = elapsed.as_millis(),
                                err = ?err_msg,
                                "transient Agent Gateway Lease renewal failure; retaining leadership"
                            );
                        }
                    } else if let Some(error) = err_msg {
                        warn!(%error, "Agent Gateway Lease acquire failed");
                    }
                }
            }
            tokio::time::sleep(self.config.renew_interval).await;
        }
    }

    fn mark_renewed(&self) {
        *self.last_renew_ok.lock().unwrap() = Instant::now();
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
        // Bug 3: promotion above (snapshot fetch, inventory install, validation) can
        // take non-trivial time. Before advertising this Pod as the ADS/management
        // leader, re-confirm the Lease still names us at the same fencing epoch. If a
        // slow promotion was superseded by another replica, publishing the leader
        // label here would add a second Service endpoint and split ADS traffic.
        if !self.still_holding(lease_epoch).await {
            anyhow::bail!(
                "Agent Gateway Lease was superseded during promotion (epoch {lease_epoch}); aborting"
            );
        }
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
                match self.classify_acquire(spec) {
                    // `try_acquire` only runs while this coordinator considers
                    // itself non-leading. If the Lease still names this Pod,
                    // it belongs to a previous local leadership term (for
                    // example after a transient API failure prevented release).
                    // Replacing it as a takeover advances leaseTransitions and
                    // gives the new authority term a fresh fencing epoch.
                    AcquireStep::Reacquire => self.takeover(existing).await,
                    AcquireStep::Yield => Ok(None),
                    AcquireStep::Takeover => self.takeover(existing).await,
                }
            }
            Err(kube::Error::Api(error)) if error.code == 404 => self.create().await,
            Err(error) => Err(error.into()),
        }
    }

    /// Decide the acquire step, using monotonic observed-time as the authoritative
    /// liveness signal for a *foreign* holder (Bug 2). `acquire_step` still encodes
    /// the identity routing (self → Reacquire, unheld → Takeover) and the wall-clock
    /// view; observed-time then overrides the foreign-holder verdict in both
    /// directions:
    ///   * wall-clock says expired but the holder is still renewing per our local
    ///     clock (fast local clock) → Yield, preventing a skew-induced split brain;
    ///   * wall-clock says live but the holder stopped renewing per our local clock
    ///     (slow local clock) → Takeover, so failover is not indefinitely delayed.
    fn classify_acquire(&self, spec: &LeaseSpec) -> AcquireStep {
        let now = Utc::now();
        let holder = spec.holder_identity.as_deref().unwrap_or("");
        match acquire_step(spec, &self.config.identity, self.config.lease_duration, now) {
            AcquireStep::Reacquire => {
                self.reset_observed();
                AcquireStep::Reacquire
            }
            AcquireStep::Takeover if holder.is_empty() || holder == self.config.identity => {
                self.reset_observed();
                AcquireStep::Takeover
            }
            // Foreign holder in either verdict → observed-time is authoritative.
            _ => {
                if self.observed_time_expired(spec.renew_time.as_ref()) {
                    AcquireStep::Takeover
                } else {
                    AcquireStep::Yield
                }
            }
        }
    }

    /// Whether a foreign holder has stopped renewing, judged by the local monotonic
    /// clock. Tracks the last observed `renewTime`: when it advances, the holder is
    /// alive and the observation window resets; when it is unchanged for at least
    /// `lease_duration` of local time, the holder is considered dead. A missing
    /// `renewTime` is immediately expired.
    fn observed_time_expired(&self, renew_time: Option<&MicroTime>) -> bool {
        let mut guard = self.observed_renew.lock().unwrap();
        observed_expiry_step(&mut guard, renew_time, Instant::now(), self.config.lease_duration)
    }

    fn reset_observed(&self) {
        *self.observed_renew.lock().unwrap() = None;
    }

    /// Whether the Lease still names this identity at the given fencing epoch.
    /// Used as a promotion guard (Bug 3); any read failure is treated as "not held"
    /// so promotion aborts rather than risk a second advertised leader.
    async fn still_holding(&self, epoch: u64) -> bool {
        match self.leases().await.get(&self.config.lease_name).await {
            Ok(lease) => lease
                .spec
                .map(|spec| {
                    let holds = spec.holder_identity.as_deref() == Some(&self.config.identity);
                    let same_epoch =
                        spec.lease_transitions.map(|t| t.max(1) as u64) == Some(epoch);
                    holds && same_epoch
                })
                .unwrap_or(false),
            Err(_) => false,
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
    /// The Lease still names this identity while the local coordinator is not
    /// leading. Reacquire it with a fresh transition epoch so guards from the
    /// revoked local term can never become valid again.
    Reacquire,
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
        AcquireStep::Reacquire
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

/// Pure core of the monotonic observed-time liveness check (Bug 2). `state` is the
/// last `(renewTime, local instant seen)` observation, updated in place. Returns
/// whether the foreign holder is considered expired:
///   * no `renewTime` → expired (and observation cleared);
///   * `renewTime` advanced vs the last observation → alive, window reset;
///   * `renewTime` unchanged for ≥ `lease_duration` of local time → expired.
/// Crucially it never compares the holder-written wall clock to the local clock,
/// so cross-node clock skew cannot make a live Lease look dead or vice versa.
fn observed_expiry_step(
    state: &mut Option<(MicroTime, Instant)>,
    renew_time: Option<&MicroTime>,
    now: Instant,
    lease_duration: Duration,
) -> bool {
    match renew_time {
        None => {
            *state = None;
            true
        }
        Some(rt) => match state {
            Some((seen_rt, seen_at)) if seen_rt == rt => now.duration_since(*seen_at) >= lease_duration,
            _ => {
                *state = Some((rt.clone(), now));
                false
            }
        },
    }
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
