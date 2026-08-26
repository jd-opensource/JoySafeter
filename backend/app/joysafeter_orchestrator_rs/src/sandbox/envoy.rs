use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use crate::ids::SandboxId;
use anyhow::Context;
use bollard::container::{
    Config, CreateContainerOptions, RemoveContainerOptions, RestartContainerOptions,
    StartContainerOptions, WaitContainerOptions,
};
use bollard::exec::{CreateExecOptions, StartExecOptions};
use bollard::models::{HostConfig, Mount, MountTypeEnum};
use bollard::Docker;
use futures::TryStreamExt;
use serde_json::json;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};

use super::lds_backend::{
    validate_egress_policy, CdsBackend, LdsBackend, ListenerKind, ListenerSpec, SandboxCredentials,
    SandboxEgressPolicy,
};

/// Per-sandbox network isolation via a shared Envoy proxy sidecar container.
///
/// Listener config is delivered through a pluggable [`LdsBackend`] using either
/// the filesystem path or Delta gRPC xDS, selected by [`EnvoyConfig::xds_mode`].
/// The bootstrap written here is generated to match
/// the active mode. Everything else (socket dirs, the wait-for-sockets loop, the
/// data plane) is identical across modes. The authoritative config lives in the
/// backends; a per-sandbox JSON file is still written under
/// `/envoy-config/sandboxes/` purely for crash-recovery/debugging visibility.
pub struct EnvoyManager {
    /// Docker client for managing the Envoy container. `None` in K8s mode,
    /// where Envoy runs as a DaemonSet and its container lifecycle is not
    /// managed by the orchestrator (socket dir prep and health checks are
    /// skipped). Only the Docker-container paths dereference it.
    docker: Option<Arc<Docker>>,
    config: EnvoyConfig,
    lds: Arc<dyn LdsBackend>,
    cds: Arc<dyn CdsBackend>,
    sandbox_apply_locks: Mutex<HashMap<SandboxId, Arc<Mutex<()>>>>,
}

#[derive(Debug, Clone)]
pub struct EnvoyConfig {
    pub envoy_image: String,
    pub socket_volume: String,
    pub socket_host_dir: Option<String>,
    pub config_dir: String,
    pub envoy_network: String,
    pub grpc_target_host: String,
    pub grpc_target_port: u16,
    pub container_name: String,
    /// `"grpc"` (default, Delta xDS) or explicit compatibility mode
    /// `"filesystem"` (`lds.json`).
    pub xds_mode: String,
    pub write_debug_entries: bool,
    pub socket_ready_timeout_ms: u64,
    pub health_check_interval_sec: u64,
    pub health_failure_threshold: u64,
    /// When true, skip `prepare_socket_dir` (socket dir creation is handled
    /// externally — e.g. by a K8s initContainer on the sandbox pod). This
    /// avoids the orchestrator trying to mkdir on a remote node's filesystem.
    pub skip_socket_dir_prep: bool,
    /// Envoy node.id for the bootstrap config. In K8s DaemonSet mode this is
    /// the node name (from downward API), enabling node-aware xDS filtering.
    /// In Docker standalone mode, defaults to "joysafeter-envoy".
    pub node_id: String,
}

impl EnvoyConfig {
    fn is_grpc_mode(&self) -> bool {
        self.xds_mode == "grpc"
    }
}

/// Poll interval while waiting for Envoy to materialize a per-sandbox egress socket.
const SOCKET_READY_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Poll `check` every `interval` until it returns `true` or `timeout` elapses.
///
/// Returns `true` iff readiness was observed within the budget. Deliberately free
/// of I/O so its timing contract can be unit-tested without Docker; callers inject
/// the actual readiness probe.
async fn poll_until_ready<F, Fut>(mut check: F, timeout: Duration, interval: Duration) -> bool
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = bool>,
{
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        if check().await {
            return true;
        }
        if tokio::time::Instant::now() >= deadline {
            return false;
        }
        tokio::time::sleep(interval).await;
    }
}

/// Human description of where the orchestrator writes per-sandbox egress socket
/// directories, used in diagnostics when Envoy cannot see them.
fn socket_storage_description(host_dir: Option<&str>, volume: &str) -> String {
    match host_dir {
        Some(dir) => format!("host bind dir {dir}"),
        None => format!("docker volume {volume}"),
    }
}

/// Precise, actionable error for when Envoy's `/sockets` mount does not point at
/// the same storage the orchestrator (and sandboxes) use for egress sockets.
fn socket_storage_mismatch_error(storage: &str) -> String {
    format!(
        "Envoy cannot see the orchestrator's sandbox egress socket storage ({storage}). \
         The orchestrator, the Envoy proxy, and every sandbox container must mount the \
         SAME storage at /sockets; otherwise Envoy binds each per-sandbox listener pipe \
         on a filesystem the sandbox never sees and all egress silently fails. Align the \
         Envoy container's /sockets mount with the orchestrator's \
         JOYSAFETER_ENVOY_SOCKET_VOLUME / JOYSAFETER_ENVOY_SOCKET_HOST_DIR."
    )
}

impl EnvoyManager {
    pub fn new(
        docker: Option<Arc<Docker>>,
        config: EnvoyConfig,
        lds: Arc<dyn LdsBackend>,
        cds: Arc<dyn CdsBackend>,
    ) -> Self {
        Self {
            docker,
            config,
            lds,
            cds,
            sandbox_apply_locks: Mutex::new(HashMap::new()),
        }
    }

