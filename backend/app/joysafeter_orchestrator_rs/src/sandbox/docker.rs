use std::sync::Arc;

use async_trait::async_trait;
use bollard::container::{
    Config, CreateContainerOptions, RemoveContainerOptions, StartContainerOptions,
    StopContainerOptions, UploadToContainerOptions,
};
use bollard::exec::{CreateExecOptions, StartExecResults};
use bollard::models::HostConfig;
use bollard::Docker;
use futures::StreamExt;
use sqlx::PgPool;
use tracing::{info, warn};

use super::envoy::{EnvoyConfig, EnvoyManager};
use super::file_injection::{FileToInject, InjectionStrategy};
use super::lds_backend::{
    CdsBackend, DeltaXdsServer, DeniedCidr, FilesystemCds, FilesystemLds, GrpcCds, GrpcLds,
    LdsBackend,
};
use super::mounts::SandboxMount;
use super::provider::{ProviderSandboxInfo, SandboxCreateConfig, SandboxProvider, SandboxStatus};
use crate::config::JoySafeterConfig;

/// S13: Retry wrapper for Docker operations that may fail due to transient errors.
/// Retries up to `max_retries` times with 1s delay on 500/503 or connection errors.
/// NOT used for `create` to avoid creating multiple containers.
async fn retry_docker<F, Fut, T>(
    op_name: &str,
    external_id: &str,
    max_retries: u32,
    f: F,
) -> anyhow::Result<T>
where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    let mut last_error = None;
    for attempt in 0..=max_retries {
        match f().await {
            Ok(val) => return Ok(val),
            Err(e) => {
                let err_str = format!("{e}");
                let is_retryable = err_str.contains("500")
                    || err_str.contains("503")
                    || err_str.contains("connection")
                    || err_str.contains("Connection")
                    || err_str.contains("hyper")
                    || err_str.contains("broken pipe");

                if !is_retryable || attempt == max_retries {
                    return Err(e);
                }

                warn!(
                    op = op_name,
                    external_id = external_id,
                    attempt = attempt + 1,
                    max_retries = max_retries,
                    "Docker {op_name} transient error, retrying in 1s: {err_str}"
                );
                last_error = Some(e);
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            }
        }
    }
    Err(last_error.unwrap_or_else(|| anyhow::anyhow!("retry_docker: no attempts made")))
}

/// Docker-backed sandbox provider using bollard.
///
/// Owns all Docker-specific subsystems: Envoy sidecar, image builder, xDS.
/// The orchestrator framework interacts only through the `SandboxProvider` trait.
#[derive(Clone)]
pub struct DockerProvider {
    docker: Arc<Docker>,
    config: JoySafeterConfig,
    socket_volume: Option<String>,
    hardening: SandboxHardening,
    /// Envoy network isolation manager (None when envoy_enabled=false).
    envoy_manager: Option<Arc<EnvoyManager>>,
    /// Delta xDS server for gRPC xDS mode (None when filesystem mode or Envoy disabled).
    xds_service: Option<Arc<DeltaXdsServer>>,
}

/// Resolved hardening settings applied to every sandbox container the
/// provider creates. Constructed once from `JoySafeterConfig` at startup.
#[derive(Clone, Debug)]
pub(crate) struct SandboxHardening {
    pub drop_all_caps: bool,
    pub no_new_privileges: bool,
    pub pids_limit: i64,
    /// `uid:gid`. Empty string means "use the image default USER".
    pub run_as_user: String,
}

