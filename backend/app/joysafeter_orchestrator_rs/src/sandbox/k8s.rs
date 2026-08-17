use std::collections::BTreeMap;
use std::sync::Arc;

use crate::ids::SandboxId;
use async_trait::async_trait;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, AttachParams, DeleteParams, PostParams};
use kube::Client;
use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::io::AsyncReadExt;
use tracing::{info, warn};

use super::envoy::{EnvoyConfig, EnvoyManager};
use super::lds_backend::{DeltaXdsServer, FilesystemLds, GrpcLds, LdsBackend, SandboxCredentials};
use super::mounts::SandboxMount;
use super::pod_watcher::PodWatcher;
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
    /// Local pod cache backed by K8s Watch — zero API calls for status/list.
    pod_watcher: PodWatcher,
}

impl K8sProvider {
    /// Create a new K8s provider. Uses in-cluster config automatically when
    /// running inside a pod (ServiceAccount token), falls back to kubeconfig.
    pub async fn new(config: &JoySafeterConfig) -> anyhow::Result<Self> {
        let client = Client::try_default()
            .await
            .map_err(|e| anyhow::anyhow!("failed to create K8s client: {e}"))?;

        // Verify connectivity
        let _version = client
            .apiserver_version()
            .await
            .map_err(|e| anyhow::anyhow!("K8s API server unreachable: {e}"))?;

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
                // K8s provider doesn't need a Docker client for Envoy (DaemonSet
                // manages its own container). EnvoyManager only uses Docker for
                // prepare_socket_dir_in_volume (skipped via initContainer) and
                // health_check (skipped via K8s livenessProbe on the DaemonSet),
                // so pass None — constructing a real bollard client here would
                // panic in a pod that has no Docker socket.
                None,
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
                    // K8s DaemonSet: Envoy's node.id is set via downward API in the
                    // DaemonSet manifest (env NODE_NAME from spec.nodeName). The
                    // bootstrap is not written by the orchestrator in K8s mode
                    // (init_xds_only), so this field is informational here.
                    node_id: "k8s-envoy".to_string(),
                },
                lds,
            )))
        } else {
            None
        };

        // Start PodWatcher — background Watch stream keeps local pod cache synced.
        // status() and list_active() read from this cache (zero API calls).
        let pod_watcher = PodWatcher::new(client.clone(), &config.k8s_namespace);

        // pids_limit has no per-pod equivalent in the K8s pod spec (it is a
        // node-level kubelet setting, `podPidsLimit`). Warn once so operators
        // know the JOYSAFETER_SANDBOX_PIDS_LIMIT knob is not enforced here and
        // must be configured on the kubelet instead.
        if config.sandbox_pids_limit > 0 {
            warn!(
                pids_limit = config.sandbox_pids_limit,
                "JOYSAFETER_SANDBOX_PIDS_LIMIT is set but K8s pods have no per-pod PID limit; \
                 configure kubelet `podPidsLimit` on the nodes to enforce it"
            );
        }

        info!(
            namespace = %config.k8s_namespace,
            envoy_enabled = config.envoy_enabled,
            "K8sProvider initialized (kube-rs SDK + PodWatcher)"
        );

        Ok(Self {
            client,
            namespace: config.k8s_namespace.clone(),
            config: config.clone(),
            orchestrator_url: config.k8s_orchestrator_url.clone(),
            envoy_manager,
            xds_service,
            pod_watcher,
        })
    }

    /// Get the xDS service (if gRPC xDS mode). Used to register ADS on gRPC server.
    pub fn xds_service(&self) -> Option<Arc<DeltaXdsServer>> {
        self.xds_service.clone()
    }

    fn pods(&self) -> Api<Pod> {
        Api::namespaced(self.client.clone(), &self.namespace)
    }

    fn pod_name(sandbox_id: SandboxId) -> String {
        format!("joysafeter-{}", sandbox_id.as_uuid())
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
        let sandbox_uuid = config.sandbox_id.as_uuid();
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
            sandbox_uuid.to_string(),
        );

        let mut env: Vec<Value> = config
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
            // Tell the runner where Envoy's per-sandbox HTTP egress pipe lives so
            // it starts the in-process proxy bridge (127.0.0.1:3128 → this socket).
            // Without this the runner has no unix:// hint (orch_url is TCP in K8s),
            // never starts the bridge, and the agent's HTTP_PROXY points at a dead
            // port → all egress hangs. Matches the LDS pipe path and the mount below.
            env.push(json!({
                "name": "JOYSAFETER_EGRESS_HTTP_SOCKET_PATH",
                "value": format!("/sockets/{sandbox_uuid}/http.sock")
            }));

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
                "mountPath": format!("/sockets/{sandbox_uuid}"),
                "subPath": sandbox_uuid.to_string()
            }));

            // initContainer: create per-sandbox socket directory with correct perms.
            // Reuse the sandbox image itself (same image as the runner container →
            // already pulled / IfNotPresent, has sh). Avoids depending on a separate
            // envoy image (which may be an unreachable docker.io default).
            init_containers.push(json!({
                "name": "create-socket-dir",
                "image": config.image,
                "imagePullPolicy": "IfNotPresent",
                "command": ["sh", "-c", format!(
                    "mkdir -p /sockets/{sid} && chmod 777 /sockets/{sid}",
                    sid = sandbox_uuid
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

        // Sandbox hardening — honor the same JOYSAFETER_SANDBOX_* config the
        // Docker provider uses, instead of hardcoding. Default config is
        // drop_all_caps=true, no_new_privileges=true, run_as_user="1000:1000",
        // so the default rendered spec is identical to before.
        let no_new_priv = self.config.sandbox_no_new_privileges;
        let drop_caps = self.config.sandbox_drop_all_caps;
        // run_as_user is "uid:gid"; empty = use the image's default USER.
        let (run_as_uid, run_as_gid): (Option<i64>, Option<i64>) = {
            let raw = self.config.sandbox_run_as_user.trim();
            if raw.is_empty() {
                (None, None)
            } else {
                let mut parts = raw.splitn(2, ':');
                let uid = parts.next().and_then(|u| u.trim().parse::<i64>().ok());
                let gid = parts.next().and_then(|g| g.trim().parse::<i64>().ok());
                (uid, gid.or(uid))
            }
        };

        let mut container_sec_ctx = json!({
            "allowPrivilegeEscalation": !no_new_priv,
            "readOnlyRootFilesystem": false,
        });
        if drop_caps {
            container_sec_ctx["capabilities"] = json!({ "drop": ["ALL"] });
        }
        if let Some(uid) = run_as_uid {
            container_sec_ctx["runAsUser"] = json!(uid);
            container_sec_ctx["runAsNonRoot"] = json!(uid != 0);
        }
        if let Some(gid) = run_as_gid {
            container_sec_ctx["runAsGroup"] = json!(gid);
        }

        let mut container = json!({
            "name": "runner",
            "image": config.image,
            "imagePullPolicy": "IfNotPresent",
            "workingDir": "/workspace",
            "env": env,
            "securityContext": container_sec_ctx,
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

        let mut pod_security_context = json!({
            "seccompProfile": { "type": "RuntimeDefault" },
            "fsGroupChangePolicy": "OnRootMismatch"
        });
        // fsGroup follows the configured gid so mounted volumes are group-owned
        // by the same gid the container runs as. Falls back to 1000 (prior default).
        pod_security_context["fsGroup"] = json!(run_as_gid.unwrap_or(1000));

        let mut pod_spec = json!({
            "restartPolicy": "Never",
            "automountServiceAccountToken": false,
            "enableServiceLinks": false,
            "securityContext": pod_security_context,
            "containers": [container],
            "volumes": volumes
        });
        if !init_containers.is_empty() {
            pod_spec["initContainers"] = json!(init_containers);
        }
        if !self.config.k8s_image_pull_secrets.is_empty() {
            pod_spec["imagePullSecrets"] = json!(self
                .config
                .k8s_image_pull_secrets
                .iter()
                .map(|name| json!({ "name": name }))
                .collect::<Vec<_>>());
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
        Ok(self.pod_watcher.status(external_id).await)
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
        Ok(self.pod_watcher.list_active().await)
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
            // Fail-closed: if xDS cannot reset or the live sandboxes' listeners
            // cannot be recovered, abort startup instead of serving them without
            // egress enforcement.
            manager.init_xds_only().await?;
            manager
                .recover_from_db(pool, &self.config.llm_egress_allowed_hosts)
                .await?;

            // Rebuild sandbox→node mappings from PodWatcher cache so that
            // node-aware xDS filtering works immediately after restart (before
            // any new setup_networking call). Without this, recovered listeners
            // would be sent to all Envoys (permissive default).
            if let Some(ref xds) = self.xds_service {
                let active_pods = self.pod_watcher.list_active().await;
                let mut mapped = 0usize;
                for pod_info in &active_pods {
                    if let Some(node) = self.pod_watcher.node_name(&pod_info.name).await {
                        if let Some(id_str) = pod_info.labels.get("joysafeter.sandbox_id") {
                            if let Ok(sandbox_id) = id_str.parse::<uuid::Uuid>() {
                                xds.set_sandbox_node(SandboxId::from_uuid(sandbox_id), node);
                                mapped += 1;
                            }
                        }
                    }
                }
                if mapped > 0 {
                    info!(
                        mapped,
                        "Rebuilt sandbox→node mappings from PodWatcher cache"
                    );
                }
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
        sandbox_id: SandboxId,
        _sandbox_external_id: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        if let Some(ref manager) = self.envoy_manager {
            // Register sandbox→node mapping BEFORE pushing the listener, so
            // node-aware xDS filtering sends it only to the Envoy on the
            // sandbox's node. With restrictive filtering, a missing mapping
            // means the listener is withheld from all Envoys — so we must wait
            // for the PodWatcher cache to learn the pod's nodeName (it may lag
            // pod creation by a moment). Bounded wait; if it never resolves the
            // periodic networking reconcile loop retries later.
            let pod_name = Self::pod_name(sandbox_id);
            if let Some(ref xds) = self.xds_service {
                let mut node = self.pod_watcher.node_name(&pod_name).await;
                if node.is_none() {
                    for _ in 0..25 {
                        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                        node = self.pod_watcher.node_name(&pod_name).await;
                        if node.is_some() {
                            break;
                        }
                    }
                }
                match node {
                    Some(node) => xds.set_sandbox_node(sandbox_id, node),
                    None => warn!(
                        sandbox_id = %sandbox_id,
                        "node name not known yet for sandbox; listener will be delivered once the \
                         networking reconcile loop resolves the node mapping"
                    ),
                }
            }
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
        sandbox_id: SandboxId,
        sandbox_external_id: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.setup_networking(sandbox_id, sandbox_external_id, networking, credentials)
            .await
    }

    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if let Some(ref manager) = self.envoy_manager {
            manager.teardown_for_sandbox(sandbox_id).await?;
        }
        // Remove sandbox→node mapping
        if let Some(ref xds) = self.xds_service {
            xds.remove_sandbox_node(sandbox_id);
        }
        Ok(())
    }
}
