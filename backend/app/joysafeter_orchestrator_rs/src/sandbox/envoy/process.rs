use std::sync::Arc;
use std::time::Duration;

use bollard::container::RestartContainerOptions;
use bollard::Docker;
use serde_json::json;
use tracing::warn;

use crate::xds::authority::{MutationAuthorityGuard, XdsAuthority};

const ENVOY_NODE_CLUSTER: &str = "joysafeter-envoy";

#[derive(Clone)]
pub struct EnvoyProcessConfig {
    pub container_name: String,
    pub health_check_interval: Duration,
    pub health_failure_threshold: u64,
    pub manage_bootstrap: bool,
    pub config_dir: String,
    pub grpc_mode: bool,
    pub grpc_target_host: String,
    pub grpc_target_port: u16,
    pub xds_auth_token: Option<String>,
    pub node_id: String,
}

pub struct EnvoyProcessSupervisor {
    docker: Option<Arc<Docker>>,
    config: EnvoyProcessConfig,
}

impl EnvoyProcessSupervisor {
    pub fn new(docker: Option<Arc<Docker>>, config: EnvoyProcessConfig) -> Self {
        Self { docker, config }
    }

    fn docker(&self) -> anyhow::Result<&Docker> {
        self.docker
            .as_deref()
            .ok_or_else(|| anyhow::anyhow!("Docker client unavailable (K8s mode)"))
    }

    pub fn is_managed(&self) -> bool {
        self.docker.is_some()
    }

