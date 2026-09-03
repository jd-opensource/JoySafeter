use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::Arc;

use crate::ids::SandboxId;
use anyhow::Context;
use async_trait::async_trait;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Api, AttachParams, DeleteParams, ListParams, Patch, PatchParams, PostParams};
use kube::Client;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tracing::{info, warn};

use super::file_injection::FileToInject;
use super::mounts::SandboxMount;
use super::pod_watcher::PodWatcher;
use super::provider::{
    NetworkIsolation, ProviderCapabilities, ProviderSandboxInfo, SandboxCreateConfig,
    SandboxProvider, SandboxStatus, StopSemantics,
};
use super::runtime::{PlacementEventSink, SandboxSocketProvisioner};
use crate::config::JoySafeterConfig;

const ENVOY_POD_SELECTOR: &str = "app=joysafeter-envoy";

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
    egress_socket: Option<Arc<dyn SandboxSocketProvisioner>>,
    /// Local pod cache backed by K8s Watch — zero API calls for status/list.
    pod_watcher: PodWatcher,
}

impl K8sProvider {
    /// Create a new K8s provider. Uses in-cluster config automatically when
    /// running inside a pod (ServiceAccount token), falls back to kubeconfig.
    pub async fn new(
        config: &JoySafeterConfig,
        egress_socket: Option<Arc<dyn SandboxSocketProvisioner>>,
        placement_events: Option<PlacementEventSink>,
    ) -> anyhow::Result<Self> {
        let client = Client::try_default()
            .await
            .map_err(|e| anyhow::anyhow!("failed to create K8s client: {e}"))?;

        // Verify connectivity
        let _version = client
            .apiserver_version()
            .await
            .map_err(|e| anyhow::anyhow!("K8s API server unreachable: {e}"))?;

        // Start PodWatcher — background Watch stream keeps local pod cache synced.
        // status() and list_active() read from this cache (zero API calls).
        //
        let pod_watcher = PodWatcher::new(
            client.clone(),
            &config.k8s_namespace,
            placement_events.clone(),
        );

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
            egress_socket,
            pod_watcher,
        })
    }

    /// Write a file into a K8s pod using a tar archive piped via exec stdin.
    ///
    /// This mirrors Docker's `upload_to_container` reliability: the tar format
    /// carries an explicit byte-length header, so `tar xf -` on the receiving end
    /// either writes the complete file or errors out — no silent 0-byte writes
    /// from stdin timing races that plagued the previous `base64 | cat >>` approach.
    async fn write_file_to_pod(
        &self,
        external_id: &str,
        normalized: &str,
        content: &[u8],
    ) -> anyhow::Result<()> {
        let parent = Path::new(normalized)
            .parent()
            .and_then(|p| p.to_str())
            .unwrap_or("/workspace");

        let relative_path = normalized
            .strip_prefix('/')
            .ok_or_else(|| anyhow::anyhow!("invalid normalized mount path: {normalized}"))?;
        if relative_path.is_empty() {
            anyhow::bail!("invalid normalized mount path: {normalized}");
        }
        self.exec(external_id, &["mkdir", "-p", parent]).await?;

        // Build a tar archive in memory (same pattern as Docker provider). Tar
        // entry names must be relative; extracting with `-C /` writes the file to
        // the requested absolute workspace path.
        let tar_buf = {
            let mut buf = Vec::new();
            {
                let mut ar = tar::Builder::new(&mut buf);
                let mut header = tar::Header::new_gnu();
                header.set_path(relative_path)?;
                header.set_size(content.len() as u64);
                header.set_mode(0o644);
                header.set_cksum();
                ar.append(&header, content)?;
                ar.finish()?;
            }
            buf
        };

        // Pipe the tar into `tar xf -` via K8s exec stdin.
        let cmd: Vec<String> = ["tar", "xf", "-", "-C", "/"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        let mut attached = self
            .pods()
            .exec(
                external_id,
                &cmd,
                &AttachParams::default()
                    .stdin(true)
                    .stdout(true)
                    .stderr(true)
                    .max_stdin_buf_size(tar_buf.len() + 1024),
            )
            .await?;

        let status_fut = attached.take_status();

        // Write the tar to stdin, then close it so tar sees EOF.
        let mut stdin = attached
            .stdin()
            .ok_or_else(|| anyhow::anyhow!("failed to open stdin for K8s exec tar"))?;
        stdin.write_all(&tar_buf).await?;
        drop(stdin);

        // Drain stdout/stderr (tar shouldn't produce output on success, but we
        // must consume them to avoid deadlock before join).
        let stdout_reader = attached.stdout();
        let stderr_reader = attached.stderr();
        let mut stderr = String::new();
        let drain = async {
            if let Some(mut r) = stdout_reader {
                let _ = tokio::io::copy(&mut r, &mut tokio::io::sink()).await;
            }
        };
        let drain_err = async {
            if let Some(mut r) = stderr_reader {
                r.read_to_string(&mut stderr).await.ok();
            }
        };
        tokio::join!(drain, drain_err);
        attached.join().await?;

        // Check exit status.
        if let Some(status_fut) = status_fut {
            if let Some(status) = status_fut.await {
                if status.status.as_deref() == Some("Failure") || status.code.unwrap_or(0) != 0 {
                    anyhow::bail!(
                        "K8s exec tar xf failed for {normalized}: code={:?} stderr={}",
                        status.code,
                        stderr.trim()
                    );
                }
            }
        }

        Ok(())
    }

    async fn upload_file_to_pod(
        &self,
        external_id: &str,
        path: &str,
        content: &[u8],
    ) -> anyhow::Result<()> {
        let normalized = normalize_workspace_mount_path(path)?;
        self.write_file_to_pod(external_id, &normalized, content)
            .await?;

        // Verify file size. With tar injection this should always match (tar
        // carries an explicit length header), but keep the check as a safety net.
        let size_output = self.exec(external_id, &["wc", "-c", &normalized]).await?;
        let actual_size = size_output
            .split_whitespace()
            .next()
            .and_then(|value| value.parse::<usize>().ok())
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "failed to verify injected file size for {normalized}: wc output={size_output:?}"
                )
            })?;
        if actual_size != content.len() {
            anyhow::bail!(
                "injected file size mismatch for {normalized}: expected {}, got {actual_size}",
                content.len()
            );
        }

        match self
            .auto_extract_archive_to_pod(external_id, &normalized, content)
            .await
        {
            Ok(true) => info!(
                external_id,
                path = %normalized,
                "Auto-extracted archive into K8s sandbox"
            ),
            Ok(false) => {}
            Err(e) => warn!(
                external_id,
                path = %normalized,
                "Failed to auto-extract archive into K8s sandbox: {e}"
            ),
        }

        Ok(())
    }

    async fn auto_extract_archive_to_pod(
        &self,
        external_id: &str,
        normalized_path: &str,
        content: &[u8],
    ) -> anyhow::Result<bool> {
        let Some(target_dir) =
            crate::sandbox::archive::archive_extract_dir(Path::new(normalized_path))
        else {
            return Ok(false);
        };

        let tmp_dir = tempfile::tempdir()?;
        let archive_name = Path::new(normalized_path)
            .file_name()
            .ok_or_else(|| anyhow::anyhow!("invalid archive path: {normalized_path}"))?;
        let archive_path = tmp_dir.path().join(archive_name);
        let extracted_path = tmp_dir.path().join("extracted");
        tokio::fs::write(&archive_path, content).await?;
        crate::sandbox::archive::extract_archive_to_dir(archive_path, extracted_path.clone())
            .await?;

        let target_dir = target_dir
            .to_str()
            .ok_or_else(|| anyhow::anyhow!("invalid archive target path"))?
            .to_string();
        self.exec(external_id, &["mkdir", "-p", &target_dir])
            .await?;

        let tar_buf = crate::sandbox::archive::build_tar_from_dir(&extracted_path)?;
        let temp_tar = format!(
            "/workspace/.joysafeter_extract_{}.tar",
            uuid::Uuid::now_v7().simple()
        );
        self.write_file_to_pod(external_id, &temp_tar, &tar_buf)
            .await?;
        let extract_result = self
            .exec(external_id, &["tar", "-xf", &temp_tar, "-C", &target_dir])
            .await;
        let _ = self.exec(external_id, &["rm", "-f", &temp_tar]).await;
        extract_result?;

        Ok(true)
    }

    fn pods(&self) -> Api<Pod> {
        Api::namespaced(self.client.clone(), &self.namespace)
    }

    async fn exec_owned(&self, external_id: &str, cmd: &[String]) -> anyhow::Result<String> {
        let mut attached = self
            .pods()
            .exec(
                external_id,
                cmd,
                &AttachParams::default()
                    .stdout(true)
                    .stderr(true)
                    .max_stdout_buf_size(64 * 1024)
                    .max_stderr_buf_size(64 * 1024),
            )
            .await?;
        let status_fut = attached.take_status();
        let stdout_reader = attached.stdout();
        let stderr_reader = attached.stderr();
        let mut stdout = String::new();
        let mut stderr = String::new();
        let stdout_fut = async {
            if let Some(mut reader) = stdout_reader {
                reader.read_to_string(&mut stdout).await?;
            }
            Ok::<(), std::io::Error>(())
        };
        let stderr_fut = async {
            if let Some(mut reader) = stderr_reader {
                reader.read_to_string(&mut stderr).await?;
            }
            Ok::<(), std::io::Error>(())
        };
        let (stdout_result, stderr_result) = tokio::join!(stdout_fut, stderr_fut);
        stdout_result?;
        stderr_result?;
        attached.join().await?;
        if let Some(status_fut) = status_fut {
            if let Some(status) = status_fut.await {
                if status.status.as_deref() == Some("Failure") || status.code.unwrap_or(0) != 0 {
                    anyhow::bail!(
                        "K8s exec failed for {:?}: status={:?} code={:?} reason={:?} message={:?} stderr={}",
                        cmd,
                        status.status,
                        status.code,
                        status.reason,
                        status.message,
                        stderr.trim()
                    );
                }
            }
        }
        if !stderr.trim().is_empty() {
            warn!(external_id, command = ?cmd, stderr = %stderr.trim(), "K8s exec wrote stderr");
        }
        Ok(stdout)
    }

    async fn cleanup_egress_socket_dir(&self, external_id: &str) -> anyhow::Result<()> {
        if self.egress_socket.is_none() {
            return Ok(());
        }

        let command = socket_cleanup_plan(external_id)?;
        let envoy_pods = self
            .pods()
            .list(&ListParams::default().labels(ENVOY_POD_SELECTOR))
            .await
            .context("failed to list Envoy pods for socket cleanup")?;
        let pod_names = envoy_pods
            .items
            .into_iter()
            .filter_map(|pod| pod.metadata.name)
            .collect::<Vec<_>>();
        if pod_names.is_empty() {
            anyhow::bail!("no Envoy pods available for K8s socket cleanup");
        }

        let mut failures = Vec::new();
        for pod_name in &pod_names {
            if let Err(error) = self.exec_owned(pod_name, &command).await {
                failures.push(format!("{pod_name}: {error}"));
            }
        }
        if !failures.is_empty() {
            anyhow::bail!(
                "failed to clean K8s Envoy socket directory through {} of {} pods: {}",
                failures.len(),
                pod_names.len(),
                failures.join("; ")
            );
        }

        info!(external_id, "Removed K8s Envoy socket directory");
        Ok(())
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

        let runtime_env = config.provider_environment();
        let mut env: Vec<Value> = runtime_env
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
        let has_egress = config.network.as_deref() == Some("none") && self.egress_socket.is_some();
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
        apply_pod_placement(
            &mut pod_spec,
            self.config.k8s_priority_class_name.as_deref(),
            &self.config.k8s_node_selector,
            &self.config.k8s_tolerations,
        );

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

fn apply_pod_placement(
    pod_spec: &mut Value,
    priority_class_name: Option<&str>,
    node_selector: &BTreeMap<String, String>,
    tolerations: &[Value],
) {
    if let Some(priority_class_name) = priority_class_name {
        pod_spec["priorityClassName"] = json!(priority_class_name);
    }
    if !node_selector.is_empty() {
        pod_spec["nodeSelector"] = json!(node_selector);
    }
    if !tolerations.is_empty() {
        pod_spec["tolerations"] = json!(tolerations);
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
            Ok(_) => {}
            Err(kube::Error::Api(err)) if err.code == 404 => {}
            Err(e) => return Err(e.into()),
        }
        self.cleanup_egress_socket_dir(external_id).await
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        self.stop(external_id).await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        Ok(self.pod_watcher.status(external_id).await)
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        let cmd_owned: Vec<String> = cmd.iter().map(|s| s.to_string()).collect();
        self.exec_owned(external_id, &cmd_owned).await
    }

    async fn patch_labels(
        &self,
        external_id: &str,
        labels: &HashMap<String, String>,
    ) -> anyhow::Result<()> {
        let patch = json!({
            "metadata": {
                "labels": labels,
            }
        });
        self.pods()
            .patch(external_id, &PatchParams::default(), &Patch::Merge(&patch))
            .await?;
        Ok(())
    }

    async fn inject_files(&self, external_id: &str, files: &[FileToInject]) -> anyhow::Result<()> {
        let mut injected = 0usize;
        let mut failures = Vec::new();
        for file in files {
            let Some(content) = file.content.as_ref() else {
                failures.push(format!("{}: missing loaded content", file.mount_path));
                continue;
            };
            if let Err(e) = self
                .upload_file_to_pod(external_id, &file.mount_path, content)
                .await
            {
                failures.push(format!("{}: {e}", file.mount_path));
                continue;
            }
            injected += 1;
        }
        if !failures.is_empty() {
            anyhow::bail!(
                "failed to inject {} of {} files into K8s sandbox: {}",
                failures.len(),
                files.len(),
                failures.join("; ")
            );
        }
        info!(external_id, injected, "Injected files into K8s sandbox");
        Ok(())
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
            has_egress_management: self.egress_socket.is_some(),
            network_isolation: if self.egress_socket.is_some() {
                NetworkIsolation::Envoy
            } else {
                NetworkIsolation::None
            },
            stop_semantics: StopSemantics::Destructive,
        }
    }
}

fn normalize_workspace_mount_path(path: &str) -> anyhow::Result<String> {
    if path.contains('\0') {
        anyhow::bail!("invalid NUL byte in mount path");
    }
    let normalized = path.replace('\\', "/");
    if !normalized.starts_with("/workspace/") {
        anyhow::bail!("mount path must be under /workspace: {path}");
    }
    let mut parts = Vec::new();
    for part in normalized.split('/') {
        match part {
            "" | "." => {}
            ".." => anyhow::bail!("path traversal blocked: {path}"),
            value => parts.push(value),
        }
    }
    Ok(format!("/{}", parts.join("/")))
}

fn socket_cleanup_plan(external_id: &str) -> anyhow::Result<Vec<String>> {
    let sandbox_uuid = external_id
        .strip_prefix("joysafeter-")
        .and_then(|value| uuid::Uuid::parse_str(value).ok())
        .ok_or_else(|| anyhow::anyhow!("invalid K8s sandbox pod name: {external_id}"))?;
    Ok(vec![
        "rm".to_string(),
        "-rf".to_string(),
        "--".to_string(),
        format!("/sockets/{sandbox_uuid}"),
    ])
}

#[cfg(test)]
mod tests;
