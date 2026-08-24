//! xDS leader coordination for K8s multi-replica mode.
//!
//! In `ha_mode=multi`, task scheduling is leaderless (all replicas active,
//! coordinated via Redis). But the Envoy xDS control plane is *stateful* — each
//! replica holds its own in-memory LDS state and each Envoy DaemonSet pod
//! connects (via a Service) to a random replica. If Envoys spread across
//! replicas, listeners created on replica A never reach an Envoy bound to
//! replica B → wrong-node NACKs and missing egress sockets.
//!
//! This module elects a single **xDS leader** using a dedicated K8s Lease
//! (independent of any scheduling leadership) and labels the leader's Pod with
//! `joysafeter-xds-leader=true`. A leader-only Service selects that label, so
//! every Envoy connects to exactly one replica — a single authoritative xDS
//! source, the same pattern kube-scheduler uses. Task scheduling and runner
//! bridges keep using the load-balanced Service across all replicas.
//!
//! Only active in K8s + multi mode. Docker/standalone/leader modes never call
//! this (Docker has one Envoy and one xDS source already).

use std::sync::Arc;
use std::time::Duration;

use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, Patch, PatchParams};
use kube::Client;
use serde_json::json;
use tokio::task::JoinHandle;
use tracing::{info, warn};

use super::leader_election::LeaderElection;
use super::xds_authority::XdsAuthorityState;
use crate::sandbox::lds_backend::DeltaXdsServer;

/// Pod label that the leader-only xDS Service selects on.
pub const XDS_LEADER_LABEL: &str = "joysafeter-xds-leader";

/// Handle to proactively hand off xDS leadership on graceful shutdown.
/// Revoking the authority and disabling ADS actively closes established xDS
/// streams; removing the label stops new Service routing, and releasing the
/// Lease lets a peer take over without waiting for lease expiry.
pub struct XdsLeaderHandle {
    election: Arc<LeaderElection>,
    authority: XdsAuthorityState,
    xds_service: Arc<DeltaXdsServer>,
    client: Client,
    namespace: String,
    pod_name: String,
    election_task: JoinHandle<()>,
    coordinator_task: JoinHandle<()>,
}

impl XdsLeaderHandle {
    pub fn authority(&self) -> XdsAuthorityState {
        self.authority.clone()
    }

    /// Best-effort graceful hand-off: fence mutations, close ADS streams,
    /// remove the Service endpoint, then release the Lease.
    pub async fn shutdown(&self) {
        self.coordinator_task.abort();
        self.authority.revoke();
        self.xds_service.set_serving(false);
        self.election_task.abort();
        set_leader_label(&self.client, &self.namespace, &self.pod_name, false).await;
        self.election.release().await;
        info!(pod = %self.pod_name, "xDS leadership handed off on shutdown");
    }
}

