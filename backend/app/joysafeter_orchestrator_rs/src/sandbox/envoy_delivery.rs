use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::debug;

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::{sha256_hex, ClusterSpec, ListenerSpec};
use crate::sandbox::envoy_render::{render_cluster_json, render_listener_json};
use crate::xds::control_plane::sandbox_id_from_resource_name;

#[async_trait]
pub trait LdsBackend: Send + Sync {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()>;
    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()>;
    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()>;
    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId>;

    async fn wait_for_sandbox_ack(
        &self,
        _sandbox_id: SandboxId,
        _timeout: Duration,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn forget_sandbox(&self, _sandbox_id: SandboxId) {}

    async fn apply_sandbox_batch(
        &self,
        _clusters: Vec<ClusterSpec>,
        _listeners: Vec<ListenerSpec>,
        _cluster_prefix: String,
    ) -> anyhow::Result<bool> {
        Ok(false)
    }
}

#[async_trait]
pub trait CdsBackend: Send + Sync {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()>;
    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()>;
}

#[derive(Clone)]
pub struct EnvoyPublishers {
    pub lds: Arc<dyn LdsBackend>,
    pub cds: Arc<dyn CdsBackend>,
}

pub struct FilesystemLds {
    config_dir: String,
    listeners: Mutex<HashMap<String, Value>>,
}

impl FilesystemLds {
    pub fn new(config_dir: String) -> Self {
        Self {
            config_dir,
            listeners: Mutex::new(HashMap::new()),
        }
    }

    async fn write(&self, listeners: &HashMap<String, Value>) -> anyhow::Result<()> {
        let mut resources = listeners.values().collect::<Vec<_>>();
        resources.sort_by_key(|value| value.to_string());
        let resources_json = serde_json::to_string(&resources)?;
        let document = json!({
            "version_info": sha256_hex(&resources_json),
            "resources": resources,
        });
        write_config_file(
            &self.config_dir,
            "lds.json",
            &serde_json::to_string(&document)?,
        )
        .await?;
        debug!(
            listener_count = listeners.len(),
            "wrote filesystem LDS snapshot"
        );
        Ok(())
    }
}

#[async_trait]
impl LdsBackend for FilesystemLds {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        for spec in specs {
            listeners.insert(spec.resource_name(), render_listener_json(&spec));
        }
        self.write(&listeners).await
    }

    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        for name in names {
            listeners.remove(&name);
        }
        self.write(&listeners).await
    }

    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        listeners.clear();
        for spec in specs {
            listeners.insert(spec.resource_name(), render_listener_json(&spec));
        }
        self.write(&listeners).await
    }

    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.listeners
            .lock()
            .await
            .keys()
            .filter_map(|name| sandbox_id_from_resource_name(name))
            .collect()
    }
}

pub struct FilesystemCds {
    config_dir: String,
    clusters: Mutex<HashMap<String, Value>>,
}

impl FilesystemCds {
    pub fn new(config_dir: String) -> Self {
        Self {
            config_dir,
            clusters: Mutex::new(HashMap::new()),
        }
    }

    async fn write(&self, clusters: &HashMap<String, Value>) -> anyhow::Result<()> {
        let mut resources = clusters.values().collect::<Vec<_>>();
        resources.sort_by_key(|value| value.to_string());
        let resources_json = serde_json::to_string(&resources)?;
        let document = json!({
            "version_info": sha256_hex(&resources_json),
            "resources": resources,
        });
        write_config_file(
            &self.config_dir,
            "cds.json",
            &serde_json::to_string(&document)?,
        )
        .await?;
        debug!(
            cluster_count = clusters.len(),
            "wrote filesystem CDS snapshot"
        );
        Ok(())
    }
}

#[async_trait]
impl CdsBackend for FilesystemCds {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
        self.write(&clusters).await
    }

    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.retain(|name, _| !name.starts_with(prefix));
        self.write(&clusters).await
    }

    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.retain(|name, _| !name.starts_with(prefix));
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
        self.write(&clusters).await
    }

    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut clusters = self.clusters.lock().await;
        clusters.clear();
        for spec in specs {
            clusters.insert(spec.name.clone(), render_cluster_json(&spec));
        }
        self.write(&clusters).await
    }
}

async fn write_config_file(
    config_dir: &str,
    relative_path: &str,
    content: &str,
) -> anyhow::Result<()> {
    let path = std::path::Path::new(config_dir).join(relative_path);
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let temporary = path.with_extension("tmp");
    tokio::fs::write(&temporary, content).await?;
    tokio::fs::rename(&temporary, &path).await?;
    Ok(())
}
