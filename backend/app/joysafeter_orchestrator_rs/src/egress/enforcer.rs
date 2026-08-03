//! Provider-neutral egress enforcement.
//!
//! [`EgressEnforcer`] is the boundary abstraction that a sandbox provider uses to
//! mediate credentialed egress. Implementations cover Docker per-sandbox Envoy
//! and shared-fleet K8s Envoy network preparation.
//!
//! The enforcer is owned by the orchestrator (built in `main.rs` via
//! [`build_enforcer`]) and threaded into the resolver, controller, and
//! scheduler. Its presence is the authority for whether credentialed egress can
//! be mediated for a sandbox.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use k8s_openapi::api::networking::v1::NetworkPolicy;
use kube::api::{DeleteParams, ListParams, Patch, PatchParams};
use kube::{Api, Client};
use serde_json::{json, Value};
use sqlx::PgPool;
use tokio::sync::OnceCell;
use tracing::{debug, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::egress::authority::{AuthorityConfig, NodeSelector, PostgresEgressPolicyAuthority};
use crate::egress::policy::SandboxCredentials;

const K8S_FIELD_MANAGER: &str = "joysafeter-orchestrator";
const K8S_EGRESS_POLICY_LABEL_SELECTOR: &str =
    "app.kubernetes.io/name=joysafeter-sandbox-egress,joysafeter.egress-data-plane=envoy";

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

    /// Stable label identifying the concrete preparer; used in tests/telemetry.
    fn kind_label(&self) -> &'static str {
        "generic"
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

    fn kind_label(&self) -> &'static str {
        "docker-envoy"
    }
}

/// Docker network preparer for `controller` xDS mode. Prepares the sandbox
/// (socket dir + one-time Envoy bootstrap) but does NOT push listeners — the Go
/// egress-controller serves them over ADS. Pairs with `AuthoritativeEnforcer`,
/// which declares the desired policy to Postgres and waits for the controller ACK.
struct DockerEnvoyNetworkPreparer {
    envoy: std::sync::Arc<crate::sandbox::envoy::EnvoyManager>,
}

#[async_trait::async_trait]
impl EgressEnforcer for DockerEnvoyNetworkPreparer {
    fn kind_label(&self) -> &'static str {
        "docker-controller"
    }

    async fn init(&self) -> anyhow::Result<()> {
        // Writes the controller-mode bootstrap and resets nothing else.
        self.envoy.init().await
    }

    async fn enforce(
        &self,
        sandbox_id: Uuid,
        _sandbox_token: &str,
        _networking: Option<&serde_json::Value>,
        _credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        // Controller owns listeners; we only guarantee the socket dir exists so
        // Envoy can bind the pipe once the controller pushes the listener.
        self.envoy.ensure_sandbox_socket_dir(sandbox_id).await
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.envoy.remove_sandbox_socket_dir(sandbox_id).await
    }

    async fn recover(&self, _pool: &PgPool) -> anyhow::Result<()> {
        // Listener recovery is the controller's job (Postgres desired-state).
        Ok(())
    }
}

/// Build the egress enforcer for the configured provider.
///
/// The enforcer is the authority for whether credentialed egress can be
/// mediated: `docker` yields an [`EnvoyEnforcer`] when an Envoy manager is
/// available, `k8s` yields a [`K8sEnvoyNetworkPreparer`] only when the durable
/// shared-Envoy authority is enabled, and all other providers (daytona/e2b)
/// yield `None` — which the resolver treats as fail-closed for secret-backed
/// sandboxes.
pub fn build_enforcer(
    config: &JoySafeterConfig,
    provider_name: &str,
    envoy_manager: Option<std::sync::Arc<crate::sandbox::envoy::EnvoyManager>>,
) -> anyhow::Result<Option<std::sync::Arc<dyn EgressEnforcer>>> {
    build_enforcer_with_pool(config, None, provider_name, envoy_manager)
}

/// The shared-Docker-Envoy [`NodeSelector`], built from the policy identity
/// config. This is the single source of truth for the Docker group identity:
/// the durable authority uses it to compute the group key it writes generations
/// under, and the Envoy bootstrap uses its [`NodeSelector::metadata_value`] so
/// the connecting Envoy hashes into that same group. `host_id` falls back to the
/// container hostname when unset, matching `provider == "docker"`'s requirement.
pub fn shared_docker_node_selector(config: &JoySafeterConfig) -> NodeSelector {
    let host_id = config
        .egress_policy_host_id
        .clone()
        .unwrap_or_else(|| gethostname::gethostname().to_string_lossy().into_owned());
    NodeSelector {
        deployment_id: config.egress_policy_deployment_id.clone(),
        environment: config.egress_policy_environment.clone(),
        region: config.egress_policy_region.clone(),
        provider: "docker".to_string(),
        shard_id: config.egress_policy_shard_id.clone(),
        host_id: Some(host_id),
        envoy_version: config.egress_policy_envoy_version.clone(),
        config_schema_version: config.egress_policy_config_schema_version.clone(),
    }
}

