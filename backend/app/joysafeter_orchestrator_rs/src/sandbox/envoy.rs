use std::sync::Arc;

use bollard::Docker;
use serde_json::json;
use tracing::{debug, info, warn};
use uuid::Uuid;

use super::lds_backend::{
    dynamic_forward_proxy_dns_cache_json, exec_in_envoy, write_file_in_envoy, CdsBackend,
    DeniedCidr, LdsBackend, ListenerKind, ListenerSpec,
};
use crate::egress::policy::{SandboxCredentials, SandboxEgressPolicy};

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
    /// `"filesystem"` (default, `lds.json`), `"grpc"` (Delta xDS to the
    /// orchestrator), or `"controller"` (Delta xDS to the Go egress controller).
    pub xds_mode: String,
    /// Controller xDS host, used when `xds_mode == "controller"`.
    pub controller_xds_host: String,
    /// Controller xDS port, used when `xds_mode == "controller"`.
    pub controller_xds_port: u16,
    /// structpb `node.metadata` emitted into the bootstrap in `controller` mode
    /// so the Go egress-controller hashes this Envoy into the same group the
    /// durable authority writes generations under. `None` in filesystem/grpc
    /// modes (no group hashing). Built from
    /// [`crate::egress::enforcer::shared_docker_node_selector`].
    pub node_metadata: Option<serde_json::Value>,
    pub denied_cidrs: Vec<DeniedCidr>,
}

impl EnvoyConfig {
    fn is_grpc_mode(&self) -> bool {
        self.xds_mode == "grpc"
    }

    fn is_controller_mode(&self) -> bool {
        self.xds_mode == "controller"
    }