    /// Returns the Docker client, or an error in K8s mode where it is absent.
    /// Only Docker-container lifecycle paths (socket dir prep, health check,
    /// restart) call this; those paths are not exercised in K8s mode.
    fn docker(&self) -> anyhow::Result<&Docker> {
        self.docker
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("Docker client unavailable (K8s mode)"))
    }

    async fn sandbox_apply_lock(&self, sandbox_id: SandboxId) -> Arc<Mutex<()>> {
        let mut locks = self.sandbox_apply_locks.lock().await;
        locks
            .entry(sandbox_id)
            .or_insert_with(|| Arc::new(Mutex::new(())))
            .clone()
    }

    async fn cleanup_sandbox_apply_lock(&self, sandbox_id: SandboxId, lock: &Arc<Mutex<()>>) {
        let mut locks = self.sandbox_apply_locks.lock().await;
        if locks
            .get(&sandbox_id)
            .is_some_and(|current| Arc::ptr_eq(current, lock))
            && Arc::strong_count(lock) <= 2
        {
            locks.remove(&sandbox_id);
        }
    }

    /// Ensure the per-sandbox socket directory exists before Envoy binds its
    /// listener pipes there and before the sandbox mounts it.
    ///
    /// In host-bind mode, create the per-sandbox directory on the host before
    /// Envoy binds its listener pipe there. In Docker-volume mode there is no
    /// host path to prepare; Docker creates the volume directory inside the Linux
    /// VM and Envoy creates the final socket path when it applies LDS.
    pub async fn prepare_socket_dir(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if self.config.skip_socket_dir_prep {
            return Ok(()); // K8s: handled by pod initContainer
        }
        self.ensure_socket_subdir(&sandbox_id.as_uuid().to_string())
            .await
    }

    /// Create a directory named `name` under the shared socket storage (host bind
    /// dir or Docker volume), matching where per-sandbox egress sockets live. Used
    /// both for per-sandbox socket dirs and the startup consistency probe.
    async fn ensure_socket_subdir(&self, name: &str) -> anyhow::Result<()> {
        match self.config.socket_host_dir.as_deref() {
            Some(root) => {
                let dir = PathBuf::from(root).join(name);
                tokio::fs::create_dir_all(&dir).await?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    tokio::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o755))
                        .await?;
                }
                Ok(())
            }
            None => self.mkdir_in_socket_volume(name).await,
        }
    }

    async fn mkdir_in_socket_volume(&self, name: &str) -> anyhow::Result<()> {
        let helper_name = format!("joysafeter-envoy-socket-init-{name}");
        let _ = self
            .docker()?
            .remove_container(
                &helper_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;

        let mkdir_cmd = format!("mkdir -p /sockets/{name} && chmod 755 /sockets/{name}");
        let container_config = Config {
            image: Some(self.config.envoy_image.clone()),
            user: Some("0".to_string()),
            entrypoint: Some(vec!["/bin/sh".to_string(), "-lc".to_string()]),
            cmd: Some(vec![mkdir_cmd]),
            host_config: Some(HostConfig {
                mounts: Some(vec![Mount {
                    target: Some("/sockets".to_string()),
                    source: Some(self.config.socket_volume.clone()),
                    typ: Some(MountTypeEnum::VOLUME),
                    read_only: Some(false),
                    ..Default::default()
                }]),
                ..Default::default()
            }),
            ..Default::default()
        };
        self.docker()?
            .create_container(
                Some(CreateContainerOptions {
                    name: helper_name.as_str(),
                    platform: None,
                }),
                container_config,
            )
            .await?;
        self.docker()?
            .start_container(&helper_name, None::<StartContainerOptions<String>>)
            .await?;
        let wait = self
            .docker()?
            .wait_container(&helper_name, None::<WaitContainerOptions<String>>)
            .try_collect::<Vec<_>>()
            .await?;
        let status_code = wait.first().map(|result| result.status_code).unwrap_or(1);
        let _ = self
            .docker()?
            .remove_container(
                &helper_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;
        if status_code != 0 {
            anyhow::bail!(
                "failed to prepare Envoy socket volume directory {name}: helper exited {status_code}"
            );
        }
        debug!(name, socket_volume = %self.config.socket_volume, "Prepared Envoy socket dir in Docker volume");
        Ok(())
    }

    fn host_socket_dir(&self, sandbox_id: SandboxId) -> Option<PathBuf> {
        self.config
            .socket_host_dir
            .as_ref()
            .map(|root| PathBuf::from(root).join(sandbox_id.as_uuid().to_string()))
    }

    /// Run `test <flag> <path>` inside the Envoy container, returning `true` iff
    /// it exits 0. This queries the path from Envoy's *own* mount namespace, which
    /// is the authority on whether a per-sandbox egress socket actually exists.
    async fn envoy_path_test(&self, flag: &str, path: &str) -> anyhow::Result<bool> {
        let docker = self.docker()?;
        let exec = docker
            .create_exec(
                &self.config.container_name,
                CreateExecOptions {
                    cmd: Some(vec!["test".to_string(), flag.to_string(), path.to_string()]),
                    attach_stdout: Some(false),
                    attach_stderr: Some(false),
                    ..Default::default()
                },
            )
            .await?;
        docker
            .start_exec(
                &exec.id,
                Some(StartExecOptions {
                    detach: true,
                    ..Default::default()
                }),
            )
            .await?;
        // `test` exits immediately; poll the exec inspection for its exit code.
        for _ in 0..50 {
            let inspect = docker.inspect_exec(&exec.id).await?;
            if inspect.running == Some(false) {
                return Ok(inspect.exit_code == Some(0));
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        Ok(false)
    }

    /// Wait until Envoy has actually created the sandbox's egress socket, or fail.
    ///
    /// xDS ACK / filesystem LDS writes only prove the *config* was accepted; the
    /// runner cannot reach the network until the Unix socket file exists on the
    /// shared mount. In Docker standalone mode we confirm this from Envoy's own
    /// view. K8s / externalized socket-dir setups skip it (no shared Docker mount
    /// the orchestrator can query here).
    async fn wait_for_socket_ready(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if self.docker.is_none() || self.config.skip_socket_dir_prep {
            return Ok(());
        }
        let socket_path = format!("/sockets/{}/http.sock", sandbox_id.as_uuid());
        self.wait_for_socket_ready_with(sandbox_id, || {
            let socket_path = socket_path.clone();
            async move {
                self.envoy_path_test("-S", &socket_path)
                    .await
                    .unwrap_or(false)
            }
        })
        .await
    }

    /// Core of [`wait_for_socket_ready`] with the readiness probe injected, so the
    /// fail-loud contract can be unit-tested without Docker.
    async fn wait_for_socket_ready_with<F, Fut>(
        &self,
        sandbox_id: SandboxId,
        check: F,
    ) -> anyhow::Result<()>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = bool>,
    {
        let timeout = Duration::from_millis(self.config.socket_ready_timeout_ms.max(1));
        if poll_until_ready(check, timeout, SOCKET_READY_POLL_INTERVAL).await {
            return Ok(());
        }
        anyhow::bail!(
            "Envoy did not create egress socket /sockets/{sandbox}/http.sock for sandbox \
             {sandbox} within {timeout_ms}ms; the sandbox has no working egress. This usually \
             means Envoy's /sockets mount does not match the orchestrator's socket storage \
             ({storage}), or Envoy rejected the listener config.",
            sandbox = sandbox_id.as_uuid(),
            timeout_ms = self.config.socket_ready_timeout_ms,
            storage = socket_storage_description(
                self.config.socket_host_dir.as_deref(),
                &self.config.socket_volume
            ),
        );
    }

    /// Startup self-check: prove that the storage the orchestrator uses for
    /// per-sandbox egress socket dirs is the *same* storage Envoy mounts at
    /// `/sockets`. Creates a marker dir via the normal socket-dir path and
    /// confirms Envoy can see it; fails fast with a precise remediation message
    /// otherwise. This makes a cross-mount misconfiguration a loud boot-time
    /// failure instead of a silent per-sandbox egress outage in a new environment.
    pub async fn verify_socket_storage_consistency(&self) -> anyhow::Result<()> {
        if self.docker.is_none() || self.config.skip_socket_dir_prep {
            return Ok(());
        }
        // Envoy must be up for the probe; surface a clear error if it is not.
        self.wait_until_ready(Duration::from_secs(15)).await?;

        const MARKER: &str = ".joysafeter-socket-preflight";
        self.ensure_socket_subdir(MARKER)
            .await
            .context("failed to create socket-storage preflight marker")?;
        let visible = self
            .envoy_path_test("-d", &format!("/sockets/{MARKER}"))
            .await
            .unwrap_or(false);
        let storage = socket_storage_description(
            self.config.socket_host_dir.as_deref(),
            &self.config.socket_volume,
        );
        if !visible {
            anyhow::bail!("{}", socket_storage_mismatch_error(&storage));
        }
        info!(storage = %storage, "Envoy socket-storage consistency verified");
        Ok(())
    }

    /// Restart the Envoy container so it reloads a changed bootstrap. Envoy parses
    /// its bootstrap only once at process start, so a bootstrap/xDS-mode change is
    /// invisible to a long-running Envoy until it restarts. No-op when Docker is
    /// unavailable (K8s) or Envoy is not currently running (its entrypoint reads
    /// the fresh bootstrap on first start).
    async fn reload_envoy_after_bootstrap_change(&self) -> anyhow::Result<()> {
        let Some(docker) = self.docker.as_deref() else {
            return Ok(());
        };
        if self.health_check().await.is_err() {
            return Ok(());
        }
        warn!("Envoy bootstrap changed; restarting Envoy to load the new xDS transport");
        docker
            .restart_container(
                &self.config.container_name,
                Some(RestartContainerOptions { t: 10 }),
            )
            .await?;
        self.wait_until_ready(Duration::from_secs(15)).await
    }

    pub fn spawn_health_monitor(
        self: Arc<Self>,
        pool: sqlx::PgPool,
        llm_egress_allowed_hosts: Vec<String>,
        authority: crate::kernel::xds_authority::XdsAuthorityGuard,
    ) {
        if self.config.health_check_interval_sec == 0 {
            return;
        }
        tokio::spawn(async move {
            let mut failures = 0u64;
            let threshold = self.config.health_failure_threshold.max(1);
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(
                self.config.health_check_interval_sec,
            ));
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                interval.tick().await;
                match self.health_check().await {
                    Ok(()) => {
                        failures = 0;
                    }
                    Err(e) => {
                        failures += 1;
                        warn!(
                            failures,
                            threshold,
                            error = %e,
                            "Envoy health check failed"
                        );
                        if failures >= threshold {
                            failures = 0;
                            if let Err(recover_err) = self
                                .restart_and_recover(&pool, &llm_egress_allowed_hosts, &authority)
                                .await
                            {
                                warn!(error = %recover_err, "Envoy restart/recovery failed");
                            }
                        }
                    }
                }
            }
        });
    }

    async fn health_check(&self) -> anyhow::Result<()> {
        let info = self
            .docker()?
            .inspect_container(&self.config.container_name, None)
            .await?;
        let state = info.state.as_ref();
        let running = state.and_then(|s| s.running).unwrap_or(false);
        if !running {
            let status = state
                .and_then(|s| s.status.as_ref())
                .map(|s| format!("{s:?}"))
                .unwrap_or_else(|| "unknown".to_string());
            anyhow::bail!("Envoy container is not running: {status}");
        }

        Ok(())
    }

    async fn restart_and_recover(
        &self,
        pool: &sqlx::PgPool,
        llm_egress_allowed_hosts: &[String],
        authority: &crate::kernel::xds_authority::XdsAuthorityGuard,
    ) -> anyhow::Result<()> {
        warn!("Restarting Envoy container after failed health checks");
        self.docker()?
            .restart_container(
                &self.config.container_name,
                Some(RestartContainerOptions { t: 10 }),
            )
            .await?;
        self.wait_until_ready(std::time::Duration::from_secs(15))
            .await?;
        self.init().await?;
        self.recover_from_db(pool, llm_egress_allowed_hosts, authority)
            .await
    }

    async fn wait_until_ready(&self, timeout: std::time::Duration) -> anyhow::Result<()> {
        let deadline = std::time::Instant::now() + timeout;
        let mut last_error = String::new();
        while std::time::Instant::now() < deadline {
            match self.health_check().await {
                Ok(()) => return Ok(()),
                Err(e) => last_error = e.to_string(),
            }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }
        anyhow::bail!("Envoy did not become ready after restart: {last_error}")
    }

    /// Initialize: clean stale config, write bootstrap, reset LDS.
    pub async fn init(&self) -> anyhow::Result<()> {
        let sandboxes_dir = PathBuf::from(&self.config.config_dir).join("sandboxes");
        let _ = tokio::fs::remove_dir_all(&sandboxes_dir).await;
        tokio::fs::create_dir_all(&sandboxes_dir).await?;

        // Write bootstrap config (mode-aware). A running Envoy only parses its
        // bootstrap at process start, so if the transport/mode changed we must
        // restart it — otherwise it keeps using the stale (e.g. gRPC) transport
        // while we serve the new (e.g. filesystem) one, and no listeners land.
        let bootstrap_changed = self.write_bootstrap_config().await?;

        // Reset xDS state to an empty initial state.
        self.cds.replace_all(vec![]).await?;
        self.lds.replace_all(vec![]).await?;

        if bootstrap_changed {
            self.reload_envoy_after_bootstrap_change().await?;
        }
        info!(
            xds_mode = %self.config.xds_mode,
            bootstrap_changed,
            "EnvoyManager initialized (container={})",
            self.config.container_name
        );
        Ok(())
    }

    /// Initialize xDS state only (no bootstrap write, no filesystem ops).
    /// Used in K8s mode where the Envoy DaemonSet manages its own bootstrap
    /// and the orchestrator only needs to reset in-memory LDS state.
    pub async fn init_xds_only(&self) -> anyhow::Result<()> {
        self.cds.replace_all(vec![]).await?;
        self.lds.replace_all(vec![]).await?;
        info!(
            xds_mode = %self.config.xds_mode,
            "EnvoyManager xDS state reset (K8s mode, no bootstrap write)"
        );
        Ok(())
    }

    /// Rebuild the LDS state for all live sandboxes from the database.
    ///
    /// The listener set is never persisted — it lives only in the filesystem
    /// `lds.json` (wiped by [`init`]) or the in-memory Delta xDS state (lost on
    /// orchestrator restart). The database (`joysafeter_sandboxes`) is the source
    /// of truth for which sandboxes are live and what egress allowlist each has
    /// (stored in `config.fingerprint.networking`). This re-derives the two
    /// listeners per sandbox and pushes them all in a single [`LdsBackend::replace_all`],
    /// so a restarted orchestrator restores networking for still-running sandboxes
    /// instead of leaving them isolated.
    pub async fn recover_from_db(
        &self,
        pool: &sqlx::PgPool,
        llm_egress_allowed_hosts: &[String],
        authority: &crate::kernel::xds_authority::XdsAuthorityGuard,
    ) -> anyhow::Result<()> {
        if !authority.is_current() {
            anyhow::bail!("xDS authority changed before networking recovery started");
        }
        let sandboxes = crate::db::queries::list_live_sandboxes_for_recovery(pool).await?;

        let mut specs = Vec::with_capacity(sandboxes.len());
        let mut clusters = Vec::new();
        let mut generations = Vec::new();
        let mut recovered = 0usize;
        for sb in &sandboxes {
            // Only sandboxes provisioned with limited networking have Envoy
            // listeners. Those store their allowlist under
            // `config.fingerprint.networking`; sandboxes without it used no proxy.
            let networking = sb
                .config
                .as_ref()
                .and_then(|c| c.get("fingerprint"))
                .and_then(|f| f.get("networking"));
            let Some(networking) = networking else {
                continue;
            };
            if networking.get("type").and_then(|t| t.as_str()) != Some("limited") {
                continue;
            }

            let allowed_hosts = extract_allowed_hosts(Some(networking));

            // Recreate the socket dir; the Envoy container may have restarted and
            // lost /sockets contents. Envoy recreates the pipes once it accepts
            // the pushed listeners. Fail-closed: if we cannot prepare a live
            // sandbox's socket dir we abort recovery rather than leave it running
            // without egress enforcement.
            self.prepare_socket_dir(sb.id).await?;

            // Re-derive the sandbox's egress credentials from the DB and render
            // both its listener routes and its per-upstream clusters.
            let creds = crate::kernel::sandbox_resolver::rebuild_sandbox_credentials(
                pool,
                sb,
                llm_egress_allowed_hosts,
            )
            .await?;
            let policy = creds.to_policy(&sb.id, allowed_hosts);
            if let Err(e) = validate_egress_policy(&sb.id, &policy) {
                let _ = crate::db::queries::update_sandbox_networking_status(
                    pool,
                    sb.id,
                    "failed",
                    sb.networking_policy_hash.as_deref(),
                    None,
                    Some(&e.to_string()),
                )
                .await;
                return Err(e.context(format!(
                    "invalid recovered egress policy for sandbox {}",
                    sb.id
                )));
            }

            let policy_hash = sb
                .networking_policy_hash
                .clone()
                .or_else(|| {
                    sb.config
                        .as_ref()
                        .and_then(|c| c.get("fingerprint"))
                        .and_then(|f| f.get("egress_policy_hash"))
                        .and_then(|v| v.as_str())
                        .map(ToOwned::to_owned)
                })
                .unwrap_or_else(|| "recovered-unknown".to_string());
            let generation = crate::db::queries::reopen_network_policy_for_authority_recovery(
                pool,
                sb.id,
                &policy_hash,
            )
            .await?;

            clusters.extend(policy.clusters(&sb.id));
            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts,
                credentials: policy.credential_routes,
                proxy_auth_token: policy.proxy_auth_token,
            });
            generations.push((sb.id, generation));
            recovered += 1;
        }

        if !authority.is_current() {
            anyhow::bail!("xDS authority changed before recovered policy publication");
        }
        self.cds.replace_all(clusters).await?;
        self.lds.replace_all(specs).await?;
        for (sandbox_id, generation) in generations {
            self.lds
                .wait_for_sandbox_ack(
                    sandbox_id,
                    std::time::Duration::from_millis(
                        self.config.socket_ready_timeout_ms.max(1_000),
                    ),
                )
                .await
                .with_context(|| {
                    format!("recovered Envoy policy was not ACKed for sandbox {sandbox_id}")
                })?;
            if !authority.is_current() {
                anyhow::bail!("xDS authority changed before recovered policy ACK persistence");
            }
            match crate::db::queries::mark_sandbox_network_policy_acked(
                pool,
                sandbox_id,
                &generation,
            )
            .await?
            {
                crate::db::queries::NetworkPolicyAckOutcome::Applied
                | crate::db::queries::NetworkPolicyAckOutcome::AlreadyReady => {}
                crate::db::queries::NetworkPolicyAckOutcome::Stale => anyhow::bail!(
                    "sandbox {sandbox_id} network policy generation changed during recovery"
                ),
                crate::db::queries::NetworkPolicyAckOutcome::Missing => {
                    anyhow::bail!("sandbox {sandbox_id} disappeared during network policy recovery")
                }
            }
        }
        info!(
            recovered_sandboxes = recovered,
            total_live = sandboxes.len(),
            "EnvoyManager recovered LDS state from DB"
        );
        Ok(())
    }

    /// Add a sandbox to Envoy config (creates socket dir, pushes listeners).
    ///
    /// `policy` carries the non-sensitive allowlist plus real secrets to inject
    /// at the egress boundary. Credential routes are rendered into the HTTP
    /// listener and never enter the sandbox.
    pub async fn add_sandbox_policy(
        &self,
        sandbox_id: SandboxId,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.add_sandbox_with_policy(sandbox_id, policy).await
    }

    async fn add_sandbox_with_policy(
        &self,
        sandbox_id: SandboxId,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        validate_egress_policy(&sandbox_id, &policy)?;
        // Create socket directory inside container.
        self.prepare_socket_dir(sandbox_id).await?;
        let sandbox_uuid = sandbox_id.as_uuid();
        let socket_dir = format!("/sockets/{sandbox_uuid}");

        if self.config.write_debug_entries {
            // Write a per-sandbox entry file for debugging visibility only.
            // NOTE: never include secrets here — only the non-sensitive allowlist.
            let entry_json = json!({
                "sandbox_id": sandbox_uuid.to_string(),
                "allowed_hosts": policy.allowlist_hosts,
            });
            let entry_path = format!("/envoy-config/sandboxes/{sandbox_uuid}.json");
            self.write_config_file(&entry_path, &serde_json::to_string(&entry_json)?)
                .await?;
        }

        {
            let sandbox_lock = self.sandbox_apply_lock(sandbox_id).await;
            let _guard =
                tokio::time::timeout(std::time::Duration::from_secs(5), sandbox_lock.lock())
                    .await
                    .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox apply lock"))?;
            let listener = ListenerSpec {
                sandbox_id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts.clone(),
                credentials: policy.credential_routes.clone(),
                proxy_auth_token: policy.proxy_auth_token.clone(),
            };
            let clusters = policy.clusters(&sandbox_id);
            let cluster_prefix = format!("up_{}_", sandbox_id.as_uuid());

            let applied_as_batch = tokio::time::timeout(
                std::time::Duration::from_secs(10),
                self.lds.apply_sandbox_batch(
                    clusters.clone(),
                    vec![listener.clone()],
                    cluster_prefix.clone(),
                ),
            )
            .await
            .map_err(|_| anyhow::anyhow!("timed out applying Envoy xDS update"))??;
            if !applied_as_batch {
                if !clusters.is_empty() {
                    anyhow::bail!(
                        "filesystem xDS cannot safely publish listener {} with dedicated clusters; use JOYSAFETER_ENVOY_XDS_MODE=grpc",
                        listener.resource_name()
                    );
                }
                self.lds.upsert(vec![listener]).await?;
            }
            drop(_guard);
            self.cleanup_sandbox_apply_lock(sandbox_id, &sandbox_lock)
                .await;
        }

        self.lds
            .wait_for_sandbox_ack(
                sandbox_id,
                std::time::Duration::from_millis(self.config.socket_ready_timeout_ms.max(1_000)),
            )
            .await?;

        // xDS acceptance is not proof of egress: the runner cannot reach the
        // network until Envoy has actually bound the per-sandbox Unix socket on
        // the shared mount. Verify it, and fail loudly (so the sandbox is torn
        // down) instead of reporting the networking as ready while it is offline.
        self.wait_for_socket_ready(sandbox_id).await?;

        info!(
            sandbox_id = %sandbox_id,
            socket_dir = %socket_dir,
            "Added sandbox to Envoy config; egress socket confirmed ready"
        );
        Ok(())
    }

    /// Remove a sandbox from Envoy config.
    async fn remove_sandbox_unlocked(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let sandbox_uuid = sandbox_id.as_uuid();
        self.cds
            .remove_by_prefix(&format!("up_{sandbox_uuid}_"))
            .await?;
        self.lds
            .remove(vec![format!("{sandbox_uuid}_http")])
            .await?;

        // Release retained per-sandbox ACK/NACK bookkeeping (grpc xDS backend)
        // so apply_status cannot grow unboundedly over the orchestrator's life.
        self.lds.forget_sandbox(sandbox_id).await;

        if let Some(socket_dir) = self.host_socket_dir(sandbox_id) {
            let _ = tokio::fs::remove_dir_all(socket_dir).await;
        }

        if self.config.write_debug_entries {
            let entry = PathBuf::from(&self.config.config_dir)
                .join("sandboxes")
                .join(format!("{sandbox_uuid}.json"));
            let _ = tokio::fs::remove_file(entry).await;
        }

        debug!(sandbox_id = %sandbox_id, "Removed sandbox from Envoy config");
        Ok(())
    }

    pub async fn remove_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let sandbox_lock = self.sandbox_apply_lock(sandbox_id).await;
        let _guard = tokio::time::timeout(std::time::Duration::from_secs(5), sandbox_lock.lock())
            .await
            .map_err(|_| anyhow::anyhow!("timed out acquiring Envoy sandbox apply lock"))?;
        let result = self.remove_sandbox_unlocked(sandbox_id).await;
        drop(_guard);
        self.cleanup_sandbox_apply_lock(sandbox_id, &sandbox_lock)
            .await;
        result
    }

    /// Remove provider-local xDS resources that no longer have a live
    /// PostgreSQL sandbox. This is intentionally a prune-only operation: live
    /// listeners are not re-published and their ready generations are not
    /// disturbed.
    pub async fn prune_networking_except(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<usize> {
        let configured = self.lds.configured_sandbox_ids().await;
        let mut stale: Vec<_> = configured.difference(live_sandbox_ids).copied().collect();
        stale.sort_by_key(|sandbox_id| sandbox_id.as_uuid());

        for sandbox_id in &stale {
            self.remove_sandbox(*sandbox_id).await?;
        }

        Ok(stale.len())
    }

    /// Write Envoy bootstrap config as JSON, matching the active xDS mode.
    ///
    /// * filesystem: `dynamic_resources.lds_config.path_config_source`.
    /// * grpc: `lds_config.ads` + `ads_config { DELTA_GRPC }` + a static
    ///   `xds_cluster` pointing at the orchestrator gRPC server.
    ///
    /// Returns `true` when the on-disk bootstrap content actually changed, so the
    /// caller can decide whether the running Envoy needs a restart to pick it up.
    async fn write_bootstrap_config(&self) -> anyhow::Result<bool> {
        let mut clusters = vec![
            json!({
                "name": "dynamic_forward_proxy",
                "connect_timeout": "10s",
                "lb_policy": "CLUSTER_PROVIDED",
                "cluster_type": {
                    "name": "envoy.clusters.dynamic_forward_proxy",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig",
                        "dns_cache_config": {
                            "name": "dynamic_forward_proxy_cache",
                            "dns_lookup_family": "V4_ONLY"
                        }
                    }
                }
            }),
            json!({
                "name": "dynamic_forward_proxy_tls",
                "connect_timeout": "10s",
                "lb_policy": "CLUSTER_PROVIDED",
                "cluster_type": {
                    "name": "envoy.clusters.dynamic_forward_proxy",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig",
                        "dns_cache_config": {
                            "name": "dynamic_forward_proxy_cache",
                            "dns_lookup_family": "V4_ONLY"
                        }
                    }
                },
                "transport_socket": {
                    "name": "envoy.transport_sockets.tls",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                        "common_tls_context": {
                            "validation_context": {
                                "trusted_ca": { "filename": "/etc/ssl/certs/ca-certificates.crt" }
                            }
                        }
                    }
                }
            }),
        ];

        // Dynamic resources differ by mode.
        let dynamic_resources = if self.config.is_grpc_mode() {
            // Add a static cluster for the xDS control plane (H2 gRPC to the
            // orchestrator). Runner control-plane gRPC does not traverse Envoy.
            clusters.push(json!({
                "name": "xds_cluster",
                "connect_timeout": "5s",
                "type": "STRICT_DNS",
                "lb_policy": "ROUND_ROBIN",
                "typed_extension_protocol_options": {
                    "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                        "@type": "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
                        "explicit_http_config": {
                            "http2_protocol_options": {}
                        }
                    }
                },
                "load_assignment": {
                    "cluster_name": "xds_cluster",
                    "endpoints": [{
                        "lb_endpoints": [{
                            "endpoint": {
                                "address": {
                                    "socket_address": {
                                        "address": self.config.grpc_target_host,
                                        "port_value": self.config.grpc_target_port
                                    }
                                }
                            }
                        }]
                    }]
                }
            }));

            json!({
                "cds_config": { "ads": {} },
                "lds_config": { "ads": {} },
                "ads_config": {
                    "api_type": "DELTA_GRPC",
                    "transport_api_version": "V3",
                    "grpc_services": [{
                        "envoy_grpc": { "cluster_name": "xds_cluster" }
                    }]
                }
            })
        } else {
            json!({
                "lds_config": {
                    "path_config_source": {
                        "path": "/envoy-config/lds.json",
                        "watched_directory": {
                            "path": "/envoy-config"
                        }
                    }
                },
                "cds_config": {
                    "path_config_source": {
                        "path": "/envoy-config/cds.json",
                        "watched_directory": {
                            "path": "/envoy-config"
                        }
                    }
                }
            })
        };

        let bootstrap = json!({
            "node": {
                "cluster": "joysafeter-proxy",
                "id": self.config.node_id
            },
            "dynamic_resources": dynamic_resources,
            "static_resources": {
                "clusters": clusters
            },
            "admin": {
                "address": {
                    "socket_address": {
                        "address": "127.0.0.1",
                        "port_value": 9901
                    }
                }
            }
        });

        let bootstrap_json = serde_json::to_string_pretty(&bootstrap)?;
        let path = PathBuf::from(&self.config.config_dir).join("bootstrap.json");
        let previous = tokio::fs::read_to_string(&path).await.ok();
        let changed = previous.as_deref() != Some(bootstrap_json.as_str());
        self.write_config_file("/envoy-config/bootstrap.json", &bootstrap_json)
            .await?;
        info!(xds_mode = %self.config.xds_mode, changed, "Wrote Envoy bootstrap config (JSON)");
        Ok(changed)
    }

    // ── Envoy container helpers ──────────────────────────────────────────

    async fn write_config_file(&self, container_path: &str, content: &str) -> anyhow::Result<()> {
        let relative = container_path
            .strip_prefix("/envoy-config/")
            .unwrap_or(container_path.trim_start_matches('/'));
        let path = PathBuf::from(&self.config.config_dir).join(relative);
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let tmp = path.with_extension("tmp");
        tokio::fs::write(&tmp, content).await?;
        tokio::fs::rename(&tmp, &path).await?;
        Ok(())
    }

    /// Setup networking for a sandbox, injecting the given credentials at the
    /// egress boundary.
    pub async fn setup_for_sandbox(
        &self,
        sandbox_id: SandboxId,
        networking_config: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        let allowed_hosts = extract_allowed_hosts(networking_config);
        self.add_sandbox_policy(
            sandbox_id,
            credentials.to_policy(&sandbox_id, allowed_hosts),
        )
        .await
    }

    /// Teardown networking for a sandbox.
    pub async fn teardown_for_sandbox(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.remove_sandbox(sandbox_id).await
    }
}