pub fn build_enforcer_with_pool(
    config: &JoySafeterConfig,
    pool: Option<PgPool>,
    provider_name: &str,
    envoy_manager: Option<std::sync::Arc<crate::sandbox::envoy::EnvoyManager>>,
) -> anyhow::Result<Option<std::sync::Arc<dyn EgressEnforcer>>> {
    let preparer = match provider_name {
        "docker" | "" => envoy_manager.map(|m| {
            if config.envoy_xds_mode == "controller" {
                std::sync::Arc::new(DockerEnvoyNetworkPreparer { envoy: m })
                    as std::sync::Arc<dyn EgressEnforcer>
            } else {
                std::sync::Arc::new(EnvoyEnforcer::new(
                    m,
                    config.llm_egress_allowed_hosts.clone(),
                )) as std::sync::Arc<dyn EgressEnforcer>
            }
        }),
        "k8s" | "kubernetes" if config.egress_policy_authority_enabled => {
            K8sEnvoyNetworkPreparer::from_config(config)?
                .map(|value| std::sync::Arc::new(value) as std::sync::Arc<dyn EgressEnforcer>)
        }
        "k8s" | "kubernetes" => None,
        _ => None, // daytona/e2b: no enforcer → fail-closed for secret sandboxes
    };
    if !config.egress_policy_authority_enabled {
        return Ok(preparer);
    }

    let preparer = preparer.ok_or_else(|| {
        anyhow::anyhow!(
            "durable egress policy authority requires a provider network preparer for {provider_name}"
        )
    })?;
    let provider = match provider_name {
        "" | "docker" => "docker",
        "k8s" | "kubernetes" => "k8s",
        other => anyhow::bail!("unsupported durable egress authority provider {other}"),
    };
    let selector = if provider == "docker" {
        // Single source of truth shared with the Envoy bootstrap node.metadata.
        shared_docker_node_selector(config)
    } else {
        NodeSelector {
            deployment_id: config.egress_policy_deployment_id.clone(),
            environment: config.egress_policy_environment.clone(),
            region: config.egress_policy_region.clone(),
            provider: provider.to_string(),
            shard_id: config.egress_policy_shard_id.clone(),
            host_id: None,
            envoy_version: config.egress_policy_envoy_version.clone(),
            config_schema_version: config.egress_policy_config_schema_version.clone(),
        }
    };
    let authority = PostgresEgressPolicyAuthority::new(
        pool.ok_or_else(|| {
            anyhow::anyhow!("durable egress policy authority requires a PostgreSQL pool")
        })?,
        AuthorityConfig {
            selector,
            denied_cidrs: config.envoy_egress_denied_cidrs.clone(),
            apply_timeout: Duration::from_millis(config.egress_policy_apply_timeout_ms),
            poll_interval: Duration::from_millis(config.egress_policy_poll_interval_ms),
        },
    )?;
    info!(
        group_key = authority.group_key(),
        provider, "Durable Envoy egress policy authority enabled"
    );
    Ok(Some(std::sync::Arc::new(AuthoritativeEnforcer {
        preparer,
        authority,
    })))
}

struct AuthoritativeEnforcer {
    preparer: std::sync::Arc<dyn EgressEnforcer>,
    authority: std::sync::Arc<PostgresEgressPolicyAuthority>,
}

#[async_trait::async_trait]
impl EgressEnforcer for AuthoritativeEnforcer {
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        sandbox_token: &str,
        networking: Option<&serde_json::Value>,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.preparer
            .enforce(sandbox_id, sandbox_token, networking, credentials.clone())
            .await?;
        let result = async {
            let handle = self
                .authority
                .declare(sandbox_id, networking, &credentials)
                .await?;
            self.authority.wait_applied(&handle).await?;
            anyhow::Ok(())
        }
        .await;
        if let Err(error) = result {
            if let Err(teardown_error) = self.preparer.teardown(sandbox_id).await {
                warn!(%sandbox_id, %teardown_error, "failed to roll back provider egress preparation");
            }
            if let Err(revoke_error) = self.authority.revoke(sandbox_id).await {
                warn!(%sandbox_id, %revoke_error, "failed to enqueue egress policy rollback");
            }
            return Err(error);
        }
        Ok(())
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let preparer_result = self.preparer.teardown(sandbox_id).await;
        let authority_result = async {
            if let Some(handle) = self.authority.revoke(sandbox_id).await? {
                self.authority.wait_applied(&handle).await?;
            }
            anyhow::Ok(())
        }
        .await;

