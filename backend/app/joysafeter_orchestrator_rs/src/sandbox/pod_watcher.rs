//! PodWatcher: K8s Watch-based local pod cache for the K8s sandbox provider.
//!
//! Instead of calling the K8s API server for every `status()` and `list_active()`
//! query (which at 200 sandboxes × 15s sweep = 800+ API calls/minute), the
//! PodWatcher maintains an in-memory cache synchronized via a single K8s Watch
//! stream. This drops API server load for status/list to **zero** after startup.
//!
//! Design (borrowed from Orchard/Microsoft):
//! - One long-lived Watch connection per K8sProvider instance
//! - `kube::runtime::watcher` drives the list-then-watch state machine and
//!   re-lists automatically on timeout/Gone (410); steady-state Apply/Delete
//!   events update the live HashMap in place
//! - A re-list is buffered into a staging map and swapped in atomically, so
//!   readers never observe an empty or half-populated cache mid-resync
//! - `status()` and `list_active()` read the HashMap (no API calls)
//! - Thread-safe via `Arc<RwLock<HashMap>>`

use std::collections::HashMap;
use std::sync::Arc;

use futures::TryStreamExt;
use k8s_openapi::api::core::v1::Pod;
use kube::runtime::watcher::{self, Event};
use kube::{Api, Client};
use tokio::sync::RwLock;
use tracing::{debug, info, warn};

use super::provider::{ProviderSandboxInfo, SandboxStatus};
use super::runtime::{PlacementEvent, PlacementEventSink};
use crate::ids::SandboxId;

/// Label selector identifying sandbox pods. Must match the label applied in
/// `K8sProvider::build_manifest`.
const SANDBOX_LABEL_SELECTOR: &str = "app.kubernetes.io/name=joysafeter-sandbox";

/// Pod label carrying the sandbox UUID. Must match the label set in
/// `K8sProvider::build_manifest` / `sandbox_resolver` (`joysafeter.sandbox_id`).
const SANDBOX_ID_LABEL: &str = "joysafeter.sandbox_id";

/// Cached pod state — lightweight subset of full Pod object.
#[derive(Clone, Debug)]
struct CachedPod {
    name: String,
    phase: String,
    initialized: bool,
    image: String,
    labels: HashMap<String, String>,
    node_name: Option<String>,
}

impl CachedPod {
    fn from_pod(pod: &Pod) -> Option<Self> {
        let name = pod.metadata.name.as_ref()?.clone();
        let phase = pod
            .status
            .as_ref()
            .and_then(|s| s.phase.clone())
            .unwrap_or_else(|| "Unknown".to_string());
        let initialized = phase == "Running"
            || pod
                .status
                .as_ref()
                .and_then(|status| status.conditions.as_ref())
                .is_some_and(|conditions| {
                    conditions.iter().any(|condition| {
                        condition.type_ == "Initialized" && condition.status == "True"
                    })
                });
        let image = pod
            .spec
            .as_ref()
            .and_then(|s| s.containers.first())
            .and_then(|c| c.image.clone())
            .unwrap_or_default();
        let labels = pod
            .metadata
            .labels
            .clone()
            .unwrap_or_default()
            .into_iter()
            .collect::<HashMap<String, String>>();
        let node_name = pod.spec.as_ref().and_then(|s| s.node_name.clone());
        Some(Self {
            name,
            phase,
            initialized,
            image,
            labels,
            node_name,
        })
    }

    fn to_status(&self) -> SandboxStatus {
        match self.phase.as_str() {
            "Running" => SandboxStatus::Running,
            "Pending" => SandboxStatus::Unknown("Pending".to_string()),
            "Succeeded" | "Failed" => SandboxStatus::Stopped,
            other => SandboxStatus::Unknown(other.to_string()),
        }
    }

    fn to_info(&self) -> ProviderSandboxInfo {
        ProviderSandboxInfo {
            id: self.name.clone(),
            name: self.name.clone(),
            status: self.phase.clone(),
            image: self.image.clone(),
            labels: self.labels.clone(),
        }
    }
}

