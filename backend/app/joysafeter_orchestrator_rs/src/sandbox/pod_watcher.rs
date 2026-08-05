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

/// Label selector identifying sandbox pods. Must match the label applied in
/// `K8sProvider::build_manifest`.
const SANDBOX_LABEL_SELECTOR: &str = "app.kubernetes.io/name=joysafeter-sandbox";

/// Cached pod state — lightweight subset of full Pod object.
#[derive(Clone, Debug)]
struct CachedPod {
    name: String,
    phase: String,
    image: String,
    labels: HashMap<String, String>,
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
        Some(Self {
            name,
            phase,
            image,
            labels,
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
    pub fn new(client: Client, namespace: &str) -> Self {
        let cache = Arc::new(RwLock::new(HashMap::new()));
        let pods: Api<Pod> = Api::namespaced(client, namespace);
        tokio::spawn(Self::watch_loop(pods, cache.clone()));
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

    /// List all active sandbox pods (from cache, zero API calls).
    pub async fn list_active(&self) -> Vec<ProviderSandboxInfo> {
        let cache = self.cache.read().await;
        cache.values().map(|pod| pod.to_info()).collect()
    }

    /// Background watch loop — maintains the cache via K8s Watch events.
    async fn watch_loop(pods: Api<Pod>, cache: Arc<RwLock<HashMap<String, CachedPod>>>) {
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
                    Ok(Some(event)) => Self::handle_event(&cache, &mut staging, event).await,
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
    ) {
        match event {
            Event::Apply(pod) => {
                if let Some(cached) = CachedPod::from_pod(&pod) {
                    debug!(pod = %cached.name, phase = %cached.phase, "PodWatcher: pod updated");
                    cache.write().await.insert(cached.name.clone(), cached);
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
}