impl DockerProvider {
    pub async fn new(config: &JoySafeterConfig) -> anyhow::Result<Self> {
        let docker = Docker::connect_with_local_defaults()
            .map_err(|e| anyhow::anyhow!("failed to connect to Docker: {e}"))?;

        // Verify connectivity
        docker
            .ping()
            .await
            .map_err(|e| anyhow::anyhow!("Docker ping failed (is Docker running?): {e}"))?;

        let docker = Arc::new(docker);

        // Build Envoy manager + xDS service if Envoy is enabled
        let mut xds_service: Option<Arc<DeltaXdsServer>> = None;
        let envoy_manager = if config.envoy_enabled {
            let (lds, cds): (Arc<dyn LdsBackend>, Arc<dyn CdsBackend>) =
                if config.envoy_xds_mode == "grpc" {
                    let server = DeltaXdsServer::new();
                    xds_service = Some(server.clone());
                    (
                        Arc::new(GrpcLds::new(server.clone())),
                        Arc::new(GrpcCds::new(server)),
                    )
                } else {
                    // `controller` mode falls here too: the Go egress-controller
                    // serves xDS over ADS, so we build no in-process DeltaXdsServer
                    // (xds_service stays None). The Filesystem backends are never
                    // contacted in controller mode — the listener-free
                    // DockerEnvoyNetworkPreparer only ensures the socket dir.
                    (
                        Arc::new(FilesystemLds::new(
                            docker.clone(),
                            config.envoy_container_name.clone(),
                        )),
                        Arc::new(FilesystemCds::new(
                            docker.clone(),
                            config.envoy_container_name.clone(),
                        )),
                    )
                };
            Some(Arc::new(EnvoyManager::new(
                docker.clone(),
                EnvoyConfig {
                    envoy_image: config.envoy_image.clone(),
                    socket_volume: config.envoy_socket_volume.clone(),
                    config_dir: config.envoy_config_dir.clone(),
                    envoy_network: config.envoy_network.clone(),
                    grpc_target_host: config.envoy_grpc_host.clone(),
                    grpc_target_port: config.envoy_grpc_port,
                    container_name: config.envoy_container_name.clone(),
                    xds_mode: config.envoy_xds_mode.clone(),
                    controller_xds_host: config.egress_controller_xds_host.clone(),
                    controller_xds_port: config.egress_controller_xds_port,
                    // Controller mode groups Envoys by node.metadata; use the
                    // same selector the durable authority hashes the group key
                    // from so this Envoy joins that group.
                    node_metadata: if config.envoy_xds_mode == "controller" {
                        Some(
                            crate::egress::enforcer::shared_docker_node_selector(config)
                                .metadata_value(),
                        )
                    } else {
                        None
                    },
                    denied_cidrs: config
                        .envoy_egress_denied_cidrs
                        .iter()
                        .map(|cidr| cidr.parse::<DeniedCidr>())
                        .collect::<anyhow::Result<Vec<_>>>()?,
                },
                lds,
                cds,
            )))
        } else {
            None
        };

        Ok(Self {
            docker,
            config: config.clone(),
            socket_volume: Some(config.envoy_socket_volume.clone()),
            hardening: SandboxHardening {
                drop_all_caps: config.sandbox_drop_all_caps,
                no_new_privileges: config.sandbox_no_new_privileges,
                pids_limit: config.sandbox_pids_limit,
                run_as_user: config.sandbox_run_as_user.clone(),
            },
            envoy_manager,
            xds_service,
        })
    }

    /// Create a no-op provider (for scheduler fallback when no provider is needed).
    pub fn new_noop() -> Self {
        Self {
            docker: Arc::new(Docker::connect_with_local_defaults().unwrap()),
            config: JoySafeterConfig::from_env(),
            socket_volume: None,
            hardening: SandboxHardening {
                drop_all_caps: true,
                no_new_privileges: true,
                pids_limit: 256,
                run_as_user: "1000:1000".to_string(),
            },
            envoy_manager: None,
            xds_service: None,
        }
    }

    /// Get the Envoy manager (if enabled). Used by framework during transition.
    pub fn envoy_manager(&self) -> Option<&Arc<EnvoyManager>> {
        self.envoy_manager.as_ref()
    }

    /// Get the xDS service (if gRPC xDS mode). Used to register ADS on gRPC server.
    pub fn xds_service(&self) -> Option<Arc<DeltaXdsServer>> {
        self.xds_service.clone()
    }