/// Extract the egress allowlist (`allowed_hosts`) from a networking config value.
fn extract_allowed_hosts(networking_config: Option<&serde_json::Value>) -> Vec<String> {
    networking_config
        .and_then(|c| c.get("allowed_hosts"))
        .and_then(|d| d.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::*;
    use crate::sandbox::lds_backend::{DeltaXdsServer, GrpcCds, GrpcLds};
    use uuid::Uuid;

    fn test_config() -> EnvoyConfig {
        EnvoyConfig {
            envoy_image: "unused".to_string(),
            socket_volume: "unused".to_string(),
            socket_host_dir: None,
            config_dir: "/tmp/joysafeter-envoy-test".to_string(),
            envoy_network: "unused".to_string(),
            grpc_target_host: "127.0.0.1".to_string(),
            grpc_target_port: 9090,
            container_name: "unused".to_string(),
            xds_mode: "grpc".to_string(),
            write_debug_entries: false,
            socket_ready_timeout_ms: 1_000,
            health_check_interval_sec: 0,
            health_failure_threshold: 1,
            skip_socket_dir_prep: true,
            node_id: "test-node".to_string(),
        }
    }

    fn listener(sandbox_id: SandboxId) -> ListenerSpec {
        ListenerSpec {
            sandbox_id,
            kind: ListenerKind::Http,
            allowed_hosts: vec![],
            credentials: vec![],
            proxy_auth_token: None,
        }
    }

    #[tokio::test]
    async fn authoritative_prune_removes_only_stale_sandbox_networking() {
        let server = DeltaXdsServer::new();
        let lds = Arc::new(GrpcLds::new(server.clone()));
        let manager = EnvoyManager::new(
            None,
            test_config(),
            lds.clone(),
            Arc::new(GrpcCds::new(server)),
        );
        let live = SandboxId::from_uuid(Uuid::from_u128(10));
        let stale = SandboxId::from_uuid(Uuid::from_u128(11));
        lds.upsert(vec![listener(live), listener(stale)])
            .await
            .expect("seed listeners");

        let removed = manager
            .prune_networking_except(&HashSet::from([live]))
            .await
            .expect("prune stale networking");

        assert_eq!(removed, 1);
        assert_eq!(lds.configured_sandbox_ids().await, HashSet::from([live]));
    }

    fn manager_without_docker() -> EnvoyManager {
        let server = DeltaXdsServer::new();
        EnvoyManager::new(
            None,
            test_config(),
            Arc::new(GrpcLds::new(server.clone())),
            Arc::new(GrpcCds::new(server)),
        )
    }

    #[tokio::test]
    async fn poll_until_ready_returns_true_once_predicate_holds() {
        let mut calls = 0u32;
        let ready = poll_until_ready(
            || {
                calls += 1;
                let hit = calls >= 3;
                async move { hit }
            },
            std::time::Duration::from_millis(500),
            std::time::Duration::from_millis(5),
        )
        .await;
        assert!(ready);
        assert!(calls >= 3, "predicate should be polled until it holds");
    }

    #[tokio::test]
    async fn poll_until_ready_times_out_when_never_ready() {
        let ready = poll_until_ready(
            || async { false },
            std::time::Duration::from_millis(30),
            std::time::Duration::from_millis(5),
        )
        .await;
        assert!(!ready);
    }

    /// Regression: the orchestrator must fail loudly when Envoy never
    /// materializes a sandbox's egress socket, instead of reporting the
    /// networking as ready (which left the sandbox silently offline).
    #[tokio::test]
    async fn socket_readiness_errors_when_socket_never_appears() {
        let manager = manager_without_docker();
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(7));
        let err = manager
            .wait_for_socket_ready_with(sandbox, || async { false })
            .await
            .expect_err("missing egress socket must fail loudly");
        let msg = err.to_string();
        assert!(msg.contains("egress socket"), "unexpected error: {msg}");
        assert!(
            msg.contains(&sandbox.as_uuid().to_string()),
            "error must name the sandbox: {msg}"
        );
    }

    #[tokio::test]
    async fn socket_readiness_succeeds_when_socket_present() {
        let manager = manager_without_docker();
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(8));
        manager
            .wait_for_socket_ready_with(sandbox, || async { true })
            .await
            .expect("an existing socket must be accepted");
    }

    #[test]
    fn socket_storage_description_reports_volume_or_host_dir() {
        assert_eq!(
            socket_storage_description(None, "joysafeter-sockets"),
            "docker volume joysafeter-sockets"
        );
        assert_eq!(
            socket_storage_description(Some("/tmp/joysafeter-sockets"), "joysafeter-sockets"),
            "host bind dir /tmp/joysafeter-sockets"
        );
    }

    #[test]
    fn socket_storage_mismatch_error_names_storage_and_remediation() {
        let msg = socket_storage_mismatch_error("docker volume joysafeter-sockets");
        assert!(
            msg.contains("docker volume joysafeter-sockets"),
            "names storage: {msg}"
        );
        assert!(msg.contains("/sockets"), "names mount point: {msg}");
        assert!(msg.to_lowercase().contains("envoy"), "names Envoy: {msg}");
    }

    #[tokio::test]
    async fn write_bootstrap_reports_change_only_when_content_differs() {
        let server = DeltaXdsServer::new();
        let mut cfg = test_config();
        let dir =
            std::env::temp_dir().join(format!("joysafeter-bootstrap-test-{}", std::process::id()));
        let _ = tokio::fs::remove_dir_all(&dir).await;
        cfg.config_dir = dir.to_string_lossy().into_owned();
        let manager = EnvoyManager::new(
            None,
            cfg,
            Arc::new(GrpcLds::new(server.clone())),
            Arc::new(GrpcCds::new(server)),
        );
        assert!(
            manager.write_bootstrap_config().await.unwrap(),
            "first write must report a change (file created)"
        );
        assert!(
            !manager.write_bootstrap_config().await.unwrap(),
            "identical rewrite must report no change"
        );
        let _ = tokio::fs::remove_dir_all(&dir).await;
    }
}
