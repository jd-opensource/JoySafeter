//! Provider-neutral egress enforcement.
//!
//! [`EgressEnforcer`] is the boundary abstraction that a sandbox provider uses to
//! mediate credentialed egress. Two implementations exist: [`EnvoyEnforcer`]
//! (Docker per-sandbox Envoy listeners over a Unix socket volume) and
//! [`GatewayEnforcer`] (K8s NetworkPolicy + in-cluster egress gateway).
//!
//! The enforcer is owned by the orchestrator (built in `main.rs` via
//! [`build_enforcer`]) and threaded into the resolver, controller, and
//! scheduler. Its presence is the authority for whether credentialed egress can
//! be mediated for a sandbox.

use std::process::Stdio;

use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tracing::{info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::egress::k8s_manager::K8sEgressManager;
use crate::egress::policy::SandboxCredentials;
use crate::kernel::sandbox_resolver::rebuild_sandbox_credentials;

/// Provider-neutral egress enforcement boundary.
///
/// An enforcer configures, tears down, and recovers the mediated egress path for
/// a sandbox. Its *presence* (the orchestrator builds one only when the provider
/// can enforce credentialed egress) is the authority for the resolver's
/// fail-closed gate — there is no capability flag to consult.
#[async_trait::async_trait]
pub trait EgressEnforcer: Send + Sync + 'static {
    /// Configure sandbox egress (allowlist + credential injection).
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()>;

    /// Tear down sandbox egress configuration.
    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()>;

    /// Recover egress state for still-live sandboxes from the database.
    async fn recover(&self, _pool: &PgPool) -> anyhow::Result<()> {
        Ok(())
    }

    /// One-time initialization at orchestrator startup.
    async fn init(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

// =====================================================================
// EnvoyEnforcer (Docker)
// =====================================================================

/// Docker egress enforcer: per-sandbox Envoy listeners over a Unix socket volume.
pub struct EnvoyEnforcer {
    manager: std::sync::Arc<crate::sandbox::envoy::EnvoyManager>,
    allowed_hosts: Vec<String>,
}

impl EnvoyEnforcer {
    pub fn new(
        manager: std::sync::Arc<crate::sandbox::envoy::EnvoyManager>,
        allowed_hosts: Vec<String>,
    ) -> Self {
        Self {
            manager,
            allowed_hosts,
        }
    }
}

#[async_trait::async_trait]
impl EgressEnforcer for EnvoyEnforcer {
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        _sandbox_token: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.manager
            .setup_for_sandbox(sandbox_id, networking, credentials)
            .await
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.manager.teardown_for_sandbox(sandbox_id).await
    }

    async fn recover(&self, pool: &PgPool) -> anyhow::Result<()> {
        self.manager
            .recover_from_db(pool, &self.allowed_hosts)
            .await
    }

    async fn init(&self) -> anyhow::Result<()> {
        self.manager.init().await
    }
}

/// Build the egress enforcer for the configured provider.
///
/// The enforcer is the authority for whether credentialed egress can be
/// mediated: `docker` yields an [`EnvoyEnforcer`] when an Envoy manager is
/// available, `k8s` yields a [`GatewayEnforcer`] when egress management is fully
/// configured, and all other providers (daytona/e2b) yield `None` — which the
/// resolver treats as fail-closed for secret-backed sandboxes.
pub fn build_enforcer(
    config: &JoySafeterConfig,
    provider_name: &str,
    envoy_manager: Option<std::sync::Arc<crate::sandbox::envoy::EnvoyManager>>,
) -> anyhow::Result<Option<std::sync::Arc<dyn EgressEnforcer>>> {
    Ok(match provider_name {
        "docker" | "" => envoy_manager.map(|m| {
            std::sync::Arc::new(EnvoyEnforcer::new(
                m,
                config.llm_egress_allowed_hosts.clone(),
            )) as std::sync::Arc<dyn EgressEnforcer>
        }),
        "k8s" | "kubernetes" => GatewayEnforcer::from_config(config)?
            .map(|g| std::sync::Arc::new(g) as std::sync::Arc<dyn EgressEnforcer>),
        _ => None, // daytona/e2b: no enforcer → fail-closed for secret sandboxes
    })
}

// =====================================================================
// GatewayEnforcer (K8s)
// =====================================================================

/// K8s egress enforcer: per-sandbox NetworkPolicy + in-cluster egress gateway.
///
/// Holds the K8s egress machinery relocated out of `K8sProvider`: kubectl access,
/// NetworkPolicy construction, the resolved service targets, and the
/// [`K8sEgressManager`] control client.
#[derive(Clone, Debug)]
pub struct GatewayEnforcer {
    namespace: String,
    kubectl_path: String,
    orchestrator_network_target: Option<K8sServiceTarget>,
    egress_gateway_network_target: Option<K8sServiceTarget>,
    llm_egress_allowed_hosts: Vec<String>,
    manager: K8sEgressManager,
}

impl GatewayEnforcer {
    /// Replicate the egress-readiness computation formerly in `K8sProvider::new`:
    /// returns `Some` only when egress management is enabled and the manager plus
    /// both service targets resolve.
    pub fn from_config(config: &JoySafeterConfig) -> anyhow::Result<Option<Self>> {
        let egress_manager = match K8sEgressManager::from_config(config) {
            Ok(manager) => manager,
            Err(err) => {
                warn!("K8s egress manager disabled: {err}");
                None
            }
        };
        let orchestrator_target_url = config
            .k8s_orchestrator_url
            .clone()
            .unwrap_or_else(|| format!("http://joysafeter-orchestrator:{}", config.grpc_port));
        let orchestrator_network_target =
            match k8s_service_target_from_url(&orchestrator_target_url, &config.k8s_namespace) {
                Ok(target) => Some(target),
                Err(err) => {
                    warn!("K8s orchestrator NetworkPolicy target disabled: {err}");
                    None
                }
            };
        let egress_gateway_network_target = config
            .egress_gateway_url
            .as_deref()
            .map(|url| k8s_service_target_from_url(url, &config.k8s_namespace))
            .transpose()
            .unwrap_or_else(|err| {
                warn!("K8s egress gateway NetworkPolicy target disabled: {err}");
                None
            });
        let has_egress_manager = egress_manager.is_some();
        let has_orchestrator_network_target = orchestrator_network_target.is_some();
        let has_egress_gateway_network_target = egress_gateway_network_target.is_some();
        let has_egress_gateway_url = config.egress_gateway_url.is_some();
        info!(
            egress_management_enabled = config.k8s_egress_management_enabled,
            has_egress_gateway_url,
            has_egress_manager,
            has_orchestrator_network_target,
            has_egress_gateway_network_target,
            has_egress_management = config.k8s_egress_management_enabled
                && has_egress_manager
                && has_orchestrator_network_target
                && has_egress_gateway_network_target,
            "K8s provider egress capability check"
        );

        if config.k8s_egress_management_enabled
            && has_egress_manager
            && has_orchestrator_network_target
            && has_egress_gateway_network_target
        {
            Ok(Some(Self {
                namespace: config.k8s_namespace.clone(),
                kubectl_path: config.k8s_kubectl_path.clone(),
                orchestrator_network_target,
                egress_gateway_network_target,
                llm_egress_allowed_hosts: config.llm_egress_allowed_hosts.clone(),
                manager: egress_manager.expect("egress manager present"),
            }))
        } else {
            Ok(None)
        }
    }

    async fn kubectl_apply(&self, manifest: &Value) -> anyhow::Result<()> {
        let args = Self::kubectl_apply_args();
        let mut child = Command::new(&self.kubectl_path)
            .args(args)
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
                "kubectl {:?} failed: {}",
                args,
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    }

    fn kubectl_apply_args() -> [&'static str; 5] {
        [
            "apply",
            "--server-side",
            "--field-manager=joysafeter-orchestrator",
            "-f",
            "-",
        ]
    }

    fn build_network_policy(&self, sandbox_id: Uuid) -> anyhow::Result<Value> {
        let Some(orchestrator) = self.orchestrator_network_target.as_ref() else {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s NetworkPolicy requires a resolvable orchestrator service target"
            );
        };
        let Some(gateway) = self.egress_gateway_network_target.as_ref() else {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: K8s NetworkPolicy requires a resolvable egress gateway service target"
            );
        };

        Ok(json!({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": format!("joysafeter-egress-{sandbox_id}"),
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/name": "joysafeter-sandbox-egress",
                    "app.kubernetes.io/part-of": "joysafeter",
                    "joysafeter.sandbox_id": sandbox_id.to_string()
                }
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "joysafeter-sandbox",
                        "joysafeter.sandbox_id": sandbox_id.to_string()
                    }
                },
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {
                                        "kubernetes.io/metadata.name": "kube-system"
                                    }
                                }
                            }
                        ],
                        "ports": [
                            { "protocol": "UDP", "port": 53 },
                            { "protocol": "TCP", "port": 53 }
                        ]
                    },
                    egress_rule_for_service(orchestrator),
                    egress_rule_for_service(gateway)
                ]
            }
        }))
    }
}