    async fn upload_file_to_container(
        &self,
        external_id: &str,
        path: &str,
        content: &[u8],
    ) -> anyhow::Result<()> {
        let normalized = normalize_workspace_mount_path(path)?;
        let parent = std::path::Path::new(&normalized)
            .parent()
            .and_then(|p| p.to_str())
            .unwrap_or("/workspace");
        let _ = self.exec(external_id, &["mkdir", "-p", parent]).await;

        let file_name = std::path::Path::new(&normalized)
            .file_name()
            .ok_or_else(|| anyhow::anyhow!("invalid target file path: {normalized}"))?;
        let upload_dir = std::path::Path::new(&normalized)
            .parent()
            .and_then(|p| p.to_str())
            .unwrap_or("/")
            .to_string();

        let mut tar_buf = Vec::new();
        {
            let mut ar = tar::Builder::new(&mut tar_buf);
            let mut header = tar::Header::new_gnu();
            header.set_path(file_name)?;
            header.set_size(content.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            ar.append(&header, content)?;
            ar.finish()?;
        }

        self.docker
            .upload_to_container(
                external_id,
                Some(UploadToContainerOptions {
                    path: upload_dir,
                    ..Default::default()
                }),
                tar_buf.into(),
            )
            .await?;

        match self
            .auto_extract_archive_to_container(external_id, &normalized, content)
            .await
        {
            Ok(true) => info!(
                external_id,
                path = %normalized,
                "Auto-extracted archive into Docker sandbox"
            ),
            Ok(false) => {}
            Err(e) => warn!(
                external_id,
                path = %normalized,
                "Failed to auto-extract archive into Docker sandbox: {e}"
            ),
        }

        Ok(())
    }

    async fn auto_extract_archive_to_container(
        &self,
        external_id: &str,
        normalized_path: &str,
        content: &[u8],
    ) -> anyhow::Result<bool> {
        let Some(target_dir) =
            crate::sandbox::archive::archive_extract_dir(std::path::Path::new(normalized_path))
        else {
            return Ok(false);
        };

        let tmp_dir = tempfile::tempdir()?;
        let archive_name = std::path::Path::new(normalized_path)
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
        let _ = self.exec(external_id, &["mkdir", "-p", &target_dir]).await;

        let tar_buf = crate::sandbox::archive::build_tar_from_dir(&extracted_path)?;
        self.docker
            .upload_to_container(
                external_id,
                Some(UploadToContainerOptions {
                    path: target_dir,
                    ..Default::default()
                }),
                tar_buf.into(),
            )
            .await?;

        Ok(true)
    }

    /// Inject files into a container via Docker archive upload.
    pub async fn inject_file_pairs(
        &self,
        external_id: &str,
        files: &[(String, Vec<u8>)],
    ) -> anyhow::Result<()> {
        for (path, content) in files {
            let mut tar_buf = Vec::new();
            {
                let mut ar = tar::Builder::new(&mut tar_buf);
                let mut header = tar::Header::new_gnu();
                header.set_path(path)?;
                header.set_size(content.len() as u64);
                header.set_mode(0o644);
                header.set_cksum();
                ar.append(&header, content.as_slice())?;
                ar.finish()?;
            }

            self.docker
                .upload_to_container(
                    external_id,
                    Some(UploadToContainerOptions {
                        path: "/",
                        ..Default::default()
                    }),
                    tar_buf.into(),
                )
                .await?;
        }

        Ok(())
    }

    /// Close the Docker client (cleanup).
    pub async fn close(&self) {
        // bollard's Docker client doesn't require explicit close;
        // connections are dropped when the Arc is dropped.
        // This method exists for API parity with Python's aiodocker.close().
    }

    async fn docker_provisioning_status(
        &self,
        external_id: &str,
    ) -> anyhow::Result<serde_json::Value> {
        match self.docker.inspect_container(external_id, None).await {
            Ok(info) => {
                let state = info
                    .state
                    .as_ref()
                    .and_then(|s| s.status.as_ref())
                    .map(|s| format!("{s:?}"))
                    .unwrap_or_default()
                    .to_lowercase();

                let (stage, progress, complete) = match state.as_str() {
                    "running" => ("running", 100, true),
                    "created" => ("created", 50, false),
                    "restarting" => ("restarting", 60, false),
                    "removing" => ("removing", 0, false),
                    "paused" => ("paused", 80, false),
                    "exited" => ("exited", 0, true),
                    "dead" => ("dead", 0, true),
                    _ => ("unknown", 0, false),
                };

                Ok(serde_json::json!({
                    "stage": stage,
                    "progress": progress,
                    "message": format!("Container state: {state}"),
                    "complete": complete,
                    "error": state == "dead" || state == "exited",
                    "error_message": if state == "dead" { Some("Container is dead") } else { None::<&str> },
                }))
            }
            Err(bollard::errors::Error::DockerResponseServerError {
                status_code: 404, ..
            }) => Ok(serde_json::json!({
                "stage": "not_found",
                "progress": 0,
                "message": "Container not found",
                "complete": false,
                "error": true,
                "error_message": "Container not found",
            })),
            Err(e) => Err(e.into()),
        }
    }
}

#[async_trait]
impl SandboxProvider for DockerProvider {
    async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
        let container_name = format!("joysafeter-{}", config.sandbox_id);

