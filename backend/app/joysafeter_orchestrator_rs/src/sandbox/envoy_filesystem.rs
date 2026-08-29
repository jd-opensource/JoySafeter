//! Non-atomic filesystem compatibility delivery for Envoy LDS/CDS snapshots.

use std::collections::{HashMap, HashSet};

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::debug;

use crate::ids::SandboxId;

use super::envoy_delivery::{DeliverySubmission, EnvoyDelivery};
use super::envoy_render::render_listener_json;
use crate::kernel::network_policy::envoy_model::{sha256_hex, ClusterSpec, ListenerSpec};
use crate::xds::delivery::DeliveryRequest;

/// Compatibility adapter that writes separate LDS and CDS filesystem snapshots.
///
/// This adapter supports listener-only sandbox updates, but rejects non-empty
/// recovery and credential-bearing cluster/listener publication. Those atomic
/// lifecycle operations remain exclusive to gRPC xDS.
pub struct FilesystemEnvoyDelivery {
    config_dir: String,
    listeners: Mutex<HashMap<String, (SandboxId, Value)>>,
}

impl FilesystemEnvoyDelivery {
    pub fn new(config_dir: String) -> Self {
        Self {
            config_dir,
            listeners: Mutex::new(HashMap::new()),
        }
    }

    async fn write_lds(
        &self,
        listeners: &HashMap<String, (SandboxId, Value)>,
    ) -> anyhow::Result<()> {
        let mut resources: Vec<&Value> = listeners.values().map(|(_, value)| value).collect();
        resources.sort_by_key(|value| value.to_string());
        let resources_json = serde_json::to_string(&resources)?;
        let lds = json!({
            "version_info": sha256_hex(&resources_json),
            "resources": resources,
        });
        write_config_file(&self.config_dir, "lds.json", &serde_json::to_string(&lds)?).await?;
        debug!(
            listener_count = listeners.len(),
            "filesystem Envoy delivery wrote lds.json"
        );
        Ok(())
    }

    async fn write_empty_cds(&self) -> anyhow::Result<()> {
        let resources: Vec<Value> = Vec::new();
        let resources_json = serde_json::to_string(&resources)?;
        let cds = json!({
            "version_info": sha256_hex(&resources_json),
            "resources": resources,
        });
        write_config_file(&self.config_dir, "cds.json", &serde_json::to_string(&cds)?).await?;
        debug!("filesystem Envoy delivery wrote empty cds.json");
        Ok(())
    }
}

#[async_trait]
impl EnvoyDelivery for FilesystemEnvoyDelivery {
    async fn prepare_for_startup(&self) -> anyhow::Result<()> {
        let mut listeners = self.listeners.lock().await;
        listeners.clear();
        self.write_lds(&listeners).await?;
        self.write_empty_cds().await
    }

    async fn apply_sandbox_batch(
        &self,
        delivery: DeliveryRequest,
        clusters: Vec<ClusterSpec>,
        listener_specs: Vec<ListenerSpec>,
    ) -> anyhow::Result<DeliverySubmission> {
        if !clusters.is_empty() {
            anyhow::bail!(
                "filesystem xDS cannot atomically publish credential-bearing cluster/listener resources"
            );
        }
        let mut listeners = self.listeners.lock().await;
        listeners.retain(|_, (owner, _)| *owner != delivery.sandbox_id);
        for spec in listener_specs {
            if spec.sandbox_id != delivery.sandbox_id {
                anyhow::bail!("listener owner does not match sandbox batch");
            }
            listeners.insert(
                spec.resource_name(),
                (spec.sandbox_id, render_listener_json(&spec)),
            );
        }
        self.write_lds(&listeners).await?;
        Ok(DeliverySubmission::AlreadyCurrent)
    }

    async fn remove_sandbox_batch(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<DeliverySubmission> {
        let mut listeners = self.listeners.lock().await;
        listeners.retain(|_, (owner, _)| *owner != sandbox_id);
        self.write_lds(&listeners).await?;
        Ok(DeliverySubmission::AlreadyCurrent)
    }

    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.listeners
            .lock()
            .await
            .values()
            .map(|(sandbox_id, _)| *sandbox_id)
            .collect()
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
    let tmp = path.with_extension("tmp");
    tokio::fs::write(&tmp, content).await?;
    tokio::fs::rename(&tmp, &path).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::network_policy::envoy_model::ListenerKind;
    use crate::kernel::network_policy::NetworkPolicyGeneration;

    #[tokio::test]
    async fn startup_preparation_clears_stale_filesystem_snapshots() {
        let config_dir = std::env::temp_dir().join(format!(
            "joysafeter-envoy-filesystem-startup-{}",
            SandboxId::new().as_uuid()
        ));
        let delivery = FilesystemEnvoyDelivery::new(config_dir.to_string_lossy().into_owned());
        let sandbox_id = SandboxId::new();
        delivery
            .apply_sandbox_batch(
                DeliveryRequest {
                    authority_epoch: 1,
                    sandbox_id,
                    generation: NetworkPolicyGeneration {
                        policy_hash: "stale-policy".to_string(),
                        policy_version: 1,
                    },
                },
                Vec::new(),
                vec![ListenerSpec {
                    sandbox_id,
                    kind: ListenerKind::Http,
                    allowed_hosts: vec!["example.com".to_string()],
                    credentials: Vec::new(),
                    proxy_auth_token: None,
                }],
            )
            .await
            .expect("seed stale LDS snapshot");
        write_config_file(
            &config_dir.to_string_lossy(),
            "cds.json",
            r#"{"version_info":"stale","resources":[{"name":"stale"}]}"#,
        )
        .await
        .expect("seed stale CDS snapshot");

        delivery
            .prepare_for_startup()
            .await
            .expect("prepare filesystem delivery");

        for file_name in ["lds.json", "cds.json"] {
            let snapshot: Value = serde_json::from_slice(
                &tokio::fs::read(config_dir.join(file_name))
                    .await
                    .expect("read prepared snapshot"),
            )
            .expect("parse prepared snapshot");
            assert_eq!(snapshot["resources"], json!([]));
        }
        assert!(delivery.configured_sandbox_ids().await.is_empty());
        let _ = tokio::fs::remove_dir_all(config_dir).await;
    }
}