/// Spawn the xDS leader coordinator. Returns a handle for graceful hand-off.
/// The election and label reconciliation run in the background. Non-fatal: on
/// any error the pod simply may not become/refresh the label and Envoys keep
/// their last config (already-established egress is unaffected).
pub fn spawn(
    client: Client,
    xds_service: Arc<DeltaXdsServer>,
    namespace: String,
    pod_name: String,
    lease_name: String,
    identity: String,
    lease_duration: Duration,
    renew_interval: Duration,
) -> XdsLeaderHandle {
    let authority = XdsAuthorityState::managed();
    xds_service.set_serving(false);
    let election = Arc::new(LeaderElection::new(
        client.clone(),
        &namespace,
        &lease_name,
        &identity,
        lease_duration,
        renew_interval,
    ));
    let election_task = election.clone().spawn();
    let coordinator_election = election.clone();
    let coordinator_client = client.clone();
    let coordinator_namespace = namespace.clone();
    let coordinator_pod_name = pod_name.clone();
    let coordinator_authority = authority.clone();
    let coordinator_xds_service = xds_service.clone();
    let coordinator_task = tokio::spawn(async move {
        info!(
            identity = %identity,
            lease = %lease_name,
            "xDS leader coordinator started (K8s multi mode)"
        );
        let mut authority_epoch = None;
        let mut labeled_for_xds = None;
        let mut last_successful_reconcile = tokio::time::Instant::now()
            .checked_sub(Duration::from_secs(10))
            .unwrap_or_else(tokio::time::Instant::now);
        loop {
            let lease_held = coordinator_election.is_leader();
            if lease_held {
                if authority_epoch.is_none() {
                    let guard = coordinator_authority.advertise();
                    authority_epoch = Some(guard.epoch());
                    info!(
                        pod = %coordinator_pod_name,
                        epoch = guard.epoch(),
                        "Acquired xDS Lease; recovering authority state before advertising"
                    );
                }
            } else if authority_epoch.take().is_some() {
                coordinator_authority.revoke();
                coordinator_xds_service.set_serving(false);
            }
            let desired_serving = should_serve_xds(lease_held, coordinator_authority.is_ready());
            if !desired_serving {
                coordinator_xds_service.set_serving(false);
            }
            let periodic_reconcile = last_successful_reconcile.elapsed() >= Duration::from_secs(10);
            if labeled_for_xds != Some(desired_serving) || periodic_reconcile {
                if desired_serving {
                    coordinator_xds_service.set_serving(true);
                }
                if set_leader_label(
                    &coordinator_client,
                    &coordinator_namespace,
                    &coordinator_pod_name,
                    desired_serving,
                )
                .await
                {
                    if desired_serving
                        && (!coordinator_election.is_leader() || !coordinator_authority.is_ready())
                    {
                        coordinator_xds_service.set_serving(false);
                        coordinator_authority.revoke();
                        authority_epoch = None;
                        let removed = set_leader_label(
                            &coordinator_client,
                            &coordinator_namespace,
                            &coordinator_pod_name,
                            false,
                        )
                        .await;
                        labeled_for_xds = removed.then_some(false);
                        warn!(pod = %coordinator_pod_name, "xDS authority changed while publishing leader endpoint");
                    } else {
                        if labeled_for_xds != Some(desired_serving) {
                            if desired_serving {
                                info!(pod = %coordinator_pod_name, "xDS authority recovered — labeled pod for leader-only Service");
                            } else {
                                warn!(pod = %coordinator_pod_name, "Not xDS authority — removed stale leader label");
                            }
                        } else {
                            debug_assert_eq!(coordinator_xds_service.is_serving(), desired_serving);
                        }
                        labeled_for_xds = Some(desired_serving);
                        last_successful_reconcile = tokio::time::Instant::now();
                    }
                } else if desired_serving {
                    coordinator_xds_service.set_serving(false);
                }
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    });

    XdsLeaderHandle {
        election,
        authority,
        xds_service,
        client,
        namespace,
        pod_name,
        election_task,
        coordinator_task,
    }
}

fn should_serve_xds(lease_held: bool, authority_ready: bool) -> bool {
    lease_held && authority_ready
}

/// Patch the pod's `joysafeter-xds-leader` label. `true` sets it to "true";
/// `false` removes it (JSON-merge null deletes the key). Best-effort with a
/// couple of retries — a transient API error must not wedge the coordinator.
async fn set_leader_label(client: &Client, namespace: &str, pod_name: &str, leader: bool) -> bool {
    let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
    let value = if leader { json!("true") } else { json!(null) };
    let patch = json!({ "metadata": { "labels": { XDS_LEADER_LABEL: value } } });
    let params = PatchParams::default();
    for attempt in 0..3 {
        match pods.patch(pod_name, &params, &Patch::Merge(&patch)).await {
            Ok(_) => return true,
            Err(e) => {
                warn!(
                    pod = %pod_name,
                    attempt,
                    error = %e,
                    "Failed to patch xDS leader label; retrying"
                );
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::should_serve_xds;

    #[test]
    fn xds_service_requires_lease_and_recovered_authority() {
        assert!(!should_serve_xds(false, false));
        assert!(!should_serve_xds(false, true));
        assert!(!should_serve_xds(true, false));
        assert!(should_serve_xds(true, true));
    }
}