#[async_trait::async_trait]
impl EgressEnforcer for GatewayEnforcer {
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        let network_policy = self.build_network_policy(sandbox_id)?;
        self.kubectl_apply(&network_policy).await?;
        self.manager
            .setup_for_sandbox(sandbox_id, sandbox_token, networking, credentials)
            .await
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.manager.teardown_for_sandbox(sandbox_id).await
    }

    async fn recover(&self, pool: &PgPool) -> anyhow::Result<()> {
        let sandboxes = queries::list_live_sandboxes_for_recovery(pool).await?;
        let mut recovered = 0usize;
        let mut skipped = 0usize;
        for sandbox in &sandboxes {
            let Some(networking) = recovery_networking(sandbox) else {
                skipped += 1;
                continue;
            };
            let Some(runner_token) = runner_token_from_sandbox_config(sandbox.config.as_ref())
            else {
                skipped += 1;
                warn!(
                    sandbox_id = %sandbox.id,
                    "Skipping K8s egress recovery because sandbox config has no runner token"
                );
                continue;
            };

            let network_policy = self.build_network_policy(sandbox.id)?;
            self.kubectl_apply(&network_policy).await?;
            let credentials =
                rebuild_sandbox_credentials(pool, sandbox, &self.llm_egress_allowed_hosts).await;
            self.manager
                .setup_for_sandbox(sandbox.id, runner_token, Some(networking), credentials)
                .await?;
            recovered += 1;
        }

        info!(
            recovered_sandboxes = recovered,
            skipped_sandboxes = skipped,
            total_live = sandboxes.len(),
            "K8s egress manager recovered sandbox policies from DB"
        );
        Ok(())
    }
}

