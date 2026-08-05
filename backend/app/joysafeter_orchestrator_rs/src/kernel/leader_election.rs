//! Production-grade K8s Lease-based Leader Election.
//!
//! Uses `coordination.k8s.io/v1.Lease` objects via kube-rs for strong-consistency
//! leader election backed by etcd (Raft). This is the same mechanism Kubernetes
//! itself uses for kube-controller-manager and kube-scheduler HA.
//!
//! Fencing guarantees:
//! - All Lease mutations carry `resourceVersion` (optimistic lock). A stale leader
//!   that attempts to renew after being superseded gets 409 Conflict → immediate
//!   demotion.
//! - On demotion the leader stops all write services (scheduler, controller) before
//!   releasing readiness, ensuring no split-brain writes.
//! - DB-level CAS (`claim_pending_task`, `attach_sandbox_to_task`) serves as the
//!   ultimate fence even if the Lease layer has a transient gap.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use k8s_openapi::api::coordination::v1::{Lease, LeaseSpec};
use k8s_openapi::apimachinery::pkg::apis::meta::v1::MicroTime;
use kube::api::{Api, ObjectMeta, PostParams};
use kube::Client;
use tokio::sync::Notify;
use tracing::{debug, error, info, warn};

/// Leader election state.
#[derive(Clone)]
pub struct LeaderElection {
    client: Client,
    namespace: String,
    lease_name: String,
    identity: String,
    lease_duration: Duration,
    renew_interval: Duration,
    leading: Arc<AtomicBool>,
    acquired: Arc<Notify>,
    lost: Arc<Notify>,
}

impl LeaderElection {
    pub fn new(
        client: Client,
        namespace: &str,
        lease_name: &str,
        identity: &str,
        lease_duration: Duration,
        renew_interval: Duration,
    ) -> Self {
        Self {
            client,
            namespace: namespace.to_string(),
            lease_name: lease_name.to_string(),
            identity: identity.to_string(),
            lease_duration,
            renew_interval,
            leading: Arc::new(AtomicBool::new(false)),
            acquired: Arc::new(Notify::new()),
            lost: Arc::new(Notify::new()),
        }
    }

    pub fn is_leader(&self) -> bool {
        self.leading.load(Ordering::Acquire)
    }

    /// Block until this instance becomes leader.
    pub async fn wait_until_leading(&self) {
        if self.is_leader() {
            return;
        }
        self.acquired.notified().await;
    }

    /// Block until leadership is lost (for the leader to react).
    pub async fn wait_until_lost(&self) {
        if !self.is_leader() {
            return;
        }
        self.lost.notified().await;
    }

    /// Graceful release — call on SIGTERM. Clears holderIdentity so standby
    /// can acquire immediately (no need to wait TTL expiry).
    pub async fn release(&self) {
        if !self.leading.swap(false, Ordering::Release) {
            return; // already not leader
        }
        info!(identity = %self.identity, "Releasing leadership (graceful shutdown)");
        let leases: Api<Lease> = Api::namespaced(self.client.clone(), &self.namespace);
        match leases.get(&self.lease_name).await {
            Ok(mut lease) => {
                if let Some(ref spec) = lease.spec {
                    if spec.holder_identity.as_deref() == Some(&self.identity) {
                        let spec_mut = lease.spec.as_mut().unwrap();
                        spec_mut.holder_identity = None;
                        spec_mut.renew_time = Some(MicroTime(Utc::now()));
                        let _ = leases
                            .replace(&self.lease_name, &PostParams::default(), &lease)
                            .await;
                    }
                }
            }
            Err(e) => warn!(error = %e, "Failed to release Lease on shutdown"),
        }
        self.lost.notify_waiters();
    }

