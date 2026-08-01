use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use futures::TryStreamExt;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, AttachParams, DeleteParams, ListParams, PostParams};
use kube::Client;
use serde_json::{json, Value};
use tokio::io::AsyncReadExt;
use tracing::{info, warn};
use uuid::Uuid;

use super::mounts::SandboxMount;
use super::provider::{
    NetworkIsolation, ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig,
    SandboxProvider, SandboxStatus,
};
use crate::config::JoySafeterConfig;

/// Kubernetes-backed sandbox provider using the kube-rs SDK.
///
/// Communicates with the K8s API server directly over HTTP/2 (via
/// ServiceAccount token when in-cluster, or kubeconfig when developing
/// locally). No kubectl CLI dependency.
#[derive(Clone)]
pub struct K8sProvider {
    client: Client,
    namespace: String,
    orchestrator_url: Option<String>,
}

impl K8sProvider {
    /// Create a new K8s provider. Uses in-cluster config automatically when
    /// running inside a pod (ServiceAccount token), falls back to kubeconfig.
    pub async fn new(config: &JoySafeterConfig) -> anyhow::Result<Self> {
        let client = Client::try_default()
            .await
            .map_err(|e| anyhow::anyhow!("failed to create K8s client: {e}"))?;

        // Verify connectivity
        let _version = client.apiserver_version().await.map_err(|e| {
            anyhow::anyhow!("K8s API server unreachable: {e}")
        })?;

        info!(
            namespace = %config.k8s_namespace,
            "K8sProvider initialized (kube-rs SDK)"
        );

        Ok(Self {
            client,
            namespace: config.k8s_namespace.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
        })
    }

    fn pods(&self) -> Api<Pod> {
        Api::namespaced(self.client.clone(), &self.namespace)
    }

    fn pod_name(sandbox_id: Uuid) -> String {
        format!("joysafeter-{sandbox_id}")
    }

    fn build_pod(&self, config: &SandboxCreateConfig, pod_name: &str) -> anyhow::Result<Pod> {
        let manifest = self.build_manifest(config, pod_name)?;
        let pod: Pod = serde_json::from_value(manifest)?;
        Ok(pod)
    }

    fn build_manifest(
        &self,
        config: &SandboxCreateConfig,
        pod_name: &str,
    ) -> anyhow::Result<Value> {
        let mut labels = BTreeMap::new();
        for (key, value) in &config.labels {
            labels.insert(sanitize_label_key(key), value.clone());
        }
        labels.insert(
            "app.kubernetes.io/name".to_string(),
            "joysafeter-sandbox".to_string(),
        );
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            config.sandbox_id.to_string(),
        );

        let env: Vec<Value> = config
            .env
            .iter()
            .map(|(name, value)| json!({ "name": name, "value": value }))
            .collect();

        let mut volumes = Vec::new();
        let mut volume_mounts = Vec::new();
        for (index, mount) in config.mounts.iter().enumerate() {
            match mount {
                SandboxMount::K8sPvc {
                    claim_name,
                    namespace,
                    mount_path,
                    sub_path,
                    read_only,
                } => {
                    if namespace.as_deref().is_some_and(|ns| ns != self.namespace) {
                        anyhow::bail!(
                            "Storage PVC namespace '{}' does not match provider namespace '{}'",
                            namespace.as_deref().unwrap_or_default(),
                            self.namespace
                        );
                    }
                    let name = format!("storage-{index}");
                    volumes.push(json!({
                        "name": name,
                        "persistentVolumeClaim": { "claimName": claim_name }
                    }));
                    let mut volume_mount = json!({
                        "name": name,
                        "mountPath": mount_path,
                        "readOnly": read_only,
                    });
                    if let Some(sub_path) = sub_path {
                        volume_mount["subPath"] = json!(sub_path);
                    }
                    volume_mounts.push(volume_mount);
                }
                SandboxMount::DockerBind { .. } => {
                    anyhow::bail!("Docker bind mount was passed to K8s provider");
                }
            }
        }