// =====================================================================
// K8s egress helpers (relocated from k8s.rs)
// =====================================================================

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct K8sServiceTarget {
    service_name: String,
    namespace: String,
    port: u16,
}

pub(crate) fn k8s_service_target_from_url(
    raw: &str,
    fallback_namespace: &str,
) -> anyhow::Result<K8sServiceTarget> {
    let url = url::Url::parse(raw)?;
    let host = url
        .host_str()
        .ok_or_else(|| anyhow::anyhow!("URL has no host"))?;
    let labels: Vec<&str> = host.split('.').filter(|part| !part.is_empty()).collect();
    let service_name = labels
        .first()
        .ok_or_else(|| anyhow::anyhow!("URL host has no service name"))?
        .to_string();
    let namespace = if labels.len() >= 3 && labels[2] == "svc" {
        labels[1].to_string()
    } else {
        fallback_namespace.to_string()
    };
    let port = url.port_or_known_default().ok_or_else(|| {
        anyhow::anyhow!("URL must include a port or use a scheme with a known default port")
    })?;

    Ok(K8sServiceTarget {
        service_name,
        namespace,
        port,
    })
}

fn egress_rule_for_service(target: &K8sServiceTarget) -> Value {
    json!({
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": target.namespace
                    }
                },
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": target.service_name
                    }
                }
            }
        ],
        "ports": [
            { "protocol": "TCP", "port": target.port }
        ]
    })
}

pub(crate) fn recovery_networking(sandbox: &JoySafeterSandbox) -> Option<&Value> {
    let networking = sandbox
        .config
        .as_ref()?
        .get("fingerprint")?
        .get("networking")?;
    (networking.get("type").and_then(|value| value.as_str()) == Some("limited"))
        .then_some(networking)
}

