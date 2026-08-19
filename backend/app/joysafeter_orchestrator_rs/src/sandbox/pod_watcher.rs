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
use crate::ids::SandboxId;

/// Label selector identifying sandbox pods. Must match the label applied in
/// `K8sProvider::build_manifest`.
const SANDBOX_LABEL_SELECTOR: &str = "app.kubernetes.io/name=joysafeter-sandbox";

/// Pod label carrying the sandbox UUID. Must match the label set in
/// `K8sProvider::build_manifest` / `sandbox_resolver` (`joysafeter.sandbox_id`).
const SANDBOX_ID_LABEL: &str = "joysafeter.sandbox_id";

/// Callback invoked the first time a sandbox pod's node assignment becomes
/// known. In K8s this is wired to [`DeltaXdsServer::set_sandbox_node`] so
/// node-aware xDS filtering can deliver the sandbox's Envoy listener the instant
/// the scheduler binds the pod — instead of waiting on the `setup_networking`
/// poll or the networking reconcile loop. Idempotent downstream, so re-invoking
/// with an unchanged mapping is harmless.
pub type NodeLearnedHook = Arc<dyn Fn(SandboxId, String) + Send + Sync>;

/// Cached pod state — lightweight subset of full Pod object.
#[derive(Clone, Debug)]
struct CachedPod {
    name: String,
    phase: String,
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
    /// `on_node_learned` (if provided) is invoked the first time each sandbox
    /// pod's node assignment becomes known, so node-aware xDS filtering can
    /// deliver the sandbox's egress listener immediately (see [`NodeLearnedHook`]).
    pub fn new(client: Client, namespace: &str, on_node_learned: Option<NodeLearnedHook>) -> Self {
        let cache = Arc::new(RwLock::new(HashMap::new()));
        let pods: Api<Pod> = Api::namespaced(client, namespace);
        tokio::spawn(Self::watch_loop(pods, cache.clone(), on_node_learned));
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

    /// Get the K8s node name where a pod is scheduled (from cache).
    pub async fn node_name(&self, pod_name: &str) -> Option<String> {
        let cache = self.cache.read().await;
        cache.get(pod_name).and_then(|pod| pod.node_name.clone())
    }

    /// List all active sandbox pods (from cache, zero API calls).
    pub async fn list_active(&self) -> Vec<ProviderSandboxInfo> {
        let cache = self.cache.read().await;
        cache.values().map(|pod| pod.to_info()).collect()
    }

    /// Background watch loop — maintains the cache via K8s Watch events.
    async fn watch_loop(
        pods: Api<Pod>,
        cache: Arc<RwLock<HashMap<String, CachedPod>>>,
        on_node_learned: Option<NodeLearnedHook>,
    ) {
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
                match stream.try_next().await {
                    Ok(Some(event)) => {
                        Self::handle_event(&cache, &mut staging, event, on_node_learned.as_ref())
                            .await
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
                }
            }
        }
    }

    async fn handle_event(
        cache: &Arc<RwLock<HashMap<String, CachedPod>>>,
        staging: &mut HashMap<String, CachedPod>,
        event: Event<Pod>,
        on_node_learned: Option<&NodeLearnedHook>,
    ) {
        match event {
            Event::Apply(pod) => {
                if let Some(cached) = CachedPod::from_pod(&pod) {
                    debug!(pod = %cached.name, phase = %cached.phase, "PodWatcher: pod updated");
                    // Register the node only on the None→Some transition (the
                    // moment the scheduler binds the pod), so node-aware xDS
                    // filtering delivers the listener without waiting on the
                    // setup_networking poll. Snapshot for the hook only in that
                    // rare branch; otherwise move `cached` into the cache with no
                    // clone. The write guard is dropped before the hook runs (the
                    // hook touches xDS state, not this cache).
                    let register = {
                        let mut guard = cache.write().await;
                        let was_known = guard
                            .get(&cached.name)
                            .and_then(|p| p.node_name.as_ref())
                            .is_some();
                        let now_known = cached.node_name.is_some();
                        let register = (now_known && !was_known).then(|| cached.clone());
                        guard.insert(cached.name.clone(), cached);
                        register
                    };
                    if let Some(cached) = register {
                        Self::maybe_register_node(&cached, on_node_learned);
                    }
                }
            }
            Event::Delete(pod) => {
                if let Some(name) = pod.metadata.name.as_ref() {
                    debug!(pod = %name, "PodWatcher: pod deleted");
                    cache.write().await.remove(name);
                }
            }
            Event::Init => staging.clear(),
            Event::InitApply(pod) => {
                if let Some(cached) = CachedPod::from_pod(&pod) {
                    // On a re-list (watch reconnect), re-register any already-
                    // scheduled sandbox's node. `set_sandbox_node` is idempotent,
                    // so re-firing for unchanged mappings is harmless.
                    Self::maybe_register_node(&cached, on_node_learned);
                    staging.insert(cached.name.clone(), cached);
                }
            }
            Event::InitDone => {
                let mut c = cache.write().await;
                std::mem::swap(&mut *c, staging);
                staging.clear();
                info!(pod_count = c.len(), "PodWatcher: cache synced");
            }
        }
    }