        match (preparer_result, authority_result) {
            (Ok(()), Ok(())) => Ok(()),
            (Err(preparer_error), Ok(())) => Err(preparer_error),
            (Ok(()), Err(authority_error)) => Err(authority_error),
            (Err(preparer_error), Err(authority_error)) => anyhow::bail!(
                "provider egress teardown failed: {preparer_error}; durable policy revoke failed: {authority_error}"
            ),
        }
    }

    async fn recover(&self, pool: &PgPool) -> anyhow::Result<()> {
        self.preparer.recover(pool).await
    }

    async fn init(&self) -> anyhow::Result<()> {
        self.preparer.init().await
    }
}

// =====================================================================
// K8sEnvoyNetworkPreparer
// =====================================================================

#[derive(Clone)]
pub struct K8sEnvoyNetworkPreparer {
    namespace: String,
    native_client: Arc<OnceCell<Result<Client, String>>>,
    orchestrator_network_target: K8sServiceTarget,
    credential_network_target: K8sServiceTarget,
    forward_proxy_network_target: K8sServiceTarget,
}

impl K8sEnvoyNetworkPreparer {
    pub fn from_config(config: &JoySafeterConfig) -> anyhow::Result<Option<Self>> {
        if !config.k8s_egress_management_enabled {
            return Ok(None);
        }
        let orchestrator_url = config
            .k8s_orchestrator_url
            .clone()
            .unwrap_or_else(|| format!("http://joysafeter-orchestrator:{}", config.grpc_port));
        let credential_url = config
            .egress_envoy_credential_url
            .as_deref()
            .ok_or_else(|| {
                anyhow::anyhow!("K8s Envoy egress requires JOYSAFETER_EGRESS_ENVOY_CREDENTIAL_URL")
            })?;
        let forward_proxy_url = config
            .egress_envoy_forward_proxy_url
            .as_deref()
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "K8s Envoy egress requires JOYSAFETER_EGRESS_ENVOY_FORWARD_PROXY_URL"
                )
            })?;
        Ok(Some(Self {
            namespace: config.k8s_namespace.clone(),
            native_client: Arc::new(OnceCell::new()),
            orchestrator_network_target: k8s_service_target_from_url(
                &orchestrator_url,
                &config.k8s_namespace,
            )?,
            credential_network_target: k8s_service_target_from_url(
                credential_url,
                &config.k8s_namespace,
            )?,
            forward_proxy_network_target: k8s_service_target_from_url(
                forward_proxy_url,
                &config.k8s_namespace,
            )?,
        }))
    }

    fn network_policy_name(sandbox_id: Uuid) -> String {
        format!("joysafeter-egress-{sandbox_id}")
    }

    fn build_network_policy(&self, sandbox_id: Uuid) -> Value {
        json!({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": Self::network_policy_name(sandbox_id),
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/name": "joysafeter-sandbox-egress",
                    "app.kubernetes.io/part-of": "joysafeter",
                    "joysafeter.sandbox_id": sandbox_id.to_string(),
                    "joysafeter.egress-data-plane": "envoy"
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
                        "to": [{
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "kube-system"
                                }
                            }
                        }],
                        "ports": [
                            { "protocol": "UDP", "port": 53 },
                            { "protocol": "TCP", "port": 53 }
                        ]
                    },
                    egress_rule_for_service(&self.orchestrator_network_target),
                    egress_rule_for_service(&self.credential_network_target),
                    egress_rule_for_service(&self.forward_proxy_network_target)
                ]
            }
        })
    }

    async fn apply_network_policy(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        apply_network_policy_manifest(
            &self.namespace,
            &self.native_client,
            &self.build_network_policy(sandbox_id),
        )
        .await
    }

    async fn delete_network_policy(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        delete_network_policy_by_name(
            &self.namespace,
            &self.native_client,
            &Self::network_policy_name(sandbox_id),
        )
        .await
    }

    async fn prune_stale_network_policies(
        &self,
        live_limited_sandboxes: &BTreeSet<Uuid>,
    ) -> anyhow::Result<usize> {
        let client = native_k8s_client(&self.native_client).await?;
        let policies: Api<NetworkPolicy> = Api::namespaced(client, &self.namespace);
        let listed = policies
            .list(
                &ListParams::default()
                    .labels(K8S_EGRESS_POLICY_LABEL_SELECTOR)
                    .timeout(30),
            )
            .await?;
        let mut pruned = 0usize;
        for policy in listed.items {
            let name = policy.metadata.name.as_deref().unwrap_or("<unnamed>");
            let Some(policy_name) = stale_network_policy_name(&policy, live_limited_sandboxes)
            else {
                continue;
            };
            delete_network_policy_by_name(&self.namespace, &self.native_client, &policy_name)
                .await?;
            pruned += 1;
            debug!(network_policy = %policy_name, "Pruned stale sandbox NetworkPolicy");

            if name != policy_name {
                warn!(network_policy = name, pruned_name = %policy_name, "stale NetworkPolicy name changed while pruning");
            }
        }
        Ok(pruned)
    }
}