pub(crate) fn runner_token_from_sandbox_config(config: Option<&Value>) -> Option<&str> {
    config?
        .get("runner_token")?
        .as_str()
        .filter(|token| !token.trim().is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gateway_enforcer_from(config: &JoySafeterConfig) -> Option<GatewayEnforcer> {
        GatewayEnforcer::from_config(config).expect("from_config")
    }

    fn enabled_gateway_config() -> JoySafeterConfig {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        config.k8s_kubectl_path = "kubectl".to_string();
        config.k8s_orchestrator_url = Some(
            "http://joysafeter-orchestrator.joysafeter-control.svc.cluster.local:9090".to_string(),
        );
        config.egress_gateway_url =
            Some("http://joysafeter-egress-gateway.joysafeter-control.svc:8088".to_string());
        config.egress_gateway_control_token = Some("control-token".to_string());
        config.k8s_egress_management_enabled = true;
        config
    }

    fn gateway_config_without_enablement() -> JoySafeterConfig {
        let mut config = enabled_gateway_config();
        config.k8s_egress_management_enabled = false;
        config
    }

    #[test]
    fn gateway_enforcer_from_config_requires_enablement_and_targets() {
        assert!(gateway_enforcer_from(&gateway_config_without_enablement()).is_none());

        gateway_enforcer_from(&enabled_gateway_config())
            .expect("enabled gateway yields an enforcer");
    }

    #[test]
    fn gateway_enforcer_network_policy_allows_only_dns_orchestrator_and_gateway() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000023").expect("valid uuid");
        let enforcer =
            gateway_enforcer_from(&enabled_gateway_config()).expect("enabled gateway enforcer");

        let policy = enforcer
            .build_network_policy(sandbox_id)
            .expect("network policy");
        let rendered = serde_json::to_string(&policy).expect("policy json");

        assert_eq!(
            policy
                .pointer("/apiVersion")
                .and_then(|value| value.as_str()),
            Some("networking.k8s.io/v1")
        );
        assert_eq!(
            policy.pointer("/kind").and_then(|value| value.as_str()),
            Some("NetworkPolicy")
        );
        assert_eq!(
            policy
                .pointer("/spec/podSelector/matchLabels/joysafeter.sandbox_id")
                .and_then(|value| value.as_str()),
            Some("018ff000-0000-7000-8000-000000000023")
        );
        assert_eq!(
            policy
                .pointer("/spec/egress")
                .and_then(|value| value.as_array())
                .map(Vec::len),
            Some(3)
        );
        assert!(rendered.contains("kube-system"));
        assert!(rendered.contains("joysafeter-orchestrator"));
        assert!(rendered.contains("joysafeter-egress-gateway"));
        assert!(!rendered.contains("ai-api.jdcloud.com"));
        assert!(!rendered.contains("api.anthropic.com"));
    }

    #[test]
    fn k8s_runtime_apply_uses_server_side_apply_without_last_applied_annotation() {
        let args = GatewayEnforcer::kubectl_apply_args();

        assert!(args.contains(&"--server-side"));
        assert!(args.contains(&"--field-manager=joysafeter-orchestrator"));
        assert!(!args.contains(&"--save-config"));
        assert!(!args.contains(&"--record"));
    }

    #[test]
    fn k8s_service_target_parses_in_cluster_service_dns() {
        let target = k8s_service_target_from_url(
            "http://joysafeter-egress-gateway.joysafeter-control.svc.cluster.local:8088",
            "joysafeter-sandboxes",
        )
        .expect("service target");

        assert_eq!(
            target,
            K8sServiceTarget {
                service_name: "joysafeter-egress-gateway".to_string(),
                namespace: "joysafeter-control".to_string(),
                port: 8088,
            }
        );
    }

    #[test]
    fn k8s_recovery_only_targets_limited_networking_sandboxes() {
        let limited = JoySafeterSandbox {
            id: Uuid::parse_str("018ff000-0000-7000-8000-000000000025").expect("valid uuid"),
            external_id: Some("joysafeter-limited".to_string()),
            status: "running".to_string(),
            config: Some(json!({
                "runner_token": "runner-token",
                "fingerprint": {
                    "networking": {
                        "type": "limited",
                        "allowed_hosts": ["api.anthropic.com"]
                    }
                }
            })),
            chat_session_id: None,
            image: Some("joysafeter-claudecode:latest".to_string()),
            disconnected_at: None,
        };
        let unrestricted = JoySafeterSandbox {
            config: Some(json!({
                "runner_token": "runner-token",
                "fingerprint": {
                    "networking": {
                        "type": "unrestricted"
                    }
                }
            })),
            ..limited.clone()
        };

        assert!(recovery_networking(&limited).is_some());
        assert!(recovery_networking(&unrestricted).is_none());
    }

    #[test]
    fn k8s_recovery_requires_non_empty_runner_token() {
        let good = json!({ "runner_token": "runner-token" });
        let empty = json!({ "runner_token": " " });

        assert_eq!(
            runner_token_from_sandbox_config(Some(&good)),
            Some("runner-token")
        );
        assert_eq!(runner_token_from_sandbox_config(Some(&empty)), None);
        assert_eq!(runner_token_from_sandbox_config(None), None);
    }
}