    /// Invoke `on_node_learned` when a pod is scheduled (has a node) and carries a
    /// parseable `joysafeter.sandbox_id` label. Mirrors the bulk mapping rebuild
    /// in `K8sProvider::on_startup`.
    fn maybe_register_node(cached: &CachedPod, on_node_learned: Option<&NodeLearnedHook>) {
        let (Some(hook), Some(node)) = (on_node_learned, cached.node_name.as_deref()) else {
            return;
        };
        let Some(id_str) = cached.labels.get(SANDBOX_ID_LABEL) else {
            return;
        };
        match id_str.parse::<uuid::Uuid>() {
            Ok(uuid) => hook(SandboxId::from_uuid(uuid), node.to_string()),
            Err(e) => debug!(
                pod = %cached.name,
                sandbox_id = %id_str,
                error = %e,
                "PodWatcher: skipping node registration; sandbox_id label is not a UUID"
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::Mutex;

    type Calls = Arc<Mutex<Vec<(SandboxId, String)>>>;

    fn recording_hook() -> (NodeLearnedHook, Calls) {
        let calls: Calls = Arc::new(Mutex::new(Vec::new()));
        let sink = calls.clone();
        let hook: NodeLearnedHook = Arc::new(move |id, node| sink.lock().unwrap().push((id, node)));
        (hook, calls)
    }

    /// Build a sandbox Pod carrying the `joysafeter.sandbox_id` label, optionally
    /// already bound to a node. `containers: []` is required for PodSpec to
    /// deserialize.
    fn sandbox_pod(name: &str, sandbox_uuid: &str, node: Option<&str>) -> Pod {
        let mut spec = json!({ "containers": [] });
        if let Some(node) = node {
            spec["nodeName"] = json!(node);
        }
        serde_json::from_value(json!({
            "metadata": {
                "name": name,
                "labels": { "joysafeter.sandbox_id": sandbox_uuid }
            },
            "spec": spec
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
    async fn apply_with_node_fires_hook_once_on_transition() {
        let uuid = uuid::Uuid::now_v7();
        let (hook, calls) = recording_hook();
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
            Some(&hook),
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
            Some(&hook),
        )
        .await;

        let calls = calls.lock().unwrap();
        assert_eq!(
            calls.len(),
            1,
            "hook should fire once on the None→Some node transition, not on every Apply"
        );
        assert_eq!(calls[0].0.as_uuid(), uuid);
        assert_eq!(calls[0].1, "node-a");
    }

    #[tokio::test]
    async fn apply_without_node_defers_until_scheduled() {
        let uuid = uuid::Uuid::now_v7();
        let (hook, calls) = recording_hook();
        let (cache, mut staging) = empty_state();

        // Unscheduled pod (no nodeName) → hook must NOT fire.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod("joysafeter-y", &uuid.to_string(), None)),
            Some(&hook),
        )
        .await;
        assert!(
            calls.lock().unwrap().is_empty(),
            "no node yet → no registration"
        );

        // Scheduler binds it → hook fires now.
        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::Apply(sandbox_pod(
                "joysafeter-y",
                &uuid.to_string(),
                Some("node-b"),
            )),
            Some(&hook),
        )
        .await;
        let calls = calls.lock().unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].0.as_uuid(), uuid);
        assert_eq!(calls[0].1, "node-b");
    }

    #[tokio::test]
    async fn init_apply_registers_scheduled_pod_on_relist() {
        let uuid = uuid::Uuid::now_v7();
        let (hook, calls) = recording_hook();
        let (cache, mut staging) = empty_state();

        PodWatcher::handle_event(
            &cache,
            &mut staging,
            Event::InitApply(sandbox_pod(
                "joysafeter-z",
                &uuid.to_string(),
                Some("node-c"),
            )),
            Some(&hook),
        )
        .await;

        let calls = calls.lock().unwrap();
        assert_eq!(
            calls.len(),
            1,
            "re-list should re-register a scheduled sandbox"
        );
        assert_eq!(calls[0].0.as_uuid(), uuid);
        assert_eq!(calls[0].1, "node-c");
    }

    #[tokio::test]
    async fn apply_with_non_uuid_label_does_not_fire() {
        let (hook, calls) = recording_hook();
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
            Some(&hook),
        )
        .await;

        assert!(
            calls.lock().unwrap().is_empty(),
            "a non-UUID sandbox_id label must not register a node"
        );
    }
}