#[async_trait::async_trait]
impl EgressEnforcer for K8sEnvoyNetworkPreparer {
    async fn enforce(
        &self,
        sandbox_id: Uuid,
        _sandbox_token: &str,
        _networking: Option<&serde_json::Value>,
        _credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        self.apply_network_policy(sandbox_id).await
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.delete_network_policy(sandbox_id).await?;
        debug!(
            %sandbox_id,
            network_policy = %Self::network_policy_name(sandbox_id),
            "Deleted sandbox NetworkPolicy after teardown"
        );
        Ok(())
    }

    async fn recover(&self, pool: &PgPool) -> anyhow::Result<()> {
        let sandboxes = queries::list_live_sandboxes_for_recovery(pool).await?;
        let mut recovered = 0usize;
        let mut live_limited_sandboxes = BTreeSet::new();
        for sandbox in sandboxes {
            if recovery_networking(&sandbox).is_some() {
                self.apply_network_policy(sandbox.id).await?;
                live_limited_sandboxes.insert(sandbox.id);
                recovered += 1;
            }
        }
        let pruned = self
            .prune_stale_network_policies(&live_limited_sandboxes)
            .await?;
        info!(
            recovered_sandboxes = recovered,
            pruned_network_policies = pruned,
            "Recovered K8s Envoy sandbox NetworkPolicies"
        );
        Ok(())
    }

    fn kind_label(&self) -> &'static str {
        "k8s-envoy"
    }
}

// =====================================================================
async fn native_k8s_client(cell: &OnceCell<Result<Client, String>>) -> anyhow::Result<Client> {
    match cell
        .get_or_init(|| async {
            Client::try_default()
                .await
                .map_err(|error| error.to_string())
        })
        .await
    {
        Ok(client) => Ok(client.clone()),
        Err(error) => anyhow::bail!("Kubernetes API client unavailable: {error}"),
    }
}

fn network_policy_apply_params() -> PatchParams {
    PatchParams::apply(K8S_FIELD_MANAGER).force()
}

async fn apply_network_policy_manifest(
    namespace: &str,
    client_cell: &OnceCell<Result<Client, String>>,
    manifest: &Value,
) -> anyhow::Result<()> {
    let name = manifest
        .pointer("/metadata/name")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow::anyhow!("NetworkPolicy manifest missing metadata.name"))?;
    let client = native_k8s_client(client_cell).await?;
    let policies: Api<NetworkPolicy> = Api::namespaced(client, namespace);
    let params = network_policy_apply_params();
    let patch = Patch::Apply(manifest);
    policies.patch(name, &params, &patch).await?;
    Ok(())
}

