use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, AttachParams, DeleteParams, ListParams, PostParams};
use kube::Client;
use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::io::AsyncReadExt;
use tracing::{info, warn};
use uuid::Uuid;

use super::envoy::{EnvoyConfig, EnvoyManager};
use super::lds_backend::{
    DeltaXdsServer, FilesystemLds, GrpcLds, LdsBackend, SandboxCredentials,
};
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
///
/// When Envoy is enabled, sandboxes use a per-node DaemonSet Envoy for egress.
/// The socket dir is shared between sandbox pod and Envoy via hostPath, and an
/// initContainer in the sandbox pod creates the per-sandbox subdirectory
/// (since orchestrator cannot create dirs on a remote node).
#[derive(Clone)]
pub struct K8sProvider {
    client: Client,
    namespace: String,
    config: JoySafeterConfig,
    orchestrator_url: Option<String>,
    /// Envoy network isolation manager (None when envoy_enabled=false).
    envoy_manager: Option<Arc<EnvoyManager>>,
    /// Delta xDS server for gRPC xDS mode.
    xds_service: Option<Arc<DeltaXdsServer>>,
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

        // Build Envoy manager + xDS service if enabled
        let mut xds_service: Option<Arc<DeltaXdsServer>> = None;
        let envoy_manager = if config.envoy_enabled {
            let lds: Arc<dyn LdsBackend> = if config.envoy_xds_mode == "grpc" {
                let server = DeltaXdsServer::new();
                xds_service = Some(server.clone());
                Arc::new(GrpcLds::new(server))
            } else {
                Arc::new(FilesystemLds::new(config.envoy_config_dir.clone()))
            };
            Some(Arc::new(EnvoyManager::new(
                // K8s provider doesn't need Docker client for Envoy (DaemonSet
                // manages its own container). Pass a dummy client — EnvoyManager
                // only uses it for prepare_socket_dir_in_volume (which we skip
                // via initContainer) and health_check (which we skip via K8s
                // livenessProbe on the DaemonSet).
                Arc::new(bollard::Docker::connect_with_local_defaults().unwrap_or_else(|_| {
                    panic!("bollard dummy client init failed")
                })),
                EnvoyConfig {
                    envoy_image: config.envoy_image.clone(),
                    socket_volume: config.envoy_socket_volume.clone(),
                    socket_host_dir: config.envoy_socket_host_dir.clone(),
                    config_dir: config.envoy_config_dir.clone(),
                    envoy_network: config.envoy_network.clone(),
                    grpc_target_host: config.envoy_grpc_host.clone(),
                    grpc_target_port: config.envoy_grpc_port,
                    container_name: config.envoy_container_name.clone(),
                    xds_mode: config.envoy_xds_mode.clone(),
                    write_debug_entries: config.envoy_write_debug_entries,
                    socket_ready_timeout_ms: config.envoy_socket_ready_timeout_ms,
                    health_check_interval_sec: 0, // K8s livenessProbe handles this
                    health_failure_threshold: 0,
                    skip_socket_dir_prep: true, // K8s: initContainer creates socket dir
                },
                lds,
            )))
        } else {
            None
        };

        info!(
            namespace = %config.k8s_namespace,
            envoy_enabled = config.envoy_enabled,
            "K8sProvider initialized (kube-rs SDK)"
        );

        Ok(Self {
            client,
            namespace: config.k8s_namespace.clone(),
            config: config.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
            envoy_manager,
            xds_service,
        })
    }

    /// Get the xDS service (if gRPC xDS mode). Used to register ADS on gRPC server.
    pub fn xds_service(&self) -> Option<Arc<DeltaXdsServer>> {
        self.xds_service.clone()
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
        let mut init_containers = Vec::new();

        // Storage PVC mounts
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

        // Envoy egress socket: hostPath shared with DaemonSet on same node.
        // initContainer creates the per-sandbox subdirectory (orchestrator can't
        // do it remotely since it may be on a different node).
        let has_egress = config.network.as_deref() == Some("none") && self.envoy_manager.is_some();
        if has_egress {
            let socket_host_dir = self
                .config
                .envoy_socket_host_dir
                .as_deref()
                .unwrap_or("/data/joysafeter/envoy-sockets");

            volumes.push(json!({
                "name": "envoy-sockets",
                "hostPath": {
                    "path": socket_host_dir,
                    "type": "DirectoryOrCreate"
                }
            }));
            volume_mounts.push(json!({
                "name": "envoy-sockets",
                "mountPath": format!("/sockets/{}", config.sandbox_id),
                "subPath": config.sandbox_id.to_string()
            }));

            // initContainer: create per-sandbox socket directory with correct perms.
            // Uses the envoy image (already pulled on the node, has sh).
            init_containers.push(json!({
                "name": "create-socket-dir",
                "image": self.config.envoy_image,
                "command": ["sh", "-c", format!(
                    "mkdir -p /sockets/{sid} && chmod 777 /sockets/{sid}",
                    sid = config.sandbox_id
                )],
                "securityContext": {
                    "runAsUser": 0
                },
                "volumeMounts": [{
                    "name": "envoy-sockets",
                    "mountPath": "/sockets"
                }]
            }));
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

        let mut pod_spec = json!({
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
        });
        if !init_containers.is_empty() {
            pod_spec["initContainers"] = json!(init_containers);
        }

        Ok(json!({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": self.namespace,
                "labels": labels
            },
            "spec": pod_spec
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
            has_egress_management: self.envoy_manager.is_some(),
            network_isolation: if self.envoy_manager.is_some() {
                NetworkIsolation::Envoy
            } else {
                NetworkIsolation::None
            },
        }
    }

    // ─── Envoy egress integration ───────────────────────────────────────────

    async fn on_startup(&self, pool: &PgPool) -> anyhow::Result<()> {
        if let Some(ref manager) = self.envoy_manager {
            if let Some(ref xds) = self.xds_service {
                xds.attach_db_pool(pool.clone()).await;
            }
            // In K8s mode, Envoy DaemonSet manages its own bootstrap (embedded).
            // We only reset in-memory xDS state and recover listeners from DB.
            if let Err(e) = manager.init_xds_only().await {
                warn!("EnvoyManager xDS init failed: {e}");
                return Ok(());
            }
            if let Err(e) = manager
                .recover_from_db(pool, &self.config.llm_egress_allowed_hosts)
                .await
            {
                warn!("EnvoyManager LDS recovery from DB failed: {e}");
            }
            // No health monitor spawn — K8s livenessProbe on DaemonSet handles it.
            info!(
                xds_mode = %self.config.envoy_xds_mode,
                "K8s EnvoyManager initialized (DaemonSet manages Envoy lifecycle)"
            );
        }
        Ok(())
    }

    async fn setup_networking(
        &self,
        sandbox_id: Uuid,
        _sandbox_external_id: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        if let Some(ref manager) = self.envoy_manager {
            // In K8s mode, prepare_socket_dir is handled by the pod's
            // initContainer (it creates the dir on the local node). We skip
            // the orchestrator-side mkdir (it would only work on the local node).
            // Just push the LDS listener to Envoy.
            manager
                .setup_for_sandbox(sandbox_id, networking, credentials)
                .await?;
        }
        Ok(())
    }

    async fn refresh_networking(
        &self,
        sandbox_id: Uuid,
        sandbox_external_id: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.setup_networking(sandbox_id, sandbox_external_id, networking, credentials)
            .await
    }

    async fn teardown_networking(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        if let Some(ref manager) = self.envoy_manager {
            manager.teardown_for_sandbox(sandbox_id).await?;
        }
        Ok(())
    }
}