    /// Build the bootstrap JSON value for the active mode (pure; no I/O).
    ///
    /// * filesystem: `dynamic_resources.lds_config.path_config_source`.
    /// * grpc / controller: `lds_config.ads` + `ads_config { DELTA_GRPC }` + a
    ///   static `xds_cluster`. In `grpc` mode that cluster points at the
    ///   orchestrator gRPC server (same host:port as `orchestrator_grpc`, since
    ///   the xDS service shares that server); in `controller` mode it points at
    ///   the Go egress controller (`controller_xds_host:controller_xds_port`).
    ///
    /// The static `orchestrator_grpc` cluster is unchanged across all modes and
    /// keeps pointing at `grpc_target_host:grpc_target_port` — it is the
    /// control-channel upstream the emitted `grpc.sock` listener routes to.
    pub fn render_bootstrap_value(&self) -> serde_json::Value {
        let dns_cache_config = dynamic_forward_proxy_dns_cache_json(&self.denied_cidrs);
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
                                        "address": self.grpc_target_host,
                                        "port_value": self.grpc_target_port
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
                        "dns_cache_config": dns_cache_config
                    }
                }
            }),
        ];

        // Dynamic resources differ by mode. Both `grpc` and `controller` add a
        // static `xds_cluster` and drive LDS/CDS over ADS Delta gRPC; they
        // differ only in the `xds_cluster` endpoint address.
        let dynamic_resources = if self.is_grpc_mode() || self.is_controller_mode() {
            // xds_cluster endpoint: controller mode → the Go controller;
            // grpc mode → the orchestrator gRPC server.
            let (xds_host, xds_port) = if self.is_controller_mode() {
                (self.controller_xds_host.clone(), self.controller_xds_port)
            } else {
                (self.grpc_target_host.clone(), self.grpc_target_port)
            };
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
                                        "address": xds_host,
                                        "port_value": xds_port
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

        // In controller mode the Go egress-controller groups Envoys by
        // node.metadata; without it the controller cannot match this Envoy to a
        // desired generation and serves an empty snapshot (apply never ACKs).
        let mut node = json!({
            "cluster": "joysafeter-proxy",
            "id": "joysafeter-envoy"
        });
        if self.is_controller_mode() {
            if let Some(metadata) = &self.node_metadata {
                node["metadata"] = metadata.clone();
            }
        }

        json!({
            "node": node,
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
        })
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

    /// Create only the per-sandbox socket directory (no listener push). Used by
    /// the controller-mode Docker preparer, where the Go controller owns LDS/CDS.
    pub async fn ensure_sandbox_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let socket_dir = format!("/sockets/{sandbox_id}");
        self.exec_in_envoy(&format!("mkdir -p {socket_dir} && chmod 777 {socket_dir}"))
            .await?;
        Ok(())
    }

    /// Remove only the per-sandbox socket directory (no listener removal).
    pub async fn remove_sandbox_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let _ = self
            .exec_in_envoy(&format!("rm -rf /sockets/{sandbox_id}"))
            .await;
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
            let socket_dir = format!("/sockets/{}", sb.id);
            let _ = self
                .exec_in_envoy(&format!("mkdir -p {socket_dir} && chmod 777 {socket_dir}"))
                .await;

            // Re-derive the sandbox's egress credentials from the DB and render
            // both its listener routes and its per-upstream clusters.
            let creds = crate::kernel::sandbox_resolver::rebuild_sandbox_credentials(
                pool,
                sb,
                llm_egress_allowed_hosts,
            )
            .await;
            // Make these routes resolvable by the ext_authz data plane after a
            // restart (same install the create path does), reusing the rebuild
            // we already did here rather than a second recovery pass.
            crate::kernel::credential_resolution::global_resolution_registry()
                .install(sb.id, &creds.routes);
            let policy = creds.to_policy(&sb.id, allowed_hosts);
            clusters.extend(policy.clusters(&sb.id));

            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Grpc,
                allowed_hosts: vec![],
                credentials: vec![],
                denied_cidrs: self.config.denied_cidrs.clone(),
            });
            specs.push(ListenerSpec {
                sandbox_id: sb.id,
                kind: ListenerKind::Http,
                allowed_hosts: policy.allowlist_hosts,
                credentials: policy.credential_routes,
                denied_cidrs: self.config.denied_cidrs.clone(),
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
        // Create socket directory inside container
        let socket_dir = format!("/sockets/{sandbox_id}");
        self.ensure_sandbox_socket_dir(sandbox_id).await?;

        // Write a per-sandbox entry file for crash-recovery/debugging visibility.
        // NOTE: never include secrets here — only the non-sensitive allowlist.
        let entry_json = json!({
            "sandbox_id": sandbox_id.to_string(),
            "allowed_hosts": policy.allowlist_hosts,
        });
        let entry_path = format!("/envoy-config/sandboxes/{sandbox_id}.json");
        self.write_file_in_envoy(&entry_path, &serde_json::to_string(&entry_json)?)
            .await?;

        let cred_clusters = policy.clusters(&sandbox_id);

        // Push clusters BEFORE listeners (make-before-break): a listener whose
        // routes reference a not-yet-known cluster would fail to warm.
        if !cred_clusters.is_empty() {
            self.cds.upsert(cred_clusters).await?;
        }

        // Push the two listeners for this sandbox through the active backend.
        self.lds
            .upsert(vec![
                ListenerSpec {
                    sandbox_id,
                    kind: ListenerKind::Grpc,
                    allowed_hosts: vec![],
                    credentials: vec![],
                    denied_cidrs: self.config.denied_cidrs.clone(),
                },
                ListenerSpec {
                    sandbox_id,
                    kind: ListenerKind::Http,
                    allowed_hosts: policy.allowlist_hosts.clone(),
                    credentials: policy.credential_routes.clone(),
                    denied_cidrs: self.config.denied_cidrs.clone(),
                },
            ])
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
        self.remove_sandbox_socket_dir(sandbox_id).await?;

        // Remove entry file
        let _ = self
            .exec_in_envoy(&format!("rm -f /envoy-config/sandboxes/{sandbox_id}.json"))
            .await;

        debug!(sandbox_id = %sandbox_id, "Removed sandbox from Envoy config");
        Ok(())
    }

    /// Write Envoy bootstrap config as JSON, matching the active xDS mode.
    ///
    /// The bootstrap JSON is built by the pure [`EnvoyConfig::render_bootstrap_value`];
    /// this method only performs the container-side file write.
    async fn write_bootstrap_config(&self) -> anyhow::Result<()> {
        let bootstrap = self.config.render_bootstrap_value();
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

#[cfg(test)]
mod bootstrap_tests {
    use super::*;

    fn cfg(mode: &str) -> EnvoyConfig {
        EnvoyConfig {
            envoy_image: "img".into(),
            socket_volume: "vol".into(),
            config_dir: "/envoy-config".into(),
            envoy_network: "net".into(),
            grpc_target_host: "joysafeter-orchestrator".into(),
            grpc_target_port: 9090,
            container_name: "joysafeter-envoy".into(),
            xds_mode: mode.into(),
            controller_xds_host: "joysafeter-egress-controller".into(),
            controller_xds_port: 18000,
            node_metadata: Some(json!({
                "deployment_id": "joysafeter",
                "environment": "production",
                "region": "local",
                "provider": "docker",
                "shard_id": "0",
                "host_id": "docker-local",
                "envoy_version": "1.39.0",
                "config_schema_version": "1"
            })),
            denied_cidrs: vec![],
        }
    }

    #[test]
    fn controller_mode_points_ads_at_controller() {
        let bootstrap = cfg("controller").render_bootstrap_value();
        let clusters = bootstrap["static_resources"]["clusters"]
            .as_array()
            .unwrap();
        // orchestrator_grpc still targets the orchestrator (control channel upstream).
        let orch = clusters
            .iter()
            .find(|c| c["name"] == "orchestrator_grpc")
            .unwrap();
        let orch_addr = &orch["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
            ["address"]["socket_address"];
        assert_eq!(orch_addr["address"], "joysafeter-orchestrator");
        assert_eq!(orch_addr["port_value"], 9090);
        // xds_cluster targets the Go controller.
        let xds = clusters
            .iter()
            .find(|c| c["name"] == "xds_cluster")
            .unwrap();
        let xds_addr = &xds["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
            ["address"]["socket_address"];
        assert_eq!(xds_addr["address"], "joysafeter-egress-controller");
        assert_eq!(xds_addr["port_value"], 18000);
        // ADS is configured.
        assert_eq!(
            bootstrap["dynamic_resources"]["ads_config"]["grpc_services"][0]["envoy_grpc"]
                ["cluster_name"],
            "xds_cluster"
        );
        // node.metadata carries the group-selector fields so the Go controller
        // hashes this Envoy into the durable authority's group. Without it the
        // controller serves an empty snapshot and the apply never ACKs.
        let meta = &bootstrap["node"]["metadata"];
        assert_eq!(meta["provider"], "docker");
        assert_eq!(meta["host_id"], "docker-local");
        assert_eq!(meta["envoy_version"], "1.39.0");
        assert_eq!(meta["config_schema_version"], "1");
    }

    #[test]
    fn non_controller_modes_omit_node_metadata() {
        // filesystem/grpc modes do not group by node.metadata; keep the node
        // block minimal so their behavior is unchanged.
        for mode in ["filesystem", "grpc"] {
            let bootstrap = cfg(mode).render_bootstrap_value();
            assert!(
                bootstrap["node"].get("metadata").is_none(),
                "{mode} bootstrap must not emit node.metadata"
            );
        }
    }
}
