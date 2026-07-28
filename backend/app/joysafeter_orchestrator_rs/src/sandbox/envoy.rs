use std::sync::Arc;

use bollard::container::RestartContainerOptions;
use bollard::Docker;
use serde_json::json;
use tracing::{debug, info, warn};
use uuid::Uuid;

use super::lds_backend::{
    exec_in_envoy, validate_egress_policy, write_file_in_envoy, CdsBackend, LdsBackend,
    ListenerKind, ListenerSpec, SandboxCredentials, SandboxEgressPolicy,
};

/// Per-sandbox network isolation via a shared Envoy proxy sidecar container.
///
/// Listener config is delivered through a pluggable [`LdsBackend`] and per-upstream
/// clusters through a [`CdsBackend`] — either the filesystem path
/// (`lds.json`/`cds.json`) or Delta gRPC xDS — selected by
/// [`EnvoyConfig::xds_mode`]. The bootstrap written here is generated to match
/// the active mode. Everything else (socket dirs, the wait-for-sockets loop, the
/// data plane) is identical across modes. The authoritative config lives in the
/// backends; a per-sandbox JSON file is still written under
/// `/envoy-config/sandboxes/` purely for crash-recovery/debugging visibility.
pub struct EnvoyManager {
    docker: Arc<Docker>,
    config: EnvoyConfig,
    lds: Arc<dyn LdsBackend>,
    cds: Arc<dyn CdsBackend>,
}

#[derive(Debug, Clone)]
pub struct EnvoyConfig {
    pub envoy_image: String,
    pub socket_volume: String,
    pub config_dir: String,
    pub envoy_network: String,
    pub grpc_target_host: String,
    pub grpc_target_port: u16,
    pub container_name: String,
    /// `"filesystem"` (default, `lds.json`) or `"grpc"` (Delta xDS).
    pub xds_mode: String,
    pub write_debug_entries: bool,
    pub socket_owner: String,
    pub health_check_interval_sec: u64,
    pub health_failure_threshold: u64,
}

impl EnvoyConfig {
    fn is_grpc_mode(&self) -> bool {
        self.xds_mode == "grpc"
    }
}

impl EnvoyManager {
    pub fn new(
        docker: Arc<Docker>,
        config: EnvoyConfig,
        lds: Arc<dyn LdsBackend>,
        cds: Arc<dyn CdsBackend>,
    ) -> Self {
        Self {
            docker,
            config,
            lds,
            cds,
        }
    }

