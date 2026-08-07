//! PodWatcher: K8s Watch-based local pod cache for the K8s sandbox provider.
//!
//! Instead of calling the K8s API server for every `status()` and `list_active()`
//! query (which at 200 sandboxes × 15s sweep = 800+ API calls/minute), the
//! PodWatcher maintains an in-memory cache synchronized via a single K8s Watch
//! stream. This drops API server load for status/list to **zero** after startup.
//!
//! Design (borrowed from Orchard/Microsoft):
//! - One long-lived Watch connection per K8sProvider instance
//! - Events (Added/Modified/Deleted) update the local HashMap
//! - `status()` and `list_active()` read the HashMap (no API calls)
//! - Automatic re-list on watch timeout/Gone (410) errors
//! - Thread-safe via `Arc<RwLock<HashMap>>`

use std::collections::HashMap;
use std::sync::Arc;

use futures::TryStreamExt;
use k8s_openapi::api::core::v1::Pod;
use kube::api::ListParams;
use kube::runtime::watcher::{self, Event};
use kube::{Api, Client};
use tokio::sync::RwLock;
use tracing::{debug, info, warn};

use super::provider::{ProviderSandboxInfo, SandboxStatus};

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
    pub fn new(client: Client, namespace: &str) -> Self {
        let cache = Arc::new(RwLock::new(HashMap::new()));
        let watcher = Self {
            cache: cache.clone(),
        };

        // Spawn the watch loop as a background task
        let pods: Api<Pod> = Api::namespaced(client, namespace);
        let cache_handle = cache;
        tokio::spawn(async move {
            Self::watch_loop(pods, cache_handle).await;
        });

        watcher
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
    async fn watch_loop(pods: Api<Pod>, cache: Arc<RwLock<HashMap<String, CachedPod>>>) {
        let lp = ListParams::default().labels("app.kubernetes.io/name=joysafeter-sandbox");

        loop {
            info!("PodWatcher: starting watch stream");

            // Initial list to populate cache
            match pods.list(&lp).await {
                Ok(pod_list) => {
                    let mut c = cache.write().await;
                    c.clear();
                    for pod in &pod_list.items {
                        if let Some(cached) = CachedPod::from_pod(pod) {
                            c.insert(cached.name.clone(), cached);
                        }
                    }
                    info!(
                        pod_count = c.len(),
                        "PodWatcher: initial list populated"
                    );
                }
                Err(e) => {
                    warn!(error = %e, "PodWatcher: initial list failed, retrying in 5s");
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                    continue;
                }
            }

            // Watch for changes
            let stream = watcher::watcher(pods.clone(), watcher::Config::default().labels(
                "app.kubernetes.io/name=joysafeter-sandbox",
            ));

            let mut stream = Box::pin(stream);
            loop {
                match stream.try_next().await {
                    Ok(Some(event)) => {
                        Self::handle_event(&cache, event).await;
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
        event: Event<Pod>,
    ) {
        match event {
            Event::Apply(pod) | Event::InitApply(pod) => {
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
            Event::Init => {
                cache.write().await.clear();
                debug!("PodWatcher: watch stream re-syncing");
            }
            Event::InitDone => {
                let count = cache.read().await.len();
                debug!(count, "PodWatcher: re-sync complete");
            }
        }
    }
}