    /// Spawn the leader election loop as a background task.
    pub fn spawn(self: Arc<Self>) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            self.run().await;
        })
    }

    async fn run(&self) {
        loop {
            if self.is_leader() {
                // Renew loop
                tokio::time::sleep(self.renew_interval).await;
                match self.try_renew().await {
                    Ok(true) => {
                        debug!(identity = %self.identity, "Lease renewed");
                    }
                    Ok(false) | Err(_) => {
                        // Lost leadership
                        warn!(identity = %self.identity, "Lost leadership (renew failed)");
                        self.leading.store(false, Ordering::Release);
                        self.lost.notify_waiters();
                    }
                }
            } else {
                // Candidate: try to acquire
                match self.try_acquire().await {
                    Ok(true) => {
                        info!(identity = %self.identity, "Acquired leadership");
                        self.leading.store(true, Ordering::Release);
                        self.acquired.notify_waiters();
                    }
                    Ok(false) => {
                        debug!(identity = %self.identity, "Lease held by another; retrying");
                        tokio::time::sleep(self.renew_interval).await;
                    }
                    Err(e) => {
                        warn!(identity = %self.identity, error = %e, "Leader election error; retrying");
                        tokio::time::sleep(self.renew_interval).await;
                    }
                }
            }
        }
    }

    async fn leases(&self) -> Api<Lease> {
        Api::namespaced(self.client.clone(), &self.namespace)
    }

    async fn try_acquire(&self) -> anyhow::Result<bool> {
        let leases = self.leases().await;

        match leases.get(&self.lease_name).await {
            Ok(existing) => {
                let default_spec = LeaseSpec::default();
                let spec = existing.spec.as_ref().unwrap_or(&default_spec);
                let holder = spec.holder_identity.as_deref().unwrap_or("");

                // Already mine (crashed and restarted)
                if holder == self.identity {
                    return self.try_renew().await;
                }

                // Someone else holds it — check if expired
                if !holder.is_empty() && !self.is_expired(spec) {
                    return Ok(false); // Still valid, I'm candidate
                }

                // Expired or empty holder → takeover
                self.try_takeover(existing).await
            }
            Err(kube::Error::Api(e)) if e.code == 404 => {
                // Lease doesn't exist → create
                self.try_create().await
            }
            Err(e) => Err(e.into()),
        }
    }

    async fn try_create(&self) -> anyhow::Result<bool> {
        let leases = self.leases().await;
        let now = Utc::now();
        let lease = Lease {
            metadata: ObjectMeta {
                name: Some(self.lease_name.clone()),
                namespace: Some(self.namespace.clone()),
                ..Default::default()
            },
            spec: Some(LeaseSpec {
                holder_identity: Some(self.identity.clone()),
                lease_duration_seconds: Some(self.lease_duration.as_secs() as i32),
                acquire_time: Some(MicroTime(now)),
                renew_time: Some(MicroTime(now)),
                lease_transitions: Some(0),
                ..Default::default()
            }),
        };
        match leases.create(&PostParams::default(), &lease).await {
            Ok(_) => Ok(true),
            Err(kube::Error::Api(e)) if e.code == 409 => Ok(false), // Someone else created first
            Err(e) => Err(e.into()),
        }
    }

    async fn try_takeover(&self, mut existing: Lease) -> anyhow::Result<bool> {
        let spec = existing.spec.get_or_insert_with(LeaseSpec::default);
        let now = Utc::now();
        spec.holder_identity = Some(self.identity.clone());
        spec.acquire_time = Some(MicroTime(now));
        spec.renew_time = Some(MicroTime(now));
        spec.lease_duration_seconds = Some(self.lease_duration.as_secs() as i32);
        spec.lease_transitions = Some(spec.lease_transitions.unwrap_or(0) + 1);

        match self
            .leases()
            .await
            .replace(&self.lease_name, &PostParams::default(), &existing)
            .await
        {
            Ok(_) => Ok(true),
            Err(kube::Error::Api(e)) if e.code == 409 => Ok(false), // Conflict: someone else took over
            Err(e) => Err(e.into()),
        }
    }

    async fn try_renew(&self) -> anyhow::Result<bool> {
        let leases = self.leases().await;
        let mut lease = match leases.get(&self.lease_name).await {
            Ok(l) => l,
            Err(e) => return Err(e.into()),
        };

        let spec = lease.spec.as_mut().unwrap();
        // Verify we still own it
        if spec.holder_identity.as_deref() != Some(&self.identity) {
            return Ok(false); // Someone else took over
        }
        spec.renew_time = Some(MicroTime(Utc::now()));

        match leases
            .replace(&self.lease_name, &PostParams::default(), &lease)
            .await
        {
            Ok(_) => Ok(true),
            Err(kube::Error::Api(e)) if e.code == 409 => {
                // resourceVersion conflict — someone modified the Lease
                warn!("Lease renew 409 Conflict — lost leadership");
                Ok(false)
            }
            Err(e) => Err(e.into()),
        }
    }

    fn is_expired(&self, spec: &LeaseSpec) -> bool {
        let Some(renew_time) = spec.renew_time.as_ref() else {
            return true; // No renew time = treat as expired
        };
        let duration_sec = spec.lease_duration_seconds.unwrap_or(15) as i64;
        let deadline = renew_time.0 + chrono::Duration::seconds(duration_sec);
        Utc::now() > deadline
    }
}