    /// Ensure the per-sandbox socket directory exists before either Envoy creates
    /// sockets in it or Docker mounts it as a volume subpath into the sandbox.
    pub async fn prepare_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let socket_dir = format!("/sockets/{sandbox_id}");
        self.exec_in_envoy(&format!(
            "mkdir -p {socket_dir} && chown {} {socket_dir} && chmod 700 {socket_dir}",
            shell_escape(&self.config.socket_owner)
        ))
            .await?;
        Ok(())
    }

    async fn secure_socket_files(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let socket_dir = format!("/sockets/{sandbox_id}");
        self.exec_in_envoy(&format!(
            "chown {} {socket_dir}/grpc.sock {socket_dir}/http.sock && chmod 600 {socket_dir}/grpc.sock {socket_dir}/http.sock",
            shell_escape(&self.config.socket_owner)
        ))
        .await?;
        Ok(())
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
                            if let Err(recover_err) = self.restart_and_recover(&pool, &llm_egress_allowed_hosts).await {
                                warn!(error = %recover_err, "Envoy restart/recovery failed");
                            }
                        }
                    }
                }
            }
        });
    }

    async fn health_check(&self) -> anyhow::Result<()> {
        let output = self
            .exec_in_envoy("wget -q -T 2 -O - http://127.0.0.1:9901/ready 2>/dev/null || true")
            .await?;
        if output.contains("LIVE") || output.contains("ready") {
            Ok(())
        } else {
            anyhow::bail!("Envoy admin /ready did not report ready: {output}")
        }
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
        self.wait_until_ready(std::time::Duration::from_secs(15)).await?;
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
        // Clean stale sandbox entries inside envoy container
        let _ = self
            .exec_in_envoy("rm -rf /envoy-config/sandboxes && mkdir -p /envoy-config/sandboxes")
            .await;

        // Write bootstrap config (mode-aware)
        self.write_bootstrap_config().await?;

        // Reset LDS + CDS to empty initial state.
        self.lds.replace_all(vec![]).await?;
        self.cds.replace_all(vec![]).await?;

        info!(
            xds_mode = %self.config.xds_mode,
            "EnvoyManager initialized (container={})",
            self.config.container_name
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
        let mut clusters = Vec::new();
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
            clusters.extend(policy.clusters(&sb.id));

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
            let _ = crate::db::queries::prepare_sandbox_network_policy_push(
                pool,
                sb.id,
                &policy_hash,
            )
            .await;

            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Grpc,
                allowed_hosts: vec![],
                credentials: vec![],
                proxy_auth_token: None,
            });
            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts,
                credentials: policy.credential_routes,
                proxy_auth_token: policy.proxy_auth_token,
            });
            recovered += 1;
        }

        // Clusters before listeners (make-before-break).
        self.cds.replace_all(clusters).await?;
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

    /// Backward-compatible entry point for legacy credential builders.
    pub async fn add_sandbox(
        &self,
        sandbox_id: Uuid,
        allowed_hosts: Vec<String>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.add_sandbox_with_policy(
            sandbox_id,
            credentials.to_policy(&sandbox_id, allowed_hosts),
        )
        .await
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
            self.write_file_in_envoy(&entry_path, &serde_json::to_string(&entry_json)?)
                .await?;
        }

        let cred_clusters = policy.clusters(&sandbox_id);
        let cluster_prefix = format!("up_{sandbox_id}_");

        // Push this sandbox's full cluster set BEFORE listeners
        // (make-before-break): a listener whose routes reference a not-yet-known
        // cluster would fail to warm. Replacing by prefix also removes clusters
        // for credentials that were deleted since the last policy refresh.
        self.cds
            .replace_by_prefix(&cluster_prefix, cred_clusters)
            .await?;

        // Push the two listeners for this sandbox through the active backend.
        self.lds
            .upsert(vec![
                ListenerSpec {
                    sandbox_id,
                    kind: ListenerKind::Grpc,
                    allowed_hosts: vec![],
                    credentials: vec![],
                    proxy_auth_token: None,
                },
                ListenerSpec {
                    sandbox_id,
                    kind: ListenerKind::Http,
                    allowed_hosts: policy.allowlist_hosts.clone(),
                    credentials: policy.credential_routes.clone(),
                    proxy_auth_token: policy.proxy_auth_token.clone(),
                },
            ])
            .await?;

        self.lds
            .wait_for_sandbox_ack(sandbox_id, std::time::Duration::from_secs(10))
            .await?;

        // Wait for sockets to appear (up to 10s). Envoy only starts listening
        // after it accepts the updated LDS config; a missing socket means the
        // sandbox would be isolated from the orchestrator.
        for _ in 0..20 {
            let check = self
                .exec_in_envoy(&format!(
                    "test -S {socket_dir}/grpc.sock && test -S {socket_dir}/http.sock && echo ok"
                ))
                .await;
            if let Ok(output) = check {
                if output.contains("ok") {
                    self.secure_socket_files(sandbox_id).await?;
                    info!(sandbox_id = %sandbox_id, "Added sandbox to Envoy config");
                    return Ok(());
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }

        let socket_state = self
            .exec_in_envoy(&format!("ls -la {socket_dir} 2>&1 || true"))
            .await
            .unwrap_or_else(|e| format!("failed to inspect socket dir: {e}"));
        // M7 fix: Clean up the listener and cluster resources we already pushed
        // to Envoy. Without this, a timeout leaves stale config pointing at
        // sockets that never materialized.
        warn!(
            sandbox_id = %sandbox_id,
            "Envoy socket timeout, cleaning up pushed listener/cluster config"
        );
        let _ = self.remove_sandbox(sandbox_id).await;
        anyhow::bail!(
            "timed out waiting for Envoy sockets for sandbox {sandbox_id}; socket dir state: {socket_state}"
        )
    }

    /// Remove a sandbox from Envoy config.
    pub async fn remove_sandbox(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        // Drop the two listeners first, then the sandbox's per-upstream clusters
        // (break-before-make: no listener references the clusters once removed).
        self.lds
            .remove(vec![
                format!("{sandbox_id}_grpc"),
                format!("{sandbox_id}_http"),
            ])
            .await?;
        let _ = self
            .cds
            .remove_by_prefix(&format!("up_{sandbox_id}_"))
            .await;

        // Remove socket dir
        let _ = self
            .exec_in_envoy(&format!("rm -rf /sockets/{sandbox_id}"))
            .await;

        if self.config.write_debug_entries {
            let _ = self
                .exec_in_envoy(&format!("rm -f /envoy-config/sandboxes/{sandbox_id}.json"))
                .await;
        }

        debug!(sandbox_id = %sandbox_id, "Removed sandbox from Envoy config");
        Ok(())
    }

    /// Write Envoy bootstrap config as JSON, matching the active xDS mode.
    ///
    /// * filesystem: `dynamic_resources.lds_config.path_config_source`.
    /// * grpc: `lds_config.ads` + `ads_config { DELTA_GRPC }` + a static
    ///   `xds_cluster` pointing at the orchestrator gRPC server (same host:port
    ///   as `orchestrator_grpc`, since the xDS service shares that server).
    async fn write_bootstrap_config(&self) -> anyhow::Result<()> {
        let mut clusters = vec![
            json!({
                "name": "orchestrator_grpc",
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
                    "cluster_name": "orchestrator_grpc",
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
            }),
            json!({
                "name": "dynamic_forward_proxy",
                "connect_timeout": "5s",
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
        ];

        // Dynamic resources differ by mode.
        let dynamic_resources = if self.config.is_grpc_mode() {
            // Add a static cluster for the xDS control plane (H2 gRPC to the
            // orchestrator). Reuses the same host:port as orchestrator_grpc.
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
        self.write_file_in_envoy("/envoy-config/bootstrap.json", &bootstrap_json)
            .await?;
        info!(xds_mode = %self.config.xds_mode, "Wrote Envoy bootstrap config (JSON)");
        Ok(())
    }

    // ── Envoy container helpers ──────────────────────────────────────────

    async fn exec_in_envoy(&self, cmd: &str) -> anyhow::Result<String> {
        exec_in_envoy(&self.docker, &self.config.container_name, cmd).await
    }

    async fn write_file_in_envoy(&self, path: &str, content: &str) -> anyhow::Result<()> {
        write_file_in_envoy(&self.docker, &self.config.container_name, path, content).await
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
        self.add_sandbox(sandbox_id, allowed_hosts, credentials)
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

fn shell_escape(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}