/// Local pod cache backed by a K8s Watch stream.
#[derive(Clone)]
pub struct PodWatcher {
    cache: Arc<RwLock<HashMap<String, CachedPod>>>,
}

impl PodWatcher {
    /// Create a new PodWatcher and spawn the background watch loop.
    ///
    pub fn new(
        client: Client,
        namespace: &str,
        placement_events: Option<PlacementEventSink>,
    ) -> Self {
        let cache = Arc::new(RwLock::new(HashMap::new()));
        let pods: Api<Pod> = Api::namespaced(client, namespace);
        tokio::spawn(Self::watch_loop(pods, cache.clone(), placement_events));
        Self { cache }
    }

    /// Get the status of a specific pod by name (from cache, zero API calls).
    pub async fn status(&self, pod_name: &str) -> SandboxStatus {
        let cache = self.cache.read().await;
        match cache.get(pod_name) {
            Some(pod) => pod.to_status(),
            None => SandboxStatus::NotFound,
        }
    }

    /// Return the assigned node only after the sandbox data plane is initialized.
    pub async fn delivery_node(&self, pod_name: &str) -> Option<String> {
        let cache = self.cache.read().await;
        cache
            .get(pod_name)
            .and_then(CachedPod::delivery_assignment)
            .map(|(_, node)| node)
    }

    /// List all active sandbox pods (from cache, zero API calls).
    pub async fn list_active(&self) -> Vec<ProviderSandboxInfo> {
        let cache = self.cache.read().await;
        cache.values().map(|pod| pod.to_info()).collect()
    }

    pub async fn delivery_ready_assignments(&self) -> HashMap<SandboxId, String> {
        self.cache
            .read()
            .await
            .values()
            .filter_map(CachedPod::delivery_assignment)
            .collect()
    }

    /// Background watch loop — maintains the cache via K8s Watch events.
    async fn watch_loop(
        pods: Api<Pod>,
        cache: Arc<RwLock<HashMap<String, CachedPod>>>,
        placement_events: Option<PlacementEventSink>,
    ) {
        const PLACEMENT_RECONCILE_INTERVAL: std::time::Duration =
            std::time::Duration::from_secs(15);
        let mut cache_synced = false;
        let mut placement_tick = tokio::time::interval(PLACEMENT_RECONCILE_INTERVAL);
        placement_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            info!("PodWatcher: starting watch stream");
            let stream = watcher::watcher(
                pods.clone(),
                watcher::Config::default().labels(SANDBOX_LABEL_SELECTOR),
            );
            let mut stream = Box::pin(stream);

            // Buffers a re-list burst so it can be swapped into the live cache
            // atomically at InitDone (readers never see a partial cache).
            let mut staging: HashMap<String, CachedPod> = HashMap::new();
            loop {
                tokio::select! {
                    event = stream.try_next() => match event {
                        Ok(Some(event)) => {
                            let init_done = matches!(event, Event::InitDone);
                            Self::handle_event(
                                &cache,
                                &mut staging,
                                event,
                                placement_events.as_ref(),
                            )
                            .await;
                            cache_synced |= init_done;
                        }
                        Ok(None) => {
                            info!("PodWatcher: watch stream ended, restarting");
                            break;
                        }
                        Err(e) => {
                            warn!(error = %e, "PodWatcher: watch error, restarting in 5s");
                            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                            break;
                        }
                    },
                    _ = placement_tick.tick(), if cache_synced && placement_events.is_some() => {
                        let assignments = cache
                            .read()
                            .await
                            .values()
                            .filter_map(CachedPod::delivery_assignment)
                            .collect();
                        Self::publish_placement(
                            placement_events.as_ref().expect("guarded above"),
                            PlacementEvent::Reconciled { assignments },
                        )
                        .await;
                    }
                }
            }
        }
    }

    async fn handle_event(
        cache: &Arc<RwLock<HashMap<String, CachedPod>>>,
        staging: &mut HashMap<String, CachedPod>,
        event: Event<Pod>,
        placement_events: Option<&PlacementEventSink>,
    ) {
        match event {
            Event::Apply(pod) => {
                if let Some(cached) = CachedPod::from_pod(&pod) {
                    debug!(pod = %cached.name, phase = %cached.phase, "PodWatcher: pod updated");
                    let observations = {
                        let mut guard = cache.write().await;
                        let previous = guard
                            .get(&cached.name)
                            .and_then(CachedPod::delivery_assignment);
                        let current = cached.delivery_assignment();
                        guard.insert(cached.name.clone(), cached);
                        delivery_node_changes(previous, current)
                    };
                    if let Some(sink) = placement_events {
                        for observation in observations {
                            Self::publish_placement(sink, observation).await;
                        }
                    }
                }
            }
            Event::Delete(pod) => {
                if let Some(name) = pod.metadata.name.as_ref() {
                    debug!(pod = %name, "PodWatcher: pod deleted");
                    let removed = cache
                        .write()
                        .await
                        .remove(name)
                        .and_then(|cached| cached.delivery_assignment());
                    if let (Some(sink), Some((sandbox_id, _))) = (placement_events, removed) {
                        Self::publish_placement(sink, PlacementEvent::Removed { sandbox_id }).await;
                    }
                }
            }
            Event::Init => staging.clear(),
            Event::InitApply(pod) => {
                if let Some(cached) = CachedPod::from_pod(&pod) {
                    staging.insert(cached.name.clone(), cached);
                }
            }
            Event::InitDone => {
                let mut c = cache.write().await;
                std::mem::swap(&mut *c, staging);
                staging.clear();
                let assignments = c
                    .values()
                    .filter_map(CachedPod::delivery_assignment)
                    .collect();
                info!(pod_count = c.len(), "PodWatcher: cache synced");
                drop(c);
                if let Some(sink) = placement_events {
                    Self::publish_placement(sink, PlacementEvent::Reconciled { assignments }).await;
                }
            }
        }
    }

    async fn publish_placement(sink: &PlacementEventSink, event: PlacementEvent) {
        if let Err(error) = sink.publish(event).await {
            warn!(?error, "PodWatcher: placement event sink is unavailable");
        }
    }
}