        let mut container = json!({
            "name": "runner",
            "image": config.image,
            "imagePullPolicy": "IfNotPresent",
            "workingDir": "/workspace",
            "env": env,
            "securityContext": {
                "allowPrivilegeEscalation": false,
                "readOnlyRootFilesystem": false,
                "runAsNonRoot": true,
                "runAsUser": 1000,
                "runAsGroup": 1000,
                "capabilities": { "drop": ["ALL"] }
            },
            "resources": {
                "requests": {},
                "limits": {}
            },
            "volumeMounts": volume_mounts
        });
        if let Some(cpu) = config.cpu_limit {
            container["resources"]["limits"]["cpu"] = json!(format!("{}m", (cpu * 1000.0) as u64));
        }
        if let Some(memory_mb) = config.memory_limit_mb {
            container["resources"]["limits"]["memory"] = json!(format!("{memory_mb}Mi"));
        }

        Ok(json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": self.namespace,
                "labels": labels
            },
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": false,
                "enableServiceLinks": false,
                "securityContext": {
                    "seccompProfile": { "type": "RuntimeDefault" },
                    "fsGroup": 1000,
                    "fsGroupChangePolicy": "OnRootMismatch"
                },
                "containers": [container],
                "volumes": volumes
            }
        }))
    }
}

fn sanitize_label_key(key: &str) -> String {
    key.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' || ch == '.' || ch == '/' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}

#[async_trait]
impl SandboxProvider for K8sProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let pod_name = Self::pod_name(config.sandbox_id);
        let pod = self.build_pod(config, &pod_name)?;
        self.pods().create(&PostParams::default(), &pod).await?;
        info!(
            sandbox_id = %config.sandbox_id,
            pod_name = %pod_name,
            image = %config.image,
            "K8s sandbox pod created"
        );
        Ok(pod_name)
    }

    async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
        // K8s pods start immediately on creation; no separate start step.
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        match self
            .pods()
            .delete(external_id, &DeleteParams::default())
            .await
        {
            Ok(_) => Ok(()),
            Err(kube::Error::Api(err)) if err.code == 404 => Ok(()),
            Err(e) => Err(e.into()),
        }
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        self.stop(external_id).await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        match self.pods().get(external_id).await {
            Ok(pod) => {
                let phase = pod
                    .status
                    .as_ref()
                    .and_then(|s| s.phase.as_deref())
                    .unwrap_or("Unknown");
                Ok(match phase {
                    "Running" => SandboxStatus::Running,
                    "Pending" => SandboxStatus::Unknown("Pending".to_string()),
                    "Succeeded" | "Failed" => SandboxStatus::Stopped,
                    other => SandboxStatus::Unknown(other.to_string()),
                })
            }
            Err(kube::Error::Api(err)) if err.code == 404 => Ok(SandboxStatus::NotFound),
            Err(e) => Err(e.into()),
        }
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        let cmd_owned: Vec<String> = cmd.iter().map(|s| s.to_string()).collect();
        let mut attached = self
            .pods()
            .exec(
                external_id,
                &cmd_owned,
                &AttachParams::default().stdout(true).stderr(true),
            )
            .await?;
        let mut stdout = String::new();
        if let Some(mut reader) = attached.stdout() {
            reader.read_to_string(&mut stdout).await?;
        }
        Ok(stdout)
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        let lp = ListParams::default().labels("app.kubernetes.io/name=joysafeter-sandbox");
        let pods = self.pods().list(&lp).await?;
        let mut result = Vec::new();
        for pod in pods.items {
            let name = pod.metadata.name.unwrap_or_default();
            let image = pod
                .spec
                .as_ref()
                .and_then(|s| s.containers.first())
                .map(|c| c.image.clone().unwrap_or_default())
                .unwrap_or_default();
            let status = pod
                .status
                .as_ref()
                .and_then(|s| s.phase.clone())
                .unwrap_or_else(|| "Unknown".to_string());
            let labels = pod
                .metadata
                .labels
                .unwrap_or_default()
                .into_iter()
                .collect();
            result.push(ProviderSandboxInfo {
                id: name.clone(),
                name,
                status,
                image,
                labels,
            });
        }
        Ok(result)
    }

    fn provider_name(&self) -> &'static str {
        "k8s"
    }

    fn orchestrator_url(&self, grpc_port: u16) -> String {
        self.orchestrator_url
            .clone()
            .unwrap_or_else(|| format!("http://joysafeter-orchestrator:{grpc_port}"))
    }

    fn capabilities(&self) -> ProviderCapabilities {
        ProviderCapabilities {
            has_host_mount: false,
            has_egress_management: false,
            network_isolation: NetworkIsolation::None,
        }
    }
}
