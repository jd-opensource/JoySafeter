use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use bollard::container::{
    Config, CreateContainerOptions, RemoveContainerOptions, RestartContainerOptions,
    StartContainerOptions, WaitContainerOptions,
};
use bollard::models::{HostConfig, Mount, MountTypeEnum};
use bollard::Docker;
use futures::TryStreamExt;
use serde_json::json;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};
use uuid::Uuid;

use super::lds_backend::{
    validate_egress_policy, LdsBackend, ListenerKind, ListenerSpec, SandboxCredentials,
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
    docker: Arc<Docker>,
    config: EnvoyConfig,
    lds: Arc<dyn LdsBackend>,
    sandbox_apply_locks: Mutex<HashMap<Uuid, Arc<Mutex<()>>>>,
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
    /// `"filesystem"` (default, `lds.json`) or `"grpc"` (Delta xDS).
    pub xds_mode: String,
    pub write_debug_entries: bool,
    pub socket_ready_timeout_ms: u64,
    pub health_check_interval_sec: u64,
    pub health_failure_threshold: u64,
    /// When true, skip `prepare_socket_dir` (socket dir creation is handled
    /// externally — e.g. by a K8s initContainer on the sandbox pod). This
    /// avoids the orchestrator trying to mkdir on a remote node's filesystem.
    pub skip_socket_dir_prep: bool,
}

impl EnvoyConfig {
    fn is_grpc_mode(&self) -> bool {
        self.xds_mode == "grpc"
    }
}

impl EnvoyManager {
    pub fn new(docker: Arc<Docker>, config: EnvoyConfig, lds: Arc<dyn LdsBackend>) -> Self {
        Self {
            docker,
            config,
            lds,
            sandbox_apply_locks: Mutex::new(HashMap::new()),
        }
    }

    async fn sandbox_apply_lock(&self, sandbox_id: Uuid) -> Arc<Mutex<()>> {
        let mut locks = self.sandbox_apply_locks.lock().await;
        locks
            .entry(sandbox_id)
            .or_insert_with(|| Arc::new(Mutex::new(())))
            .clone()
    }

    async fn cleanup_sandbox_apply_lock(&self, sandbox_id: Uuid, lock: &Arc<Mutex<()>>) {
        let mut locks = self.sandbox_apply_locks.lock().await;
        if locks
            .get(&sandbox_id)
            .is_some_and(|current| Arc::ptr_eq(current, lock))
            && Arc::strong_count(lock) <= 2
        {
            locks.remove(&sandbox_id);
        }
    }