async fn delete_network_policy_by_name(
    namespace: &str,
    client_cell: &OnceCell<Result<Client, String>>,
    name: &str,
) -> anyhow::Result<()> {
    let client = native_k8s_client(client_cell).await?;
    let policies: Api<NetworkPolicy> = Api::namespaced(client, namespace);
    match policies.delete(name, &DeleteParams::default()).await {
        Ok(_) => Ok(()),
        Err(kube::Error::Api(error)) if error.code == 404 => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn stale_network_policy_name(
    policy: &NetworkPolicy,
    live_limited_sandboxes: &BTreeSet<Uuid>,
) -> Option<String> {
    let labels = policy.metadata.labels.as_ref()?;
    let sandbox_id = labels.get("joysafeter.sandbox_id")?;
    let sandbox_id = Uuid::parse_str(sandbox_id).ok()?;
    if live_limited_sandboxes.contains(&sandbox_id) {
        return None;
    }
    policy.metadata.name.clone()
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

    /// Construct an `EnvoyManager` mirroring `docker.rs`'s non-grpc wiring.
    ///
    /// Requires a reachable Docker daemon (`Docker::connect_with_local_defaults`),
    /// so callers must gate the test with `#[ignore]`.
    fn test_envoy_manager(
        config: &JoySafeterConfig,
    ) -> std::sync::Arc<crate::sandbox::envoy::EnvoyManager> {
        use crate::sandbox::envoy::{EnvoyConfig, EnvoyManager};
        use crate::sandbox::lds_backend::{
            CdsBackend, DeniedCidr, FilesystemCds, FilesystemLds, LdsBackend,
        };

        let docker =
            std::sync::Arc::new(bollard::Docker::connect_with_local_defaults().expect("docker"));
        let lds: std::sync::Arc<dyn LdsBackend> = std::sync::Arc::new(FilesystemLds::new(
            docker.clone(),
            config.envoy_container_name.clone(),
        ));
        let cds: std::sync::Arc<dyn CdsBackend> = std::sync::Arc::new(FilesystemCds::new(
            docker.clone(),
            config.envoy_container_name.clone(),
        ));
        std::sync::Arc::new(EnvoyManager::new(
            docker,
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
                node_metadata: if config.envoy_xds_mode == "controller" {
                    Some(shared_docker_node_selector(config).metadata_value())
                } else {
                    None
                },
                denied_cidrs: config
                    .envoy_egress_denied_cidrs
                    .iter()
                    .map(|cidr| cidr.parse::<DeniedCidr>())
                    .collect::<anyhow::Result<Vec<_>>>()
                    .expect("denied cidrs"),
            },
            lds,
            cds,
        ))
    }

    /// requires Docker daemon; run with --include-ignored
    #[test]
    #[ignore = "requires Docker daemon; run with --include-ignored"]
    fn controller_mode_docker_uses_listener_free_preparer() {
        // In controller mode, the Docker preparer must not be the in-process
        // EnvoyEnforcer (which pushes LDS/CDS). We assert the builder returns a
        // preparer whose type name is the listener-free one.
        let mut config = JoySafeterConfig::from_env();
        config.egress_policy_authority_enabled = false; // isolate preparer selection from authority wrap
        config.envoy_enabled = true;
        config.envoy_xds_mode = "controller".to_string();
        let mgr = test_envoy_manager(&config); // helper above
        let preparer = build_enforcer(&config, "docker", Some(mgr))
            .expect("build_enforcer")
            .expect("preparer present");
        assert_eq!(preparer.kind_label(), "docker-controller");
    }

    /// Docker-free assertion of the preparer labels: `K8sEnvoyNetworkPreparer`
    /// constructs without a Docker daemon, so this runs in plain CI and locks in
    /// the `kind_label` contract the ignored builder test relies on.
    #[test]
    fn kind_labels_are_stable() {
        let preparer = K8sEnvoyNetworkPreparer::from_config(&enabled_envoy_config())
            .expect("from config")
            .expect("preparer enabled");
        assert_eq!(preparer.kind_label(), "k8s-envoy");
    }

    fn base_k8s_config() -> JoySafeterConfig {
        let mut config = JoySafeterConfig::from_env();
        config.k8s_namespace = "joysafeter-sandboxes".to_string();
        config.k8s_orchestrator_url = Some(
            "http://joysafeter-orchestrator.joysafeter-control.svc.cluster.local:9090".to_string(),
        );
        config.k8s_egress_management_enabled = true;
        config
    }

    fn enabled_envoy_config() -> JoySafeterConfig {
        let mut config = base_k8s_config();
        config.egress_policy_authority_enabled = true;
        config.egress_envoy_credential_url = Some(
            "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443".to_string(),
        );
        config.egress_envoy_forward_proxy_url = Some(
            "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8080".to_string(),
        );
        config
    }

    #[test]
    fn k8s_without_durable_authority_has_no_enforcer() {
        let mut config = base_k8s_config();
        config.egress_policy_authority_enabled = false;

        assert!(build_enforcer(&config, "k8s", None)
            .expect("build_enforcer")
            .is_none());
    }

    #[test]
    fn envoy_preparer_network_policy_allows_only_dns_orchestrator_and_envoy() {
        let sandbox_id =
            Uuid::parse_str("018ff000-0000-7000-8000-000000000024").expect("valid uuid");
        let preparer = K8sEnvoyNetworkPreparer::from_config(&enabled_envoy_config())
            .expect("from config")
            .expect("preparer enabled");
        let policy = preparer.build_network_policy(sandbox_id);
        let rendered = serde_json::to_string(&policy).expect("policy json");

        assert_eq!(
            policy
                .pointer("/spec/egress")
                .and_then(|value| value.as_array())
                .map(Vec::len),
            Some(4)
        );
        assert!(rendered.contains("joysafeter-orchestrator"));
        assert!(rendered.contains("joysafeter-egress-envoy"));
        assert!(rendered.contains("8443"));
        assert!(rendered.contains("8080"));
        assert!(!rendered.contains("0.0.0.0/0"));

        let service_names: Vec<&str> = policy
            .pointer("/spec/egress")
            .and_then(|value| value.as_array())
            .expect("egress rules")
            .iter()
            .skip(1)
            .map(|rule| {
                rule.pointer("/to/0/podSelector/matchLabels/app.kubernetes.io~1name")
                    .and_then(Value::as_str)
                    .expect("service selector")
            })
            .collect();
        assert_eq!(
            service_names,
            vec![
                "joysafeter-orchestrator",
                "joysafeter-egress-envoy",
                "joysafeter-egress-envoy"
            ]
        );
    }

    #[test]
    fn k8s_runtime_apply_uses_server_side_apply_without_last_applied_annotation() {
        let params = network_policy_apply_params();

        assert_eq!(params.field_manager.as_deref(), Some(K8S_FIELD_MANAGER));
        assert!(params.force);

        let policy = K8sEnvoyNetworkPreparer::from_config(&enabled_envoy_config())
            .expect("from config")
            .expect("preparer enabled")
            .build_network_policy(Uuid::now_v7());
        assert!(policy.pointer("/metadata/annotations").is_none());
    }

    #[test]
    fn k8s_enforcer_source_has_no_cli_runtime_path() {
        let source = include_str!("enforcer.rs");
        assert!(!source.contains(&["kube", "ctl"].concat()));
        assert!(!source.contains(concat!("Command", "::", "new")));
    }

    #[test]
    fn stale_network_policy_pruning_only_targets_non_live_labeled_policies() {
        use k8s_openapi::apimachinery::pkg::apis::meta::v1::ObjectMeta;
        use std::collections::BTreeMap;

        fn policy(name: &str, sandbox_id: Option<String>) -> NetworkPolicy {
            let labels = sandbox_id.map(|sandbox_id| {
                BTreeMap::from([("joysafeter.sandbox_id".to_string(), sandbox_id)])
            });
            NetworkPolicy {
                metadata: ObjectMeta {
                    name: Some(name.to_string()),
                    labels,
                    ..Default::default()
                },
                ..Default::default()
            }
        }

        let live = Uuid::parse_str("018ff000-0000-7000-8000-000000000026").unwrap();
        let dead = Uuid::parse_str("018ff000-0000-7000-8000-000000000027").unwrap();
        let live_limited_sandboxes = BTreeSet::from([live]);

        assert_eq!(
            stale_network_policy_name(
                &policy("joysafeter-egress-live", Some(live.to_string())),
                &live_limited_sandboxes,
            ),
            None,
            "live limited-networking policy must not be pruned"
        );
        assert_eq!(
            stale_network_policy_name(
                &policy("joysafeter-egress-dead", Some(dead.to_string())),
                &live_limited_sandboxes,
            ),
            Some("joysafeter-egress-dead".to_string()),
            "non-live labeled policy is platform-owned stale state"
        );
        assert_eq!(
            stale_network_policy_name(&policy("missing-label", None), &live_limited_sandboxes),
            None,
            "policies without a sandbox label are left untouched"
        );
        assert_eq!(
            stale_network_policy_name(
                &policy("bad-label", Some("not-a-uuid".to_string())),
                &live_limited_sandboxes,
            ),
            None,
            "invalid sandbox labels are not deleted blindly"
        );
    }

    #[test]
    fn k8s_service_target_parses_in_cluster_service_dns() {
        let target = k8s_service_target_from_url(
            "https://joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local:8443",
            "joysafeter-sandboxes",
        )
        .expect("service target");

        assert_eq!(
            target,
            K8sServiceTarget {
                service_name: "joysafeter-egress-envoy".to_string(),
                namespace: "joysafeter-egress".to_string(),
                port: 8443,
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
}
