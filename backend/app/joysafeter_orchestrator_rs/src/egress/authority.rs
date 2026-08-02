//! Durable desired-state authority for the unified Envoy egress plane.
//!
//! The authority is intentionally provider-neutral: it persists immutable,
//! ref-only policy generations and waits for the Go xDS controller to record a
//! durable apply decision. It never forwards traffic and never resolves secret
//! material.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use sqlx::postgres::PgListener;
use sqlx::{PgPool, Postgres, Transaction};
use tokio::sync::broadcast;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;
use tracing::warn;
use uuid::Uuid;

use crate::egress::policy::{
    credential_consumer_route_id, CredentialRef, EgressCredentialRoute, EgressExposure, EgressKind,
    InjectScheme, SandboxCredentials,
};

const POLICY_SCHEMA_VERSION: i32 = 1;
const GENERATION_EVENT_TYPE: &str = "egress.group_generation.desired";
const APPLY_NOTIFICATION_CHANNEL: &str = "joysafeter_egress_apply_status";
const GROUP_KEY_SCHEMA: &str = "v1";
const ALL_HTTP_METHODS: [&str; 7] = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"];

#[derive(Debug, Clone)]
pub struct AuthorityConfig {
    pub selector: NodeSelector,
    pub denied_cidrs: Vec<String>,
    pub apply_timeout: Duration,
    pub poll_interval: Duration,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct NodeSelector {
    pub deployment_id: String,
    pub environment: String,
    pub region: String,
    pub provider: String,
    pub shard_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub host_id: Option<String>,
    pub envoy_version: String,
    pub config_schema_version: String,
}

impl NodeSelector {
    pub fn normalize(mut self) -> anyhow::Result<Self> {
        self.deployment_id = normalize_group_value(&self.deployment_id);
        self.environment = normalize_group_value(&self.environment);
        self.region = normalize_group_value(&self.region);
        self.provider = normalize_group_value(&self.provider);
        self.shard_id = normalize_group_value(&self.shard_id);
        self.host_id = self
            .host_id
            .map(|value| normalize_group_value(&value))
            .filter(|value| !value.is_empty());
        self.envoy_version = normalize_group_value(&self.envoy_version);
        self.config_schema_version = normalize_group_value(&self.config_schema_version);

        let required = [
            ("deployment_id", self.deployment_id.as_str()),
            ("environment", self.environment.as_str()),
            ("region", self.region.as_str()),
            ("provider", self.provider.as_str()),
            ("shard_id", self.shard_id.as_str()),
            ("envoy_version", self.envoy_version.as_str()),
            ("config_schema_version", self.config_schema_version.as_str()),
        ];
        for (name, value) in required {
            anyhow::ensure!(!value.is_empty(), "egress node selector {name} is required");
            anyhow::ensure!(
                !value.contains(['\0', '\n', '\r']),
                "egress node selector {name} contains control characters"
            );
        }
        anyhow::ensure!(
            matches!(self.provider.as_str(), "docker" | "k8s" | "kubernetes"),
            "unsupported egress node selector provider {}",
            self.provider
        );
        if self.provider == "docker" {
            anyhow::ensure!(
                self.host_id.is_some(),
                "Docker egress selector requires host_id"
            );
        }
        Ok(self)
    }

    pub fn group_key(&self) -> anyhow::Result<String> {
        let selector = self.clone().normalize()?;
        let canonical = [
            selector.deployment_id,
            selector.environment,
            selector.region,
            selector.provider,
            selector.shard_id,
            selector.host_id.unwrap_or_default(),
            selector.envoy_version,
            selector.config_schema_version,
        ]
        .join("\0");
        let digest = Sha256::digest(canonical.as_bytes());
        Ok(format!(
            "{GROUP_KEY_SCHEMA}:{}",
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest)
        ))
    }