    /// Ensure the per-sandbox socket directory exists before either Envoy creates
    /// Ensure the per-sandbox socket directory exists before Envoy binds its
    /// listener pipes there and before the sandbox mounts it.
    ///
    /// In host-bind mode, create the per-sandbox directory on the host before
    /// Envoy binds its listener pipe there. In Docker-volume mode there is no
    /// host path to prepare; Docker creates the volume directory inside the Linux
    /// VM and Envoy creates the final socket path when it applies LDS.
    pub async fn prepare_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        if self.config.skip_socket_dir_prep {
            return Ok(()); // K8s: handled by pod initContainer
        }
        let Some(socket_dir) = self.host_socket_dir(sandbox_id) else {
            self.prepare_socket_dir_in_volume(sandbox_id).await?;
            return Ok(());
        };
        tokio::fs::create_dir_all(&socket_dir).await?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            tokio::fs::set_permissions(&socket_dir, std::fs::Permissions::from_mode(0o755)).await?;
        }
        Ok(())
    }

    async fn prepare_socket_dir_in_volume(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let helper_name = format!("joysafeter-envoy-socket-init-{sandbox_id}");
        let _ = self
            .docker
            .remove_container(
                &helper_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;

        let mkdir_cmd =
            format!("mkdir -p /sockets/{sandbox_id} && chmod 755 /sockets/{sandbox_id}");
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
        self.docker
            .create_container(
                Some(CreateContainerOptions {
                    name: helper_name.as_str(),
                    platform: None,
                }),
                container_config,
            )
            .await?;
        self.docker
            .start_container(&helper_name, None::<StartContainerOptions<String>>)
            .await?;
        let wait = self
            .docker
            .wait_container(&helper_name, None::<WaitContainerOptions<String>>)
            .try_collect::<Vec<_>>()
            .await?;
        let status_code = wait.first().map(|result| result.status_code).unwrap_or(1);
        let _ = self
            .docker
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
                "failed to prepare Envoy socket volume directory for sandbox {sandbox_id}: helper exited {status_code}"
            );
        }
        debug!(sandbox_id = %sandbox_id, socket_volume = %self.config.socket_volume, "Prepared Envoy socket dir in Docker volume");
        Ok(())
    }

    /// Socket file permissions are set by Envoy at bind time via the listener
    /// pipe `mode` (0666 in both the JSON and protobuf renderers), so the sandbox
    /// (uid 1000) can connect without any post-hoc chmod. We still defensively
    /// re-apply 0666 on the host in case a restrictive umask altered the created
    /// socket file. No `docker exec`.
    async fn secure_socket_files(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        if let Some(socket_dir) = self.host_socket_dir(sandbox_id) {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                for name in ["http.sock"] {
                    let path = socket_dir.join(name);
                    if tokio::fs::metadata(&path).await.is_ok() {
                        tokio::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))
                            .await?;
                    }
                }
            }
        }
        Ok(())
    }

    fn host_socket_dir(&self, sandbox_id: Uuid) -> Option<PathBuf> {
        self.config
            .socket_host_dir
            .as_ref()
            .map(|root| PathBuf::from(root).join(sandbox_id.to_string()))
    }

    pub fn spawn_health_monitor(
        self: Arc<Self>,
        pool: sqlx::PgPool,
        llm_egress_allowed_hosts: Vec<String>,
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
                                .restart_and_recover(&pool, &llm_egress_allowed_hosts)
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
            .docker
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
    ) -> anyhow::Result<()> {
        warn!("Restarting Envoy container after failed health checks");
        self.docker
            .restart_container(
                &self.config.container_name,
                Some(RestartContainerOptions { t: 10 }),
            )
            .await?;
        self.wait_until_ready(std::time::Duration::from_secs(15))
            .await?;
        self.init().await?;
        self.recover_from_db(pool, llm_egress_allowed_hosts).await
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

        // Write bootstrap config (mode-aware)
        self.write_bootstrap_config().await?;

        // Reset LDS to empty initial state.
        self.lds.replace_all(vec![]).await?;
        info!(
            xds_mode = %self.config.xds_mode,
            "EnvoyManager initialized (container={})",
            self.config.container_name
        );
        Ok(())
    }

    /// Initialize xDS state only (no bootstrap write, no filesystem ops).
    /// Used in K8s mode where the Envoy DaemonSet manages its own bootstrap
    /// and the orchestrator only needs to reset in-memory LDS state.
    pub async fn init_xds_only(&self) -> anyhow::Result<()> {
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
    ) -> anyhow::Result<()> {
        let sandboxes = crate::db::queries::list_live_sandboxes_for_recovery(pool).await?;

        let mut specs = Vec::with_capacity(sandboxes.len() * 2);
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
            // the pushed listeners.
            let _ = self.prepare_socket_dir(sb.id).await;

            // Re-derive the sandbox's egress credentials from the DB and render
            // both its listener routes and its per-upstream clusters.
            let creds = crate::kernel::sandbox_resolver::rebuild_sandbox_credentials(
                pool,
                sb,
                llm_egress_allowed_hosts,
            )
            .await;
            let policy = creds.to_policy(&sb.id, allowed_hosts);
            if let Err(e) = validate_egress_policy(&sb.id, &policy) {
                warn!(sandbox_id = %sb.id, error = %e, "Skipping invalid recovered egress policy");
                let _ = crate::db::queries::update_sandbox_networking_status(
                    pool,
                    sb.id,
                    "failed",
                    sb.networking_policy_hash.as_deref(),
                    None,
                    Some(&e.to_string()),
                )
                .await;
                continue;
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
            let _ =
                crate::db::queries::prepare_sandbox_network_policy_push(pool, sb.id, &policy_hash)
                    .await;

            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts,
                credentials: policy.credential_routes,
                proxy_auth_token: policy.proxy_auth_token,
            });
            recovered += 1;
        }

        // Only LDS needed — clusters are shared via bootstrap.
        self.lds.replace_all(specs).await?;
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
        sandbox_id: Uuid,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.add_sandbox_with_policy(sandbox_id, policy).await
    }

    async fn add_sandbox_with_policy(
        &self,
        sandbox_id: Uuid,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        validate_egress_policy(&sandbox_id, &policy)?;
        // Create socket directory inside container.
        self.prepare_socket_dir(sandbox_id).await?;
        let socket_dir = format!("/sockets/{sandbox_id}");

        if self.config.write_debug_entries {
            // Write a per-sandbox entry file for debugging visibility only.
            // NOTE: never include secrets here — only the non-sensitive allowlist.
            let entry_json = json!({
                "sandbox_id": sandbox_id.to_string(),
                "allowed_hosts": policy.allowlist_hosts,
            });
            let entry_path = format!("/envoy-config/sandboxes/{sandbox_id}.json");
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

            // Only push the per-sandbox LDS listener. No CDS needed: all
            // credential-injection routes point to the global shared
            // dynamic_forward_proxy / dynamic_forward_proxy_tls clusters
            // (pre-created in bootstrap, always healthy, zero warming).
            tokio::time::timeout(
                std::time::Duration::from_secs(10),
                self.lds.upsert(vec![listener]),
            )
            .await
            .map_err(|_| anyhow::anyhow!("timed out applying Envoy LDS update"))??;
            drop(_guard);
            self.cleanup_sandbox_apply_lock(sandbox_id, &sandbox_lock)
                .await;
        }

        // Runner control traffic no longer depends on Envoy: runner gRPC uses
        // the orchestrator-owned control Unix socket directly. Envoy is only the
        // sandbox egress gateway, and the runner's local HTTP proxy bridge
        // already waits/retries for the egress socket in the background. Do not
        // block sandbox start on Envoy listener ACK/socket materialisation here:
        // in filesystem mode especially, Envoy may need a short reload window,
        // and blocking here strands the container in Created state even though
        // the control plane is ready.
        let lds = self.lds.clone();
        let config = self.config.clone();
        tokio::spawn(async move {
            let ack_timeout = if config.is_grpc_mode() {
                std::time::Duration::from_millis(500)
            } else {
                std::time::Duration::from_secs(2)
            };
            if let Err(e) = lds.wait_for_sandbox_ack(sandbox_id, ack_timeout).await {
                let message = e.to_string();
                if message.contains("NACK") {
                    warn!(sandbox_id = %sandbox_id, error = %message, "Envoy rejected sandbox listener config");
                } else {
                    debug!(sandbox_id = %sandbox_id, error = %message, "Envoy ACK was not observed after config push");
                }
            }
        });

        info!(
            sandbox_id = %sandbox_id,
            socket_dir = %socket_dir,
            "Added sandbox to Envoy config; egress socket readiness will be reconciled asynchronously"
        );
        Ok(())
    }

    async fn wait_for_socket_readiness(
        &self,
        sandbox_id: Uuid,
        _socket_dir: &str,
    ) -> anyhow::Result<bool> {
        let timeout =
            std::time::Duration::from_millis(self.config.socket_ready_timeout_ms.max(1_000));
        let deadline = std::time::Instant::now() + timeout;
        let mut attempt = 0u32;
        loop {
            attempt += 1;
            // Host bind-mount mode: stat the sockets directly on the host FS.
            let ready = match self.host_socket_dir(sandbox_id) {
                Some(dir) => tokio::fs::metadata(dir.join("http.sock")).await.is_ok(),
                None => {
                    anyhow::bail!(
                        "JOYSAFETER_ENVOY_SOCKET_HOST_DIR is required for Envoy socket readiness checks"
                    )
                }
            };
            if ready {
                info!(sandbox_id = %sandbox_id, attempt, "Envoy sockets are ready");
                return Ok(true);
            }
            if std::time::Instant::now() >= deadline {
                break;
            }
            debug!(sandbox_id = %sandbox_id, attempt, "Envoy sockets not ready yet");
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }
        Ok(false)
    }

    async fn socket_dir_state(&self, sandbox_id: Uuid) -> String {
        let Some(host_socket_dir) = self.host_socket_dir(sandbox_id) else {
            return "JOYSAFETER_ENVOY_SOCKET_HOST_DIR is not configured".to_string();
        };
        match tokio::fs::read_dir(&host_socket_dir).await {
            Ok(mut entries) => {
                let mut names = Vec::new();
                while let Ok(Some(entry)) = entries.next_entry().await {
                    names.push(entry.file_name().to_string_lossy().into_owned());
                }
                names.sort();
                format!("host dir {} entries={names:?}", host_socket_dir.display())
            }
            Err(e) => {
                format!(
                    "failed to inspect host dir {}: {e}",
                    host_socket_dir.display()
                )
            }
        }
    }

    /// Remove a sandbox from Envoy config.
    async fn remove_sandbox_unlocked(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        // Drop the current HTTP egress listener plus the historical gRPC listener
        // name so rolling upgrades clean up any Envoy-proxied runner control
        // resources left by older versions. No per-sandbox clusters to remove —
        // all routes point to the shared dynamic_forward_proxy clusters.
        self.lds
            .remove(vec![
                format!("{sandbox_id}_grpc"),
                format!("{sandbox_id}_http"),
            ])
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
                .join(format!("{sandbox_id}.json"));
            let _ = tokio::fs::remove_file(entry).await;
        }

        debug!(sandbox_id = %sandbox_id, "Removed sandbox from Envoy config");
        Ok(())
    }

    pub async fn remove_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
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

    /// Write Envoy bootstrap config as JSON, matching the active xDS mode.
    ///
    /// * filesystem: `dynamic_resources.lds_config.path_config_source`.
    /// * grpc: `lds_config.ads` + `ads_config { DELTA_GRPC }` + a static
    ///   `xds_cluster` pointing at the orchestrator gRPC server.
    async fn write_bootstrap_config(&self) -> anyhow::Result<()> {
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
                "id": "joysafeter-envoy"
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
        self.write_config_file("/envoy-config/bootstrap.json", &bootstrap_json)
            .await?;
        info!(xds_mode = %self.config.xds_mode, "Wrote Envoy bootstrap config (JSON)");
        Ok(())
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
        sandbox_id: Uuid,
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
    pub async fn teardown_for_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
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
