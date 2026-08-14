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

/// Pod label that the leader-only xDS Service selects on.
pub const XDS_LEADER_LABEL: &str = "joysafeter-xds-leader";

/// Handle to proactively hand off xDS leadership on graceful shutdown.
/// Removing the label immediately drops this pod from the leader-only Service
/// endpoint, and releasing the Lease lets a peer take over within seconds
/// instead of waiting for the ~lease-duration expiry.
pub struct XdsLeaderHandle {
    election: Arc<LeaderElection>,
    client: Client,
    namespace: String,
    pod_name: String,
    election_task: JoinHandle<()>,
    coordinator_task: JoinHandle<()>,
}

impl XdsLeaderHandle {
    /// Best-effort graceful hand-off: drop the pod label so the xDS Service
    /// stops routing to us, then release the Lease so a peer wins immediately.
    pub async fn shutdown(&self) {
        self.coordinator_task.abort();
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
    namespace: String,
    pod_name: String,
    lease_name: String,
    identity: String,
    lease_duration: Duration,
    renew_interval: Duration,
) -> XdsLeaderHandle {
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
    let coordinator_task = tokio::spawn(async move {
        info!(
            identity = %identity,
            lease = %lease_name,
            "xDS leader coordinator started (K8s multi mode)"
        );
        let mut advertised_leader = None;
        let mut last_successful_reconcile = tokio::time::Instant::now()
            .checked_sub(Duration::from_secs(10))
            .unwrap_or_else(tokio::time::Instant::now);
        loop {
            let desired_leader = coordinator_election.is_leader();
            let periodic_reconcile = last_successful_reconcile.elapsed() >= Duration::from_secs(10);
            if advertised_leader != Some(desired_leader) || periodic_reconcile {
                if set_leader_label(
                    &coordinator_client,
                    &coordinator_namespace,
                    &coordinator_pod_name,
                    desired_leader,
                )
                .await
                {
                    if advertised_leader != Some(desired_leader) {
                        if desired_leader {
                            info!(pod = %coordinator_pod_name, "Became xDS leader — labeled pod for leader-only Service");
                        } else {
                            warn!(pod = %coordinator_pod_name, "Not xDS leader — removed stale leader label");
                        }
                    }
                    advertised_leader = Some(desired_leader);
                    last_successful_reconcile = tokio::time::Instant::now();
                }
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    });

    XdsLeaderHandle {
        election,
        client,
        namespace,
        pod_name,
        election_task,
        coordinator_task,
    }
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