    pub async fn initialize(&self) -> anyhow::Result<()> {
        if !self.config.manage_bootstrap {
            return Ok(());
        }
        let changed = self.write_bootstrap_config().await?;
        if changed {
            self.reload_after_bootstrap_change().await?;
        }
        Ok(())
    }

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
                        "dns_cache_config": { "name": "dynamic_forward_proxy_cache", "dns_lookup_family": "V4_ONLY" }
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
                        "dns_cache_config": { "name": "dynamic_forward_proxy_cache", "dns_lookup_family": "V4_ONLY" }
                    }
                },
                "transport_socket": {
                    "name": "envoy.transport_sockets.tls",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                        "common_tls_context": { "validation_context": { "trusted_ca": { "filename": "/etc/ssl/certs/ca-certificates.crt" } } }
                    }
                }
            }),
        ];
        let dynamic_resources = if self.config.grpc_mode {
            let token = self.config.xds_auth_token.as_deref().ok_or_else(|| {
                anyhow::anyhow!("gRPC xDS bootstrap requires an authentication token")
            })?;
            clusters.push(json!({
                "name": "xds_cluster",
                "connect_timeout": "5s",
                "type": "STRICT_DNS",
                "lb_policy": "ROUND_ROBIN",
                "typed_extension_protocol_options": {
                    "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                        "@type": "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
                        "explicit_http_config": { "http2_protocol_options": {} }
                    }
                },
                "load_assignment": {
                    "cluster_name": "xds_cluster",
                    "endpoints": [{ "lb_endpoints": [{ "endpoint": { "address": { "socket_address": {
                        "address": self.config.grpc_target_host,
                        "port_value": self.config.grpc_target_port
                    } } } }] }]
                }
            }));
            json!({
                "cds_config": { "ads": {} },
                "lds_config": { "ads": {} },
                "ads_config": {
                    "api_type": "DELTA_GRPC",
                    "transport_api_version": "V3",
                    "grpc_services": [{
                        "envoy_grpc": { "cluster_name": "xds_cluster" },
                        "initial_metadata": [{ "key": crate::xds::auth::XDS_AUTH_HEADER, "value": token }]
                    }]
                }
            })
        } else {
            json!({ "lds_config": { "path_config_source": {
                "path": "/envoy-config/lds.json",
                "watched_directory": { "path": "/envoy-config" }
            } } })
        };
        let bootstrap = json!({
            "node": {
                "id": self.config.node_id,
                "cluster": ENVOY_NODE_CLUSTER
            },
            "dynamic_resources": dynamic_resources,
            "static_resources": { "clusters": clusters },
            "admin": { "address": { "socket_address": { "address": "127.0.0.1", "port_value": 9901 } } }
        });
        let content = serde_json::to_string_pretty(&bootstrap)?;
        let path = std::path::PathBuf::from(&self.config.config_dir).join("bootstrap.json");
        let previous = tokio::fs::read_to_string(&path).await.ok();
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let temporary = path.with_extension("tmp");
        tokio::fs::write(&temporary, &content).await?;
        tokio::fs::rename(temporary, &path).await?;
        Ok(previous.as_deref() != Some(content.as_str()))
    }

    pub fn spawn_health_monitor(self: Arc<Self>, authority: XdsAuthority) {
        if !self.is_managed() || self.config.health_check_interval.is_zero() {
            return;
        }
        tokio::spawn(async move {
            let mut failures = 0u64;
            let threshold = self.config.health_failure_threshold.max(1);
            let mut interval = tokio::time::interval(self.config.health_check_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                interval.tick().await;
                match self.health_check().await {
                    Ok(()) => failures = 0,
                    Err(error) => {
                        failures += 1;
                        warn!(failures, threshold, %error, "Envoy health check failed");
                        if failures >= threshold {
                            failures = 0;
                            let Some(guard) = authority.mutation_guard() else {
                                warn!("Skipping Envoy recovery without mutation authority");
                                continue;
                            };
                            if let Err(error) = self.restart(&guard).await {
                                warn!(%error, "Envoy restart/recovery failed");
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
        if state.and_then(|state| state.running).unwrap_or(false) {
            return Ok(());
        }
        let status = state
            .and_then(|state| state.status.as_ref())
            .map(|status| format!("{status:?}"))
            .unwrap_or_else(|| "unknown".to_string());
        anyhow::bail!("Envoy container is not running: {status}")
    }

    pub async fn restart(&self, authority: &MutationAuthorityGuard) -> anyhow::Result<()> {
        authority.validate()?;
        self.docker()?
            .restart_container(
                &self.config.container_name,
                Some(RestartContainerOptions { t: 10 }),
            )
            .await?;
        self.wait_until_ready(Duration::from_secs(15)).await?;
        authority.validate()?;
        Ok(())
    }

    pub async fn reload_after_bootstrap_change(&self) -> anyhow::Result<()> {
        if !self.is_managed() || self.health_check().await.is_err() {
            return Ok(());
        }
        self.docker()?
            .restart_container(
                &self.config.container_name,
                Some(RestartContainerOptions { t: 10 }),
            )
            .await?;
        self.wait_until_ready(Duration::from_secs(15)).await
    }

    pub async fn wait_until_ready(&self, timeout: Duration) -> anyhow::Result<()> {
        if !self.is_managed() {
            return Ok(());
        }
        let deadline = std::time::Instant::now() + timeout;
        let mut last_error = String::new();
        while std::time::Instant::now() < deadline {
            match self.health_check().await {
                Ok(()) => return Ok(()),
                Err(error) => last_error = error.to_string(),
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
        anyhow::bail!("Envoy did not become ready after restart: {last_error}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(config_dir: String, grpc_mode: bool) -> EnvoyProcessConfig {
        EnvoyProcessConfig {
            container_name: "unused".to_string(),
            health_check_interval: Duration::ZERO,
            health_failure_threshold: 1,
            manage_bootstrap: true,
            config_dir,
            grpc_mode,
            grpc_target_host: "control-plane".to_string(),
            grpc_target_port: 18000,
            xds_auth_token: Some("test-control-plane-token-with-enough-entropy".to_string()),
            node_id: "node-a".to_string(),
        }
    }

    #[tokio::test]
    async fn grpc_bootstrap_contains_delta_ads_identity_and_authentication() {
        let directory = tempfile::tempdir().expect("tempdir");
        let supervisor = EnvoyProcessSupervisor::new(
            None,
            config(directory.path().to_string_lossy().into_owned(), true),
        );

        supervisor.initialize().await.expect("write bootstrap");
        let value: serde_json::Value = serde_json::from_slice(
            &tokio::fs::read(directory.path().join("bootstrap.json"))
                .await
                .expect("read bootstrap"),
        )
        .expect("parse bootstrap");

        assert_eq!(value["node"]["id"], "node-a");
        assert_eq!(value["node"]["cluster"], "joysafeter-envoy");
        assert_eq!(
            value["dynamic_resources"]["ads_config"]["api_type"],
            "DELTA_GRPC"
        );
        assert_eq!(
            value["dynamic_resources"]["ads_config"]["grpc_services"][0]["initial_metadata"][0]
                ["value"],
            "test-control-plane-token-with-enough-entropy"
        );
    }

    #[tokio::test]
    async fn filesystem_bootstrap_uses_watched_lds_path() {
        let directory = tempfile::tempdir().expect("tempdir");
        let supervisor = EnvoyProcessSupervisor::new(
            None,
            config(directory.path().to_string_lossy().into_owned(), false),
        );

        supervisor.initialize().await.expect("write bootstrap");
        let value: serde_json::Value = serde_json::from_slice(
            &tokio::fs::read(directory.path().join("bootstrap.json"))
                .await
                .expect("read bootstrap"),
        )
        .expect("parse bootstrap");

        assert_eq!(
            value["dynamic_resources"]["lds_config"]["path_config_source"]["path"],
            "/envoy-config/lds.json"
        );
        assert!(value["dynamic_resources"].get("ads_config").is_none());
    }
}