    /// structpb-compatible `node.metadata` for the Envoy bootstrap. The keys and
    /// their values MUST match the Go controller's `group.Hasher` required
    /// metadata exactly so the connecting Envoy hashes into the same group this
    /// selector's [`group_key`] produces; otherwise the controller serves an
    /// empty snapshot and the apply never ACKs. `host_id` is emitted only when
    /// present (required by the Go hasher when `provider == "docker"`).
    ///
    /// [`group_key`]: NodeSelector::group_key
    pub fn metadata_value(&self) -> Value {
        let mut map = serde_json::Map::new();
        map.insert("deployment_id".into(), self.deployment_id.clone().into());
        map.insert("environment".into(), self.environment.clone().into());
        map.insert("region".into(), self.region.clone().into());
        map.insert("provider".into(), self.provider.clone().into());
        map.insert("shard_id".into(), self.shard_id.clone().into());
        if let Some(host_id) = &self.host_id {
            map.insert("host_id".into(), host_id.clone().into());
        }
        map.insert("envoy_version".into(), self.envoy_version.clone().into());
        map.insert(
            "config_schema_version".into(),
            self.config_schema_version.clone().into(),
        );
        Value::Object(map)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesiredSandboxPolicy {
    pub sandbox_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
    pub mode: String,
    pub credential_routes: Vec<DesiredCredentialRoute>,
    pub allowed_public_hosts: Vec<String>,
    pub denied_cidrs: Vec<String>,
}

impl DesiredSandboxPolicy {
    pub fn from_inputs(
        sandbox_id: Uuid,
        networking: Option<&Value>,
        credentials: &SandboxCredentials,
        denied_cidrs: &[String],
    ) -> Self {
        let mode = networking
            .and_then(|value| value.get("type"))
            .and_then(Value::as_str)
            .filter(|value| value.eq_ignore_ascii_case("limited"))
            .map(|_| "limited")
            .unwrap_or("unrestricted")
            .to_string();
        let allowed_public_hosts = sorted_strings(
            networking
                .and_then(|value| value.get("allowed_hosts"))
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(normalize_host_value),
        );
        let mut credential_routes = credentials
            .routes
            .iter()
            .map(DesiredCredentialRoute::from_route)
            .collect::<Vec<_>>();
        credential_routes.sort_by(|left, right| left.route_id.cmp(&right.route_id));

        Self {
            sandbox_id: sandbox_id.to_string(),
            project_id: None,
            mode,
            credential_routes,
            allowed_public_hosts,
            denied_cidrs: sorted_strings(denied_cidrs.iter().map(|value| value.trim().to_string())),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesiredCredentialRoute {
    pub route_id: String,
    #[serde(default)]
    pub consumer_route_id: String,
    pub kind: String,
    pub match_authority: String,
    pub match_path: DesiredPathMatch,
    pub methods: Vec<String>,
    pub upstream: DesiredUpstream,
    pub credential_ref: DesiredCredentialRef,
    pub inject_header: String,
    pub inject_scheme: DesiredInjectScheme,
    pub remove_headers: Vec<String>,
    pub timeout_profile: String,
    pub websocket: bool,
}

impl DesiredCredentialRoute {
    fn from_route(route: &EgressCredentialRoute) -> Self {
        let kind = kind_name(route.kind).to_string();
        let inject_header = route.inject_header.trim().to_ascii_lowercase();
        let remove_headers = sorted_strings(
            route
                .remove_headers
                .iter()
                .map(|value| value.trim().to_ascii_lowercase())
                .chain(std::iter::once(inject_header.clone())),
        );
        Self {
            route_id: route.id.trim().to_string(),
            consumer_route_id: credential_consumer_route_id(route).to_string(),
            kind: kind.clone(),
            match_authority: normalize_host_value(&route.match_host),
            match_path: DesiredPathMatch {
                kind: if route.exact_path { "exact" } else { "prefix" }.to_string(),
                value: normalize_path(&route.match_prefix),
            },
            methods: ALL_HTTP_METHODS
                .iter()
                .map(|value| (*value).to_string())
                .collect(),
            upstream: DesiredUpstream {
                scheme: if route.upstream_tls { "https" } else { "http" }.to_string(),
                host: normalize_host_value(&route.upstream_host),
                port: route.upstream_port,
                base_path: normalize_path(&route.upstream_prefix),
                protocol: "auto".to_string(),
            },
            credential_ref: DesiredCredentialRef::from_ref(&route.credential_ref),
            inject_header,
            inject_scheme: DesiredInjectScheme::from_scheme(&route.inject_scheme),
            remove_headers,
            timeout_profile: timeout_profile(route.kind).to_string(),
            websocket: false,
        }
    }

    pub(crate) fn to_runtime_route(&self) -> anyhow::Result<EgressCredentialRoute> {
        let kind = match self.kind.as_str() {
            "llm" => EgressKind::Llm,
            "mcp" => EgressKind::Mcp,
            "git" => EgressKind::Git,
            "external" => EgressKind::External,
            other => anyhow::bail!("unsupported durable credential route kind {other}"),
        };
        Ok(EgressCredentialRoute {
            id: self.route_id.clone(),
            kind,
            exposure: EgressExposure::Placeholder,
            match_host: self.match_authority.clone(),
            match_prefix: self.match_path.value.clone(),
            exact_path: self.match_path.kind == "exact",
            upstream_host: self.upstream.host.clone(),
            upstream_port: self.upstream.port,
            upstream_prefix: self.upstream.base_path.clone(),
            upstream_tls: self.upstream.scheme == "https",
            cluster_name: String::new(),
            credential_ref: self.credential_ref.to_runtime_ref()?,
            inject_header: self.inject_header.clone(),
            inject_scheme: self.inject_scheme.to_runtime_scheme(),
            remove_headers: self.remove_headers.clone(),
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesiredPathMatch {
    pub kind: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesiredUpstream {
    pub scheme: String,
    pub host: String,
    pub port: u16,
    pub base_path: String,
    pub protocol: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
pub enum DesiredCredentialRef {
    Llm {
        secret_name: String,
        secret_key: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        project_id: Option<String>,
    },
    Mcp {
        vault_id: String,
        mcp_server_url: String,
    },
    Git {
        session_id: String,
        mount_name: String,
    },
    External {
        secret_name: String,
        secret_key: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        project_id: Option<String>,
    },
}

impl DesiredCredentialRef {
    fn from_ref(reference: &CredentialRef) -> Self {
        match reference {
            CredentialRef::Llm {
                secret_name,
                secret_key,
                project_id,
            } => Self::Llm {
                secret_name: secret_name.clone(),
                secret_key: secret_key.clone(),
                project_id: project_id.clone(),
            },
            CredentialRef::Mcp {
                vault_id,
                mcp_server_url,
            } => Self::Mcp {
                vault_id: vault_id.to_string(),
                mcp_server_url: mcp_server_url.clone(),
            },
            CredentialRef::Git {
                session_id,
                mount_name,
            } => Self::Git {
                session_id: session_id.to_string(),
                mount_name: mount_name.clone(),
            },
            CredentialRef::External {
                secret_name,
                secret_key,
                project_id,
            } => Self::External {
                secret_name: secret_name.clone(),
                secret_key: secret_key.clone(),
                project_id: project_id.clone(),
            },
        }
    }

    fn to_runtime_ref(&self) -> anyhow::Result<CredentialRef> {
        Ok(match self {
            Self::Llm {
                secret_name,
                secret_key,
                project_id,
            } => CredentialRef::Llm {
                secret_name: secret_name.clone(),
                secret_key: secret_key.clone(),
                project_id: project_id.clone(),
            },
            Self::Mcp {
                vault_id,
                mcp_server_url,
            } => CredentialRef::Mcp {
                vault_id: Uuid::parse_str(vault_id)?,
                mcp_server_url: mcp_server_url.clone(),
            },
            Self::Git {
                session_id,
                mount_name,
            } => CredentialRef::Git {
                session_id: Uuid::parse_str(session_id)?,
                mount_name: mount_name.clone(),
            },
            Self::External {
                secret_name,
                secret_key,
                project_id,
            } => CredentialRef::External {
                secret_name: secret_name.clone(),
                secret_key: secret_key.clone(),
                project_id: project_id.clone(),
            },
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
pub enum DesiredInjectScheme {
    Bearer,
    Basic { username: String },
    Raw,
}

impl DesiredInjectScheme {
    fn from_scheme(scheme: &InjectScheme) -> Self {
        match scheme {
            InjectScheme::Bearer => Self::Bearer,
            InjectScheme::Basic { username } => Self::Basic {
                username: username.clone(),
            },
            InjectScheme::Raw => Self::Raw,
        }
    }

    fn to_runtime_scheme(&self) -> InjectScheme {
        match self {
            Self::Bearer => InjectScheme::Bearer,
            Self::Basic { username } => InjectScheme::Basic {
                username: username.clone(),
            },
            Self::Raw => InjectScheme::Raw,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ApplyHandle {
    group_key: String,
    initial_generation: i64,
    expected: ExpectedPolicyState,
}

#[derive(Debug, Clone)]
enum ExpectedPolicyState {
    Present(DesiredSandboxPolicy),
    Absent(Uuid),
}

#[derive(Debug, Clone)]
struct ApplySignal {
    group_key: String,
}

pub struct PostgresEgressPolicyAuthority {
    pool: PgPool,
    selector: NodeSelector,
    group_key: String,
    denied_cidrs: Vec<String>,
    apply_timeout: Duration,
    poll_interval: Duration,
    apply_signals: broadcast::Sender<ApplySignal>,
    shutdown: CancellationToken,
}

impl PostgresEgressPolicyAuthority {
    pub fn new(pool: PgPool, config: AuthorityConfig) -> anyhow::Result<Arc<Self>> {
        let selector = config.selector.normalize()?;
        let group_key = selector.group_key()?;
        anyhow::ensure!(
            !config.apply_timeout.is_zero(),
            "egress apply timeout must be greater than zero"
        );
        anyhow::ensure!(
            !config.poll_interval.is_zero(),
            "egress apply poll interval must be greater than zero"
        );
        let (apply_signals, _) = broadcast::channel(256);
        let authority = Arc::new(Self {
            pool: pool.clone(),
            selector,
            group_key,
            denied_cidrs: config.denied_cidrs,
            apply_timeout: config.apply_timeout,
            poll_interval: config.poll_interval,
            apply_signals: apply_signals.clone(),
            shutdown: CancellationToken::new(),
        });
        spawn_apply_listener(pool, apply_signals, authority.shutdown.clone());
        Ok(authority)
    }

    pub fn group_key(&self) -> &str {
        &self.group_key
    }

    pub async fn declare(
        &self,
        sandbox_id: Uuid,
        networking: Option<&Value>,
        credentials: &SandboxCredentials,
    ) -> anyhow::Result<ApplyHandle> {
        let policy = DesiredSandboxPolicy::from_inputs(
            sandbox_id,
            networking,
            credentials,
            &self.denied_cidrs,
        );
        let generation = self
            .write_generation(GenerationMutation::Upsert(policy.clone()))
            .await?
            .context("egress policy declaration unexpectedly produced no generation")?;
        Ok(ApplyHandle {
            group_key: self.group_key.clone(),
            initial_generation: generation,
            expected: ExpectedPolicyState::Present(policy),
        })
    }

    pub async fn revoke(&self, sandbox_id: Uuid) -> anyhow::Result<Option<ApplyHandle>> {
        let generation = self
            .write_generation(GenerationMutation::Remove(sandbox_id))
            .await?;
        Ok(generation.map(|generation| ApplyHandle {
            group_key: self.group_key.clone(),
            initial_generation: generation,
            expected: ExpectedPolicyState::Absent(sandbox_id),
        }))
    }

    pub async fn wait_applied(&self, handle: &ApplyHandle) -> anyhow::Result<i64> {
        anyhow::ensure!(
            handle.group_key == self.group_key,
            "egress apply handle belongs to a different node group"
        );
        let deadline = Instant::now() + self.apply_timeout;
        let mut signals = self.apply_signals.subscribe();

        loop {
            let observed = self.observe_current(&handle.expected).await?;
            match observed {
                ObservedApply::Applied(generation) => return Ok(generation),
                ObservedApply::Failed {
                    generation,
                    reason_code,
                    error_summary,
                } => {
                    anyhow::bail!(
                        "EGRESS_POLICY_APPLY_FAILED: group={} generation={} reason={} error={}",
                        self.group_key,
                        generation,
                        reason_code.unwrap_or_else(|| "unknown".to_string()),
                        error_summary.unwrap_or_else(|| "unspecified".to_string())
                    );
                }
                ObservedApply::Superseded => {
                    anyhow::bail!(
                        "EGRESS_POLICY_SUPERSEDED: group={} initial_generation={}",
                        self.group_key,
                        handle.initial_generation
                    );
                }
                ObservedApply::Pending => {}
            }

            let now = Instant::now();
            if now >= deadline {
                anyhow::bail!(
                    "EGRESS_POLICY_APPLY_TIMEOUT: group={} initial_generation={} timeout_ms={}",
                    self.group_key,
                    handle.initial_generation,
                    self.apply_timeout.as_millis()
                );
            }
            let sleep_for = self
                .poll_interval
                .min(deadline.saturating_duration_since(now));
            tokio::select! {
                _ = tokio::time::sleep(sleep_for) => {}
                signal = signals.recv() => {
                    if let Ok(signal) = signal {
                        if signal.group_key != self.group_key {
                            continue;
                        }
                    }
                }
            }
        }
    }

    async fn write_generation(&self, mutation: GenerationMutation) -> anyhow::Result<Option<i64>> {
        let mut transaction = self.pool.begin().await?;
        lock_group(&mut transaction, &self.group_key).await?;

        let current = sqlx::query_as::<_, (i64, Value, String)>(
            r#"
            SELECT generation, desired_policies, content_sha256
            FROM joysafeter_egress_group_generations
            WHERE group_key = $1 AND state = 'desired'
            ORDER BY generation DESC
            LIMIT 1
            "#,
        )
        .bind(&self.group_key)
        .fetch_optional(&mut *transaction)
        .await?;

        let mut policies = match &current {
            Some((_, raw, _)) => serde_json::from_value::<Vec<DesiredSandboxPolicy>>(raw.clone())
                .context("decode current egress desired policies")?,
            None => Vec::new(),
        };
        let changed = mutation.apply(&mut policies);
        // Self-heal: drop policies for sandboxes the database confirms are no
        // longer live. Non-explicit teardown paths (idle sweep, stopped-TTL,
        // task-failure cleanup) can mark a sandbox dead without routing through
        // the egress teardown that issues a Remove, which would otherwise leave
        // the dead sandbox's Envoy listener + credential route in the durable
        // desired-state (and Envoy) forever. Only sandboxes PRESENT in the DB
        // with a terminal status are pruned, so a just-created sandbox whose row
        // is not yet visible is never dropped.
        let pruned = prune_dead_sandboxes(&mut policies, &mut transaction).await?;
        if !changed && !pruned {
            transaction.commit().await?;
            return Ok(current.map(|(generation, _, _)| generation));
        }
        policies.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));

        let canonical = serde_json::to_vec(&policies)?;
        let content_sha256 = hex::encode(Sha256::digest(&canonical));
        if let Some((generation, _, current_hash)) = &current {
            if current_hash == &content_sha256 {
                transaction.commit().await?;
                return Ok(Some(*generation));
            }
        }

        let generation = sqlx::query_scalar::<_, i64>(
            r#"
            SELECT COALESCE(MAX(generation), 0) + 1
            FROM joysafeter_egress_group_generations
            WHERE group_key = $1
            "#,
        )
        .bind(&self.group_key)
        .fetch_one(&mut *transaction)
        .await?;

        sqlx::query(
            r#"
            UPDATE joysafeter_egress_group_generations
            SET state = 'superseded', superseded_at = NOW(), updated_at = NOW()
            WHERE group_key = $1 AND state = 'desired'
            "#,
        )
        .bind(&self.group_key)
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            r#"
            UPDATE joysafeter_egress_apply_status
            SET state = 'superseded', updated_at = NOW()
            WHERE group_key = $1 AND state IN ('pending', 'published')
            "#,
        )
        .bind(&self.group_key)
        .execute(&mut *transaction)
        .await?;

        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_group_generations (
                id, group_key, generation, node_selector, policy_schema_version,
                desired_policies, content_sha256, state
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'desired')
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&self.group_key)
        .bind(generation)
        .bind(serde_json::to_value(&self.selector)?)
        .bind(POLICY_SCHEMA_VERSION)
        .bind(serde_json::to_value(&policies)?)
        .bind(&content_sha256)
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_outbox_events (
                id, group_key, generation, event_type
            ) VALUES ($1, $2, $3, $4)
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&self.group_key)
        .bind(generation)
        .bind(GENERATION_EVENT_TYPE)
        .execute(&mut *transaction)
        .await?;

        transaction.commit().await?;
        Ok(Some(generation))
    }

    async fn observe_current(
        &self,
        expected: &ExpectedPolicyState,
    ) -> anyhow::Result<ObservedApply> {
        let row =
            sqlx::query_as::<_, (i64, Value, Option<String>, Option<String>, Option<String>)>(
                r#"
            SELECT g.generation, g.desired_policies, a.state, a.reason_code, a.error_summary
            FROM joysafeter_egress_group_generations AS g
            LEFT JOIN joysafeter_egress_apply_status AS a
              ON a.group_key = g.group_key AND a.generation = g.generation
            WHERE g.group_key = $1 AND g.state = 'desired'
            ORDER BY g.generation DESC
            LIMIT 1
            "#,
            )
            .bind(&self.group_key)
            .fetch_optional(&self.pool)
            .await?;
        let Some((generation, raw, state, reason_code, error_summary)) = row else {
            return Ok(ObservedApply::Superseded);
        };
        let policies = serde_json::from_value::<Vec<DesiredSandboxPolicy>>(raw)
            .context("decode observed egress desired policies")?;
        if !expected.matches(&policies) {
            return Ok(ObservedApply::Superseded);
        }
        Ok(match state.as_deref() {
            Some("applied") => ObservedApply::Applied(generation),
            Some("failed") => ObservedApply::Failed {
                generation,
                reason_code,
                error_summary,
            },
            Some("superseded") => ObservedApply::Pending,
            _ => ObservedApply::Pending,
        })
    }
}

impl Drop for PostgresEgressPolicyAuthority {
    fn drop(&mut self) {
        self.shutdown.cancel();
    }
}

#[derive(Debug)]
enum GenerationMutation {
    Upsert(DesiredSandboxPolicy),
    Remove(Uuid),
}

/// Remove desired-state policies whose sandbox the database confirms is no
/// longer live (terminal status or `destroyed_at` set), matching ext_authz's
/// live-status gate. Only sandboxes PRESENT in the DB with a dead status are
/// pruned — an absent row (e.g. a just-created sandbox not yet visible in this
/// transaction) is left untouched, so creation is never disrupted. Returns
/// whether any policy was pruned.
async fn prune_dead_sandboxes(
    policies: &mut Vec<DesiredSandboxPolicy>,
    transaction: &mut Transaction<'_, Postgres>,
) -> anyhow::Result<bool> {
    if policies.is_empty() {
        return Ok(false);
    }
    let ids: Vec<Uuid> = policies
        .iter()
        .filter_map(|policy| Uuid::parse_str(&policy.sandbox_id).ok())
        .collect();
    if ids.is_empty() {
        return Ok(false);
    }
    let dead: Vec<Uuid> = sqlx::query_scalar::<_, Uuid>(
        r#"
        SELECT id
        FROM joysafeter_sandboxes
        WHERE id = ANY($1)
          AND (
              destroyed_at IS NOT NULL
              OR status NOT IN ('creating', 'provisioning', 'idle', 'running')
          )
        "#,
    )
    .bind(&ids)
    .fetch_all(&mut **transaction)
    .await?;
    if dead.is_empty() {
        return Ok(false);
    }
    let dead: BTreeSet<String> = dead.iter().map(Uuid::to_string).collect();
    let before = policies.len();
    policies.retain(|policy| !dead.contains(&policy.sandbox_id));
    Ok(policies.len() != before)
}

impl GenerationMutation {
    fn apply(self, policies: &mut Vec<DesiredSandboxPolicy>) -> bool {
        match self {
            Self::Upsert(policy) => {
                if let Some(existing) = policies
                    .iter_mut()
                    .find(|existing| existing.sandbox_id == policy.sandbox_id)
                {
                    if existing == &policy {
                        return false;
                    }
                    *existing = policy;
                    true
                } else {
                    policies.push(policy);
                    true
                }
            }
            Self::Remove(sandbox_id) => {
                let before = policies.len();
                policies.retain(|policy| policy.sandbox_id != sandbox_id.to_string());
                policies.len() != before
            }
        }
    }
}

impl ExpectedPolicyState {
    fn matches(&self, policies: &[DesiredSandboxPolicy]) -> bool {
        match self {
            Self::Present(expected) => policies
                .iter()
                .any(|policy| policy.sandbox_id == expected.sandbox_id && policy == expected),
            Self::Absent(sandbox_id) => policies
                .iter()
                .all(|policy| policy.sandbox_id != sandbox_id.to_string()),
        }
    }
}

#[derive(Debug)]
enum ObservedApply {
    Pending,
    Applied(i64),
    Failed {
        generation: i64,
        reason_code: Option<String>,
        error_summary: Option<String>,
    },
    Superseded,
}

async fn lock_group(
    transaction: &mut Transaction<'_, Postgres>,
    group_key: &str,
) -> anyhow::Result<()> {
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))")
        .bind(group_key)
        .execute(&mut **transaction)
        .await?;
    Ok(())
}

fn spawn_apply_listener(
    pool: PgPool,
    signals: broadcast::Sender<ApplySignal>,
    shutdown: CancellationToken,
) {
    tokio::spawn(async move {
        let mut reconnect_delay = Duration::from_millis(100);
        loop {
            if shutdown.is_cancelled() {
                return;
            }
            match PgListener::connect_with(&pool).await {
                Ok(mut listener) => {
                    if let Err(error) = listener.listen(APPLY_NOTIFICATION_CHANNEL).await {
                        warn!(%error, "failed to subscribe to egress apply notifications");
                    } else {
                        reconnect_delay = Duration::from_millis(100);
                        loop {
                            tokio::select! {
                                _ = shutdown.cancelled() => return,
                                notification = listener.recv() => match notification {
                                    Ok(notification) => {
                                        if let Some((group_key, _)) = notification.payload().rsplit_once(':') {
                                            let _ = signals.send(ApplySignal { group_key: group_key.to_string() });
                                        }
                                    }
                                    Err(error) => {
                                        warn!(%error, "egress apply notification listener disconnected");
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
                Err(error) => warn!(%error, "failed to connect egress apply notification listener"),
            }
            tokio::select! {
                _ = shutdown.cancelled() => return,
                _ = tokio::time::sleep(reconnect_delay) => {}
            }
            reconnect_delay = (reconnect_delay * 2).min(Duration::from_secs(5));
        }
    });
}

fn kind_name(kind: EgressKind) -> &'static str {
    match kind {
        EgressKind::Llm => "llm",
        EgressKind::Mcp => "mcp",
        EgressKind::Git => "git",
        EgressKind::External => "external",
    }
}

fn timeout_profile(kind: EgressKind) -> &'static str {
    match kind {
        EgressKind::Llm | EgressKind::Mcp => "streaming",
        EgressKind::Git => "long_running",
        EgressKind::External => "default",
    }
}

fn normalize_group_value(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn normalize_host_value(value: &str) -> String {
    value.trim().trim_end_matches('.').to_ascii_lowercase()
}

fn normalize_path(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        "/".to_string()
    } else if trimmed.starts_with('/') {
        trimmed.to_string()
    } else {
        format!("/{trimmed}")
    }
}

fn sorted_strings(values: impl IntoIterator<Item = String>) -> Vec<String> {
    values
        .into_iter()
        .filter(|value| !value.is_empty())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::egress::policy::{EgressExposure, LLM_EGRESS_HOST};
    use sqlx::postgres::PgPoolOptions;

    fn selector() -> NodeSelector {
        NodeSelector {
            deployment_id: "Prod-A".to_string(),
            environment: "Production".to_string(),
            region: "cn-east-1".to_string(),
            provider: "k8s".to_string(),
            shard_id: "17".to_string(),
            host_id: None,
            envoy_version: "1.39.0".to_string(),
            config_schema_version: "1".to_string(),
        }
    }

    /// The bootstrap `node.metadata` must carry exactly the fields the group
    /// key is derived from, so an Envoy advertising that metadata hashes into
    /// the group the authority wrote generations under. Reconstructing a
    /// selector from `metadata_value()` must reproduce the same `group_key`.
    #[test]
    fn metadata_value_round_trips_to_same_group_key() {
        let docker = NodeSelector {
            provider: "docker".to_string(),
            host_id: Some("docker-local".to_string()),
            ..selector()
        };
        let meta = docker.metadata_value();
        let s = |k: &str| meta[k].as_str().unwrap().to_string();
        let reconstructed = NodeSelector {
            deployment_id: s("deployment_id"),
            environment: s("environment"),
            region: s("region"),
            provider: s("provider"),
            shard_id: s("shard_id"),
            host_id: meta
                .get("host_id")
                .and_then(|v| v.as_str())
                .map(String::from),
            envoy_version: s("envoy_version"),
            config_schema_version: s("config_schema_version"),
        };
        assert_eq!(
            reconstructed.group_key().unwrap(),
            docker.group_key().unwrap(),
            "node.metadata must reconstruct the authority's group key"
        );
    }

    fn database_url() -> Option<String> {
        std::env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| std::env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    fn test_credentials(route_id: &str) -> SandboxCredentials {
        SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: route_id.to_string(),
                kind: EgressKind::Llm,
                exposure: EgressExposure::Placeholder,
                match_host: LLM_EGRESS_HOST.to_string(),
                match_prefix: "/v1".to_string(),
                exact_path: false,
                upstream_host: "api.example.com".to_string(),
                upstream_port: 443,
                upstream_prefix: "/v1".to_string(),
                upstream_tls: true,
                cluster_name: String::new(),
                credential_ref: CredentialRef::Llm {
                    secret_name: format!("secret-{route_id}"),
                    secret_key: "api_key".to_string(),
                    project_id: None,
                },
                inject_header: "authorization".to_string(),
                inject_scheme: InjectScheme::Bearer,
                remove_headers: Vec::new(),
            }],
        }
    }

    async fn cleanup_group(pool: &PgPool, group_key: &str) {
        let _ = sqlx::query("DELETE FROM joysafeter_egress_group_generations WHERE group_key = $1")
            .bind(group_key)
            .execute(pool)
            .await;
    }

    #[test]
    fn group_key_matches_go_contract() {
        assert_eq!(
            selector().group_key().unwrap(),
            "v1:9YMnDnoG41rXIUgdMrKfL8IqwNSJU9j8EZTNkQ1fQv8"
        );
    }

    #[test]
    fn desired_policy_is_ref_only_and_deterministic() {
        let sandbox_id = Uuid::parse_str("11111111-1111-4111-8111-111111111111").unwrap();
        let credentials = SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: "llm:primary".to_string(),
                kind: EgressKind::Llm,
                exposure: EgressExposure::Placeholder,
                match_host: LLM_EGRESS_HOST.to_string(),
                match_prefix: "/v1".to_string(),
                exact_path: false,
                upstream_host: "API.Example.com".to_string(),
                upstream_port: 443,
                upstream_prefix: "/v1".to_string(),
                upstream_tls: true,
                cluster_name: String::new(),
                credential_ref: CredentialRef::Llm {
                    secret_name: "managed-key".to_string(),
                    secret_key: "api_key".to_string(),
                    project_id: Some("22222222-2222-4222-8222-222222222222".to_string()),
                },
                inject_header: "Authorization".to_string(),
                inject_scheme: InjectScheme::Bearer,
                remove_headers: vec!["X-Api-Key".to_string()],
            }],
        };
        let policy = DesiredSandboxPolicy::from_inputs(
            sandbox_id,
            Some(&serde_json::json!({
                "type": "limited",
                "allowed_hosts": ["Downloads.Example.com", "downloads.example.com"]
            })),
            &credentials,
            &["10.0.0.0/8".to_string()],
        );
        let encoded = serde_json::to_string(&policy).unwrap();
        assert!(!encoded.contains("actual-secret-value"));
        assert!(encoded.contains("managed-key"));
        assert_eq!(policy.allowed_public_hosts, vec!["downloads.example.com"]);
        assert_eq!(policy.credential_routes[0].consumer_route_id, "llm:primary");
        assert_eq!(policy.credential_routes[0].inject_header, "authorization");
        assert_eq!(
            policy.credential_routes[0].remove_headers,
            vec!["authorization", "x-api-key"]
        );
    }

    #[test]
    fn external_allowed_path_routes_share_consumer_route_id() {
        let sandbox_id = Uuid::now_v7();
        let mut credentials = test_credentials("external-direct:crm:0");
        let route = &mut credentials.routes[0];
        route.kind = EgressKind::External;
        route.match_host = "crm.example.com".to_string();
        route.match_prefix = "/api/customers/current".to_string();
        route.upstream_host = "crm.example.com".to_string();
        route.upstream_prefix = route.match_prefix.clone();
        route.exact_path = true;
        route.credential_ref = CredentialRef::External {
            secret_name: "crm-secret".to_string(),
            secret_key: "ACCESS_TOKEN".to_string(),
            project_id: None,
        };

        let policy = DesiredSandboxPolicy::from_inputs(sandbox_id, None, &credentials, &[]);

        assert_eq!(
            policy.credential_routes[0].route_id,
            "external-direct:crm:0"
        );
        assert_eq!(
            policy.credential_routes[0].consumer_route_id,
            "external-direct:crm"
        );
    }

    #[tokio::test]
    async fn postgres_writer_serializes_generations_and_gates_apply_state() {
        let Some(url) = database_url() else {
            eprintln!("skipping egress authority PostgreSQL test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(8)
            .connect(&url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let unique = Uuid::now_v7().simple().to_string();
        let authority = PostgresEgressPolicyAuthority::new(
            pool.clone(),
            AuthorityConfig {
                selector: NodeSelector {
                    deployment_id: format!("authority-test-{unique}"),
                    environment: "test".to_string(),
                    region: "local".to_string(),
                    provider: "k8s".to_string(),
                    shard_id: "0".to_string(),
                    host_id: None,
                    envoy_version: "1.39.0".to_string(),
                    config_schema_version: "1".to_string(),
                },
                denied_cidrs: vec!["10.0.0.0/8".to_string()],
                apply_timeout: Duration::from_millis(800),
                poll_interval: Duration::from_millis(25),
            },
        )
        .unwrap();
        cleanup_group(&pool, authority.group_key()).await;

        let first_sandbox = Uuid::now_v7();
        let second_sandbox = Uuid::now_v7();
        let first_credentials = test_credentials("llm:first");
        let second_credentials = test_credentials("llm:second");
        let (first, second) = tokio::join!(
            authority.declare(first_sandbox, None, &first_credentials),
            authority.declare(second_sandbox, None, &second_credentials),
        );
        let first = first.unwrap();
        let second = second.unwrap();

        let generations: Vec<(i64, String, Value)> = sqlx::query_as(
            r#"
            SELECT generation, state, desired_policies
            FROM joysafeter_egress_group_generations
            WHERE group_key = $1
            ORDER BY generation
            "#,
        )
        .bind(authority.group_key())
        .fetch_all(&pool)
        .await
        .unwrap();
        assert_eq!(generations.len(), 2);
        assert_eq!(generations[0].1, "superseded");
        assert_eq!(generations[1].1, "desired");
        let latest = serde_json::from_value::<Vec<DesiredSandboxPolicy>>(
            generations.last().unwrap().2.clone(),
        )
        .unwrap();
        assert_eq!(latest.len(), 2);
        assert!(latest
            .iter()
            .any(|policy| policy.sandbox_id == first_sandbox.to_string()));
        assert!(latest
            .iter()
            .any(|policy| policy.sandbox_id == second_sandbox.to_string()));

        let outbox_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_egress_outbox_events WHERE group_key = $1",
        )
        .bind(authority.group_key())
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(outbox_count, 2);

        let current_generation = generations.last().unwrap().0;
        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_apply_status (
                id, group_key, generation, xds_version, required_type_urls, state,
                connected_nodes, required_acks, acked_acks
            ) VALUES ($1, $2, $3, $4, '["type.googleapis.com/envoy.config.listener.v3.Listener"]'::jsonb,
                      'applied', 1, 1, 1)
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(authority.group_key())
        .bind(current_generation)
        .bind(format!("test-{current_generation}"))
        .execute(&pool)
        .await
        .unwrap();
        assert_eq!(
            authority.wait_applied(&first).await.unwrap(),
            current_generation
        );
        assert_eq!(
            authority.wait_applied(&second).await.unwrap(),
            current_generation
        );

        let failed_sandbox = Uuid::now_v7();
        let failed = authority
            .declare(failed_sandbox, None, &test_credentials("llm:failed"))
            .await
            .unwrap();
        let failed_generation = failed.initial_generation;
        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_apply_status (
                id, group_key, generation, xds_version, required_type_urls, state,
                connected_nodes, required_acks, acked_acks, reason_code, error_summary
            ) VALUES ($1, $2, $3, $4, '["type.googleapis.com/envoy.config.listener.v3.Listener"]'::jsonb,
                      'failed', 1, 1, 0, 'envoy_nack', 'sanitized rejection')
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(authority.group_key())
        .bind(failed_generation)
        .bind(format!("test-{failed_generation}"))
        .execute(&pool)
        .await
        .unwrap();
        let error = authority
            .wait_applied(&failed)
            .await
            .unwrap_err()
            .to_string();
        assert!(error.contains("EGRESS_POLICY_APPLY_FAILED"));
        assert!(error.contains("envoy_nack"));

        let timeout_sandbox = Uuid::now_v7();
        let timeout = authority
            .declare(timeout_sandbox, None, &test_credentials("llm:timeout"))
            .await
            .unwrap();
        let error = authority
            .wait_applied(&timeout)
            .await
            .unwrap_err()
            .to_string();
        assert!(error.contains("EGRESS_POLICY_APPLY_TIMEOUT"));

        let revoked = authority.revoke(timeout_sandbox).await.unwrap().unwrap();
        let current: Value = sqlx::query_scalar(
            r#"
            SELECT desired_policies
            FROM joysafeter_egress_group_generations
            WHERE group_key = $1 AND state = 'desired'
            "#,
        )
        .bind(authority.group_key())
        .fetch_one(&pool)
        .await
        .unwrap();
        assert!(!current.to_string().contains(&timeout_sandbox.to_string()));
        assert!(revoked.initial_generation > timeout.initial_generation);

        cleanup_group(&pool, authority.group_key()).await;
    }

    /// The durable desired-state must self-heal: a sandbox the database marks
    /// dead (by any teardown path, including idle-sweep / TTL / task-failure
    /// cleanup that does not route through the egress Remove) must be pruned
    /// from `desired_policies` on the next generation write, so its Envoy
    /// listener + credential route do not linger forever (finding #8). A live
    /// sandbox is never pruned.
    #[tokio::test]
    async fn write_generation_prunes_dead_sandboxes_from_desired_state() {
        let Some(url) = database_url() else {
            eprintln!("skipping egress prune test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(4)
            .connect(&url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let unique = Uuid::now_v7().simple().to_string();
        let authority = PostgresEgressPolicyAuthority::new(
            pool.clone(),
            AuthorityConfig {
                selector: NodeSelector {
                    deployment_id: format!("prune-test-{unique}"),
                    environment: "test".to_string(),
                    region: "local".to_string(),
                    provider: "docker".to_string(),
                    shard_id: "0".to_string(),
                    host_id: Some(format!("prune-host-{unique}")),
                    envoy_version: "1.39.0".to_string(),
                    config_schema_version: "1".to_string(),
                },
                denied_cidrs: vec!["10.0.0.0/8".to_string()],
                apply_timeout: Duration::from_millis(800),
                poll_interval: Duration::from_millis(25),
            },
        )
        .unwrap();
        cleanup_group(&pool, authority.group_key()).await;

        let live = Uuid::now_v7();
        let dead = Uuid::now_v7();
        for id in [live, dead] {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_sandboxes (id, external_id, provider, status, config, image)
                VALUES ($1, $2, 'docker', 'idle', '{}'::jsonb, 'test-image')
                "#,
            )
            .bind(id)
            .bind(format!("prune-{id}"))
            .execute(&pool)
            .await
            .unwrap();
        }

        authority
            .declare(live, None, &test_credentials("llm:live"))
            .await
            .unwrap();
        authority
            .declare(dead, None, &test_credentials("llm:dead"))
            .await
            .unwrap();

        let before: Value = sqlx::query_scalar(
            "SELECT desired_policies FROM joysafeter_egress_group_generations WHERE group_key = $1 AND state = 'desired'",
        )
        .bind(authority.group_key())
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(
            serde_json::from_value::<Vec<DesiredSandboxPolicy>>(before)
                .unwrap()
                .len(),
            2,
            "both live sandboxes should be in the desired-state"
        );

        // A non-explicit teardown marks the sandbox dead WITHOUT revoking egress.
        sqlx::query(
            "UPDATE joysafeter_sandboxes SET status = 'destroyed', destroyed_at = NOW() WHERE id = $1",
        )
        .bind(dead)
        .execute(&pool)
        .await
        .unwrap();

        // The next generation write self-heals: re-declaring the live sandbox
        // (no content change) prunes the dead one from the desired-state.
        authority
            .declare(live, None, &test_credentials("llm:live"))
            .await
            .unwrap();

        let after: Value = sqlx::query_scalar(
            "SELECT desired_policies FROM joysafeter_egress_group_generations WHERE group_key = $1 AND state = 'desired'",
        )
        .bind(authority.group_key())
        .fetch_one(&pool)
        .await
        .unwrap();
        let policies = serde_json::from_value::<Vec<DesiredSandboxPolicy>>(after).unwrap();
        assert_eq!(
            policies.len(),
            1,
            "dead sandbox must be pruned from the desired-state"
        );
        assert_eq!(policies[0].sandbox_id, live.to_string());

        cleanup_group(&pool, authority.group_key()).await;
        sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = ANY($1)")
            .bind(vec![live, dead])
            .execute(&pool)
            .await
            .unwrap();
    }
}