        let mut labels = config.labels.clone();
        labels.insert("joysafeter".to_string(), "true".to_string());
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            config.sandbox_id.to_string(),
        );

        let mut env_map = config.env.clone();
        let mut binds = Vec::new();

        if config.network.as_deref() == Some("none") {
            let socket_volume = self
                .socket_volume
                .clone()
                .unwrap_or_else(|| "joysafeter-sockets".to_string());
            binds.push(format!("{socket_volume}:/sockets"));
            let orchestrator_url = format!("unix:///sockets/{}/grpc.sock", config.sandbox_id);
            env_map.insert(
                "JOYSAFETER_ORCHESTRATOR_URL".to_string(),
                orchestrator_url.clone(),
            );
            env_map.insert("JOYSAFETER_ORCHESTRATOR_URL".to_string(), orchestrator_url);

            // Bind the LLM credential env vars to this sandbox's runner token so
            // the runner's model request carries the identity the egress Envoy
            // ext_authz validates before it strips the placeholder and injects
            // the real platform credential. Without this the sandbox sends the
            // generic placeholder, ext_authz denies (403), and the real key is
            // never injected. K8s does the equivalent in `render_pod_env`; both
            // planes share `apply_llm_identity_credentials` as the one source of
            // truth for this identity mapping.
            if let Some(runner_token) = env_map.get("JOYSAFETER_RUNNER_TOKEN").cloned() {
                crate::egress::llm::apply_llm_identity_credentials(&mut env_map, &runner_token);
            }
        }

        let env: Vec<String> = env_map.iter().map(|(k, v)| format!("{k}={v}")).collect();

        let mut host_config = HostConfig {
            ..Default::default()
        };

        // CPU limit
        if let Some(cpu) = config.cpu_limit {
            host_config.nano_cpus = Some((cpu * 1e9) as i64);
        }

        // Memory limit
        if let Some(mem_mb) = config.memory_limit_mb {
            host_config.memory = Some((mem_mb * 1024 * 1024) as i64);
        }

        // Network
        if let Some(ref network) = config.network {
            host_config.network_mode = Some(network.clone());
        }

