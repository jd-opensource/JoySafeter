use std::collections::BTreeMap;
use std::process::Stdio;

use async_trait::async_trait;
use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tracing::warn;
use uuid::Uuid;

use super::mounts::SandboxMount;
use super::provider::{
    NetworkIsolation, ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig,
    SandboxProvider, SandboxStatus,
};
use crate::config::JoySafeterConfig;

#[derive(Clone, Debug)]
pub struct K8sProvider {
    namespace: String,
    kubectl_path: String,
    orchestrator_url: Option<String>,
}

impl K8sProvider {
    pub fn new(config: &JoySafeterConfig) -> Self {
        Self {
            namespace: config.k8s_namespace.clone(),
            kubectl_path: config.k8s_kubectl_path.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
        }
    }

    async fn kubectl_json(&self, args: &[&str]) -> anyhow::Result<Value> {
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(serde_json::from_slice(&output.stdout)?)
    }

    async fn kubectl_status(&self, args: &[&str]) -> anyhow::Result<()> {
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    }

    async fn kubectl_apply(&self, manifest: &Value) -> anyhow::Result<()> {
        let mut child = Command::new(&self.kubectl_path)
            .args(["apply", "-f", "-"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| anyhow::anyhow!("failed to open kubectl stdin"))?;
        let bytes = serde_json::to_vec(manifest)?;
        stdin.write_all(&bytes).await?;
        drop(stdin);
        let output = child.wait_with_output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl apply failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    }

    fn pod_name(sandbox_id: Uuid) -> String {
        format!("joysafeter-{sandbox_id}")
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

        let env = config
            .env
            .iter()
            .map(|(name, value)| json!({ "name": name, "value": value }))
            .collect::<Vec<_>>();

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
        let manifest = self.build_manifest(config, &pod_name)?;
        self.kubectl_apply(&manifest).await?;
        Ok(pod_name)
    }

    async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
        Ok(())
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        self.kubectl_status(&[
            "-n",
            &self.namespace,
            "delete",
            "pod",
            external_id,
            "--ignore-not-found=true",
        ])
        .await
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        self.stop(external_id).await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        let output = self
            .kubectl_json(&[
                "-n",
                &self.namespace,
                "get",
                "pod",
                external_id,
                "-o",
                "json",
            ])
            .await;
        let pod = match output {
            Ok(value) => value,
            Err(err)
                if format!("{err}").contains("NotFound")
                    || format!("{err}").contains("not found") =>
            {
                return Ok(SandboxStatus::NotFound);
            }
            Err(err) => return Err(err),
        };
        let phase = pod
            .pointer("/status/phase")
            .and_then(|value| value.as_str())
            .unwrap_or("Unknown");
        Ok(match phase {
            "Running" => SandboxStatus::Running,
            "Succeeded" | "Failed" => SandboxStatus::Stopped,
            other => SandboxStatus::Unknown(other.to_string()),
        })
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        let mut args = vec!["-n", self.namespace.as_str(), "exec", external_id, "--"];
        args.extend_from_slice(cmd);
        let output = Command::new(&self.kubectl_path).args(args).output().await?;
        if !output.status.success() {
            anyhow::bail!(
                "kubectl exec failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        let pods = self
            .kubectl_json(&[
                "-n",
                &self.namespace,
                "get",
                "pods",
                "-l",
                "app.kubernetes.io/name=joysafeter-sandbox",
                "-o",
                "json",
            ])
            .await?;
        let mut result = Vec::new();
        for item in pods
            .get("items")
            .and_then(|value| value.as_array())
            .into_iter()
            .flatten()
        {
            let Some(name) = item
                .pointer("/metadata/name")
                .and_then(|value| value.as_str())
            else {
                continue;
            };
            let image = item
                .pointer("/spec/containers/0/image")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_string();
            let status = item
                .pointer("/status/phase")
                .and_then(|value| value.as_str())
                .unwrap_or("Unknown")
                .to_string();
            let labels = item
                .pointer("/metadata/labels")
                .and_then(|value| value.as_object())
                .map(|labels| {
                    labels
                        .iter()
                        .filter_map(|(key, value)| {
                            value.as_str().map(|v| (key.clone(), v.to_string()))
                        })
                        .collect()
                })
                .unwrap_or_default();
            result.push(ProviderSandboxInfo {
                id: name.to_string(),
                name: name.to_string(),
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

impl Drop for K8sProvider {
    fn drop(&mut self) {
        if self.namespace.is_empty() {
            warn!("K8sProvider namespace is empty");
        }
    }
}