impl CachedPod {
    fn delivery_assignment(&self) -> Option<(SandboxId, String)> {
        if !self.initialized {
            return None;
        }
        let node = self.node_name.clone()?;
        let Some(id_str) = self.labels.get(SANDBOX_ID_LABEL) else {
            return None;
        };
        match id_str.parse::<uuid::Uuid>() {
            Ok(uuid) => Some((SandboxId::from_uuid(uuid), node)),
            Err(error) => {
                debug!(
                    pod = %self.name,
                    sandbox_id = %id_str,
                    %error,
                    "PodWatcher: skipping node registration; sandbox_id label is not a UUID"
                );
                None
            }
        }
    }
}

fn delivery_node_changes(
    previous: Option<(SandboxId, String)>,
    current: Option<(SandboxId, String)>,
) -> Vec<PlacementEvent> {
    match (previous, current) {
        (Some((previous_id, previous_node)), Some((current_id, current_node)))
            if previous_id == current_id && previous_node == current_node =>
        {
            Vec::new()
        }
        (Some((previous_id, _)), Some((current_id, current_node))) if previous_id == current_id => {
            vec![PlacementEvent::Assigned {
                sandbox_id: current_id,
                node_name: current_node,
            }]
        }
        (Some((previous_id, _)), Some((current_id, current_node))) => {
            vec![
                PlacementEvent::Removed {
                    sandbox_id: previous_id,
                },
                PlacementEvent::Assigned {
                    sandbox_id: current_id,
                    node_name: current_node,
                },
            ]
        }
        (None, Some((sandbox_id, node))) => {
            vec![PlacementEvent::Assigned {
                sandbox_id,
                node_name: node,
            }]
        }
        (Some((sandbox_id, _)), None) => {
            vec![PlacementEvent::Removed { sandbox_id }]
        }
        (None, None) => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    struct PlacementEventProbe {
        receiver: tokio::sync::mpsc::Receiver<PlacementEvent>,
        observed: Vec<PlacementEvent>,
    }

    impl PlacementEventProbe {
        fn observed(&mut self) -> &[PlacementEvent] {
            while let Ok(event) = self.receiver.try_recv() {
                self.observed.push(event);
            }
            &self.observed
        }
    }

    fn recording_sink() -> (PlacementEventSink, PlacementEventProbe) {
        let (sink, receiver) = PlacementEventSink::channel(16);
        (
            sink,
            PlacementEventProbe {
                receiver,
                observed: Vec::new(),
            },
        )
    }

    /// Build a sandbox Pod carrying the `joysafeter.sandbox_id` label, optionally
    /// already bound to a node. `containers: []` is required for PodSpec to
    /// deserialize.
    fn sandbox_pod(name: &str, sandbox_uuid: &str, node: Option<&str>) -> Pod {
        sandbox_pod_with_state(name, sandbox_uuid, node, "Running", None)
    }

    fn sandbox_pod_with_state(
        name: &str,
        sandbox_uuid: &str,
        node: Option<&str>,
        phase: &str,
        initialized: Option<&str>,
    ) -> Pod {
        let mut spec = json!({ "containers": [] });
        if let Some(node) = node {
            spec["nodeName"] = json!(node);
        }
        let mut status = json!({ "phase": phase });
        if let Some(initialized) = initialized {
            status["conditions"] = json!([{
                "type": "Initialized",
                "status": initialized,
                "lastTransitionTime": "2026-08-28T00:00:00Z"
            }]);
        }
        serde_json::from_value(json!({
            "metadata": {
                "name": name,
                "labels": { "joysafeter.sandbox_id": sandbox_uuid }
            },
            "spec": spec,
            "status": status
        }))
        .expect("valid Pod json")
    }

    fn empty_state() -> (
        Arc<RwLock<HashMap<String, CachedPod>>>,
        HashMap<String, CachedPod>,
    ) {
        (Arc::new(RwLock::new(HashMap::new())), HashMap::new())
    }

    #[tokio::test]
    async fn scheduled_pod_is_hidden_until_initialized() {
        let uuid = uuid::Uuid::now_v7();
        let pod_name = "joysafeter-init-barrier";
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();
        let watcher = PodWatcher {
            cache: cache.clone(),
        };

        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod_with_state(
                pod_name,
                &uuid.to_string(),
                Some("node-a"),
                "Pending",
                Some("False"),
            )),
            Some(&sink),
        )
        .await;

        assert_eq!(watcher.delivery_node(pod_name).await, None);
        assert!(probe.observed().is_empty());

        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod_with_state(
                pod_name,
                &uuid.to_string(),
                Some("node-a"),
                "Pending",
                Some("True"),
            )),
            Some(&sink),
        )
        .await;

        assert_eq!(
            watcher.delivery_node(pod_name).await.as_deref(),
            Some("node-a")
        );
        assert!(matches!(
            probe.observed(),
            [PlacementEvent::Assigned { sandbox_id, node_name }]
                if sandbox_id.as_uuid() == uuid && node_name == "node-a"
        ));
    }

    #[test]
    fn running_pod_is_delivery_ready_without_condition_list() {
        let uuid = uuid::Uuid::now_v7();
        let cached = CachedPod::from_pod(&sandbox_pod(
            "joysafeter-running",
            &uuid.to_string(),
            Some("node-a"),
        ))
        .expect("cache pod");

        assert_eq!(
            cached.delivery_assignment(),
            Some((SandboxId::from_uuid(uuid), "node-a".to_string()))
        );
    }

    #[tokio::test]
    async fn apply_with_node_fires_hook_once_on_transition() {
        let uuid = uuid::Uuid::now_v7();
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();

        // First Apply: pod already scheduled (has nodeName) → hook fires once.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-x",
                &uuid.to_string(),
                Some("node-a"),
            )),
            Some(&sink),
        )
        .await;

        // Second Apply: same node (e.g. Pending→Running status change) → no re-fire.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-x",
                &uuid.to_string(),
                Some("node-a"),
            )),
            Some(&sink),
        )
        .await;

        let calls = probe.observed();
        assert_eq!(
            calls.len(),
            1,
            "unchanged ownership must not emit duplicate observations"
        );
        assert!(matches!(
            &calls[0],
            PlacementEvent::Assigned { sandbox_id, node_name }
                if sandbox_id.as_uuid() == uuid && node_name == "node-a"
        ));
    }

    #[tokio::test]
    async fn apply_without_node_defers_until_scheduled() {
        let uuid = uuid::Uuid::now_v7();
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();

        // Unscheduled pod (no nodeName) → hook must NOT fire.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod("joysafeter-y", &uuid.to_string(), None)),
            Some(&sink),
        )
        .await;
        assert!(probe.observed().is_empty(), "no node yet → no registration");

        // Scheduler binds it → hook fires now.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-y",
                &uuid.to_string(),
                Some("node-b"),
            )),
            Some(&sink),
        )
        .await;
        let calls = probe.observed();
        assert_eq!(calls.len(), 1);
        assert!(matches!(
            &calls[0],
            PlacementEvent::Assigned { sandbox_id, node_name }
                if sandbox_id.as_uuid() == uuid && node_name == "node-b"
        ));
    }

    #[tokio::test]
    async fn init_done_emits_one_authoritative_relist() {
        let uuid = uuid::Uuid::now_v7();
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();

        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::InitApply(sandbox_pod(
                "joysafeter-z",
                &uuid.to_string(),
                Some("node-c"),
            )),
            Some(&sink),
        )
        .await;

        assert!(
            probe.observed().is_empty(),
            "partial relist state must never escape before InitDone"
        );

        PodWatcher::handle_event(&cache, &mut staging, Event::InitDone, Some(&sink)).await;

        let calls = probe.observed();
        assert_eq!(calls.len(), 1);
        assert!(matches!(
            &calls[0],
            PlacementEvent::Reconciled { assignments }
                if assignments.get(&SandboxId::from_uuid(uuid)).map(String::as_str)
                    == Some("node-c")
        ));
    }

    #[tokio::test]
    async fn node_move_and_delete_emit_complete_lifecycle() {
        let uuid = uuid::Uuid::now_v7();
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();

        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-move",
                &uuid.to_string(),
                Some("node-a"),
            )),
            Some(&sink),
        )
        .await;
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod_with_state(
                "joysafeter-move",
                &uuid.to_string(),
                Some("node-b"),
                "Pending",
                Some("False"),
            )),
            Some(&sink),
        )
        .await;
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod_with_state(
                "joysafeter-move",
                &uuid.to_string(),
                Some("node-b"),
                "Pending",
                Some("True"),
            )),
            Some(&sink),
        )
        .await;
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Delete(sandbox_pod(
                "joysafeter-move",
                &uuid.to_string(),
                Some("node-b"),
            )),
            Some(&sink),
        )
        .await;

        let calls = probe.observed();
        assert!(matches!(
            &calls[0],
            PlacementEvent::Assigned { node_name, .. } if node_name == "node-a"
        ));
        assert!(matches!(
            &calls[1],
            PlacementEvent::Removed { sandbox_id }
                if sandbox_id.as_uuid() == uuid
        ));
        assert!(matches!(
            &calls[2],
            PlacementEvent::Assigned { node_name, .. } if node_name == "node-b"
        ));
        assert!(matches!(
            &calls[3],
            PlacementEvent::Removed { sandbox_id }
                if sandbox_id.as_uuid() == uuid
        ));
    }

    #[tokio::test]
    async fn apply_with_non_uuid_label_does_not_fire() {
        let (sink, mut probe) = recording_sink();
        let (cache, mut staging) = empty_state();

        // A malformed sandbox_id label (e.g. the `sbx_`-prefixed public form, not
        // the bare UUID) must be skipped gracefully — no hook, no panic.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-bad",
                "sbx_not-a-uuid",
                Some("node-a"),
            )),
            Some(&sink),
        )
        .await;

        assert!(
            probe.observed().is_empty(),
            "a non-UUID sandbox_id label must not register a node"
        );
    }
}