        // Workspace bind mount — workspace_path is the full host path (root/session_id)
        if let Some(ref workspace) = config.workspace_path {
            let host_path = workspace.clone();
            // Ensure host directory exists
            let _ = tokio::fs::create_dir_all(&host_path).await;
            // #32: Set perns 0o777 (Python L362: os.chmod(workspace_path, 0o777))
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ =
                    tokio::fs::set_permissions(&host_path, std::fs::Permissions::from_mode(0o777))
                        .await;
            }
            binds.push(format!("{host_path}:/workspace"));
        }

        // C6 fix: Memory store bind mounts (matching Python docker_provider.py)
        for (host_path, container_path) in &config.memory_mounts {
            let _ = tokio::fs::create_dir_all(host_path).await;
            binds.push(format!("{host_path}:{container_path}"));
        }

        for mount in &config.mounts {
            match mount {
                SandboxMount::DockerBind {
                    source,
                    target,
                    read_only,
                } => {
                    let mode = if *read_only { ":ro" } else { ":rw" };
                    binds.push(format!("{source}:{target}{mode}"));
                }
                SandboxMount::K8sPvc { .. } => {
                    anyhow::bail!("K8s PVC mount was passed to Docker provider");
                }
            }
        }

        if !binds.is_empty() {
            host_config.binds = Some(binds);
        }

        // ExtraHosts: enable host.docker.internal on Linux
        host_config.extra_hosts = Some(vec!["host.docker.internal:host-gateway".to_string()]);

        // -- P0.1 hardening ----------------------------------------------------
        // Apply the Anthropic "Securely deploying AI agents" baseline. Coding
        // agents run as a non-root user inside the container and don't need
        // any of these capabilities, so dropping them has no operational
        // impact — but it cuts the privilege-escalation chain that a prompt
        // injection would otherwise exploit if it landed code execution.
        if self.hardening.drop_all_caps {
            host_config.cap_drop = Some(vec!["ALL".to_string()]);
        }
        // security_opt is a Vec<String>; merge with whatever the caller may
        // have set elsewhere (currently nothing, but keep it forward-safe).
        let mut sec_opts: Vec<String> = host_config.security_opt.take().unwrap_or_default();
        if self.hardening.no_new_privileges {
            sec_opts.push("no-new-privileges:true".to_string());
        }
        if !sec_opts.is_empty() {
            host_config.security_opt = Some(sec_opts);
        }
        if self.hardening.pids_limit > 0 {
            host_config.pids_limit = Some(self.hardening.pids_limit);
        }

        let container_user = if self.hardening.run_as_user.is_empty() {
            None
        } else {
            Some(self.hardening.run_as_user.clone())
        };

        let container_config = Config {
            image: Some(config.image.clone()),
            user: container_user,
            working_dir: Some("/workspace".to_string()),
            env: Some(env),
            labels: Some(labels),
            host_config: Some(host_config),
            ..Default::default()
        };

        let create_opts = CreateContainerOptions {
            name: &container_name,
            platform: None,
        };

        // Remove existing container with same name if any
        let _ = self
            .docker
            .remove_container(
                &container_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;

        let response = self
            .docker
            .create_container(Some(create_opts), container_config)
            .await?;

        let container_id = response.id;

        // Start container; clean up on failure (Python L118-125)
        if let Err(e) = self
            .docker
            .start_container(&container_id, None::<StartContainerOptions<String>>)
            .await
        {
            let _ = self
                .docker
                .remove_container(
                    &container_id,
                    Some(RemoveContainerOptions {
                        force: true,
                        ..Default::default()
                    }),
                )
                .await;
            return Err(e.into());
        }

        info!(
            sandbox_id = %config.sandbox_id,
            container_name = %container_name,
            image = %config.image,
            "Docker container created and started"
        );

        // Return container_name (not container_id) — matches Python L127
        Ok(container_name)
    }

    async fn start(&self, external_id: &str) -> anyhow::Result<()> {
        let docker = self.docker.clone();
        let ext_id = external_id.to_string();
        retry_docker("start", external_id, 2, || {
            let docker = docker.clone();
            let ext_id = ext_id.clone();
            async move {
                docker
                    .start_container(&ext_id, None::<StartContainerOptions<String>>)
                    .await?;
                Ok(())
            }
        })
        .await
    }

    async fn stop(&self, external_id: &str) -> anyhow::Result<()> {
        let docker = self.docker.clone();
        let ext_id = external_id.to_string();
        retry_docker("stop", external_id, 2, || {
            let docker = docker.clone();
            let ext_id = ext_id.clone();
            async move {
                match docker
                    .stop_container(&ext_id, Some(StopContainerOptions { t: 10 }))
                    .await
                {
                    Ok(_) => Ok(()),
                    Err(bollard::errors::Error::DockerResponseServerError {
                        status_code: 304,
                        ..
                    })
                    | Err(bollard::errors::Error::DockerResponseServerError {
                        status_code: 404,
                        ..
                    }) => Ok(()),
                    Err(e) => Err(e.into()),
                }
            }
        })
        .await
    }

    async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
        let docker = self.docker.clone();
        let ext_id = external_id.to_string();
        retry_docker("destroy", external_id, 2, || {
            let docker = docker.clone();
            let ext_id = ext_id.clone();
            async move {
                // Two-phase: stop first, then delete (matching Python L149-160)
                let _ = docker
                    .stop_container(&ext_id, Some(StopContainerOptions { t: 10 }))
                    .await;
                match docker
                    .remove_container(
                        &ext_id,
                        Some(RemoveContainerOptions {
                            force: true,
                            v: true,
                            ..Default::default()
                        }),
                    )
                    .await
                {
                    Ok(_) => Ok(()),
                    Err(bollard::errors::Error::DockerResponseServerError {
                        status_code: 404,
                        ..
                    }) => Ok(()),
                    Err(e) => Err(e.into()),
                }
            }
        })
        .await
    }

    async fn status(&self, external_id: &str) -> anyhow::Result<SandboxStatus> {
        match self.docker.inspect_container(external_id, None).await {
            Ok(info) => {
                let state = info
                    .state
                    .and_then(|s| s.status)
                    .map(|s| format!("{s:?}"))
                    .unwrap_or_default()
                    .to_lowercase();

                match state.as_str() {
                    "running" => Ok(SandboxStatus::Running),
                    "exited" | "dead" | "created" => Ok(SandboxStatus::Stopped),
                    other => Ok(SandboxStatus::Unknown(other.to_string())),
                }
            }
            Err(bollard::errors::Error::DockerResponseServerError {
                status_code: 404, ..
            }) => Ok(SandboxStatus::NotFound),
            Err(e) => Err(e.into()),
        }
    }

    async fn exec(&self, external_id: &str, cmd: &[&str]) -> anyhow::Result<String> {
        let exec = self
            .docker
            .create_exec(
                external_id,
                CreateExecOptions {
                    cmd: Some(cmd.iter().map(|s| s.to_string()).collect()),
                    attach_stdout: Some(true),
                    attach_stderr: Some(true),
                    ..Default::default()
                },
            )
            .await?;

        let mut output = String::new();
        if let StartExecResults::Attached {
            output: mut stream, ..
        } = self.docker.start_exec(&exec.id, None).await?
        {
            while let Some(Ok(msg)) = stream.next().await {
                output.push_str(&msg.to_string());
            }
        }

        Ok(output)
    }

    fn provider_name(&self) -> &'static str {
        "docker"
    }

    async fn list_active(&self) -> anyhow::Result<Vec<ProviderSandboxInfo>> {
        use bollard::container::ListContainersOptions;
        let mut filters = std::collections::HashMap::new();
        filters.insert("label".to_string(), vec!["joysafeter=true".to_string()]);
        filters.insert(
            "status".to_string(),
            vec!["running".to_string(), "exited".to_string()],
        );

        let containers = self
            .docker
            .list_containers(Some(ListContainersOptions {
                all: true,
                filters,
                ..Default::default()
            }))
            .await?;

        Ok(containers
            .into_iter()
            .map(|container| {
                let labels = container.labels.unwrap_or_default();
                let name = container
                    .names
                    .unwrap_or_default()
                    .into_iter()
                    .next()
                    .unwrap_or_default()
                    .trim_start_matches('/')
                    .to_string();
                ProviderSandboxInfo {
                    id: container.id.unwrap_or_default(),
                    name,
                    status: container.state.unwrap_or_default(),
                    image: container.image.unwrap_or_default(),
                    labels,
                }
            })
            .collect())
    }

    async fn provisioning_status(
        &self,
        external_id: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        self.docker_provisioning_status(external_id).await.map(Some)
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
                .upload_file_to_container(external_id, &file.mount_path, content)
                .await
            {
                failures.push(format!("{}: {e}", file.mount_path));
                continue;
            }
            injected += 1;
        }
        if !failures.is_empty() {
            anyhow::bail!(
                "failed to inject {} of {} files into Docker sandbox: {}",
                failures.len(),
                files.len(),
                failures.join("; ")
            );
        }
        info!(external_id, injected, "Injected files into Docker sandbox");
        Ok(())
    }

    // =================================================================
    // New execution-plane trait methods
    // =================================================================

    async fn on_startup(&self, _pool: &PgPool) -> anyhow::Result<()> {
        // Envoy init + LDS recovery is now performed by the orchestrator-owned
        // EgressEnforcer in main.rs; the provider no longer owns egress state.
        if self.envoy_manager.is_none() {
            info!("Envoy network isolation disabled");
        }
        Ok(())
    }

    fn orchestrator_url(&self, grpc_port: u16) -> String {
        self.config
            .grpc_public_url
            .clone()
            .unwrap_or_else(|| format!("http://host.docker.internal:{grpc_port}"))
    }

    fn supported_injection_strategies(&self) -> Vec<InjectionStrategy> {
        vec![
            InjectionStrategy::HostMount,
            InjectionStrategy::ProviderFallback,
        ]
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
