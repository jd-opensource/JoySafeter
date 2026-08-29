use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Context;
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Postgres, Row, Transaction};
use tracing::{debug, info, warn};
use url::Url;
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::{JoySafeterAgent, JoySafeterSandbox};
use crate::db::queries;
use crate::ids::{AgentId, ProjectId, SandboxId, SessionId, TaskId, UserId};
#[cfg(test)]
use crate::ids::{CredentialId, EnvironmentId};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
#[cfg(test)]
use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::credentials::runtime_projection::{
    build_external_egress, build_git_egress, extract_llm_egress, resolve_agent_env_from,
    sandbox_runner_token, EnvironmentRow,
};
#[cfg(test)]
use crate::kernel::credentials::runtime_projection::{
    model_protocol_env_value, model_protocol_provider_switch, remove_agent_identity_routes,
};
use crate::kernel::environment_binding;
use crate::kernel::mcp_runtime_plan::{
    effective_network_mode, resolve_mcp_runtime_plan_with_access, EffectiveNetworkMode,
};
#[cfg(test)]
use crate::kernel::mcp_url;
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::MCP_EGRESS_HOST;
use crate::kernel::network_policy::envoy_model::{EgressCredentialRoute, SandboxCredentials};
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::{
    EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher, EgressRetryMode,
};
use crate::kernel::network_policy::material::{
    NetworkPolicyMaterialResolver, UnconfiguredNetworkPolicyMaterialResolver,
};
use crate::kernel::network_policy::ports::NetworkPolicyRequestQueue;
use crate::kernel::network_policy::ports::{NetworkPolicyRuntime, NoopNetworkPolicyRuntime};
use crate::kernel::network_policy::{
    DesiredNetworkPolicy, NetworkPolicyGeneration, NetworkPolicyRequest,
};
use crate::kernel::run_spec::{agent_for_execution, environment_for_execution};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::kernel::task_identity::material::{
    TaskIdentityMaterialAdapter, TaskIdentityMaterialError,
};
use crate::sandbox::mounts::{resolve_mount_resources, SandboxMount, SandboxMountFingerprint};
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

#[cfg(test)]
use super::llm_providers::{CLAUDE_CODE_PLACEHOLDER_API_KEY, CODEX_PLACEHOLDER_OPENAI_API_KEY};

/// Task-scoped identity context loaded from the internal identity table.
struct LoadedIdentityContext {
    /// User's SSO cookie (Web scenario). Empty if auth_code is used.
    identity_token: String,
    /// Provider-approved request metadata captured with the identity token.
    headers_map: HashMap<String, String>,
    /// One-time BotAuthCode (API scenario). None if identity_token is used.
    auth_code: Option<String>,
    /// User name / email for cache keying.
    user_name: String,
    /// Immutable authenticated user ID.
    user_id: UserId,
}

type LoadedIdentityRow = (UserId, Option<String>, String, String);
type PersistedIdentityRow = (UserId, Option<String>, String, Option<String>);

fn require_identity_material(
    row: Option<PersistedIdentityRow>,
) -> Result<Option<LoadedIdentityRow>, TaskIdentityContextError> {
    row.map(
        |(user_id, user_name, credential_kind, encrypted_credential)| {
            Ok((
                user_id,
                user_name,
                credential_kind,
                encrypted_credential.ok_or(TaskIdentityMaterialError::FieldMissing)?,
            ))
        },
    )
    .transpose()
}

fn decode_revealed_identity_material(
    credential_kind: &str,
    credential: String,
) -> Result<(String, HashMap<String, String>, Option<String>), TaskIdentityContextError> {
    match credential_kind {
        "auth_code" => Ok((String::new(), HashMap::new(), Some(credential))),
        "identity_token" => {
            let Ok(envelope) = serde_json::from_str::<serde_json::Value>(&credential) else {
                return Ok((credential, HashMap::new(), None));
            };
            let envelope = envelope
                .as_object()
                .ok_or(TaskIdentityContextError::ContextInvalid)?;
            if envelope.get("version").and_then(serde_json::Value::as_u64) != Some(1) {
                return Err(TaskIdentityContextError::ContextInvalid);
            }
            let identity_token = envelope
                .get("identity_token")
                .and_then(serde_json::Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or(TaskIdentityContextError::ContextInvalid)?
                .to_string();
            let headers = envelope
                .get("headers_map")
                .and_then(serde_json::Value::as_object)
                .ok_or(TaskIdentityContextError::ContextInvalid)?;
            if headers.len() > 5 {
                return Err(TaskIdentityContextError::ContextInvalid);
            }
            let allowed_headers = [
                "Cookie",
                "Accept-Language",
                "User-Agent",
                "X-Forwarded-For",
                "X-Real-IP",
            ];
            let mut headers_map = HashMap::with_capacity(headers.len());
            for (name, value) in headers {
                if !allowed_headers.contains(&name.as_str()) {
                    return Err(TaskIdentityContextError::ContextInvalid);
                }
                let value = value
                    .as_str()
                    .filter(|value| {
                        !value.is_empty() && value.len() <= 4096 && !value.contains(['\r', '\n'])
                    })
                    .ok_or(TaskIdentityContextError::ContextInvalid)?;
                headers_map.insert(name.clone(), value.to_string());
            }
            Ok((identity_token, headers_map, None))
        }
        _ => Err(TaskIdentityContextError::KindInvalid),
    }
}

impl std::fmt::Debug for LoadedIdentityContext {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LoadedIdentityContext")
            .field("identity_token", &"<redacted>")
            .field("auth_code", &self.auth_code.as_ref().map(|_| "<redacted>"))
            .field("user_name", &self.user_name)
            .field("user_id", &self.user_id)
            .finish()
    }
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
enum TaskIdentityContextError {
    #[error("task identity database operation failed")]
    Database,
    #[error("task identity project does not match")]
    ProjectMismatch,
    #[error("task identity requires project and session scope")]
    ScopeMissing,
    #[error("task identity requires an authenticated task actor")]
    ActorMissing,
    #[error(transparent)]
    Material(#[from] TaskIdentityMaterialError),
    #[error("task identity credential kind is invalid")]
    KindInvalid,
    #[error("task identity context is invalid")]
    ContextInvalid,
    #[error("task identity provider is disabled for a requested route")]
    ProviderDisabled,
    #[error("task identity has no trusted egress hosts")]
    NoTrustedHosts,
    #[error("task identity provider returned no injection targets")]
    EmptyInjection,
    #[error("task identity provider failed")]
    Provider,
    #[error("task identity provider returned a mismatched route")]
    RouteMismatch,
    #[error("task identity claim changed while locked")]
    ClaimConflict,
}

/// Hard client-side bound on a provider networking setup/refresh call (Envoy
/// socket prep + xDS push + ACK/socket-readiness wait). The individual steps are
/// bounded, but this outer bound guarantees the sandbox-provisioning path can
/// never block indefinitely on a wedged Envoy/xDS: on timeout the sandbox is
/// marked `failed` (fail-closed: it keeps network=none, no egress) and the
/// networking-reconcile loop retries it. Prevents a single stuck setup from
/// freezing task scheduling.

#[cfg(test)]
mod protocol_env_tests {
    use super::{model_protocol_env_value, model_protocol_provider_switch};

    #[test]
    fn maps_known_protocols() {
        assert_eq!(
            model_protocol_env_value("openai_responses"),
            Some("openai_responses".to_string())
        );
        assert_eq!(
            model_protocol_env_value("chat_completions"),
            Some("chat_completions".to_string())
        );
        assert_eq!(
            model_protocol_env_value("anthropic_messages"),
            Some("anthropic_messages".to_string())
        );
    }

    #[test]
    fn ignores_custom_and_blank() {
        assert_eq!(model_protocol_env_value("custom"), None);
        assert_eq!(model_protocol_env_value(""), None);
        assert_eq!(model_protocol_env_value("   "), None);
    }

    #[test]
    fn openai_family_protocols_get_ccb_provider_switch() {
        assert_eq!(
            model_protocol_provider_switch("openai_responses"),
            Some("CLAUDE_CODE_USE_OPENAI")
        );
        assert_eq!(
            model_protocol_provider_switch(" chat_completions "),
            Some("CLAUDE_CODE_USE_OPENAI")
        );
    }

    #[test]
    fn anthropic_and_custom_protocols_get_no_switch() {
        assert_eq!(model_protocol_provider_switch("anthropic_messages"), None);
        assert_eq!(model_protocol_provider_switch("custom"), None);
        assert_eq!(model_protocol_provider_switch(""), None);
    }
}

fn apply_sandbox_timezone(env: &mut HashMap<String, String>, platform_timezone: &str) {
    let platform_timezone = platform_timezone.trim();
    if !platform_timezone.is_empty() {
        env.entry("TZ".to_string())
            .or_insert_with(|| platform_timezone.to_string());
    }
}

fn apply_claude_code_sandbox_privacy(env: &mut HashMap<String, String>) {
    env.entry("DISABLE_TELEMETRY".to_string())
        .or_insert_with(|| "1".to_string());
    env.entry("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC".to_string())
        .or_insert_with(|| "1".to_string());
}

/// 3-stage sandbox resolution with full Python parity:
/// 1. Reuse existing active sandbox for the session (with fingerprint check)
/// 1b. Restart stopped sandbox for the session
/// 2. Claim from warm pool (with liveness check)
/// 3. Create a new sandbox (with runner token, JOYSAFETER_* env vars)
///
/// Mirrors the Python `SandboxResolver`.
pub struct SandboxResolver {
    pool: PgPool,
    provider: Arc<dyn SandboxProvider>,
    network_policy_runtime: Arc<dyn NetworkPolicyRuntime>,
    network_policy_material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    config: JoySafeterConfig,
    /// Per-session locks to prevent concurrent resolution
    session_locks: dashmap::DashMap<SessionId, Arc<tokio::sync::Mutex<()>>>,
    /// In-process confirmation that this orchestrator has successfully pushed
    /// the sandbox's current Envoy policy. DB state alone is not enough after a
    /// process restart because xDS state is in-memory; the first reuse after
    /// restart refreshes Envoy and repopulates this cache.
    network_policy_ready: dashmap::DashMap<SandboxId, String>,
    /// Optional notify to trigger immediate pool replenishment after a claim.
    pool_replenish_notify: Option<Arc<tokio::sync::Notify>>,
    /// Multi-replica requests are submitted to the elected xDS authority.
    /// `None` means this process is the single local authority.
    network_policy_queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    xds_authority: crate::xds::authority::XdsAuthorityState,
    /// Pluggable agent identity provider for outbound credential injection.
    identity_provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
    identity_allowed_hosts: Vec<String>,
    task_identity_material: Option<TaskIdentityMaterialAdapter>,
}

impl SandboxResolver {
    pub fn new(pool: PgPool, provider: Arc<dyn SandboxProvider>, config: JoySafeterConfig) -> Self {
        Self {
            pool,
            provider,
            network_policy_runtime: Arc::new(NoopNetworkPolicyRuntime),
            network_policy_material_resolver: Arc::new(UnconfiguredNetworkPolicyMaterialResolver),
            config,
            session_locks: dashmap::DashMap::new(),
            network_policy_ready: dashmap::DashMap::new(),
            pool_replenish_notify: None,
            network_policy_queue: None,
            xds_authority: crate::xds::authority::XdsAuthorityState::standalone(),
            identity_provider: Arc::new(
                crate::kernel::agent_identity_provider::NoopAgentIdentityProvider,
            ),
            identity_allowed_hosts: Self::identity_allowed_hosts_from_env(),
            task_identity_material: None,
        }
    }

    pub fn with_network_policy_runtime(mut self, runtime: Arc<dyn NetworkPolicyRuntime>) -> Self {
        self.network_policy_runtime = runtime;
        self
    }

    pub fn with_network_policy_material_resolver(
        mut self,
        resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    ) -> Self {
        self.network_policy_material_resolver = resolver;
        self
    }

    /// Set the agent identity provider.
    pub fn with_identity_provider(
        mut self,
        provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
    ) -> Self {
        self.identity_provider = provider;
        self
    }

    #[cfg(test)]
    fn with_identity_allowed_hosts(mut self, allowed_hosts: Vec<String>) -> Self {
        self.identity_allowed_hosts = allowed_hosts;
        self
    }

    #[cfg(test)]
    fn with_task_identity_material_adapter(
        mut self,
        material: TaskIdentityMaterialAdapter,
    ) -> Self {
        self.task_identity_material = Some(material);
        self
    }

    /// Set the pool replenish notify (called from scheduler setup).
    pub fn with_pool_replenish_notify(mut self, notify: Arc<tokio::sync::Notify>) -> Self {
        self.pool_replenish_notify = Some(notify);
        self
    }

    /// Route networking changes through the elected xDS authority in multi mode.
    pub fn with_network_policy_queue(mut self, queue: Arc<dyn NetworkPolicyRequestQueue>) -> Self {
        self.network_policy_queue = Some(queue);
        self
    }

    pub fn with_network_policy_control(
        mut self,
        authority: crate::xds::authority::XdsAuthorityState,
        queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    ) -> Self {
        self.xds_authority = authority;
        self.network_policy_queue = queue;
        self
    }

    async fn apply_prepared_network_policy(
        &self,
        sandbox_id: SandboxId,
        _external_id: &str,
        context: &ResolveContext,
        generation: &NetworkPolicyGeneration,
        _task_id: Option<TaskId>,
        proxy_auth_token: Option<String>,
    ) -> anyhow::Result<()> {
        if context.has_task_identity() {
            if self.network_policy_queue.is_some() {
                anyhow::bail!(
                    "task-scoped Agent Identity requires secure ephemeral delivery to the elected xDS authority"
                );
            }
            let _application_lock = self.xds_authority.lock_application().await;
            let guard = self
                .xds_authority
                .ready_guard()
                .ok_or_else(|| anyhow::anyhow!("local xDS authority is not ready"))?;
            let mut credentials = context.credentials.clone();
            credentials.proxy_auth_token = proxy_auth_token;
            crate::kernel::network_policy::application::apply_generation_with_credentials_as_authority(
                &self.pool,
                self.network_policy_runtime.as_ref(),
                sandbox_id,
                generation,
                credentials,
                &guard,
            )
            .await?;
        } else {
            crate::kernel::network_policy::application::ensure_ready(
                &self.pool,
                self.network_policy_runtime.as_ref(),
                self.network_policy_material_resolver.as_ref(),
                self.network_policy_queue.as_deref(),
                &self.xds_authority,
                sandbox_id,
                generation,
                crate::kernel::network_policy::application::POLICY_APPLY_TIMEOUT,
            )
            .await?;
        }

        if context.has_task_identity() {
            let task_id = _task_id.ok_or_else(|| {
                anyhow::anyhow!("task-scoped Agent Identity requires a task identifier")
            })?;
            let lease = identity_lease_metadata(task_id, context.identity_refresh_after_seconds);
            if !queries::merge_sandbox_config(
                &self.pool,
                sandbox_id,
                &serde_json::json!({"agent_identity_lease": lease}),
            )
            .await?
            {
                anyhow::bail!("sandbox {sandbox_id} disappeared before identity lease persistence");
            }
        }

        self.network_policy_ready
            .insert(sandbox_id, generation.policy_hash.clone());
        Ok(())
    }

    /// Signal that a pool sandbox was claimed — triggers immediate replenishment.
    fn signal_pool_claimed(&self) {
        if let Some(ref notify) = self.pool_replenish_notify {
            notify.notify_one();
        }
    }

    /// Resolve a sandbox for the given task.
    /// Returns the sandbox identity plus the generation captured during resolution.
    ///
    /// Uses an in-process tokio Mutex per session to serialize concurrent
    /// resolution attempts. We intentionally do NOT use pg_advisory_lock here
    /// because the resolver performs many separate DB calls across the
    /// resolution stages — a session-level advisory lock acquired via the
    /// connection pool will lock on one pooled connection but the unlock
    /// executes on a *different* pooled connection, leaving the lock held
    /// forever and blocking all subsequent tasks for the same session.
    ///
    /// The tokio Mutex is sufficient for single-instance deployments. For
    /// multi-instance HA, the freshness and ownership guards in
    /// `attach_sandbox_to_task_guarded` prevent
    /// double-attachment.
    pub async fn resolve(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolvedSandbox> {
        // Per-session in-process lock to prevent concurrent resolution
        let _lock = if let Some(sid) = session_id {
            let lock = self
                .session_locks
                .entry(sid)
                .or_insert_with(|| Arc::new(tokio::sync::Mutex::new(())))
                .clone();
            Some(lock.lock_owned().await)
        } else {
            None
        };

        let result = self
            .resolve_inner(task_id, session_id, agent_id, project_id)
            .await;

        // Clean up stale session locks (no other waiters)
        if let Some(sid) = session_id {
            if let Some(entry) = self.session_locks.get(&sid) {
                if Arc::strong_count(entry.value()) <= 2 {
                    drop(entry);
                    self.session_locks.remove(&sid);
                }
            }
        }

        result
    }

    async fn resolve_inner(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolvedSandbox> {
        let context = self
            .build_resolve_context(task_id, session_id, agent_id, project_id)
            .await?;
        // Stage 1: Try to reuse existing sandbox for this session
        if let Some(sid) = session_id {
            if let Some(sandbox) = queries::find_sandbox_for_session(&self.pool, sid).await? {
                if !runtime_fingerprint_matches(
                    sandbox.config.as_ref(),
                    sandbox.image.as_deref(),
                    &context.expected,
                ) {
                    if matches!(
                        sandbox.status.as_str(),
                        "running" | "provisioning" | "creating"
                    ) {
                        anyhow::bail!("Session has an active sandbox with different configuration");
                    }
                    info!(sandbox_id = %sandbox.id, "Sandbox fingerprint differs, destroying instead of reusing");
                    if !self
                        .destroy_observed_sandbox(&sandbox, "fingerprint mismatch")
                        .await?
                    {
                        anyhow::bail!(
                            "session sandbox {} changed state before fingerprint cleanup",
                            sandbox.id
                        );
                    }
                } else {
                    if matches!(sandbox.status.as_str(), "idle" | "running" | "provisioning")
                        && (sandbox.runtime_config_status != "ready"
                            || sandbox.runtime_config_applied_generation
                                != context.runtime_config_generation)
                    {
                        return Err(RuntimeFreshnessError::RuntimeRestartRequired {
                            sandbox_id: sandbox.id,
                        }
                        .into());
                    }
                    match sandbox.status.as_str() {
                        // S10: Do NOT reuse `creating` sandboxes - container may not exist yet.
                        // S16: For idle/running, only touch last_used_at (don't reset
                        //      provisioning timeout). For provisioning, return as-is.
                        "idle" | "running" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                if context.is_limited_networking() {
                                    self.refresh_reused_sandbox_networking(
                                        &sandbox, ext_id, &context,
                                    )
                                    .await?;
                                }
                                info!(
                                    sandbox_id = %sandbox.id,
                                    task_id = %task_id,
                                    status = %sandbox.status,
                                    "Reusing existing sandbox for session"
                                );
                                // S16: Only touch last_used_at, don't call transition_sandbox
                                let _ = queries::touch_sandbox(&self.pool, sandbox.id).await;
                                return Ok(context.resolved(sandbox.id, ext_id.clone()));
                            }
                        }
                        "provisioning" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                info!(
                                    sandbox_id = %sandbox.id,
                                    task_id = %task_id,
                                    status = %sandbox.status,
                                    "Reusing provisioning sandbox for session (not touching last_used_at)"
                                );
                                // S16: Do NOT touch last_used_at for provisioning -
                                // preserves provisioning timeout detection
                                return Ok(context.resolved(sandbox.id, ext_id.clone()));
                            }
                        }
                        "creating" => {
                            // S10: Don't reuse a `creating` sandbox — the container
                            // may not exist yet. But we MUST destroy it first,
                            // otherwise the unique constraint
                            // `idx_csb_active_session_unique` blocks creating a
                            // replacement and the scheduler enters a retry loop.
                            if !self
                                .destroy_observed_sandbox(&sandbox, "stale creating")
                                .await?
                            {
                                anyhow::bail!(
                                    "creating sandbox {} changed state before stale cleanup",
                                    sandbox.id
                                );
                            }
                            debug!(
                                sandbox_id = %sandbox.id,
                                "Destroyed stale creating sandbox before re-provisioning"
                            );
                        }
                        "stopped" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                if self
                                    .restart_stopped_sandbox(sandbox.id, ext_id, &context)
                                    .await?
                                {
                                    info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox");
                                    return Ok(context.resolved(sandbox.id, ext_id.clone()));
                                }
                                // Restart failed (e.g. pod deleted in K8s). Destroy the
                                // stale DB record so the unique-session constraint is freed
                                // and a fresh sandbox can be created below.
                                if !self
                                    .destroy_observed_sandbox(&sandbox, "stopped restart failed")
                                    .await?
                                {
                                    anyhow::bail!(
                                        "stopped sandbox {} changed state before cleanup after failed restart",
                                        sandbox.id
                                    );
                                }
                            }
                        }
                        "error" => {
                            if !self.destroy_observed_sandbox(&sandbox, "error").await? {
                                anyhow::bail!(
                                    "error sandbox {} changed state before cleanup",
                                    sandbox.id
                                );
                            }
                        }
                        "stopping" => {
                            // M5 fix: A sandbox stuck in "stopping" blocks new
                            // session sandboxes indefinitely. Clean it up so the
                            // resolver can proceed to create a fresh one.
                            debug!(sandbox_id = %sandbox.id, "Sandbox is stopping, cleaning up and creating new");
                            if !self.destroy_observed_sandbox(&sandbox, "stopping").await? {
                                anyhow::bail!(
                                    "stopping sandbox {} changed state before cleanup",
                                    sandbox.id
                                );
                            }
                        }
                        _ => {}
                    }
                }
            }

            // Also check stopped sandboxes
            if let Ok(Some(sandbox)) =
                queries::find_stopped_sandbox_for_session(&self.pool, sid).await
            {
                if !runtime_fingerprint_matches(
                    sandbox.config.as_ref(),
                    sandbox.image.as_deref(),
                    &context.expected,
                ) {
                    if !self
                        .destroy_observed_sandbox(&sandbox, "stopped fingerprint mismatch")
                        .await?
                    {
                        anyhow::bail!(
                            "stopped sandbox {} changed state before fingerprint cleanup",
                            sandbox.id
                        );
                    }
                    return self.create_new_sandbox(task_id, &context).await;
                }
                if let Some(ref ext_id) = sandbox.external_id {
                    if self
                        .restart_stopped_sandbox(sandbox.id, ext_id, &context)
                        .await?
                    {
                        info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox for session");
                        return Ok(context.resolved(sandbox.id, ext_id.clone()));
                    }
                    // Restart failed — destroy stale record to free the unique-session
                    // constraint so a fresh sandbox can be created below.
                    if !self
                        .destroy_observed_sandbox(&sandbox, "stopped restart failed (session)")
                        .await?
                    {
                        anyhow::bail!(
                            "stopped sandbox {} changed state before cleanup after failed restart",
                            sandbox.id
                        );
                    }
                }
            }
        }

        // Stage 2: Claim from warm pool
        // Pool sandboxes are created with deny-all networking. For limited-networking
        // sessions, refresh_networking is called after claim to inject credentials.
        let requires_persistent_workspace =
            context.session_id.is_some() && self.config.sandbox_workspace_root.is_some();
        if self.config.sandbox_pool_enabled
            && context.expected.env.is_empty()
            && !requires_persistent_workspace
            && context.session_id.is_some()
        {
            let image = context.expected.image.as_str();
            if let Some(sandbox) = queries::claim_pool_sandbox(&self.pool, image).await? {
                if let Some(ref ext_id) = sandbox.external_id {
                    let session_id = context.session_id.expect("pool path requires session");
                    let attachment = match queries::activate_reserved_pool_sandbox_guarded(
                        &self.pool,
                        sandbox.id,
                        ext_id,
                        session_id,
                        context.project_id,
                        &context.expected.to_json(),
                        context.runtime_config_generation,
                    )
                    .await
                    {
                        Ok(attachment) => attachment,
                        Err(error) => {
                            match self
                                .destroy_unattached_pool_claim(
                                    &sandbox,
                                    "pool activation guard rejection",
                                )
                                .await
                            {
                                Ok(true) => return Err(error.into()),
                                Ok(false) => {
                                    return Err(RuntimeFreshnessError::Conflict(format!(
                                        "reserved pool sandbox {} changed before rejected activation cleanup",
                                        sandbox.id
                                    ))
                                    .into());
                                }
                                Err(cleanup_error) => {
                                    return Err(RuntimeFreshnessError::CleanupFailed(format!(
                                        "failed to destroy rejected pool sandbox {}: {cleanup_error}",
                                        sandbox.id
                                    ))
                                    .into());
                                }
                            }
                        }
                    };

                    let progress = provisioning_config(
                        "pool_claimed",
                        80,
                        "Claimed from warm pool, waiting for runner readiness",
                        false,
                        &context.expected,
                        None,
                    );
                    let _ = queries::update_sandbox_status_and_config(
                        &self.pool,
                        sandbox.id,
                        "provisioning",
                        &progress,
                    )
                    .await?;

                    if let Err(error) = self
                        .patch_claimed_pool_labels(ext_id, Some(session_id), &context)
                        .await
                    {
                        warn!(
                            sandbox_id = %sandbox.id,
                            external_id = %ext_id,
                            error = %error,
                            "Failed to patch labels for claimed pooled sandbox"
                        );
                    }

                    match self.provider.status(ext_id).await {
                        Ok(SandboxStatus::Running) => {}
                        Ok(SandboxStatus::Stopped) => {
                            if let Err(error) = self.provider.start(ext_id).await {
                                self.cleanup_attached_pool_claim(
                                    &attachment,
                                    "stopped pooled runtime failed to start",
                                )
                                .await?;
                                return Err(error.context("failed to start claimed pool sandbox"));
                            }
                            let restarting = provisioning_config(
                                "pool_restarting",
                                75,
                                "Claimed stopped pooled sandbox, restarting runtime",
                                false,
                                &context.expected,
                                None,
                            );
                            let _ = queries::update_sandbox_status_and_config(
                                &self.pool,
                                sandbox.id,
                                "provisioning",
                                &restarting,
                            )
                            .await?;
                        }
                        Ok(status) => {
                            self.cleanup_attached_pool_claim(
                                &attachment,
                                "claimed pool sandbox has unexpected provider status",
                            )
                            .await?;
                            anyhow::bail!(
                                "claimed pool sandbox {} has unexpected provider status {status:?}",
                                sandbox.id
                            );
                        }
                        Err(error) => {
                            self.cleanup_attached_pool_claim(
                                &attachment,
                                "claimed pool sandbox provider status failed",
                            )
                            .await?;
                            return Err(error.context("failed to inspect claimed pool sandbox"));
                        }
                    }
                    if !self.attached_pool_claim_is_current(&attachment).await? {
                        return Err(RuntimeFreshnessError::Conflict(format!(
                            "attached pool sandbox {} changed during provider activation",
                            sandbox.id
                        ))
                        .into());
                    }

                    let ctx = crate::sandbox::file_injection::FileInjectionContext {
                        session_id,
                        external_id: ext_id.clone(),
                        workspace_path: None,
                        runner_capabilities: vec![],
                        is_pool_sandbox: true,
                    };
                    if let Err(error) = crate::sandbox::file_injection::inject_session_files(
                        &self.pool,
                        &ctx,
                        self.provider.as_ref(),
                    )
                    .await
                    {
                        self.cleanup_attached_pool_claim(
                            &attachment,
                            "pooled session file injection failed",
                        )
                        .await?;
                        return Err(error.context(format!(
                            "failed to inject session files into pooled sandbox {} for session {}",
                            sandbox.id, session_id
                        )));
                    }

                    if context.is_limited_networking() {
                        if let Err(error) = self
                            .setup_pool_sandbox_networking(sandbox.id, ext_id, &context)
                            .await
                        {
                            self.cleanup_attached_pool_claim(
                                &attachment,
                                "pooled sandbox networking setup failed",
                            )
                            .await?;
                            return Err(error.context(format!(
                                "failed to setup networking for pooled sandbox {}",
                                sandbox.id
                            )));
                        }
                    }

                    info!(
                        sandbox_id = %sandbox.id,
                        task_id = %task_id,
                        "Claimed sandbox from warm pool"
                    );
                    self.signal_pool_claimed();
                    return Ok(context.resolved(sandbox.id, ext_id.clone()));
                } else {
                    warn!(sandbox_id = %sandbox.id, "Pooled sandbox has no external_id, destroying");
                    let _ = self
                        .destroy_observed_sandbox(&sandbox, "pooled sandbox without external id")
                        .await;
                }
            }
        }

        // Stage 3: Create new sandbox
        self.create_new_sandbox(task_id, &context).await
    }

    /// Create a brand-new sandbox container with full env vars and runner token.
    async fn create_new_sandbox(
        &self,
        task_id: TaskId,
        context: &ResolveContext,
    ) -> anyhow::Result<ResolvedSandbox> {
        let sandbox_db_id = SandboxId::from_uuid(Uuid::now_v7());
        let expected = context.expected.clone();
        let image = expected.image.clone();
        let runner_token = generate_runner_token();

        // Build environment variables — both JOYSAFETER_* and JOYSAFETER_* variants
        let mut env = expected.env.clone();
        apply_sandbox_timezone(&mut env, &self.config.sandbox_timezone);
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.as_uuid().to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());
        apply_claude_code_sandbox_privacy(&mut env);
        if !self.config.sandbox_timezone.trim().is_empty() {
            env.entry("TZ".to_string())
                .or_insert_with(|| self.config.sandbox_timezone.clone());
        }

        let grpc_url = self.provider.orchestrator_url(self.config.grpc_port);
        env.insert("JOYSAFETER_ORCHESTRATOR_URL".to_string(), grpc_url.clone());

        let mut labels = HashMap::new();
        labels.insert("joysafeter".to_string(), "true".to_string());
        labels.insert("joysafeter.managed".to_string(), "true".to_string());
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            sandbox_db_id.as_uuid().to_string(),
        );
        labels.insert(
            "joysafeter.owner_instance_id".to_string(),
            self.config.instance_id.clone(),
        );
        labels.insert(
            "joysafeter.created_at_unix".to_string(),
            chrono::Utc::now().timestamp().to_string(),
        );
        labels.insert(
            "joysafeter.engine_kind".to_string(),
            expected.engine_kind.clone(),
        );
        labels.insert("joysafeter.pool".to_string(), "false".to_string());
        labels.insert("joysafeter.claimed".to_string(), "true".to_string());
        labels.insert("joysafeter.allocation".to_string(), "session".to_string());
        if let Some(ref sid) = context.session_id {
            labels.insert("joysafeter.session_id".to_string(), sid.to_string());
        }
        if let Some(ref project_id) = context.project_id {
            labels.insert("joysafeter.project_id".to_string(), project_id.to_public());
        }

        let limited_networking = context.network.as_deref() == Some("none");
        let create_config = SandboxCreateConfig {
            sandbox_id: sandbox_db_id,
            image: image.clone(),
            env,
            labels,
            cpu_limit: self.config.sandbox_cpu,
            memory_limit_mb: self.config.sandbox_memory_mb,
            network: context.network.clone(),
            // Restricted sandboxes are created stopped, then started explicitly
            // right after create() — BEFORE the Envoy egress push — so the runner
            // (which reaches the orchestrator over a direct control UDS, not
            // Envoy) boots without waiting on xDS. The egress push and socket
            // materialization happen off the critical path; the runner's
            // in-process HTTP bridge retries the egress socket until it appears.
            start_immediately: !limited_networking,
            // Use session_id for workspace path (Python L332-333: workspace_root/session_id)
            workspace_path: self.config.sandbox_workspace_root.as_ref().map(|root| {
                if let Some(sid) = context.session_id {
                    format!("{}/{}", root, sid)
                } else {
                    format!("{}/{}", root, sandbox_db_id)
                }
            }),
            memory_mounts: context.memory_mounts.clone(),
            mounts: context.mounts.clone(),
        };

        // #13: File injection — write local session files to workspace before start.
        //
        // NB: memory stores are NOT preloaded here. The runner writes them to
        // the canonical `/mnt/memory/{slug}` mount inside the container from the
        // SetupSandbox `memory_mounts[].files` payload (see harness_input_builder).
        // A previous preload wrote them to `/workspace/mnt/memory/` too, which
        // created a stale duplicate that real-time updates never touched.
        if let (Some(sid), Some(ref workspace_root)) =
            (context.session_id, &self.config.sandbox_workspace_root)
        {
            let workspace_path = format!("{}/{}", workspace_root, sid);
            let ctx = crate::sandbox::file_injection::FileInjectionContext {
                session_id: sid,
                external_id: String::new(),
                workspace_path: Some(workspace_path.clone()),
                runner_capabilities: vec![],
                is_pool_sandbox: false,
            };
            crate::sandbox::file_injection::inject_session_files(
                &self.pool,
                &ctx,
                self.provider.as_ref(),
            )
            .await
            .map_err(|err| {
                anyhow::anyhow!(
                    "failed to inject session files into workspace before sandbox create for session {sid}: {err}"
                )
            })?;
        }

        // Store runner token in sandbox config
        let sandbox_config = provisioning_config(
            "container_started",
            70,
            "Sandbox created, waiting for runner ready",
            false,
            &expected,
            Some(&runner_token),
        );

        let external_id = match self.provider.create(&create_config).await {
            Ok(external_id) => external_id,
            Err(e) => {
                let _ = self.teardown_networking(sandbox_db_id).await;
                return Err(e);
            }
        };

        let create_result = if let Some(session_id) = context.session_id {
            queries::create_session_bound_sandbox_guarded(
                &self.pool,
                sandbox_db_id,
                &external_id,
                self.config.sandbox_provider.as_str(),
                &image,
                session_id,
                context.project_id,
                create_config.workspace_path.as_deref(),
                Some(&sandbox_config),
                context.runtime_config_generation,
            )
            .await
            .map_err(anyhow::Error::new)
        } else {
            queries::create_sandbox(
                &self.pool,
                sandbox_db_id,
                &external_id,
                self.config.sandbox_provider.as_str(),
                &image,
                None,
                context.project_id,
                create_config.workspace_path.as_deref(),
                Some(&sandbox_config),
            )
            .await
            .map_err(anyhow::Error::new)
        };
        if let Err(e) = create_result {
            self.cleanup_rejected_new_sandbox(sandbox_db_id, &external_id, None)
                .await?;
            return Err(e);
        }

        // Start the container as soon as it exists, BEFORE pushing Envoy egress
        // config. This takes Envoy off the sandbox-start critical path:
        //   * runner control-plane gRPC uses a direct orchestrator UDS, not Envoy,
        //     so the runner can connect and receive Setup/StartTask immediately;
        //   * the runner's in-process HTTP egress bridge binds instantly and
        //     connects to the per-sandbox Envoy socket lazily (retrying until it
        //     appears), so the egress socket need not exist at start time.
        // A slow or failing Envoy push therefore only delays *outbound* traffic,
        // never sandbox/runner boot. (For non-limited networking the container was
        // already started inside `create()` via start_immediately.)
        if !create_config.start_immediately {
            if let Err(e) = self.provider.start(&external_id).await {
                self.cleanup_rejected_new_sandbox(sandbox_db_id, &external_id, None)
                    .await?;
                return Err(e.context("failed to start sandbox after control-plane setup"));
            }
            info!(
                sandbox_id = %sandbox_db_id,
                external_id = %external_id,
                "Started sandbox (egress config applied asynchronously)"
            );
        }

        if limited_networking {
            if !self.provider.capabilities().has_egress_management {
                self.cleanup_rejected_new_sandbox(sandbox_db_id, &external_id, None)
                    .await?;
                anyhow::bail!(
                    "limited sandbox networking requires egress management, but provider does not support it"
                );
            }
            info!(
                sandbox_id = %sandbox_db_id,
                external_id = %external_id,
                policy_hash = %context.expected.egress_policy_hash,
                "Preparing Envoy networking (sandbox already started)"
            );
            let policy_generation = match queries::prepare_desired_network_policy(
                &self.pool,
                sandbox_db_id,
                &context.expected.egress_policy_hash,
            )
            .await
            {
                Ok(outcome) => outcome.into_generation(),
                Err(e) => {
                    self.cleanup_rejected_new_sandbox(sandbox_db_id, &external_id, None)
                        .await?;
                    return Err(anyhow::anyhow!(
                        "failed to mark sandbox network policy pending: {e}"
                    ));
                }
            };
            info!(
                sandbox_id = %sandbox_db_id,
                external_id = %external_id,
                "Pushing Envoy networking (off the sandbox-start critical path)"
            );
            if let Err(error) = self
                .apply_prepared_network_policy(
                    sandbox_db_id,
                    &external_id,
                    &context,
                    &policy_generation,
                    Some(task_id),
                    Some(runner_token.clone()),
                )
                .await
            {
                if self
                    .cleanup_rejected_new_sandbox(
                        sandbox_db_id,
                        &external_id,
                        Some(&policy_generation),
                    )
                    .await?
                {
                    return Err(error.context("failed to setup Envoy networking for new sandbox"));
                }
                info!(
                    sandbox_id = %sandbox_db_id,
                    policy_version = policy_generation.policy_version,
                    "Adopted concurrently ready network policy after stale apply result"
                );
            }

            info!(
                sandbox_id = %sandbox_db_id,
                external_id = %external_id,
                policy_version = policy_generation.policy_version,
                "Envoy networking ready"
            );
        }

        let transitioned =
            queries::transition_sandbox_cas(&self.pool, sandbox_db_id, "creating", "provisioning")
                .await?;
        if !transitioned
            && self
                .active_sandbox_status(sandbox_db_id, &external_id)
                .await?
                .is_none()
        {
            warn!(
                sandbox_id = %sandbox_db_id,
                "Skipped new-sandbox provider destroy because DB row changed before provisioning transition"
            );
            anyhow::bail!("sandbox {sandbox_db_id} changed state before provisioning transition");
        }

        info!(
            sandbox_id = %sandbox_db_id,
            external_id = %external_id,
            task_id = %task_id,
            "Created new sandbox (with runner token)"
        );

        Ok(context.resolved(sandbox_db_id, external_id))
    }

    async fn build_resolve_context(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolveContext> {
        let live_agent = match agent_id {
            Some(aid) => queries::get_agent(&self.pool, aid).await?,
            None => None,
        };
        let session = match session_id {
            Some(sid) => queries::get_session(&self.pool, sid).await?,
            None => None,
        };
        let snapshot_environment = environment_for_execution(session.as_ref());
        let agent = agent_for_execution(live_agent, session.as_ref())?;
        let project_id = project_id
            .or_else(|| session.as_ref().and_then(|s| s.project_id))
            .or_else(|| agent.as_ref().and_then(|a| a.project_id));
        // Validate the live environment binding before provisioning anything.
        // An explicit (session) binding that is archived, missing, or
        // cross-project fails here with SessionBindingInvalid — the same gate
        // the harness applies at StartTask — so the resolver never provisions a
        // sandbox the harness would then reject.
        let live_environment = environment_binding::resolve_live_environment_binding(
            &self.pool,
            session.as_ref().and_then(|session| session.environment_id),
            agent.as_ref().and_then(|agent| agent.environment_id),
            project_id,
            session_id,
        )
        .await?;

        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else {
            live_environment.map(|environment| EnvironmentRow {
                config: environment.config,
                image_tag: environment.image_tag,
            })
        };

        let engine_kind = agent
            .as_ref()
            .and_then(|a| a.engine_kind.clone())
            .unwrap_or_else(|| "claude".to_string());
        let image = match environment.as_ref().and_then(|env| env.image_tag.clone()) {
            Some(tag) => tag,
            None => self.config.image_for_provider(&engine_kind)?,
        };
        let access_context = CredentialAccessContext::runtime(
            session_id,
            Some(task_id),
            session
                .as_ref()
                .map(|session| session.runtime_config_generation),
        );
        let credential_access = CredentialMaterialAccessService::new(self.pool.clone());
        let resolved_env = resolve_agent_env_from(
            &credential_access,
            &access_context,
            agent.as_ref(),
            environment.as_ref(),
        )
        .await?;
        let mut env = resolved_env.values;
        let llm_binding = resolved_env.llm_binding;
        let configured_networking = environment
            .as_ref()
            .and_then(|env| env.config.get("networking").cloned());
        let networking = effective_networking_config(
            configured_networking,
            self.config.envoy_enabled,
            environment.as_ref(),
        )?;
        let network_mode = effective_network_mode(networking.as_ref(), self.config.envoy_enabled)?;
        let network = match network_mode {
            EffectiveNetworkMode::Limited | EffectiveNetworkMode::Disabled => {
                Some("none".to_string())
            }
            EffectiveNetworkMode::Unrestricted => None,
        };
        let runtime_generation = session
            .as_ref()
            .map(|session| session.runtime_config_generation)
            .unwrap_or(0);
        let mcp_plan = match agent.as_ref() {
            Some(agent) => Some(
                resolve_mcp_runtime_plan_with_access(
                    &credential_access,
                    &access_context,
                    project_id,
                    session_id,
                    agent.id,
                    runtime_generation,
                    network_mode,
                    agent.mcp_servers.as_ref(),
                )
                .await?,
            ),
            None => None,
        };

        // Egress credential injection only applies to limited-networking sandboxes
        // (those routed through Envoy). For those, pull the LLM key out of the
        // container env and repoint the base URL at the egress boundary so the
        // real key never enters the sandbox. Unrestricted sandboxes keep the
        // key in their environment because they do not route through Envoy.
        let mut credentials = SandboxCredentials::default();
        let mut identity_refresh_after_seconds = None;
        if network_mode == EffectiveNetworkMode::Limited {
            let mut routes = Vec::new();
            routes.extend(extract_llm_egress(
                &mut env,
                llm_binding.as_ref(),
                &self.config.llm_egress_allowed_hosts,
            ));
            routes.extend(
                mcp_plan
                    .as_ref()
                    .map(|plan| plan.egress_routes())
                    .unwrap_or_default(),
            );
            routes.extend(build_git_egress(&self.pool, session_id).await?);
            let (external_routes, identity_targets) = build_external_egress(
                &credential_access,
                &access_context,
                environment.as_ref(),
                project_id,
            )
            .await?;
            routes.extend(external_routes);

            // Agent identity is composed into existing MCP placeholder routes.
            // Never create a transparent HTTPS interception route.
            if !identity_targets.is_empty() {
                if self.network_policy_queue.is_some() {
                    anyhow::bail!(
                        "task-scoped Agent Identity requires secure ephemeral delivery to the elected xDS authority"
                    );
                }
                if !self.identity_provider.enabled() {
                    return Err(TaskIdentityContextError::ProviderDisabled.into());
                }
                if let Some(injection) = self
                    .resolve_identity_injection(
                        agent.as_ref(),
                        task_id,
                        session_id,
                        project_id,
                        &identity_targets,
                    )
                    .await?
                {
                    identity_refresh_after_seconds = injection.valid_for_seconds;
                    Self::merge_identity_into_routes(&mut routes, injection)?;
                }
            }

            credentials = SandboxCredentials {
                routes,
                proxy_auth_token: None,
            };
        }
        let egress_policy_hash =
            DesiredNetworkPolicy::from_inputs(networking.as_ref(), &credentials)?
                .revision()
                .to_string();

        let storage_catalog = self.load_storage_volume_catalog(project_id).await?;
        let (mounts, mount_fingerprint) = resolve_mount_resources(
            environment.as_ref().map(|env| &env.config),
            &storage_catalog,
            &self.config.sandbox_provider,
        )?;

        Ok(ResolveContext {
            session_id,
            project_id,
            runtime_config_generation: runtime_generation,
            network,
            expected: ExpectedFingerprint {
                image,
                engine_kind,
                networking,
                env,
                mounts: mount_fingerprint,
                egress_policy_hash,
            },
            memory_mounts: vec![], // populated by caller when memory stores are resolved
            mounts,
            credentials,
            identity_refresh_after_seconds,
        })
    }

    async fn refresh_reused_sandbox_networking(
        &self,
        sandbox: &crate::db::models::JoySafeterSandbox,
        external_id: &str,
        context: &ResolveContext,
    ) -> anyhow::Result<()> {
        if sandbox.networking_status == "ready"
            && sandbox.networking_policy_hash.as_deref()
                == Some(context.expected.egress_policy_hash.as_str())
            && self
                .network_policy_ready
                .get(&sandbox.id)
                .map(|hash| hash.value() == &context.expected.egress_policy_hash)
                .unwrap_or(false)
        {
            debug!(
                sandbox_id = %sandbox.id,
                "Reusing ready Envoy policy without refresh"
            );
            return Ok(());
        }

        let policy_generation = queries::prepare_desired_network_policy(
            &self.pool,
            sandbox.id,
            &context.expected.egress_policy_hash,
        )
        .await?
        .into_generation();
        self.apply_prepared_network_policy(
            sandbox.id,
            external_id,
            context,
            &policy_generation,
            None,
            sandbox_runner_token(sandbox),
        )
        .await
        .with_context(|| format!("failed to refresh Envoy policy for sandbox {}", sandbox.id))?;

        queries::merge_sandbox_config(
            &self.pool,
            sandbox.id,
            &serde_json::json!({"fingerprint": context.expected.to_json()}),
        )
        .await
        .with_context(|| {
            format!(
                "failed to persist refreshed Envoy policy fingerprint for sandbox {}",
                sandbox.id
            )
        })?;
        Ok(())
    }

    /// Setup networking for a pool-claimed sandbox that needs limited networking.
    ///
    /// Pool sandboxes are created with deny-all networking. This method pushes
    /// the session's egress policy (credentials + allowlist) after claim.
    async fn setup_pool_sandbox_networking(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
        context: &ResolveContext,
    ) -> anyhow::Result<()> {
        let policy_generation = queries::prepare_desired_network_policy(
            &self.pool,
            sandbox_id,
            &context.expected.egress_policy_hash,
        )
        .await?
        .into_generation();

        self.apply_prepared_network_policy(
            sandbox_id,
            external_id,
            context,
            &policy_generation,
            None,
            None,
        )
        .await
        .with_context(|| {
            format!("failed to setup Envoy policy for pool-claimed sandbox {sandbox_id}")
        })?;
        info!(
            sandbox_id = %sandbox_id,
            policy_hash = %context.expected.egress_policy_hash,
            "Setup networking for pool-claimed sandbox"
        );
        Ok(())
    }

    pub(crate) async fn task_identity_refresh_delay(
        &self,
        sandbox_id: SandboxId,
        task_id: TaskId,
    ) -> anyhow::Result<Option<std::time::Duration>> {
        let Some(sandbox) = queries::get_sandbox(&self.pool, sandbox_id).await? else {
            return Ok(None);
        };
        if !identity_lease_matches(sandbox.config.as_ref(), task_id) {
            return Ok(None);
        }
        let Some(seconds) = identity_lease_refresh_after_seconds(sandbox.config.as_ref()) else {
            return Ok(None);
        };
        Ok(Some(if sandbox.networking_status == "ready" {
            std::time::Duration::from_secs(seconds.max(1))
        } else {
            std::time::Duration::ZERO
        }))
    }

    pub(crate) async fn refresh_task_agent_identity_policy(
        &self,
        task_id: TaskId,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<Option<u64>> {
        let task = queries::get_task(&self.pool, task_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh task no longer exists"))?;
        if task.sandbox_id != Some(sandbox_id) || task.status != "running" {
            return Ok(None);
        }
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh sandbox no longer exists"))?;
        if !identity_lease_matches(sandbox.config.as_ref(), task_id) {
            return Ok(None);
        }
        let session_id = task
            .session_id
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh task has no session"))?;
        let agent_id = task
            .agent_id
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh task has no agent"))?;
        let external_id = sandbox
            .external_id
            .as_deref()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh sandbox has no external_id"))?;
        let context = self
            .build_resolve_context(task_id, Some(session_id), Some(agent_id), task.project_id)
            .await?;
        if !context.has_task_identity() {
            anyhow::bail!("Agent Identity lease exists without a dynamic identity route");
        }
        let latest = queries::get_task(&self.pool, task_id).await?;
        if !matches!(latest, Some(ref current) if current.status == "running" && current.sandbox_id == Some(sandbox_id))
        {
            return Ok(None);
        }
        self.refresh_reused_sandbox_networking(&sandbox, external_id, &context)
            .await?;
        Ok(context.identity_refresh_after_seconds)
    }

    pub(crate) async fn clear_task_agent_identity_policy(
        &self,
        sandbox_id: SandboxId,
        task_id: TaskId,
    ) -> anyhow::Result<bool> {
        let Some(sandbox) = queries::get_sandbox(&self.pool, sandbox_id).await? else {
            return Ok(false);
        };
        if !identity_lease_matches(sandbox.config.as_ref(), task_id) {
            return Ok(false);
        }

        let cleanup_result = crate::kernel::network_policy::application::request_reconcile(
            &self.pool,
            self.network_policy_runtime.as_ref(),
            self.network_policy_material_resolver.as_ref(),
            &sandbox,
            self.network_policy_queue.as_deref(),
            &self.xds_authority,
        )
        .await;
        let policy_hash = match cleanup_result {
            Ok(crate::kernel::network_policy::application::NetworkingReconcileOutcome::Refreshed { policy_hash })
            | Ok(crate::kernel::network_policy::application::NetworkingReconcileOutcome::AlreadyReady { policy_hash }) => policy_hash,
            Ok(crate::kernel::network_policy::application::NetworkingReconcileOutcome::NotLimited) => {
                anyhow::bail!("Agent Identity lease exists on a non-limited sandbox")
            }
            Err(error) => {
                let reason = format!("Agent Identity cleanup failed: {error:#}");
                let _ = queries::mark_sandbox_error(&self.pool, sandbox_id, Some(&reason)).await;
                let destroyed = self
                    .destroy_observed_sandbox(&sandbox, "Agent Identity cleanup failure")
                    .await
                    .context("failed to destroy sandbox after Agent Identity cleanup failure")?;
                if !destroyed {
                    anyhow::bail!(
                        "sandbox {sandbox_id} changed state before failed identity cleanup could destroy it"
                    );
                }
                return Err(error);
            }
        };

        let mut fingerprint = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        if let Some(object) = fingerprint.as_object_mut() {
            object.insert(
                "egress_policy_hash".to_string(),
                serde_json::Value::String(policy_hash.clone()),
            );
        }
        if !queries::merge_sandbox_config(
            &self.pool,
            sandbox_id,
            &serde_json::json!({
                "fingerprint": fingerprint,
                "agent_identity_lease": null,
            }),
        )
        .await?
        {
            anyhow::bail!("sandbox {sandbox_id} disappeared before identity cleanup persistence");
        }
        self.network_policy_ready.insert(sandbox_id, policy_hash);
        Ok(true)
    }

    async fn load_storage_volume_catalog(
        &self,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<serde_json::Value> {
        let Some(project_id) = project_id else {
            return Ok(serde_json::Value::Object(serde_json::Map::new()));
        };
        let rows = {
            sqlx::query(
                r#"
                SELECT v.volume_ref, v.backend_type, v.max_access AS volume_max_access,
                       v.allowed_prefixes AS volume_allowed_prefixes, v.docker, v.k8s,
                       og.max_access AS org_grant_max_access, og.allowed_prefixes AS org_grant_allowed_prefixes,
                       g.max_access AS grant_max_access, g.allowed_prefixes AS grant_allowed_prefixes
                  FROM joysafeter_storage_volumes v
                  JOIN joysafeter_organization_projects p ON p.id = $1
                  JOIN joysafeter_storage_organization_grants og
                    ON og.volume_id = v.id AND og.org_id = p.org_id
                  JOIN joysafeter_storage_project_grants g ON g.volume_id = v.id
                 WHERE v.deleted_at IS NULL
                   AND v.enabled IS TRUE
                   AND og.enabled IS TRUE
                   AND g.enabled IS TRUE
                   AND g.project_id = $1
                "#,
            )
            .bind(project_id)
            .fetch_all(&self.pool)
            .await?
        };

        let mut map = serde_json::Map::new();
        for row in rows {
            let volume_ref: String = row.try_get("volume_ref")?;
            let backend_type: String = row.try_get("backend_type")?;
            let volume_max_access: String = row.try_get("volume_max_access")?;
            let org_grant_max_access: Option<String> = row.try_get("org_grant_max_access")?;
            let grant_max_access: Option<String> = row.try_get("grant_max_access")?;
            let volume_allowed_prefixes: serde_json::Value =
                row.try_get("volume_allowed_prefixes")?;
            let org_grant_allowed_prefixes: Option<serde_json::Value> =
                row.try_get("org_grant_allowed_prefixes")?;
            let grant_allowed_prefixes: Option<serde_json::Value> =
                row.try_get("grant_allowed_prefixes")?;
            let docker: serde_json::Value = row.try_get("docker")?;
            let k8s: serde_json::Value = row.try_get("k8s")?;
            let volume_prefixes = volume_allowed_prefixes
                .as_array()
                .cloned()
                .unwrap_or_default();
            let grant_prefixes = grant_allowed_prefixes
                .as_ref()
                .and_then(|value| value.as_array().cloned())
                .unwrap_or_default();
            let org_grant_prefixes = org_grant_allowed_prefixes
                .as_ref()
                .and_then(|value| value.as_array().cloned())
                .unwrap_or_default();
            let allowed_prefixes =
                effective_prefixes(vec![volume_prefixes, org_grant_prefixes, grant_prefixes]);
            let max_access = if volume_max_access == "read_only"
                || org_grant_max_access.as_deref() == Some("read_only")
                || grant_max_access.as_deref() == Some("read_only")
            {
                "read_only"
            } else {
                "read_write"
            };
            map.insert(
                volume_ref,
                serde_json::json!({
                    "backend_type": backend_type,
                    "max_access": max_access,
                    "allowed_prefixes": allowed_prefixes,
                    "docker": docker,
                    "k8s": k8s,
                }),
            );
        }
        Ok(serde_json::Value::Object(map))
    }

    /// Resolve task-scoped agent identity via the pluggable provider.
    async fn resolve_identity_injection(
        &self,
        agent: Option<&JoySafeterAgent>,
        task_id: TaskId,
        session_id: Option<SessionId>,
        project_id: Option<ProjectId>,
        candidate_targets: &[crate::kernel::agent_identity_provider::IdentityEgressRequestTarget],
    ) -> Result<
        Option<crate::kernel::agent_identity_provider::AgentIdentityInjection>,
        TaskIdentityContextError,
    > {
        use crate::kernel::agent_identity_provider::IdentityResolveContext;

        let agent = agent.ok_or(TaskIdentityContextError::ScopeMissing)?;
        // Provider config is optional (global mode); pass agent_identity block if
        // present, otherwise an empty object.
        let provider_config = agent
            .metadata
            .as_ref()
            .and_then(|m| m.get("agent_identity"))
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));

        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;
        let captured_identity_ctx = self
            .load_identity_context_for_update(&mut transaction, task_id, project_id)
            .await?;
        let has_captured_material = captured_identity_ctx.is_some();
        let identity_ctx = match captured_identity_ctx {
            Some(context) => context,
            None => {
                self.load_task_actor_context_for_update(&mut transaction, task_id, project_id)
                    .await?
            }
        };
        if candidate_targets.is_empty()
            || candidate_targets.iter().any(|target| {
                !Self::identity_host_allowed(&target.host, &self.identity_allowed_hosts)
            })
        {
            return Err(TaskIdentityContextError::NoTrustedHosts);
        }
        if has_captured_material
            && !Self::consume_locked_identity_context(&mut transaction, task_id, project_id).await?
        {
            return Err(TaskIdentityContextError::ClaimConflict);
        }
        transaction
            .commit()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;

        let mut egress_targets = candidate_targets.to_vec();
        egress_targets.sort_by(|left, right| left.route_id.cmp(&right.route_id));
        egress_targets.dedup_by(|left, right| left.route_id == right.route_id);
        if egress_targets.is_empty() {
            return Err(TaskIdentityContextError::NoTrustedHosts);
        }
        debug!(
            agent_id = %agent.id,
            targets = egress_targets.len(),
            "agent identity: resolving with environment routes"
        );

        let context = IdentityResolveContext {
            project_id: project_id.ok_or(TaskIdentityContextError::ScopeMissing)?,
            user_id: identity_ctx.user_id,
            agent_id: agent.id,
            session_id: session_id.ok_or(TaskIdentityContextError::ScopeMissing)?,
            task_id,
            identity_token: identity_ctx.identity_token,
            headers_map: identity_ctx.headers_map,
            auth_code: identity_ctx.auth_code,
            user_name: identity_ctx.user_name,
            provider_config,
            egress_targets,
        };

        match self.identity_provider.resolve(&context).await {
            Ok(injection) if !injection.targets.is_empty() => Ok(Some(injection)),
            Ok(_) => Err(TaskIdentityContextError::EmptyInjection),
            Err(e) => {
                warn!(
                    agent_id = %agent.id,
                    error = %e,
                    "agent identity provider failed"
                );
                Err(TaskIdentityContextError::Provider)
            }
        }
    }

    async fn load_task_actor_context_for_update(
        &self,
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<LoadedIdentityContext, TaskIdentityContextError> {
        let row: Option<(Option<ProjectId>, Option<UserId>, Option<String>)> = sqlx::query_as(
            r#"
            SELECT task.project_id, task.user_id, actor.email
            FROM joysafeter_tasks AS task
            LEFT JOIN joysafeter_users AS actor ON actor.id = task.user_id
            WHERE task.id = $1
            FOR UPDATE OF task
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some((task_project_id, user_id, user_name)) = row else {
            return Err(TaskIdentityContextError::Database);
        };
        if task_project_id != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }
        let user_id = user_id.ok_or(TaskIdentityContextError::ActorMissing)?;
        Ok(LoadedIdentityContext {
            identity_token: String::new(),
            headers_map: HashMap::new(),
            auth_code: None,
            user_name: user_name.unwrap_or_else(|| user_id.to_public()),
            user_id,
        })
    }

    async fn load_identity_context_for_update(
        &self,
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let persisted_project: Option<Option<ProjectId>> = sqlx::query_scalar(
            r#"
            SELECT project_id
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
            FOR UPDATE
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some(persisted_project) = persisted_project else {
            return Ok(None);
        };
        if persisted_project != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }

        let row: Option<PersistedIdentityRow> = sqlx::query_as(
            r#"
            SELECT user_id, user_name, credential_kind, encrypted_credential
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
              AND consumed_at IS NULL
              AND expires_at > NOW()
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;

        self.decode_identity_context(task_id, require_identity_material(row)?)
    }

    async fn load_identity_context(
        &self,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let persisted_project: Option<Option<ProjectId>> = sqlx::query_scalar(
            r#"
            SELECT project_id
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
            "#,
        )
        .bind(task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some(persisted_project) = persisted_project else {
            return Ok(None);
        };
        if persisted_project != project_id {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }

        let row: Option<PersistedIdentityRow> = sqlx::query_as(
            r#"
            SELECT user_id, user_name, credential_kind, encrypted_credential
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
              AND consumed_at IS NULL
              AND expires_at > NOW()
            "#,
        )
        .bind(task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;

        self.decode_identity_context(task_id, require_identity_material(row)?)
    }

    fn decode_identity_context(
        &self,
        _task_id: TaskId,
        row: Option<LoadedIdentityRow>,
    ) -> Result<Option<LoadedIdentityContext>, TaskIdentityContextError> {
        let Some((user_id, user_name, credential_kind, encrypted_credential)) = row else {
            return Ok(None);
        };
        let credential = match &self.task_identity_material {
            Some(material) => material.reveal(&encrypted_credential)?,
            None => TaskIdentityMaterialAdapter::from_env().reveal(&encrypted_credential)?,
        };
        let (identity_token, headers_map, auth_code) =
            decode_revealed_identity_material(&credential_kind, credential)?;

        Ok(Some(LoadedIdentityContext {
            identity_token,
            headers_map,
            auth_code,
            user_name: user_name.unwrap_or_else(|| user_id.to_public()),
            user_id,
        }))
    }

    async fn consume_locked_identity_context(
        transaction: &mut Transaction<'_, Postgres>,
        task_id: TaskId,
        project_id: Option<ProjectId>,
    ) -> Result<bool, TaskIdentityContextError> {
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_task_identity_contexts
            SET consumed_at = NOW(), erased_at = NOW(), encrypted_credential = NULL, updated_at = NOW()
            WHERE task_id = $1
              AND project_id IS NOT DISTINCT FROM $2
              AND consumed_at IS NULL
              AND expires_at > NOW()
              AND encrypted_credential IS NOT NULL
            "#,
        )
        .bind(task_id)
        .bind(project_id)
        .execute(&mut **transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        Ok(result.rows_affected() == 1)
    }

    fn identity_allowed_hosts_from_env() -> Vec<String> {
        std::env::var("AGENT_IDENTITY_ALLOWED_HOSTS")
            .unwrap_or_default()
            .split(',')
            .map(|host| host.trim().trim_end_matches('.').to_lowercase())
            .filter(|host| !host.is_empty())
            .collect()
    }

    fn identity_host_allowed(host: &str, allowed_hosts: &[String]) -> bool {
        let host = host.trim().trim_end_matches('.').to_lowercase();
        allowed_hosts.iter().any(|allowed| {
            if let Some(suffix) = allowed.strip_prefix("*.") {
                host != suffix && host.ends_with(&format!(".{suffix}"))
            } else {
                host == *allowed
            }
        })
    }

    fn merge_identity_into_routes(
        routes: &mut [EgressCredentialRoute],
        injection: crate::kernel::agent_identity_provider::AgentIdentityInjection,
    ) -> Result<(), TaskIdentityContextError> {
        for target in injection.targets {
            let route = routes
                .iter_mut()
                .find(|route| route.id == target.route_id)
                .ok_or(TaskIdentityContextError::RouteMismatch)?;
            if !route.upstream_host.eq_ignore_ascii_case(&target.host)
                || route.upstream_port != target.port
                || route.upstream_tls != target.tls
            {
                return Err(TaskIdentityContextError::RouteMismatch);
            }
            for (name, value) in &target.inject_headers {
                route
                    .inject_headers
                    .retain(|(existing, _)| !existing.eq_ignore_ascii_case(name));
                route.inject_headers.push((name.clone(), value.clone()));
            }
            for header in &target.remove_headers {
                if !route
                    .remove_headers
                    .iter()
                    .any(|existing| existing.eq_ignore_ascii_case(header))
                {
                    route.remove_headers.push(header.clone());
                }
            }
        }
        Ok(())
    }

    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        if let Some(queue) = self.network_policy_queue.as_ref() {
            queue
                .publish(NetworkPolicyRequest::remove(sandbox_id))
                .await
        } else {
            self.network_policy_runtime.remove(sandbox_id).await
        }
    }

    async fn cleanup_rejected_new_sandbox(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
        generation: Option<&NetworkPolicyGeneration>,
    ) -> anyhow::Result<bool> {
        self.network_policy_ready.remove(&sandbox_id);
        if let Some(generation) = generation {
            if !queries::begin_owned_sandbox_cleanup(
                &self.pool,
                sandbox_id,
                external_id,
                generation,
            )
            .await?
            {
                let current = queries::get_sandbox(&self.pool, sandbox_id).await?;
                if current.as_ref().is_some_and(|sandbox| {
                    sandbox.networking_status == "ready"
                        && sandbox.networking_policy_hash.as_deref()
                            == Some(&generation.policy_hash)
                        && sandbox.networking_policy_version == generation.policy_version
                        && sandbox.networking_applied_hash.as_deref()
                            == Some(&generation.policy_hash)
                        && sandbox.networking_applied_version == Some(generation.policy_version)
                }) {
                    return Ok(false);
                }
                anyhow::bail!(
                    "sandbox {sandbox_id} cleanup ownership lost for network policy generation {}",
                    generation.policy_version
                );
            }
            return crate::kernel::sandbox_lifecycle::finalize_claimed_sandbox_destroy(
                &self.pool,
                &self.provider,
                self.network_policy_runtime.as_ref(),
                self.network_policy_queue.as_deref(),
                sandbox_id,
                Some(external_id),
                "creating",
                "failed new-sandbox networking",
            )
            .await;
        }

        if queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .is_none()
        {
            crate::kernel::sandbox_lifecycle::destroy_unpersisted_sandbox(
                &self.provider,
                self.network_policy_runtime.as_ref(),
                self.network_policy_queue.as_deref(),
                sandbox_id,
                external_id,
                "rejected new sandbox",
            )
            .await
            .map_err(|error| RuntimeFreshnessError::CleanupFailed(error.to_string()))?;
            return Ok(true);
        }

        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
            self.network_policy_runtime.as_ref(),
            self.network_policy_queue.as_deref(),
            sandbox_id,
            "creating",
            Some(external_id),
            "rejected new sandbox",
        )
        .await
    }

    async fn destroy_observed_sandbox(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
            self.network_policy_runtime.as_ref(),
            self.network_policy_queue.as_deref(),
            sandbox.id,
            &sandbox.status,
            sandbox.external_id.as_deref(),
            reason,
        )
        .await
    }

    async fn destroy_unattached_pool_claim(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
        // Pool-claim rows use a bespoke claim (status may be `creating` or
        // `provisioning`); the claim returns the prior status to restore on
        // failure. The destroy/finalize protocol is then shared.
        let previous_status = queries::claim_unattached_pool_sandbox_for_passive_destroy(
            &self.pool,
            sandbox.id,
            sandbox.external_id.as_deref(),
        )
        .await?;

        let Some(previous_status) = previous_status else {
            warn!(sandbox_id = %sandbox.id, reason, "Skipped pool-claim provider destroy because DB row changed before cleanup");
            return Ok(false);
        };

        crate::kernel::sandbox_lifecycle::finalize_claimed_sandbox_destroy(
            &self.pool,
            &self.provider,
            self.network_policy_runtime.as_ref(),
            self.network_policy_queue.as_deref(),
            sandbox.id,
            sandbox.external_id.as_deref(),
            &previous_status,
            reason,
        )
        .await
    }

    async fn cleanup_attached_pool_claim(
        &self,
        claim: &queries::AttachedPoolSandboxClaim,
        reason: &str,
    ) -> anyhow::Result<()> {
        let claimed =
            queries::claim_attached_pool_sandbox_for_cleanup_guarded(&self.pool, claim, reason)
                .await
                .map_err(anyhow::Error::new)?;
        if !claimed {
            return Err(RuntimeFreshnessError::Conflict(format!(
                "attached pool sandbox {} changed before cleanup",
                claim.sandbox_id
            ))
            .into());
        }

        if let Some(external_id) = claim.external_id.as_deref() {
            if let Err(error) = self.provider.destroy(external_id).await {
                return Err(RuntimeFreshnessError::CleanupFailed(format!(
                    "failed to destroy attached pool sandbox {} during {reason}: {error}",
                    claim.sandbox_id
                ))
                .into());
            }
        }

        let destroyed = queries::destroy_sandbox_if_status_and_external_id(
            &self.pool,
            claim.sandbox_id,
            "stopping",
            claim.external_id.as_deref(),
        )
        .await?;
        if !destroyed {
            return Err(RuntimeFreshnessError::Conflict(format!(
                "attached pool sandbox {} changed before cleanup finalization",
                claim.sandbox_id
            ))
            .into());
        }
        let _ = self.teardown_networking(claim.sandbox_id).await;
        Ok(())
    }

    async fn attached_pool_claim_is_current(
        &self,
        claim: &queries::AttachedPoolSandboxClaim,
    ) -> anyhow::Result<bool> {
        let current = sqlx::query_as::<
            _,
            (
                Option<SessionId>,
                Option<ProjectId>,
                String,
                String,
                i64,
                Option<serde_json::Value>,
            ),
        >(
            r#"
            SELECT chat_session_id, project_id, status, runtime_config_status,
                   runtime_config_applied_generation, config->'fingerprint'
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND destroyed_at IS NULL
            "#,
        )
        .bind(claim.sandbox_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(matches!(
            current,
            Some((session_id, project_id, status, runtime_status, applied_generation, fingerprint))
                if session_id == Some(claim.session_id)
                    && project_id == claim.project_id
                    && matches!(status.as_str(), "provisioning" | "idle" | "running")
                    && runtime_status == "ready"
                    && applied_generation == claim.claimed_runtime_config_applied_generation
                    && fingerprint.as_ref() == Some(&claim.config_fingerprint)
        ))
    }

    async fn restart_stopped_sandbox(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
        context: &ResolveContext,
    ) -> anyhow::Result<bool> {
        let session_id = context
            .session_id
            .ok_or_else(|| anyhow::anyhow!("stopped sandbox restart requires a session"))?;
        let claim = match queries::claim_stopped_sandbox_for_restart_guarded(
            &self.pool,
            sandbox_id,
            external_id,
            session_id,
            context.project_id,
            context.runtime_config_generation,
        )
        .await
        {
            Ok(claim) => claim,
            Err(error @ RuntimeFreshnessError::Conflict(_)) => {
                if let Some(status) = self.active_sandbox_status(sandbox_id, external_id).await? {
                    debug!(
                        sandbox_id = %sandbox_id,
                        status = %status,
                        "Stopped sandbox became active before restart claim"
                    );
                    return Ok(true);
                }
                return Err(error.into());
            }
            Err(error) => return Err(error.into()),
        };

        // Verify the runtime still exists. In K8s, pods cannot be "restarted"
        // once deleted; provider.start() is a no-op and the pod will never come
        // back. Without this check the sandbox transitions to provisioning and
        // waits indefinitely for a runner that never connects. Return false so
        // the caller falls through to create a fresh sandbox instead.
        use crate::sandbox::provider::SandboxStatus;
        match self.provider.status(external_id).await {
            Ok(SandboxStatus::NotFound | SandboxStatus::Unknown(_)) => {
                // Pod/container doesn't exist — can't restart.
                self.compensate_failed_stopped_restart(sandbox_id, external_id, &claim)
                    .await?;
                debug!(
                    sandbox_id = %sandbox_id,
                    "Cannot restart stopped sandbox — runtime gone (pod deleted); will create new"
                );
                return Ok(false);
            }
            Ok(SandboxStatus::Running) => {
                // Still alive somehow (unusual for "stopped" in DB) — proceed.
            }
            Ok(SandboxStatus::Stopped) => {
                // Docker: container stopped but exists, can be restarted.
                // K8s: shouldn't reach here (deleted pods are NotFound).
                // Proceed with start() attempt.
            }
            Err(_) => {
                // Provider check failed — be conservative, don't restart.
                self.compensate_failed_stopped_restart(sandbox_id, external_id, &claim)
                    .await?;
                return Ok(false);
            }
        }

        if self.provider.start(external_id).await.is_err() {
            self.compensate_failed_stopped_restart(sandbox_id, external_id, &claim)
                .await?;
            return Ok(false);
        }

        if let Some(status) = self.active_sandbox_status(sandbox_id, external_id).await? {
            debug!(
                sandbox_id = %sandbox_id,
                status = %status,
                "Restarted stopped sandbox remains active after provider start"
            );
            return Ok(true);
        }

        anyhow::bail!("stopped sandbox {sandbox_id} changed state during restart");
    }

    async fn compensate_failed_stopped_restart(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
        claim: &queries::GuardedStoppedSandboxRestartClaim,
    ) -> anyhow::Result<()> {
        let restored = queries::restore_stopped_sandbox_after_restart_start_failure_guarded(
            &self.pool,
            sandbox_id,
            external_id,
            claim,
        )
        .await?;
        if !restored {
            return Err(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id }.into());
        }
        Ok(())
    }

    async fn active_sandbox_status(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
    ) -> anyhow::Result<Option<String>> {
        let Some(sandbox) = queries::get_sandbox(&self.pool, sandbox_id).await? else {
            return Ok(None);
        };
        if sandbox.external_id.as_deref() != Some(external_id) {
            return Ok(None);
        }
        if matches!(sandbox.status.as_str(), "idle" | "running" | "provisioning") {
            return Ok(Some(sandbox.status));
        }
        Ok(None)
    }

    fn engine_kind_for_image(&self, image: &str) -> String {
        if !self.config.image_codex.is_empty() && image == self.config.image_codex {
            return "codex".to_string();
        }
        if !self.config.image_native.is_empty() && image == self.config.image_native {
            return "native".to_string();
        }
        if !self.config.image_pi.is_empty() && image == self.config.image_pi {
            return "pi".to_string();
        }
        if !self.config.image_claude.is_empty() && image == self.config.image_claude {
            return "claude".to_string();
        }
        if image == self.config.sandbox_image {
            return "claude".to_string();
        }

        let lower = image.to_ascii_lowercase();
        if lower.contains("codex") {
            "codex".to_string()
        } else if lower.contains("native") {
            "native".to_string()
        } else if lower.contains("pi") {
            "pi".to_string()
        } else {
            "claude".to_string()
        }
    }

    async fn patch_claimed_pool_labels(
        &self,
        external_id: &str,
        session_id: Option<SessionId>,
        context: &ResolveContext,
    ) -> anyhow::Result<()> {
        let mut labels = HashMap::new();
        labels.insert(
            "joysafeter.engine_kind".to_string(),
            context.expected.engine_kind.clone(),
        );
        labels.insert("joysafeter.pool".to_string(), "false".to_string());
        labels.insert("joysafeter.claimed".to_string(), "true".to_string());
        labels.insert("joysafeter.allocation".to_string(), "session".to_string());
        if let Some(sid) = session_id {
            labels.insert("joysafeter.session_id".to_string(), sid.to_string());
        }
        if let Some(project_id) = context.project_id.as_ref() {
            labels.insert("joysafeter.project_id".to_string(), project_id.to_public());
        }
        self.provider.patch_labels(external_id, &labels).await
    }

    /// Provision a warm-pool sandbox (called from SandboxController).
    pub async fn provision_pool_sandbox(&self, image: &str) -> anyhow::Result<SandboxId> {
        let sandbox_db_id = SandboxId::from_uuid(Uuid::now_v7());
        let runner_token = generate_runner_token();

        let mut env = HashMap::new();
        apply_sandbox_timezone(&mut env, &self.config.sandbox_timezone);
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.as_uuid().to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());
        apply_claude_code_sandbox_privacy(&mut env);
        if !self.config.sandbox_timezone.trim().is_empty() {
            env.insert("TZ".to_string(), self.config.sandbox_timezone.clone());
        }

        let grpc_url = self.provider.orchestrator_url(self.config.grpc_port);
        env.insert("JOYSAFETER_ORCHESTRATOR_URL".to_string(), grpc_url.clone());

        let engine_kind = self.engine_kind_for_image(image);

        let create_config = SandboxCreateConfig {
            sandbox_id: sandbox_db_id,
            image: image.to_string(),
            env,
            labels: [
                ("joysafeter".to_string(), "true".to_string()),
                ("joysafeter.managed".to_string(), "true".to_string()),
                (
                    "joysafeter.sandbox_id".to_string(),
                    sandbox_db_id.as_uuid().to_string(),
                ),
                (
                    "joysafeter.owner_instance_id".to_string(),
                    self.config.instance_id.clone(),
                ),
                (
                    "joysafeter.created_at_unix".to_string(),
                    chrono::Utc::now().timestamp().to_string(),
                ),
                ("joysafeter.engine_kind".to_string(), engine_kind.clone()),
                ("joysafeter.pool".to_string(), "true".to_string()),
                ("joysafeter.claimed".to_string(), "false".to_string()),
                ("joysafeter.allocation".to_string(), "pool".to_string()),
            ]
            .into(),
            cpu_limit: self.config.sandbox_cpu,
            memory_limit_mb: self.config.sandbox_memory_mb,
            network: None,
            start_immediately: true,
            // Warm-pool sandboxes are not bound to a session yet. Mounting the
            // workspace root here would expose every persisted session
            // workspace under /workspace inside an otherwise idle pooled
            // container. Session sandboxes still mount root/session_id in
            // resolve_sandbox above.
            workspace_path: None,
            memory_mounts: vec![],
            mounts: vec![],
        };

        let expected = ExpectedFingerprint {
            image: image.to_string(),
            engine_kind: engine_kind.clone(),
            networking: None,
            env: create_config.env.clone(),
            mounts: vec![],
            egress_policy_hash: DesiredNetworkPolicy::from_inputs(
                None,
                &SandboxCredentials::default(),
            )
            .expect("empty sandbox policy must be valid")
            .revision()
            .to_string(),
        };
        let sandbox_config = provisioning_config(
            "pool_warm",
            100,
            "Warm pooled sandbox ready for claim",
            true,
            &expected,
            Some(&runner_token),
        );

        // #23: Create container first, then DB record (matching Python provision_pool_sandbox)
        let external_id = self.provider.create(&create_config).await?;

        // S4 fix: if DB insert fails, destroy the container to prevent leak
        let db_result = queries::create_sandbox(
            &self.pool,
            sandbox_db_id,
            &external_id,
            self.config.sandbox_provider.as_str(),
            image,
            None,
            None,
            create_config.workspace_path.as_deref(),
            Some(&sandbox_config),
        )
        .await;

        if let Err(e) = db_result {
            warn!(sandbox_id = %sandbox_db_id, "DB insert failed for pool sandbox, destroying container");
            let _ = self.provider.destroy(&external_id).await;
            return Err(e.into());
        }

        if !queries::mark_pool_sandbox_ready(&self.pool, sandbox_db_id).await? {
            warn!(
                sandbox_id = %sandbox_db_id,
                "Warm pool sandbox changed state before ready finalization"
            );
            match queries::get_sandbox(&self.pool, sandbox_db_id).await? {
                Some(ref sandbox)
                    if sandbox.external_id.as_deref() == Some(external_id.as_str()) =>
                {
                    if let Err(cleanup_err) = self
                        .destroy_unattached_pool_claim(sandbox, "pool ready finalization failure")
                        .await
                    {
                        warn!(
                            sandbox_id = %sandbox_db_id,
                            error = %cleanup_err,
                            "Failed to cleanup warm-pool sandbox after ready finalization failure"
                        );
                    }
                }
                Some(_) => {
                    warn!(
                        sandbox_id = %sandbox_db_id,
                        "Skipped warm-pool provider destroy because external id changed before cleanup"
                    );
                }
                None => {
                    warn!(
                        sandbox_id = %sandbox_db_id,
                        "Skipped warm-pool provider destroy because DB row disappeared before cleanup"
                    );
                }
            }
            return Err(anyhow::anyhow!(
                "warm pool sandbox {sandbox_db_id} changed state before ready finalization"
            ));
        }

        info!(sandbox_id = %sandbox_db_id, image = image, "Provisioned pool sandbox");
        Ok(sandbox_db_id)
    }
}

fn identity_lease_metadata(
    task_id: TaskId,
    refresh_after_seconds: Option<u64>,
) -> serde_json::Value {
    serde_json::json!({
        "task_id": task_id.to_string(),
        "refresh_after_seconds": refresh_after_seconds,
    })
}

fn identity_lease_matches(config: Option<&serde_json::Value>, task_id: TaskId) -> bool {
    config
        .and_then(|value| value.get("agent_identity_lease"))
        .and_then(|lease| lease.get("task_id"))
        .and_then(serde_json::Value::as_str)
        == Some(task_id.to_string().as_str())
}

fn identity_lease_refresh_after_seconds(config: Option<&serde_json::Value>) -> Option<u64> {
    config
        .and_then(|value| value.get("agent_identity_lease"))
        .and_then(|lease| lease.get("refresh_after_seconds"))
        .and_then(serde_json::Value::as_u64)
}

#[derive(Debug, Clone)]
struct ExpectedFingerprint {
    image: String,
    engine_kind: String,
    networking: Option<serde_json::Value>,
    env: HashMap<String, String>,
    mounts: Vec<SandboxMountFingerprint>,
    egress_policy_hash: String,
}

#[derive(Debug, Clone)]
struct ResolveContext {
    session_id: Option<SessionId>,
    project_id: Option<ProjectId>,
    runtime_config_generation: i64,
    network: Option<String>,
    expected: ExpectedFingerprint,
    /// Memory store bind mounts: (host_path, container_mount_path).
    memory_mounts: Vec<(String, String)>,
    /// Platform-resolved sandbox mounts.
    mounts: Vec<SandboxMount>,
    /// Secret-bearing egress routes resolved for this task. These remain
    /// process-local and are never serialized into PostgreSQL or Redis.
    credentials: SandboxCredentials,
    /// Provider-advertised lifetime for task-scoped identity credentials.
    identity_refresh_after_seconds: Option<u64>,
}

impl ResolveContext {
    fn is_limited_networking(&self) -> bool {
        self.network.as_deref() == Some("none")
    }

    fn resolved(&self, sandbox_id: SandboxId, external_id: String) -> ResolvedSandbox {
        ResolvedSandbox {
            sandbox_id,
            external_id,
            runtime_config_generation: self.runtime_config_generation,
            identity_refresh_after_seconds: self.identity_refresh_after_seconds,
        }
    }

    fn has_task_identity(&self) -> bool {
        self.credentials.routes.iter().any(|route| {
            route.id.starts_with("external-identity:") && !route.inject_headers.is_empty()
        })
    }
}

#[derive(Debug, Clone)]
pub struct ResolvedSandbox {
    pub sandbox_id: SandboxId,
    pub external_id: String,
    pub runtime_config_generation: i64,
    pub identity_refresh_after_seconds: Option<u64>,
}

impl ExpectedFingerprint {
    fn to_json(&self) -> serde_json::Value {
        let env_hashes = self
            .env
            .iter()
            .map(|(key, value)| {
                let mut hasher = Sha256::new();
                hasher.update(value.as_bytes());
                (
                    key.clone(),
                    serde_json::Value::String(hex::encode(hasher.finalize())),
                )
            })
            .collect::<serde_json::Map<_, _>>();
        serde_json::json!({
            "image": self.image,
            "engine_kind": self.engine_kind,
            "networking": self.networking.clone().unwrap_or_else(|| serde_json::json!({})),
            "env": env_hashes,
            "mounts": self.mounts,
            "egress_policy_hash": self.egress_policy_hash,
        })
    }
}

fn runtime_fingerprint_matches(
    config: Option<&serde_json::Value>,
    sandbox_image: Option<&str>,
    expected: &ExpectedFingerprint,
) -> bool {
    let Some(config) = config else {
        return sandbox_image == Some(expected.image.as_str());
    };
    match config.get("fingerprint") {
        Some(actual) => {
            let mut actual_runtime = actual.clone();
            if let Some(obj) = actual_runtime.as_object_mut() {
                obj.remove("egress_policy_hash");
            }
            let mut expected_runtime = expected.to_json();
            if let Some(obj) = expected_runtime.as_object_mut() {
                obj.remove("egress_policy_hash");
            }
            actual_runtime == expected_runtime
        }
        None => sandbox_image == Some(expected.image.as_str()),
    }
}

fn provisioning_config(
    stage: &str,
    progress: i64,
    message: &str,
    complete: bool,
    expected: &ExpectedFingerprint,
    runner_token: Option<&str>,
) -> serde_json::Value {
    let mut config = serde_json::json!({
        "provisioning": {
            "stage": stage,
            "progress": progress,
            "message": message,
            "complete": complete,
            "error": false,
        },
        "fingerprint": expected.to_json(),
    });

    if let Some(token) = runner_token {
        if let Some(obj) = config.as_object_mut() {
            obj.insert(
                "runner_token".to_string(),
                serde_json::Value::String(token.to_string()),
            );
        }
    }

    config
}

/// Generate a random runner token (hex-encoded 32 bytes).
fn generate_runner_token() -> String {
    let random_bytes: [u8; 32] = rand::random();
    hex::encode(random_bytes)
}

fn effective_networking_config(
    networking: Option<serde_json::Value>,
    envoy_enabled: bool,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<Option<serde_json::Value>> {
    match networking_type(networking.as_ref()) {
        Some("limited") => networking
            .map(|networking| sanitize_limited_networking(networking, environment))
            .transpose(),
        Some("unrestricted" | "disabled") => Ok(networking),
        Some(other) => anyhow::bail!("unsupported sandbox networking.type: {other}"),
        None if envoy_enabled => {
            let mut effective = networking.unwrap_or_else(|| serde_json::json!({}));
            let Some(object) = effective.as_object_mut() else {
                anyhow::bail!(
                    "sandbox networking config must be an object when Envoy default-limited networking is enabled"
                );
            };
            object.insert(
                "type".to_string(),
                serde_json::Value::String("limited".to_string()),
            );
            sanitize_limited_networking(effective, environment).map(Some)
        }
        None => Ok(networking),
    }
}

fn networking_type(networking: Option<&serde_json::Value>) -> Option<&str> {
    networking.and_then(|value| value.get("type").and_then(|value| value.as_str()))
}

fn sanitize_limited_networking(
    mut networking: serde_json::Value,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<serde_json::Value> {
    if networking_type(Some(&networking)) != Some("limited") {
        return Ok(networking);
    }

    let mut allowed_hosts = networking
        .get("allowed_hosts")
        .and_then(|value| value.as_array())
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(ToOwned::to_owned))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    // Remove external egress service hosts from allowlist. Each external service
    // emits a transparent credential vhost keyed on its real host. If the same
    // host also appears in allowed_hosts, the `allowed` vhost would declare a
    // duplicate domain and Envoy rejects the config.
    if let Some(egress_hosts) = environment
        .and_then(|env| env.config.get("egress_services"))
        .and_then(|v| v.as_array())
    {
        let external_hosts: Vec<String> = egress_hosts
            .iter()
            .filter_map(|svc| svc.get("base_url").and_then(|v| v.as_str()))
            .filter_map(|url| extract_host(url))
            .collect();
        allowed_hosts.retain(|h| !external_hosts.iter().any(|eh| eh == h));
    }

    let Some(object) = networking.as_object_mut() else {
        return Ok(networking);
    };
    object.insert(
        "allowed_hosts".to_string(),
        serde_json::Value::Array(
            allowed_hosts
                .into_iter()
                .map(serde_json::Value::String)
                .collect(),
        ),
    );
    Ok(networking)
}

fn extract_host(raw_url: &str) -> Option<String> {
    Url::parse(raw_url)
        .ok()
        .and_then(|url| url.host_str().map(ToOwned::to_owned))
}

fn prefix_allows(sub_path: &str, prefixes: &[serde_json::Value]) -> bool {
    let sub_path = sub_path.trim_matches('/');
    if prefixes.is_empty() {
        return sub_path.is_empty();
    }
    prefixes.iter().any(|prefix| {
        let Some(prefix) = prefix.as_str() else {
            return false;
        };
        let prefix = prefix.trim_matches('/');
        prefix.is_empty() || sub_path == prefix || sub_path.starts_with(&format!("{prefix}/"))
    })
}

fn effective_prefixes(prefix_sets: Vec<Vec<serde_json::Value>>) -> Vec<serde_json::Value> {
    let mut constrained: Vec<Vec<serde_json::Value>> = prefix_sets
        .into_iter()
        .filter(|prefixes| !prefixes.is_empty())
        .collect();
    if constrained.is_empty() {
        return Vec::new();
    }
    let mut candidates = constrained.pop().unwrap_or_default();
    while let Some(prefixes) = constrained.pop() {
        let mut next = Vec::new();
        for candidate in &candidates {
            let Some(candidate_str) = candidate.as_str() else {
                continue;
            };
            if prefix_allows(candidate_str, &prefixes) && !next.contains(candidate) {
                next.push(candidate.clone());
            }
        }
        for prefix in &prefixes {
            let Some(prefix_str) = prefix.as_str() else {
                continue;
            };
            if prefix_allows(prefix_str, &candidates) && !next.contains(prefix) {
                next.push(prefix.clone());
            }
        }
        candidates = next;
    }
    candidates
}

#[cfg(test)]
mod egress_tests {
    use super::*;
    use crate::ids::{CredentialGroupId, FileId, OrganizationId, SessionResourceId};
    use async_trait::async_trait;
    use sqlx::postgres::PgPoolOptions;
    use sqlx::PgPool;
    use std::env;
    use std::net::IpAddr;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use tokio::sync::Mutex;

    const ENCRYPTED_HELLO_WORLD: &str =
        "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
    const TEST_IDENTITY_KEY: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];

    struct StaticMcpAddressResolver;

    #[async_trait]
    impl crate::kernel::mcp_network_policy::McpAddressResolver for StaticMcpAddressResolver {
        async fn resolve(
            &self,
            _host: &str,
            _port: u16,
        ) -> Result<Vec<IpAddr>, crate::kernel::mcp_network_policy::McpNetworkPolicyError> {
            Ok(vec!["93.184.216.34".parse().expect("valid public IP")])
        }
    }

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    fn allow(hosts: &[&str]) -> Vec<String> {
        hosts.iter().map(|host| host.to_string()).collect()
    }

    fn identity_target(
        host: &str,
    ) -> crate::kernel::agent_identity_provider::IdentityEgressRequestTarget {
        crate::kernel::agent_identity_provider::IdentityEgressRequestTarget {
            route_id: format!("external-identity:{host}:0"),
            endpoint: format!("https://{host}/"),
            host: host.to_string(),
            port: 443,
            tls: true,
        }
    }

    #[tokio::test]
    async fn external_egress_rejects_malformed_credential_ref() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("create lazy pool");
        let environment = EnvironmentRow {
            config: serde_json::json!({
                "egress_services": [
                    {
                        "name": "secocean",
                        "base_url": "https://secocean.example.com",
                        "credential_ref": "019f891f-6539-71d3-b791-c25814af3efd",
                        "inject": {
                            "type": "cookie",
                            "credential_field": "COOKIE_HEADER"
                        }
                    }
                ]
            }),
            image_tag: None,
        };

        let access = CredentialMaterialAccessService::new(pool.clone());
        let context = CredentialAccessContext::runtime(None, None, None);
        let error = build_external_egress(&access, &context, Some(&environment), None)
            .await
            .expect_err("bare UUID in external egress must fail");

        assert_eq!(
            error.downcast_ref(),
            Some(&CredentialRuntimeError::CorruptRecord)
        );
    }

    #[tokio::test]
    async fn external_egress_rejects_non_string_credential_ref() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("create lazy pool");
        let environment = EnvironmentRow {
            config: serde_json::json!({
                "egress_services": [
                    {
                        "name": "secocean",
                        "base_url": "https://secocean.example.com",
                        "credential_ref": 7,
                        "inject": {
                            "type": "cookie",
                            "credential_field": "COOKIE_HEADER"
                        }
                    }
                ]
            }),
            image_tag: None,
        };

        let access = CredentialMaterialAccessService::new(pool.clone());
        let context = CredentialAccessContext::runtime(None, None, None);
        let error = build_external_egress(&access, &context, Some(&environment), None)
            .await
            .expect_err("non-string external egress credential id must fail");

        assert_eq!(
            error.downcast_ref(),
            Some(&CredentialRuntimeError::CorruptRecord)
        );
    }

    #[tokio::test]
    async fn external_egress_builds_route_scoped_agent_identity_targets() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://localhost/unused")
            .expect("create lazy pool");
        let environment = EnvironmentRow {
            config: serde_json::json!({
                "egress_services": [{
                    "name": "crm-internal",
                    "base_url": "http://crm.internal:8080/api/",
                    "auth_source": "agent_identity",
                    "allowed_paths": ["/customer/"]
                }]
            }),
            image_tag: None,
        };
        let access = CredentialMaterialAccessService::new(pool);
        let context = CredentialAccessContext::runtime(None, None, None);

        let (routes, targets) = build_external_egress(&access, &context, Some(&environment), None)
            .await
            .expect("build identity egress route");

        assert_eq!(routes.len(), 1);
        assert_eq!(routes[0].id, "external-identity:crm-internal:0");
        assert!(routes[0].inject_headers.is_empty());
        assert_eq!(targets.len(), 1);
        assert_eq!(targets[0].route_id, routes[0].id);
        assert_eq!(targets[0].endpoint, "http://crm.internal:8080/api/");
        assert_eq!(targets[0].host, "crm.internal");
        assert_eq!(targets[0].port, 8080);
        assert!(!targets[0].tls);
    }

    #[test]
    fn identity_host_allowlist_is_exact_or_dot_boundary_wildcard() {
        let allowed = vec!["api.example.com".to_string(), "*.trusted.test".to_string()];

        assert!(SandboxResolver::identity_host_allowed(
            "api.example.com",
            &allowed
        ));
        assert!(SandboxResolver::identity_host_allowed(
            "mcp.trusted.test",
            &allowed
        ));
        assert!(!SandboxResolver::identity_host_allowed(
            "evil-api.example.com",
            &allowed
        ));
        assert!(!SandboxResolver::identity_host_allowed(
            "trusted.test",
            &allowed
        ));
        assert!(!SandboxResolver::identity_host_allowed(
            "trusted.test.evil.invalid",
            &allowed
        ));
    }

    #[test]
    fn identity_lease_metadata_uses_canonical_task_id_without_credentials() {
        let task_id = TaskId::new();
        let lease = identity_lease_metadata(task_id, Some(120));

        assert_eq!(lease["task_id"], task_id.to_string());
        assert_eq!(lease["refresh_after_seconds"], 120);
        assert!(lease.get("credential").is_none());
        assert!(lease.get("headers").is_none());
    }

    #[test]
    fn identity_lease_matches_only_the_owning_task() {
        let owner = TaskId::new();
        let other = TaskId::new();
        let config = serde_json::json!({
            "agent_identity_lease": identity_lease_metadata(owner, Some(60))
        });

        assert!(identity_lease_matches(Some(&config), owner));
        assert!(!identity_lease_matches(Some(&config), other));
        assert!(!identity_lease_matches(None, owner));
    }

    #[test]
    fn static_recovery_removes_agent_identity_routes() {
        let mut routes = vec![
            EgressCredentialRoute {
                id: "external-identity:crm:0".to_string(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: "crm.example.com".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix("/api/".to_string()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "crm.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![("authorization".to_string(), "secret".to_string())],
                remove_headers: vec!["authorization".to_string()],
            },
            EgressCredentialRoute {
                id: "external:static:0".to_string(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: "static.example.com".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix("/".to_string()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "static.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![("authorization".to_string(), "static".to_string())],
                remove_headers: vec!["authorization".to_string()],
            },
        ];

        remove_agent_identity_routes(&mut routes);

        assert_eq!(routes.len(), 1);
        assert_eq!(routes[0].id, "external:static:0");
    }

    #[test]
    fn identity_headers_merge_only_into_matching_mcp_placeholder_route() {
        let mut routes = vec![EgressCredentialRoute {
            id: "mcp:trusted".to_string(),
            kind: EgressKind::Mcp,
            exposure: EgressExposure::Placeholder,
            match_host: MCP_EGRESS_HOST.to_string(),
            path_mapping: EgressPathMapping::RewriteExact {
                exposed_path: "/mcp/trusted/".to_string(),
                upstream_path: "/api".to_string(),
            },
            retry_mode: EgressRetryMode::Disabled,
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "Bearer mcp".to_string())],
            remove_headers: vec!["authorization".to_string()],
        }];

        SandboxResolver::merge_identity_into_routes(
            &mut routes,
            crate::kernel::agent_identity_provider::AgentIdentityInjection {
                targets: vec![
                    crate::kernel::agent_identity_provider::IdentityEgressTarget {
                        route_id: "mcp:trusted".to_string(),
                        host: "api.example.com".to_string(),
                        port: 443,
                        tls: true,
                        inject_headers: vec![(
                            "X-Security-AgentToken".to_string(),
                            "agent-token".to_string(),
                        )],
                        remove_headers: vec!["x-security-agenttoken".to_string()],
                    },
                ],
                valid_for_seconds: Some(300),
            },
        )
        .expect("matching route should merge");

        assert_eq!(routes[0].inject_headers.len(), 2);
        assert!(routes[0]
            .inject_headers
            .iter()
            .any(|(name, value)| name == "authorization" && value == "Bearer mcp"));
        assert!(routes[0]
            .inject_headers
            .iter()
            .any(|(name, value)| { name == "X-Security-AgentToken" && value == "agent-token" }));
        assert!(routes[0]
            .remove_headers
            .iter()
            .any(|name| name == "x-security-agenttoken"));
    }

    /// Run `extract_llm_egress` and return the single LLM route it emits, if any.
    /// The builder now returns a `Vec<EgressCredentialRoute>`; LLM egress is
    /// always zero or one route.
    fn extract_llm_route(
        env: &mut HashMap<String, String>,
        provider_id: &str,
        protocol_id: &str,
        allowed_hosts: &[String],
    ) -> Option<EgressCredentialRoute> {
        let binding = crate::kernel::llm_catalog::validate_runtime_secret(
            "native",
            "model",
            Some(provider_id),
            Some(protocol_id),
        )
        .expect("test binding must be Catalog-valid");
        extract_llm_egress(env, Some(&binding), allowed_hosts)
            .into_iter()
            .next()
    }

    fn expected_fingerprint(egress_policy_hash: &str) -> ExpectedFingerprint {
        ExpectedFingerprint {
            image: "joysafeter-agent:latest".to_string(),
            engine_kind: "claude".to_string(),
            networking: Some(serde_json::json!({
                "type": "limited",
                "allowed_hosts": ["api.example.com"]
            })),
            env: HashMap::from([("SAFE_ENV".to_string(), "value".to_string())]),
            mounts: vec![],
            egress_policy_hash: egress_policy_hash.to_string(),
        }
    }

    fn empty_network_policy_revision() -> String {
        DesiredNetworkPolicy::from_inputs(None, &SandboxCredentials::default())
            .expect("empty sandbox policy must be valid")
            .revision()
            .to_string()
    }

    #[test]
    fn sandbox_timezone_uses_platform_default_without_overriding_environment() {
        let mut default_env = HashMap::new();
        apply_sandbox_timezone(&mut default_env, "Asia/Shanghai");
        assert_eq!(
            default_env.get("TZ").map(String::as_str),
            Some("Asia/Shanghai")
        );

        let mut explicit_env = HashMap::from([("TZ".to_string(), "America/New_York".to_string())]);
        apply_sandbox_timezone(&mut explicit_env, "Asia/Shanghai");
        assert_eq!(
            explicit_env.get("TZ").map(String::as_str),
            Some("America/New_York")
        );
    }

    #[test]
    fn claude_code_sandbox_privacy_defaults_without_overriding_environment() {
        let mut default_env = HashMap::new();
        apply_claude_code_sandbox_privacy(&mut default_env);
        assert_eq!(
            default_env.get("DISABLE_TELEMETRY").map(String::as_str),
            Some("1")
        );
        assert_eq!(
            default_env
                .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
                .map(String::as_str),
            Some("1")
        );

        let mut explicit_env = HashMap::from([
            ("DISABLE_TELEMETRY".to_string(), "0".to_string()),
            (
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC".to_string(),
                "0".to_string(),
            ),
        ]);
        apply_claude_code_sandbox_privacy(&mut explicit_env);
        assert_eq!(
            explicit_env.get("DISABLE_TELEMETRY").map(String::as_str),
            Some("0")
        );
        assert_eq!(
            explicit_env
                .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
                .map(String::as_str),
            Some("0")
        );
    }

    #[test]
    fn runtime_fingerprint_ignores_egress_policy_hash_only() {
        let expected = expected_fingerprint("new-policy");
        let mut stored = expected_fingerprint("old-policy").to_json();

        assert!(runtime_fingerprint_matches(
            Some(&serde_json::json!({"fingerprint": stored.clone()})),
            Some("different-column-image"),
            &expected,
        ));

        stored["image"] = serde_json::Value::String("other-image".to_string());
        assert!(!runtime_fingerprint_matches(
            Some(&serde_json::json!({"fingerprint": stored})),
            Some("joysafeter-agent:latest"),
            &expected,
        ));
    }

    #[test]
    fn egress_policy_hash_tracks_header_secret_without_leaking_it() {
        let mut credentials = SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: "external_svc".to_string(),
                kind: EgressKind::External,
                exposure: EgressExposure::Placeholder,
                match_host: "external-egress.internal".to_string(),
                path_mapping: EgressPathMapping::RewritePrefix {
                    exposed_prefix: "/svc/".to_string(),
                    upstream_prefix: "/".to_string(),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "api.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: "external_svc".to_string(),
                vetted_addresses: vec![],
                inject_headers: vec![("authorization".to_string(), "Bearer first".to_string())],
                remove_headers: vec![],
            }],
            proxy_auth_token: None,
        };
        let networking = serde_json::json!({"type": "limited"});

        let first = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials)
            .unwrap()
            .revision();
        credentials.routes[0].inject_headers[0].1 = "Bearer second".to_string();
        let second = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials)
            .unwrap()
            .revision();

        assert_ne!(first, second);
        assert!(!first.to_string().contains("first"));
        assert!(!second.to_string().contains("second"));
    }

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres sandbox resolver test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(3)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    #[tokio::test]
    async fn expired_repository_tokens_are_not_exposed_to_git_egress() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let repo_id = SessionResourceId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();

        let result: anyhow::Result<()> = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("expired-repo-token-agent-{unique}"))
            .bind(serde_json::json!({"id": "claude-sonnet"}))
            .execute(&pool)
            .await?;

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await?;

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_repos (
                    id, session_id, url, branch, mount_path, mount_name,
                    encrypted_token, token_expires_at, token_rotated_at
                )
                VALUES (
                    $1, $2, 'https://github.com/example/private.git', 'main',
                    '/workspace/private', 'private', $3, NOW() - INTERVAL '1 second',
                    NOW() - INTERVAL '1 hour'
                )
                "#,
            )
            .bind(repo_id)
            .bind(session_id)
            .bind(ENCRYPTED_HELLO_WORLD)
            .execute(&pool)
            .await?;

            let routes = build_git_egress(&pool, Some(session_id)).await?;
            anyhow::ensure!(
                routes.is_empty(),
                "expired repository token reached Git egress"
            );
            Ok(())
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_repos WHERE id = $1")
            .bind(repo_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;

        result.expect("expired repository token must be unavailable to Git egress");
    }

    async fn assert_existing_runtime_requires_restart(
        runtime_config_status: &str,
        applied_generation: i64,
    ) {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-runtime-freshness-{unique}:latest");
        let external_id = format!("resolver-runtime-freshness-{sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver freshness system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-runtime-freshness-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-runtime-freshness-model"}))
            .execute(&pool)
            .await
            .expect("insert runtime freshness agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, runtime_config_generation
                )
                VALUES ($1, $2, 'idle', 2)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert runtime freshness session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "runtime_freshness",
                100,
                "Runtime freshness fixture",
                true,
                &expected,
                Some("resolver-runtime-freshness-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create runtime freshness sandbox");
            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET status = 'running',
                    runtime_config_status = $2,
                    runtime_config_applied_generation = $3
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .bind(runtime_config_status)
            .bind(applied_generation)
            .execute(&pool)
            .await
            .expect("set runtime freshness state");

            let provider = Arc::new(RecordingProvider::default());
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image;

            let resolver = recording_resolver(pool.clone(), provider.clone(), config);
            let error = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("stale existing runtime must require an explicit restart");
            assert!(matches!(
                error.downcast_ref::<RuntimeFreshnessError>(),
                Some(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id: id })
                    if *id == sandbox_id
            ));
            assert!(provider.destroyed.lock().await.is_empty());
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;

        result
    }

    #[tokio::test]
    async fn sandbox_resolver_rejects_raw_stale_existing_runtime_without_destroy() {
        assert_existing_runtime_requires_restart("restart_required", 2).await;
    }

    #[tokio::test]
    async fn sandbox_resolver_rejects_generation_mismatched_existing_runtime_without_destroy() {
        assert_existing_runtime_requires_restart("ready", 1).await;
    }

    async fn assert_new_sandbox_generation_rejection_cleanup(destroy_fails: bool) {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-new-generation-{unique}:latest");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver generation system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-new-generation-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-new-generation-model"}))
            .execute(&pool)
            .await
            .expect("insert new generation agent");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, runtime_config_generation
                )
                VALUES ($1, $2, 'idle', 1)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert new generation session");

            let provider = Arc::new(RecordingProvider {
                create_advances_generation: Mutex::new(Some((pool.clone(), session_id))),
                destroy_error: Mutex::new(
                    destroy_fails.then(|| "provider destroy failed".to_string()),
                ),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image;

            let resolver = recording_resolver(pool.clone(), provider.clone(), config);
            let error = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("generation change after provider create must reject activation");
            if destroy_fails {
                assert!(matches!(
                    error.downcast_ref::<RuntimeFreshnessError>(),
                    Some(RuntimeFreshnessError::CleanupFailed(_))
                ));
            } else {
                assert!(matches!(
                    error.downcast_ref::<RuntimeFreshnessError>(),
                    Some(RuntimeFreshnessError::GenerationChanged {
                        expected: 1,
                        actual: 2
                    })
                ));
            }
            assert_eq!(provider.created.lock().await.len(), 1);
            assert_eq!(provider.destroyed.lock().await.len(), 1);
            assert_eq!(provider.networking_teardowns.lock().await.len(), 1);
            let sandbox_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count rejected sandbox rows");
            assert_eq!(sandbox_count, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;

        result
    }

    #[tokio::test]
    async fn sandbox_resolver_destroys_new_provider_after_generation_rejection() {
        assert_new_sandbox_generation_rejection_cleanup(false).await;
    }

    #[tokio::test]
    async fn sandbox_resolver_stops_after_new_provider_cleanup_failure() {
        assert_new_sandbox_generation_rejection_cleanup(true).await;
    }

    #[derive(Default)]
    struct RecordingProvider {
        created: Mutex<Vec<SandboxCreateConfig>>,
        create_advances_generation: Mutex<Option<(PgPool, SessionId)>>,
        networking: Mutex<Vec<(SandboxId, Option<serde_json::Value>)>>,
        networking_credentials: Mutex<Vec<SandboxCredentials>>,
        networking_error: Mutex<Option<String>>,
        networking_teardowns: Mutex<Vec<SandboxId>>,
        start_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
        start_observed_statuses: Mutex<Vec<String>>,
        start_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
        start_error: Mutex<Option<String>>,
        status_marks_idle: Mutex<Option<(PgPool, SandboxId)>>,
        status_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
        status_marks_restart_required: Mutex<Option<(PgPool, SandboxId)>>,
        status_error: Mutex<Option<String>>,
        status_result: Mutex<Option<SandboxStatus>>,
        destroy_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
        destroy_observed_statuses: Mutex<Vec<String>>,
        destroyed: Mutex<Vec<String>>,
        destroy_error: Mutex<Option<String>>,
    }

    #[async_trait]
    impl SandboxProvider for RecordingProvider {
        async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
            self.created.lock().await.push(config.clone());
            if let Some((pool, session_id)) = self.create_advances_generation.lock().await.clone() {
                sqlx::query(
                    r#"
                    UPDATE joysafeter_sessions
                    SET runtime_config_generation = runtime_config_generation + 1
                    WHERE id = $1
                    "#,
                )
                .bind(session_id)
                .execute(&pool)
                .await?;
            }
            Ok(format!("external-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            if let Some((pool, sandbox_id)) = self.start_status_probe.lock().await.clone() {
                if let Some(status) = sqlx::query_scalar::<_, String>(
                    "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_optional(&pool)
                .await?
                {
                    self.start_observed_statuses.lock().await.push(status);
                }
            }
            if let Some((pool, sandbox_id)) = self.start_marks_error.lock().await.clone() {
                queries::mark_sandbox_error(&pool, sandbox_id, Some("concurrent restart failure"))
                    .await?;
            }
            if let Some(message) = self.start_error.lock().await.clone() {
                anyhow::bail!(message);
            }
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
            if let Some((pool, sandbox_id)) = self.destroy_status_probe.lock().await.clone() {
                if let Some(status) = sqlx::query_scalar::<_, String>(
                    "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_optional(&pool)
                .await?
                {
                    self.destroy_observed_statuses.lock().await.push(status);
                }
            }
            self.destroyed.lock().await.push(external_id.to_string());
            if let Some(message) = self.destroy_error.lock().await.clone() {
                anyhow::bail!(message);
            }
            Ok(())
        }

        async fn status(&self, _external_id: &str) -> anyhow::Result<SandboxStatus> {
            if let Some((pool, sandbox_id)) = self.status_marks_idle.lock().await.clone() {
                queries::transition_sandbox_cas(&pool, sandbox_id, "provisioning", "idle").await?;
            }
            if let Some((pool, sandbox_id)) = self.status_marks_error.lock().await.clone() {
                queries::mark_sandbox_error(&pool, sandbox_id, Some("concurrent pool claim error"))
                    .await?;
            }
            if let Some((pool, sandbox_id)) =
                self.status_marks_restart_required.lock().await.clone()
            {
                sqlx::query(
                    r#"
                    UPDATE joysafeter_sandboxes
                    SET runtime_config_status = 'restart_required',
                        runtime_config_last_reason = 'newer_provider_marker',
                        runtime_config_required_at = '2026-08-21T14:15:16.777777Z'::timestamptz
                    WHERE id = $1
                    "#,
                )
                .bind(sandbox_id)
                .execute(&pool)
                .await?;
            }
            if let Some(message) = self.status_error.lock().await.clone() {
                anyhow::bail!(message);
            }
            Ok(self
                .status_result
                .lock()
                .await
                .clone()
                .unwrap_or(SandboxStatus::Running))
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "recording"
        }

        fn capabilities(&self) -> crate::sandbox::provider::ProviderCapabilities {
            crate::sandbox::provider::ProviderCapabilities {
                has_host_mount: false,
                has_egress_management: true,
                network_isolation: crate::sandbox::provider::NetworkIsolation::Envoy,
                stop_preserves_state: false,
            }
        }
    }

    #[async_trait]
    impl NetworkPolicyRuntime for RecordingProvider {
        async fn initialize(&self) -> anyhow::Result<()> {
            Ok(())
        }

        async fn prune(
            &self,
            _live_sandbox_ids: &std::collections::HashSet<SandboxId>,
        ) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn apply(
            &self,
            sandbox_id: SandboxId,
            policy: crate::kernel::network_policy::envoy_model::SandboxEgressPolicy,
        ) -> anyhow::Result<()> {
            self.networking.lock().await.push((
                sandbox_id,
                Some(serde_json::json!({
                    "type": "limited",
                    "allowed_hosts": policy.allowlist_hosts,
                })),
            ));
            self.networking_credentials
                .lock()
                .await
                .push(SandboxCredentials {
                    routes: policy.credential_routes,
                    proxy_auth_token: policy.proxy_auth_token,
                });
            if let Some(message) = self.networking_error.lock().await.clone() {
                anyhow::bail!(message);
            }
            Ok(())
        }

        async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
            self.networking_teardowns.lock().await.push(sandbox_id);
            Ok(())
        }
    }

    struct PostgresTestNetworkPolicyMaterialResolver {
        pool: PgPool,
    }

    #[async_trait]
    impl NetworkPolicyMaterialResolver for PostgresTestNetworkPolicyMaterialResolver {
        async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
            let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
                .await?
                .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
            let networking = sandbox
                .config
                .as_ref()
                .and_then(|config| config.get("fingerprint"))
                .and_then(|fingerprint| fingerprint.get("networking"));
            let credentials =
                crate::kernel::credentials::runtime_projection::rebuild_sandbox_credentials(
                    &self.pool,
                    &sandbox,
                    &[],
                )
                .await?;
            DesiredNetworkPolicy::from_inputs(networking, &credentials)
        }
    }

    fn recording_resolver(
        pool: PgPool,
        provider: Arc<RecordingProvider>,
        config: JoySafeterConfig,
    ) -> SandboxResolver {
        SandboxResolver::new(pool.clone(), provider.clone(), config)
            .with_network_policy_runtime(provider)
            .with_network_policy_material_resolver(Arc::new(
                PostgresTestNetworkPolicyMaterialResolver { pool },
            ))
    }

    #[tokio::test]
    async fn local_authority_applies_ephemeral_identity_credentials_without_rebuild() {
        let provider = RecordingProvider::default();
        let authority = crate::xds::authority::XdsAuthorityState::standalone();
        let guard = authority.ready_guard().expect("standalone authority guard");
        let sandbox_id = SandboxId::new();
        let credentials = SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: "external-identity:crm:0".to_string(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: "crm.example.com".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix("/api/".to_string()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "crm.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![(
                    "X-Security-AgentToken".to_string(),
                    "ephemeral-token".to_string(),
                )],
                remove_headers: vec!["x-security-agenttoken".to_string()],
            }],
            proxy_auth_token: Some("runner-token".to_string()),
        };
        let networking = serde_json::json!({
            "type": "limited",
            "allowed_hosts": []
        });

        crate::kernel::network_policy::application::apply_ephemeral(
            &provider,
            sandbox_id,
            DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials)
                .expect("desired policy")
                .render_for(sandbox_id),
            &guard,
        )
        .await
        .expect("ephemeral credentials should reach local authority");

        let applied = provider.networking_credentials.lock().await;
        assert_eq!(applied.len(), 1);
        assert_eq!(
            applied[0].routes[0].inject_headers,
            vec![(
                "X-Security-AgentToken".to_string(),
                "ephemeral-token".to_string()
            )]
        );
    }

    #[tokio::test]
    async fn task_identity_cleanup_replaces_dynamic_policy_and_clears_lease() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = SandboxId::new();
        let task_id = TaskId::new();
        let networking = serde_json::json!({"type": "limited", "allowed_hosts": []});
        let dynamic_credentials = SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: "external-identity:crm:0".to_string(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: "crm.example.com".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix("/api/".to_string()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "crm.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![(
                    "X-Security-AgentToken".to_string(),
                    "ephemeral-token".to_string(),
                )],
                remove_headers: vec!["x-security-agenttoken".to_string()],
            }],
            proxy_auth_token: Some("runner-token".to_string()),
        };
        let dynamic_hash =
            DesiredNetworkPolicy::from_inputs(Some(&networking), &dynamic_credentials)
                .expect("dynamic policy")
                .revision()
                .to_string();
        let expected = ExpectedFingerprint {
            image: "identity-cleanup:latest".to_string(),
            engine_kind: "claude".to_string(),
            networking: Some(networking),
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: dynamic_hash.clone(),
        };
        let mut config =
            provisioning_config("ready", 100, "Ready", true, &expected, Some("runner-token"));
        config["agent_identity_lease"] = identity_lease_metadata(task_id, Some(120));
        queries::create_sandbox(
            &pool,
            sandbox_id,
            "external-identity-cleanup",
            "recording",
            "identity-cleanup:latest",
            None,
            None,
            None,
            Some(&config),
        )
        .await
        .expect("create identity cleanup sandbox");
        let generation = queries::prepare_desired_network_policy(&pool, sandbox_id, &dynamic_hash)
            .await
            .expect("prepare dynamic generation")
            .into_generation();
        assert_eq!(
            queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &generation)
                .await
                .expect("mark dynamic policy ready"),
            queries::NetworkPolicyAckOutcome::Applied
        );
        let provider = Arc::new(RecordingProvider::default());
        let mut resolver_config = JoySafeterConfig::from_env();
        resolver_config.sandbox_provider = "recording".to_string();
        let resolver = recording_resolver(pool.clone(), provider.clone(), resolver_config);

        let other_task_id = TaskId::new();
        assert!(!resolver
            .clear_task_agent_identity_policy(sandbox_id, other_task_id)
            .await
            .expect("foreign task must not clear identity policy"));
        assert!(provider.networking_credentials.lock().await.is_empty());
        let sandbox_before_owner_cleanup = queries::get_sandbox(&pool, sandbox_id)
            .await
            .expect("load sandbox before owner cleanup")
            .expect("sandbox exists before owner cleanup");
        assert!(identity_lease_matches(
            sandbox_before_owner_cleanup.config.as_ref(),
            task_id
        ));

        assert!(resolver
            .clear_task_agent_identity_policy(sandbox_id, task_id)
            .await
            .expect("clear identity policy"));

        let applied = provider.networking_credentials.lock().await;
        assert_eq!(applied.len(), 1);
        assert!(applied[0].routes.is_empty());
        assert_eq!(applied[0].proxy_auth_token.as_deref(), Some("runner-token"));
        let sandbox = queries::get_sandbox(&pool, sandbox_id)
            .await
            .expect("load sandbox")
            .expect("sandbox exists");
        assert_eq!(
            sandbox
                .config
                .as_ref()
                .and_then(|value| value.get("agent_identity_lease")),
            Some(&serde_json::Value::Null)
        );
        assert_eq!(sandbox.networking_status, "ready");
        assert_ne!(
            sandbox.networking_applied_hash.as_deref(),
            Some(dynamic_hash.as_str())
        );

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    struct AckingNetworkPolicyQueue {
        pool: PgPool,
        requests: Mutex<Vec<NetworkPolicyRequest>>,
    }

    #[async_trait]
    impl NetworkPolicyRequestQueue for AckingNetworkPolicyQueue {
        async fn publish(&self, request: NetworkPolicyRequest) -> anyhow::Result<()> {
            if let Some(generation) = request.generation.as_ref() {
                assert!(matches!(
                    queries::mark_sandbox_network_policy_acked(
                        &self.pool,
                        request.sandbox_id,
                        generation,
                    )
                    .await?,
                    queries::NetworkPolicyAckOutcome::Applied
                        | queries::NetworkPolicyAckOutcome::AlreadyReady
                ));
            }
            self.requests.lock().await.push(request);
            Ok(())
        }
    }

    #[tokio::test]
    async fn multi_replica_networking_requests_authority_without_local_provider_push() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let networking = serde_json::json!({
            "type": "limited",
            "allowed_hosts": ["api.example.com"]
        });
        let context = ResolveContext {
            session_id: None,
            project_id: None,
            runtime_config_generation: 0,
            network: Some("none".to_string()),
            expected: ExpectedFingerprint {
                image: "authority-test:latest".to_string(),
                engine_kind: "claude".to_string(),
                networking: Some(networking),
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: "authority-policy".to_string(),
            },
            memory_mounts: vec![],
            mounts: vec![],
            credentials: SandboxCredentials::default(),
            identity_refresh_after_seconds: None,
        };
        queries::create_sandbox(
            &pool,
            sandbox_id,
            "external-authority-test",
            "recording",
            "authority-test:latest",
            None,
            None,
            None,
            Some(&provisioning_config(
                "networking",
                80,
                "Awaiting authority",
                false,
                &context.expected,
                Some("runner-token"),
            )),
        )
        .await
        .expect("create authority test sandbox");
        let generation = queries::prepare_desired_network_policy(
            &pool,
            sandbox_id,
            &context.expected.egress_policy_hash,
        )
        .await
        .expect("prepare authority generation")
        .into_generation();
        let provider = Arc::new(RecordingProvider::default());
        let request_queue = Arc::new(AckingNetworkPolicyQueue {
            pool: pool.clone(),
            requests: Mutex::new(Vec::new()),
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config)
            .with_network_policy_queue(request_queue.clone());

        resolver
            .apply_prepared_network_policy(
                sandbox_id,
                "external-authority-test",
                &context,
                &generation,
                None,
                Some("runner-token".to_string()),
            )
            .await
            .expect("authority request should become ready");

        assert!(provider.networking.lock().await.is_empty());
        assert_eq!(
            request_queue.requests.lock().await.as_slice(),
            &[NetworkPolicyRequest::reconcile(sandbox_id, generation)]
        );

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn duplicate_authority_request_keeps_ready_generation_without_provider_push() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let networking = serde_json::json!({"type": "limited", "allowed_hosts": []});
        let expected = ExpectedFingerprint {
            image: "authority-duplicate:latest".to_string(),
            engine_kind: "claude".to_string(),
            networking: Some(networking),
            env: HashMap::new(),
            mounts: vec![],
            egress_policy_hash: "authority-duplicate-policy".to_string(),
        };
        queries::create_sandbox(
            &pool,
            sandbox_id,
            "external-authority-duplicate",
            "recording",
            "authority-duplicate:latest",
            None,
            None,
            None,
            Some(&provisioning_config(
                "networking",
                100,
                "Ready",
                true,
                &expected,
                Some("runner-token"),
            )),
        )
        .await
        .expect("create duplicate authority test sandbox");
        let generation = queries::prepare_desired_network_policy(
            &pool,
            sandbox_id,
            &expected.egress_policy_hash,
        )
        .await
        .expect("prepare duplicate generation")
        .into_generation();
        assert_eq!(
            queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &generation)
                .await
                .expect("mark duplicate generation ready"),
            queries::NetworkPolicyAckOutcome::Applied
        );
        let provider = RecordingProvider::default();
        let authority = crate::xds::authority::XdsAuthorityState::standalone();
        let guard = authority.ready_guard().expect("authority guard");

        let material_resolver = UnconfiguredNetworkPolicyMaterialResolver;
        let outcome = crate::kernel::network_policy::application::apply_generation_as_authority(
            &pool,
            &provider,
            &material_resolver,
            sandbox_id,
            &generation,
            &guard,
        )
        .await
        .expect("duplicate request should be idempotent");

        assert_eq!(
            outcome,
            crate::kernel::network_policy::application::NetworkingReconcileOutcome::AlreadyReady {
                policy_hash: generation.policy_hash.clone()
            }
        );
        assert!(provider.networking.lock().await.is_empty());
        let state: String =
            sqlx::query_scalar("SELECT networking_status FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load duplicate request state");
        assert_eq!(state, "ready");

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
    }

    #[derive(Debug, Default)]
    struct SlowIdentityProvider {
        calls: AtomicUsize,
        captured_material: Mutex<Vec<bool>>,
    }

    #[derive(Debug, Default)]
    struct EmptyIdentityProvider {
        calls: AtomicUsize,
    }

    #[async_trait]
    impl crate::kernel::agent_identity_provider::AgentIdentityProvider for EmptyIdentityProvider {
        fn name(&self) -> &str {
            "empty-test"
        }

        fn enabled(&self) -> bool {
            true
        }

        async fn resolve(
            &self,
            _context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
        ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection>
        {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(
                crate::kernel::agent_identity_provider::AgentIdentityInjection {
                    targets: vec![],
                    valid_for_seconds: None,
                },
            )
        }

        async fn cleanup(
            &self,
            _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
        ) {
        }
    }

    #[derive(Debug, Default)]
    struct FailingIdentityProvider {
        calls: AtomicUsize,
    }

    #[async_trait]
    impl crate::kernel::agent_identity_provider::AgentIdentityProvider for FailingIdentityProvider {
        fn name(&self) -> &str {
            "failing-test"
        }

        fn enabled(&self) -> bool {
            true
        }

        async fn resolve(
            &self,
            _context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
        ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection>
        {
            self.calls.fetch_add(1, Ordering::SeqCst);
            anyhow::bail!("deterministic identity provider failure")
        }

        async fn cleanup(
            &self,
            _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
        ) {
        }
    }

    #[async_trait]
    impl crate::kernel::agent_identity_provider::AgentIdentityProvider for SlowIdentityProvider {
        fn name(&self) -> &str {
            "slow-test"
        }

        fn enabled(&self) -> bool {
            true
        }

        async fn resolve(
            &self,
            context: &crate::kernel::agent_identity_provider::IdentityResolveContext,
        ) -> anyhow::Result<crate::kernel::agent_identity_provider::AgentIdentityInjection>
        {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.captured_material
                .lock()
                .await
                .push(!context.identity_token.is_empty() || context.auth_code.is_some());
            tokio::time::sleep(Duration::from_millis(100)).await;
            Ok(
                crate::kernel::agent_identity_provider::AgentIdentityInjection {
                    targets: vec![
                        crate::kernel::agent_identity_provider::IdentityEgressTarget {
                            route_id: context.egress_targets[0].route_id.clone(),
                            host: context.egress_targets[0].host.clone(),
                            port: 443,
                            tls: true,
                            inject_headers: vec![(
                                "X-Security-AgentToken".to_string(),
                                "agent-token".to_string(),
                            )],
                            remove_headers: vec!["x-security-agenttoken".to_string()],
                        },
                    ],
                    valid_for_seconds: Some(120),
                },
            )
        }

        async fn cleanup(
            &self,
            _context: &crate::kernel::agent_identity_provider::IdentityCleanupContext,
        ) {
        }
    }

    #[tokio::test]
    async fn task_identity_context_is_project_scoped_expiring_and_single_consume() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let empty_task_id = TaskId::from_uuid(Uuid::now_v7());
        let failing_task_id = TaskId::from_uuid(Uuid::now_v7());
        let expired_task_id = TaskId::from_uuid(Uuid::now_v7());
        let malformed_task_id = TaskId::from_uuid(Uuid::now_v7());
        let invalid_kind_task_id = TaskId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let unique = Uuid::now_v7().simple().to_string();
        let project_id = ProjectId::new();
        let org_id = OrganizationId::new();
        let user_id = UserId::new();

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Identity Org {unique}"))
            .bind(format!("identity-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Identity Project {unique}"))
            .bind(format!("identity-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands, permission_mode,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("identity-agent-{unique}"))
            .bind(serde_json::json!({"id": "claude-sonnet"}))
            .execute(&pool)
            .await
            .expect("insert agent");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert identity session");
            for id in [
                task_id,
                empty_task_id,
                failing_task_id,
                expired_task_id,
                malformed_task_id,
            ] {
                sqlx::query(
                    r#"
                    INSERT INTO joysafeter_tasks (
                        id, project_id, user_id, agent_id, chat_session_id, status, prompt, output,
                        timeout_sec, retry_count, max_retries
                    )
                    VALUES ($1, $2, $3, $4, $5, 'pending', 'identity', '', 7200, 0, 2)
                    "#,
                )
                .bind(id)
                .bind(&project_id)
                .bind(user_id)
                .bind(agent_id)
                .bind(session_id)
                .execute(&pool)
                .await
                .expect("insert task");
            }
            let ciphertext = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
            for id in [task_id, empty_task_id, failing_task_id] {
                sqlx::query(
                    r#"
                    INSERT INTO joysafeter_task_identity_contexts (
                        task_id, project_id, user_id, user_name, credential_kind,
                        credential_fingerprint, encrypted_credential, captured_at, expires_at
                    )
                    VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                            NULL, $4, NOW(), NOW() + INTERVAL '5 minutes')
                    "#,
                )
                .bind(id)
                .bind(&project_id)
                .bind(user_id)
                .bind(ciphertext)
                .execute(&pool)
                .await
                .expect("insert active identity context");
            }
            sqlx::query(
                r#"
                INSERT INTO joysafeter_task_identity_contexts (
                    task_id, project_id, user_id, user_name, credential_kind,
                    credential_fingerprint, encrypted_credential, captured_at, expires_at
                )
                VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                        NULL, $4, NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '5 minutes')
                "#,
            )
            .bind(expired_task_id)
            .bind(&project_id)
            .bind(user_id)
            .bind(ciphertext)
            .execute(&pool)
            .await
            .expect("insert expired identity context");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_task_identity_contexts (
                    task_id, project_id, user_id, user_name, credential_kind,
                    credential_fingerprint, encrypted_credential, captured_at, expires_at
                )
                VALUES ($1, $2, $3, 'user@example.com', 'identity_token',
                        NULL, $4, NOW(), NOW() + INTERVAL '5 minutes')
                "#,
            )
            .bind(malformed_task_id)
            .bind(&project_id)
            .bind(user_id)
            .bind("enc:v1:not-base64")
            .execute(&pool)
            .await
            .expect("insert malformed identity context");

            let key_error_provider = Arc::new(SlowIdentityProvider::default());
            let key_error_resolver = SandboxResolver::new(
                pool.clone(),
                Arc::new(RecordingProvider::default()),
                JoySafeterConfig::from_env(),
            )
            .with_identity_provider(key_error_provider.clone())
            .with_identity_allowed_hosts(allow(&["api.example.com"]))
            .with_task_identity_material_adapter(TaskIdentityMaterialAdapter::without_key());
            let key_error_agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load key-error agent")
                .expect("key-error agent exists");
            assert_eq!(
                key_error_resolver
                    .resolve_identity_injection(
                        Some(&key_error_agent),
                        task_id,
                        None,
                        Some(project_id),
                        &[identity_target("api.example.com")],
                    )
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::Material(TaskIdentityMaterialError::KeyInvalid)
            );
            assert_eq!(key_error_provider.calls.load(Ordering::SeqCst), 0);

            let identity_provider = Arc::new(SlowIdentityProvider::default());
            let resolver = SandboxResolver::new(
                pool.clone(),
                Arc::new(RecordingProvider::default()),
                JoySafeterConfig::from_env(),
            )
            .with_identity_provider(identity_provider.clone())
            .with_identity_allowed_hosts(allow(&["api.example.com"]))
            .with_task_identity_material_adapter(
                TaskIdentityMaterialAdapter::with_key(TEST_IDENTITY_KEY),
            );
            assert_eq!(
                resolver
                    .load_identity_context(task_id, Some(ProjectId::new()))
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::ProjectMismatch
            );
            assert!(resolver
                .load_identity_context(expired_task_id, Some(project_id))
                .await
                .expect("expired lookup is an absence")
                .is_none());

            assert_eq!(
                resolver
                    .resolve_identity_injection(
                        Some(
                            &queries::get_agent(&pool, agent_id)
                                .await
                                .expect("load agent")
                                .expect("agent exists"),
                        ),
                        malformed_task_id,
                        Some(session_id),
                        Some(project_id),
                        &[identity_target("api.example.com")],
                    )
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::Material(TaskIdentityMaterialError::EnvelopeInvalid)
            );
            assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 0);

            let agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load agent")
                .expect("agent exists");
            let no_host_provider = Arc::new(SlowIdentityProvider::default());
            let no_host_resolver = SandboxResolver::new(
                pool.clone(),
                Arc::new(RecordingProvider::default()),
                JoySafeterConfig::from_env(),
            )
            .with_identity_provider(no_host_provider.clone())
            .with_identity_allowed_hosts(allow(&["other.example.com"]))
            .with_task_identity_material_adapter(
                TaskIdentityMaterialAdapter::with_key(TEST_IDENTITY_KEY),
            );
            assert_eq!(
                no_host_resolver
                    .resolve_identity_injection(
                        Some(&agent),
                        empty_task_id,
                        Some(session_id),
                        Some(project_id),
                        &[identity_target("api.example.com")],
                    )
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::NoTrustedHosts
            );
            assert_eq!(no_host_provider.calls.load(Ordering::SeqCst), 0);

            let empty_provider = Arc::new(EmptyIdentityProvider::default());
            let empty_resolver = SandboxResolver::new(
                pool.clone(),
                Arc::new(RecordingProvider::default()),
                JoySafeterConfig::from_env(),
            )
            .with_identity_provider(empty_provider.clone())
            .with_identity_allowed_hosts(allow(&["api.example.com"]))
            .with_task_identity_material_adapter(
                TaskIdentityMaterialAdapter::with_key(TEST_IDENTITY_KEY),
            );
            assert_eq!(
                empty_resolver
                    .resolve_identity_injection(
                        Some(&agent),
                        empty_task_id,
                        Some(session_id),
                        Some(project_id),
                        &[identity_target("api.example.com")],
                    )
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::EmptyInjection
            );
            assert_eq!(empty_provider.calls.load(Ordering::SeqCst), 1);

            let failing_provider = Arc::new(FailingIdentityProvider::default());
            let failing_resolver = SandboxResolver::new(
                pool.clone(),
                Arc::new(RecordingProvider::default()),
                JoySafeterConfig::from_env(),
            )
            .with_identity_provider(failing_provider.clone())
            .with_identity_allowed_hosts(allow(&["api.example.com"]))
            .with_task_identity_material_adapter(
                TaskIdentityMaterialAdapter::with_key(TEST_IDENTITY_KEY),
            );
            assert_eq!(
                failing_resolver
                    .resolve_identity_injection(
                        Some(&agent),
                        failing_task_id,
                        Some(session_id),
                        Some(project_id),
                        &[identity_target("api.example.com")],
                    )
                    .await
                    .unwrap_err(),
                TaskIdentityContextError::Provider
            );
            assert_eq!(failing_provider.calls.load(Ordering::SeqCst), 1);

            assert_eq!(
                resolver
                    .decode_identity_context(
                        invalid_kind_task_id,
                        Some((
                            user_id,
                            Some("user@example.com".to_string()),
                            "future_identity".to_string(),
                            ENCRYPTED_HELLO_WORLD.to_string(),
                        )),
                    )
                    .unwrap_err(),
                TaskIdentityContextError::KindInvalid
            );
            assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 0);

            let candidate_hosts = [identity_target("api.example.com")];
            let first = resolver.resolve_identity_injection(
                Some(&agent),
                task_id,
                Some(session_id),
                Some(project_id),
                &candidate_hosts,
            );
            let second = resolver.resolve_identity_injection(
                Some(&agent),
                task_id,
                Some(session_id),
                Some(project_id),
                &candidate_hosts,
            );
            let (first, second) = tokio::join!(first, second);
            let first = first.expect("first identity claim resolves without error");
            let second = second.expect("second identity claim resolves without error");
            assert_eq!(identity_provider.calls.load(Ordering::SeqCst), 2);
            assert_eq!(
                usize::from(first.is_some()) + usize::from(second.is_some()),
                2
            );
            let mut captured_material = identity_provider.captured_material.lock().await.clone();
            captured_material.sort_unstable();
            assert_eq!(captured_material, vec![false, true]);
            assert!(resolver
                .load_identity_context(task_id, Some(project_id))
                .await
                .expect("consumed lookup is an absence")
                .is_none());
            let consumed: (bool, bool) = sqlx::query_as(
                r#"
                SELECT consumed_at IS NOT NULL, encrypted_credential IS NULL
                FROM joysafeter_task_identity_contexts WHERE task_id = $1
                "#,
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load consumed identity state");
            assert_eq!(consumed, (true, true));
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE agent_id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn task_identity_sql_errors_are_not_optional_absence() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let resolver = SandboxResolver::new(
            pool.clone(),
            Arc::new(RecordingProvider::default()),
            JoySafeterConfig::from_env(),
        )
        .with_identity_allowed_hosts(allow(&["api.example.com"]));
        pool.close().await;

        assert_eq!(
            resolver
                .load_identity_context(TaskId::from_uuid(Uuid::now_v7()), Some(ProjectId::new()))
                .await
                .unwrap_err(),
            TaskIdentityContextError::Database
        );
    }

    #[test]
    fn anthropic_auth_token_uses_bearer_and_leaves_no_key() {
        // Gateway / internal endpoint style: ANTHROPIC_AUTH_TOKEN → Bearer.
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
            ("ANTHROPIC_API_KEY", "tok-123"),
            ("ANTHROPIC_BASE_URL", "https://llm.internal.example.com/v1"),
            ("DB_PASSWORD", "keepme"),
        ]);
        let egress = extract_llm_route(
            &mut e,
            "anthropic",
            "anthropic_messages",
            &allow(&["llm.internal.example.com"]),
        )
        .expect("egress");

        // Bearer header, real host preserved in egress, TLS upstream.
        assert_eq!(egress.upstream_host, "llm.internal.example.com");
        assert_eq!(egress.upstream_port, 443);
        assert_eq!(
            egress.path_mapping,
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any
            }
        );
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.inject_headers,
            vec![("authorization".to_string(), "Bearer tok-123".to_string())]
        );

        // No real LLM key remains in the container env; Claude Code only gets a
        // non-secret placeholder so it does not fall back to /login.
        assert_eq!(
            e.get("ANTHROPIC_API_KEY").unwrap(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY
        );
        assert!(!e.contains_key("ANTHROPIC_AUTH_TOKEN"));
        assert_eq!(
            e.get("ANTHROPIC_BASE_URL").unwrap(),
            "http://llm.internal.example.com:443/v1/"
        );
        // Non-LLM env var is untouched.
        assert_eq!(e.get("DB_PASSWORD").unwrap(), "keepme");
    }

    #[test]
    fn llm_egress_uses_catalog_binding_instead_of_key_inference() {
        let binding = crate::kernel::llm_catalog::validate_runtime_secret(
            "native",
            "model",
            Some("deepseek"),
            Some("chat_completions"),
        )
        .expect("DeepSeek Chat Completions must be valid for Native");
        let mut e = env(&[("OPENAI_API_KEY", "sk-deepseek")]);

        let egress = extract_llm_egress(&mut e, Some(&binding), &allow(&["api.deepseek.com"]))
            .into_iter()
            .next()
            .expect("egress route");

        assert_eq!(egress.upstream_host, "api.deepseek.com");
        assert_eq!(
            egress.inject_headers,
            vec![(
                "authorization".to_string(),
                "Bearer sk-deepseek".to_string()
            )]
        );
    }

    #[test]
    fn anthropic_api_key_uses_x_api_key() {
        // Official-style key (no AUTH_TOKEN) → x-api-key header.
        let mut e = env(&[
            ("ANTHROPIC_API_KEY", "sk-ant-xyz"),
            ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ]);
        let egress = extract_llm_route(
            &mut e,
            "anthropic",
            "anthropic_messages",
            &allow(&["api.anthropic.com"]),
        )
        .expect("egress");
        assert_eq!(
            egress.inject_headers,
            vec![("x-api-key".to_string(), "sk-ant-xyz".to_string())]
        );
        assert_eq!(
            e.get("ANTHROPIC_API_KEY").unwrap(),
            CLAUDE_CODE_PLACEHOLDER_API_KEY
        );
    }

    #[test]
    fn official_host_requires_explicit_allowlist() {
        let mut e = env(&[
            ("ANTHROPIC_API_KEY", "sk-ant-xyz"),
            ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ]);

        assert!(extract_llm_route(&mut e, "anthropic", "anthropic_messages", &[]).is_none());
        assert!(!e.contains_key("ANTHROPIC_API_KEY"));
        assert_eq!(
            e.get("ANTHROPIC_BASE_URL").unwrap(),
            "https://api.anthropic.com"
        );
    }

    #[test]
    fn unallowlisted_custom_host_removes_real_key_without_placeholder() {
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
            ("ANTHROPIC_API_KEY", "tok-123"),
            ("ANTHROPIC_BASE_URL", "https://evil.example.com/v1"),
        ]);

        assert!(extract_llm_route(
            &mut e,
            "anthropic",
            "anthropic_messages",
            &allow(&["api.anthropic.com"]),
        )
        .is_none());
        assert!(!e.contains_key("ANTHROPIC_AUTH_TOKEN"));
        assert!(!e.contains_key("ANTHROPIC_API_KEY"));
        assert_eq!(
            e.get("ANTHROPIC_BASE_URL").unwrap(),
            "https://evil.example.com/v1"
        );
    }

    #[test]
    fn llm_base_path_keeps_trailing_slash_for_envoy_rewrite() {
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
            ("ANTHROPIC_BASE_URL", "http://ai-api.jdcloud.com/anthropic"),
        ]);
        let egress = extract_llm_route(
            &mut e,
            "custom",
            "anthropic_messages",
            &allow(&["ai-api.jdcloud.com"]),
        )
        .expect("egress");
        assert_eq!(egress.upstream_host, "ai-api.jdcloud.com");
        assert_eq!(egress.upstream_port, 80);
        assert_eq!(
            egress.path_mapping,
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any
            }
        );
        assert!(!egress.upstream_tls);
    }

    #[test]
    fn openai_uses_bearer() {
        let mut e = env(&[
            ("OPENAI_API_KEY", "sk-oai"),
            ("OPENAI_BASE_URL", "https://gw.internal/v1"),
        ]);
        let egress = extract_llm_route(
            &mut e,
            "custom",
            "openai_responses",
            &allow(&["gw.internal"]),
        )
        .expect("egress");
        assert_eq!(egress.upstream_host, "gw.internal");
        assert_eq!(
            egress.path_mapping,
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any
            }
        );
        assert_eq!(
            egress.inject_headers,
            vec![("authorization".to_string(), "Bearer sk-oai".to_string())]
        );
        assert_eq!(
            e.get("OPENAI_API_KEY").unwrap(),
            CODEX_PLACEHOLDER_OPENAI_API_KEY
        );
        assert!(!e.contains_key("ANTHROPIC_API_KEY"));
        assert_eq!(
            e.get("OPENAI_BASE_URL").unwrap(),
            "http://gw.internal:443/v1/"
        );
    }

    #[test]
    fn no_llm_key_returns_none() {
        let mut e = env(&[("DB_PASSWORD", "x")]);
        assert!(extract_llm_route(&mut e, "openai", "openai_responses", &[]).is_none());
        assert_eq!(e.get("DB_PASSWORD").unwrap(), "x");
    }

    #[test]
    fn plaintext_base_url_keeps_http_upstream() {
        // If the configured endpoint is plain http, the cluster should not TLS.
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "t"),
            ("ANTHROPIC_BASE_URL", "http://llm.internal:8080/v1"),
        ]);
        let egress = extract_llm_route(
            &mut e,
            "custom",
            "anthropic_messages",
            &allow(&["llm.internal"]),
        )
        .expect("egress");
        assert_eq!(egress.upstream_host, "llm.internal");
        assert_eq!(egress.upstream_port, 8080);
        assert_eq!(
            egress.path_mapping,
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any
            }
        );
        assert!(!egress.upstream_tls);
        assert_eq!(
            e.get("ANTHROPIC_BASE_URL").unwrap(),
            "http://llm.internal:8080/v1/"
        );
    }

    #[test]
    fn localhost_and_private_ip_literals_are_rejected_even_if_allowlisted() {
        for host in ["localhost", "127.0.0.1", "10.0.0.1", "169.254.169.254"] {
            let mut e = env(&[
                ("OPENAI_API_KEY", "sk-oai"),
                ("OPENAI_BASE_URL", &format!("https://{host}/v1")),
            ]);

            assert!(
                extract_llm_route(&mut e, "custom", "openai_responses", &allow(&[host]),).is_none(),
                "host should be rejected: {host}"
            );
            assert!(!e.contains_key("OPENAI_API_KEY"));
        }
    }

    #[test]
    fn unsupported_base_url_scheme_is_rejected_without_placeholder() {
        let mut e = env(&[
            ("OPENAI_API_KEY", "sk-oai"),
            ("OPENAI_BASE_URL", "file:///tmp/socket"),
        ]);

        assert!(extract_llm_route(
            &mut e,
            "custom",
            "openai_responses",
            &allow(&["api.openai.com"]),
        )
        .is_none());
        assert!(!e.contains_key("OPENAI_API_KEY"));
    }

    #[tokio::test]
    async fn sandbox_resolver_provision_pool_sandbox_finalizes_pooled_row() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let image = format!("resolver-pool-image-{}:latest", Uuid::now_v7().simple());
        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;

        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);
        let sandbox_id = resolver
            .provision_pool_sandbox(&image)
            .await
            .expect("provision warm pool sandbox");

        let result = async {
            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
                "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load provisioned pool sandbox");
            assert_eq!(sandbox.0, "pooled");
            assert_eq!(sandbox.1, None);
            assert_eq!(
                sandbox
                    .2
                    .get("provisioning")
                    .and_then(|value| value.get("stage"))
                    .and_then(|value| value.as_str()),
                Some("pool_warm")
            );
            assert!(sandbox.2.get("runner_token").is_some());

            let created = provider.created.lock().await;
            assert_eq!(created.len(), 1);
            assert_eq!(created[0].sandbox_id, sandbox_id);
            assert_eq!(created[0].image.as_str(), image);
            assert_eq!(created[0].workspace_path.as_deref(), None);
            assert_eq!(
                created[0].env.get("JOYSAFETER_SANDBOX_ID"),
                Some(&sandbox_id.as_uuid().to_string())
            );
            assert_eq!(
                created[0].env.get("DISABLE_TELEMETRY").map(String::as_str),
                Some("1")
            );
            assert_eq!(
                created[0]
                    .env
                    .get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
                    .map(String::as_str),
                Some("1")
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_pool_ready_error_race_does_not_destroy_changed_runtime() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let unique = Uuid::now_v7().simple().to_string();
        let image = format!("resolver-pool-ready-error-{unique}:latest");
        let trigger_name = format!("trg_pool_ready_error_{unique}");
        let function_name = format!("fn_pool_ready_error_{unique}");
        let image_literal = image.replace('\'', "''");

        sqlx::query(&format!(
            r#"
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.image = '{image_literal}' THEN
                    NEW.status := 'error';
                    NEW.config := COALESCE(NEW.config, '{{}}'::jsonb)
                        || jsonb_build_object('setup_error', 'concurrent pool ready error');
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            "#
        ))
        .execute(&pool)
        .await
        .expect("create pool ready error trigger function");
        sqlx::query(&format!(
            r#"
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON joysafeter_sandboxes
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            "#
        ))
        .execute(&pool)
        .await
        .expect("create pool ready error trigger");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let result = resolver.provision_pool_sandbox(&image).await;
        let destroyed = provider.destroyed.lock().await.clone();
        let sandbox: Option<(Uuid, String, serde_json::Value)> = sqlx::query_as(
            "SELECT id, status, config FROM joysafeter_sandboxes WHERE image = $1 ORDER BY created_at DESC LIMIT 1",
        )
        .bind(&image)
        .fetch_optional(&pool)
        .await
        .expect("load pool ready error sandbox");

        let _ = sqlx::query(&format!(
            "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
        ))
        .execute(&pool)
        .await;
        let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
            .execute(&pool)
            .await;
        if let Some((sandbox_id, _, _)) = sandbox.as_ref() {
            let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await;
        }

        let err = result.expect_err("concurrent pool-ready error must abort provisioning");
        let message = err.to_string();
        assert!(
            message.contains("changed state before ready finalization"),
            "{message}"
        );
        assert!(destroyed.is_empty());
        let Some((_, status, config)) = sandbox else {
            panic!("expected pool ready error sandbox row");
        };
        assert_eq!(status, "error");
        assert_eq!(
            config.get("setup_error").and_then(|value| value.as_str()),
            Some("concurrent pool ready error")
        );
    }

    #[tokio::test]
    async fn sandbox_resolver_new_sandbox_error_race_does_not_destroy_changed_runtime() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let unique = Uuid::now_v7().simple().to_string();
        let image = format!("resolver-new-error-{unique}:latest");
        let trigger_name = format!("trg_new_sandbox_error_{unique}");
        let function_name = format!("fn_new_sandbox_error_{unique}");
        let image_literal = image.replace('\'', "''");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
            VALUES ($1, $2, 'claude', '{}'::jsonb, 'bypassPermissions', 1)
            "#,
        )
        .bind(agent_id)
        .bind(format!("resolver-new-error-agent-{unique}"))
        .execute(&pool)
        .await
        .expect("insert new sandbox error agent");
        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(&pool)
        .await
        .expect("insert new sandbox error session");

        sqlx::query(&format!(
            r#"
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.image = '{image_literal}' THEN
                    NEW.status := 'error';
                    NEW.config := COALESCE(NEW.config, '{{}}'::jsonb)
                        || jsonb_build_object('setup_error', 'concurrent new sandbox error');
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            "#
        ))
        .execute(&pool)
        .await
        .expect("create new sandbox error trigger function");
        sqlx::query(&format!(
            r#"
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON joysafeter_sandboxes
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            "#
        ))
        .execute(&pool)
        .await
        .expect("create new sandbox error trigger");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = false;
        config.image_claude = image.clone();
        config.sandbox_image = image.clone();
        let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

        let result = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await;
        let destroyed = provider.destroyed.lock().await.clone();
        let sandbox: Option<(Uuid, String, serde_json::Value)> = sqlx::query_as(
            "SELECT id, status, config FROM joysafeter_sandboxes WHERE chat_session_id = $1 ORDER BY created_at DESC LIMIT 1",
        )
        .bind(session_id)
        .fetch_optional(&pool)
        .await
        .expect("load new sandbox error row");

        let _ = sqlx::query(&format!(
            "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
        ))
        .execute(&pool)
        .await;
        let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
            .execute(&pool)
            .await;
        if let Some((sandbox_id, _, _)) = sandbox.as_ref() {
            let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await;
        }
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;

        let err = result.expect_err("concurrent new-sandbox error must abort resolve");
        let message = err.to_string();
        assert!(
            message.contains("changed state before provisioning transition"),
            "{message}"
        );
        assert!(destroyed.is_empty());
        let Some((_, status, config)) = sandbox else {
            panic!("expected new sandbox error row");
        };
        assert_eq!(status, "error");
        assert_eq!(
            config.get("setup_error").and_then(|value| value.as_str()),
            Some("concurrent new sandbox error")
        );
    }

    #[tokio::test]
    async fn sandbox_resolver_pool_claim_accepts_runner_ready_idle_race() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-pool-claim-idle-{unique}:latest");
        let external_id = format!("resolver-pool-claim-idle-{sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
                VALUES ($1, $2, 'claude', '{}'::jsonb, 'bypassPermissions', 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-pool-claim-idle-agent-{unique}"))
            .execute(&pool)
            .await
            .expect("insert pool claim idle agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert pool claim idle session");
            sqlx::query(
                "UPDATE joysafeter_sessions SET runtime_config_generation = 7 WHERE id = $1",
            )
            .bind(session_id)
            .execute(&pool)
            .await
            .expect("set pool claim desired generation");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "pool_warm",
                100,
                "Warm pooled sandbox ready for claim",
                true,
                &expected,
                Some("pool-claim-idle-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create pooled sandbox");
            assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize pooled sandbox"));

            let provider = Arc::new(RecordingProvider {
                status_marks_idle: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = true;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.image_claude = image.clone();
            config.sandbox_image = image.clone();
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("pool claim should survive runner-ready idle race");
            assert_eq!(resolved.sandbox_id, sandbox_id);
            assert_eq!(resolved.external_id, external_id);
            assert_eq!(resolved.runtime_config_generation, 7);
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<SessionId>, serde_json::Value, String, i64) =
                sqlx::query_as(
                "SELECT status, chat_session_id, config, runtime_config_status, runtime_config_applied_generation FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load claimed pool sandbox after idle race");
            assert_eq!(sandbox.0, "idle");
            assert_eq!(sandbox.1, Some(session_id));
            assert_eq!(
                sandbox
                    .2
                    .get("provisioning")
                    .and_then(|value| value.get("stage"))
                    .and_then(|value| value.as_str()),
                Some("pool_claimed")
            );
            assert_eq!(sandbox.3, "ready");
            assert_eq!(sandbox.4, 7);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_stopped_pool_claim_starts_after_db_claim() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-pool-stopped-start-{unique}:latest");
        let external_id = format!("resolver-pool-stopped-start-{sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
                VALUES ($1, $2, 'claude', '{}'::jsonb, 'bypassPermissions', 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-pool-stopped-start-agent-{unique}"))
            .execute(&pool)
            .await
            .expect("insert stopped pool claim agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert stopped pool claim session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "pool_warm",
                100,
                "Stopped warm pooled sandbox ready for claim",
                true,
                &expected,
                Some("pool-stopped-start-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stopped pooled sandbox");
            assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize stopped pooled sandbox"));

            let provider = Arc::new(RecordingProvider {
                start_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
                status_result: Mutex::new(Some(SandboxStatus::Stopped)),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = true;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.image_claude = image.clone();
            config.sandbox_image = image.clone();
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("stopped pool claim should restart after DB claim");
            assert_eq!(resolved.sandbox_id, sandbox_id);
            assert_eq!(resolved.external_id, external_id);

            assert_eq!(
                provider.start_observed_statuses.lock().await.as_slice(),
                &["provisioning".to_string()]
            );
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<SessionId>, serde_json::Value) = sqlx::query_as(
                "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load stopped pool sandbox after restart claim");
            assert_eq!(sandbox.0, "provisioning");
            assert_eq!(sandbox.1, Some(session_id));
            assert_eq!(
                sandbox
                    .2
                    .get("provisioning")
                    .and_then(|value| value.get("stage"))
                    .and_then(|value| value.as_str()),
                Some("pool_restarting")
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_pool_claim_error_race_does_not_destroy_changed_runtime() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-pool-claim-error-{unique}:latest");
        let external_id = format!("resolver-pool-claim-error-{sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
                VALUES ($1, $2, 'claude', '{}'::jsonb, 'bypassPermissions', 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-pool-claim-error-agent-{unique}"))
            .execute(&pool)
            .await
            .expect("insert pool claim error agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert pool claim error session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "pool_warm",
                100,
                "Warm pooled sandbox ready for claim",
                true,
                &expected,
                Some("pool-claim-error-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create pooled sandbox");
            assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize pooled sandbox"));

            let provider = Arc::new(RecordingProvider {
                status_marks_error: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = true;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.image_claude = image.clone();
            config.sandbox_image = image.clone();
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("concurrent pool claim error must abort resolve");
            let message = err.to_string();
            assert!(
                message.contains("changed during provider activation"),
                "{message}"
            );
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
                "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load pool sandbox after error race");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1, Some(session_id.as_uuid()));
            assert_eq!(
                sandbox
                    .2
                    .get("setup_error")
                    .and_then(|value| value.as_str()),
                Some("concurrent pool claim error")
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_pool_cleanup_failure_keeps_attached_runtime_non_ready() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-pool-cleanup-failure-{unique}:latest");
        let external_id = format!("resolver-pool-cleanup-failure-{sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
                VALUES ($1, $2, 'claude', '{}'::jsonb, 'bypassPermissions', 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-pool-cleanup-failure-agent-{unique}"))
            .execute(&pool)
            .await
            .expect("insert pool cleanup failure agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert pool cleanup failure session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "pool_warm",
                100,
                "Warm pooled sandbox ready for claim",
                true,
                &expected,
                Some("pool-cleanup-failure-token"),
            );
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create pooled sandbox");
            assert!(queries::mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize pooled sandbox"));

            let provider = Arc::new(RecordingProvider {
                status_error: Mutex::new(Some("provider status failed".to_string())),
                destroy_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
                destroy_error: Mutex::new(Some("provider destroy failed".to_string())),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = true;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.image_claude = image.clone();
            config.sandbox_image = image.clone();
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("provider cleanup failure must stop pool resolution");
            assert!(matches!(
                err.downcast_ref::<RuntimeFreshnessError>(),
                Some(RuntimeFreshnessError::CleanupFailed(_))
            ));
            assert_eq!(
                provider.destroyed.lock().await.as_slice(),
                &[external_id.clone()]
            );
            assert_eq!(
                provider.destroy_observed_statuses.lock().await.as_slice(),
                &["stopping".to_string()]
            );
            assert_eq!(provider.created.lock().await.len(), 0);

            let sandbox: (
                String,
                Option<SessionId>,
                String,
                Option<String>,
                bool,
                Option<i64>,
            ) = sqlx::query_as(
                r#"
                    SELECT status, chat_session_id, runtime_config_status,
                           runtime_config_last_reason,
                           runtime_config_required_at IS NOT NULL,
                           runtime_config_applied_generation
                    FROM joysafeter_sandboxes
                    WHERE id = $1
                    "#,
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load pool sandbox after cleanup failure");
            assert_eq!(sandbox.0, "stopping");
            assert_eq!(sandbox.1, Some(session_id));
            assert_eq!(sandbox.2, "restart_required");
            assert_eq!(
                sandbox.3.as_deref(),
                Some("claimed pool sandbox provider status failed")
            );
            assert!(sandbox.4);
            assert_eq!(sandbox.5, Some(0));
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_builds_mcp_egress_from_session_credential_groups() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
        let credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let mcp_url = "https://mcp.vault-alias.example/api";
        let normalized = mcp_url::normalize(mcp_url);

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Resolver MCP Org {unique}"))
            .bind(format!("resolver-mcp-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Resolver MCP Project {unique}"))
            .bind(format!("resolver-mcp-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credential_groups (id, project_id, name, description)
                VALUES ($1, $2, $3, '')
                "#,
            )
            .bind(group_id)
            .bind(&project_id)
            .bind(format!("resolver-group-alias-{unique}"))
            .execute(&pool)
            .await
            .expect("insert credential group");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_credentials
                    (id, project_id, kind, name, credential_type, mcp_server_url,
                     normalized_mcp_server_url, group_id, data)
                VALUES ($1, $2, 'mcp', 'resolver alias credential', 'static_bearer', $3,
                        $4, $5, $6)
                "#,
            )
            .bind(credential_id)
            .bind(&project_id)
            .bind(mcp_url)
            .bind(&normalized)
            .bind(group_id)
            .bind(serde_json::json!({"token_value": ENCRYPTED_HELLO_WORLD}))
            .execute(&pool)
            .await
            .expect("insert mcp credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb, $5,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("resolver-vault-alias-agent-{unique}"))
            .bind(serde_json::json!({"id": "claude-sonnet"}))
            .bind(serde_json::json!([{
                "name": "secure-mcp",
                "type": "streamable_http",
                "url": mcp_url,
                "auth_requirement": "required"
            }]))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
                VALUES ($1, $2)
                "#,
            )
            .bind(session_id)
            .bind(group_id)
            .execute(&pool)
            .await
            .expect("bind session credential group");

            let agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load agent")
                .expect("agent exists");
            let access = CredentialMaterialAccessService::with_material_adapter(
                pool.clone(),
                crate::kernel::credentials::material::ManagedCredentialMaterialAdapter::from_key(
                    TEST_IDENTITY_KEY,
                ),
            );
            let context = CredentialAccessContext::runtime(Some(session_id), None, Some(0));
            let egress =
                crate::kernel::mcp_runtime_plan::resolve_mcp_runtime_plan_with_access_and_resolver(
                    &access,
                    &context,
                    Some(project_id),
                    Some(session_id),
                    agent.id,
                    0,
                    EffectiveNetworkMode::Limited,
                    agent.mcp_servers.as_ref(),
                    &StaticMcpAddressResolver,
                    &crate::kernel::mcp_network_policy::McpNetworkPolicy::default(),
                )
                .await
                .expect("build MCP runtime plan")
                .egress_routes();

            assert_eq!(egress.len(), 1);
            assert!(egress[0].id.starts_with("mcp:"));
            let EgressPathMapping::RewriteExact {
                exposed_path,
                upstream_path,
            } = &egress[0].path_mapping
            else {
                panic!("expected exact MCP path rewrite")
            };
            assert!(exposed_path.starts_with("/r/"));
            assert!(!exposed_path.contains("secure-mcp"));
            assert_eq!(egress[0].upstream_host, "mcp.vault-alias.example");
            assert_eq!(egress[0].upstream_port, 443);
            assert_eq!(upstream_path, "/api");
            assert!(egress[0].upstream_tls);
            assert_eq!(
                egress[0].inject_headers,
                vec![(
                    "authorization".to_string(),
                    "Bearer hello-world".to_string()
                )]
            );
            let audit =
                sqlx::query_as::<_, (String, String, Option<SessionId>, serde_json::Value)>(
                    r#"
                SELECT usage, result, session_id, field_names
                FROM joysafeter_credential_access_audits
                WHERE credential_id = $1
                "#,
                )
                .bind(credential_id)
                .fetch_one(&pool)
                .await
                .expect("load MCP credential access audit");
            assert_eq!(audit.0, "mcp_egress");
            assert_eq!(audit.1, "success");
            assert_eq!(audit.2, Some(session_id));
            assert_eq!(audit.3, serde_json::json!(["token_value"]));

            sqlx::query("UPDATE joysafeter_credentials SET data = $2 WHERE id = $1")
                .bind(credential_id)
                .bind(serde_json::json!({
                    "token_value": "invalid-envelope-secret-sentinel"
                }))
                .execute(&pool)
                .await
                .expect("corrupt MCP credential envelope");
            let failure_context = CredentialAccessContext::runtime(Some(session_id), None, Some(1));
            let error = resolve_mcp_runtime_plan_with_access(
                &access,
                &failure_context,
                Some(project_id),
                Some(session_id),
                agent.id,
                1,
                EffectiveNetworkMode::Limited,
                agent.mcp_servers.as_ref(),
            )
            .await
            .expect_err("invalid MCP ciphertext must fail closed");
            assert_eq!(
                error.downcast_ref(),
                Some(&CredentialRuntimeError::EnvelopeInvalid)
            );
            let failed_audit = sqlx::query_as::<_, (String, String, serde_json::Value)>(
                r#"
                SELECT result, error_code, field_names
                FROM joysafeter_credential_access_audits
                WHERE credential_id = $1 AND generation = 1
                "#,
            )
            .bind(credential_id)
            .fetch_one(&pool)
            .await
            .expect("load failed MCP credential access audit");
            assert_eq!(failed_audit.0, "failed");
            assert_eq!(failed_audit.1, "envelope_invalid");
            assert_eq!(failed_audit.2, serde_json::json!(["token_value"]));
        }
        .await;

        let _ =
            sqlx::query("DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1")
                .bind(session_id)
                .execute(&pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
            .bind(credential_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_credential_groups WHERE id = $1")
            .bind(group_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_restart_does_not_resurrect_concurrent_error() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-race-image-{unique}:latest");
        let external_id = format!("resolver-race-{sandbox_id}");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver race system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-race-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-race-model"}))
            .execute(&pool)
            .await
            .expect("insert resolver race agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert resolver race session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stopped_for_restart",
                100,
                "Stopped sandbox ready for restart",
                true,
                &expected,
                Some("resolver-race-token"),
            );

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stopped sandbox");
            sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("mark sandbox stopped");

            let provider = Arc::new(RecordingProvider {
                start_marks_error: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider, config);
            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("concurrent error must abort stopped sandbox restart");
            let message = err.to_string();
            assert!(
                message.contains("changed state during restart"),
                "{message}"
            );

            let sandbox: (String, serde_json::Value) =
                sqlx::query_as("SELECT status, config FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load sandbox after restart race");
            assert_eq!(sandbox.0, "error");
            assert_eq!(
                sandbox
                    .1
                    .get("setup_error")
                    .and_then(|value| value.as_str()),
                Some("concurrent restart failure")
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_restart_claims_row_before_provider_start() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-restart-ordering-{unique}:latest");
        let external_id = format!("resolver-restart-ordering-{sandbox_id}");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver restart ordering system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-restart-ordering-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-restart-ordering-model"}))
            .execute(&pool)
            .await
            .expect("insert resolver restart ordering agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert resolver restart ordering session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stopped_for_restart",
                100,
                "Stopped sandbox ready for restart",
                true,
                &expected,
                Some("resolver-restart-ordering-token"),
            );

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create restart ordering sandbox");
            sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("mark restart ordering sandbox stopped");

            let provider = Arc::new(RecordingProvider {
                start_status_probe: Mutex::new(Some((pool.clone(), sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);
            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("restart stopped sandbox");
            assert_eq!(resolved.sandbox_id, sandbox_id);
            assert_eq!(resolved.external_id, external_id);

            assert_eq!(
                provider.start_observed_statuses.lock().await.as_slice(),
                &["provisioning".to_string()]
            );

            let sandbox_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load restarted sandbox status");
            assert_eq!(sandbox_status, "provisioning");
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[derive(Clone, Copy)]
    enum RestartProviderFailure {
        RuntimeGone,
        StatusError,
        StartError,
    }

    async fn assert_restart_failure_restores_runtime_configuration(
        failure: RestartProviderFailure,
        write_newer_marker: bool,
    ) {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-restart-compensation-{unique}:latest");
        let external_id = format!("resolver-restart-compensation-{sandbox_id}");
        let original_required_at = "2026-08-21T12:34:56.123456Z"
            .parse::<chrono::DateTime<chrono::Utc>>()
            .expect("valid original timestamp");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver restart compensation system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-restart-compensation-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-restart-compensation-model"}))
            .execute(&pool)
            .await
            .expect("insert resolver restart compensation agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert resolver restart compensation session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stopped_for_restart",
                100,
                "Stopped sandbox ready for restart",
                true,
                &expected,
                Some("resolver-restart-compensation-token"),
            );

            queries::create_sandbox(
                &pool,
                sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stopped sandbox");
            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET status = 'stopped',
                    runtime_config_status = 'restart_required',
                    runtime_config_last_reason = 'original_provider_marker',
                    runtime_config_required_at = $2
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .bind(original_required_at)
            .execute(&pool)
            .await
            .expect("mark stopped sandbox restart required");

            let provider = Arc::new(RecordingProvider {
                status_result: Mutex::new(match failure {
                    RestartProviderFailure::RuntimeGone => Some(SandboxStatus::NotFound),
                    RestartProviderFailure::StatusError | RestartProviderFailure::StartError => {
                        Some(SandboxStatus::Stopped)
                    }
                }),
                status_error: Mutex::new(match failure {
                    RestartProviderFailure::StatusError => Some("provider status failed".to_string()),
                    _ => None,
                }),
                start_error: Mutex::new(match failure {
                    RestartProviderFailure::StartError => Some("provider start failed".to_string()),
                    _ => None,
                }),
                status_marks_restart_required: Mutex::new(
                    write_newer_marker.then_some((pool.clone(), sandbox_id)),
                ),
                destroy_error: Mutex::new(Some("provider destroy failed".to_string())),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider, config);
            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("destroy failure must abort replacement provisioning");
            if write_newer_marker {
                assert!(matches!(
                    err.downcast_ref::<RuntimeFreshnessError>(),
                    Some(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id: id })
                        if *id == sandbox_id
                ));
            } else {
                assert!(err.to_string().contains("failed to destroy sandbox"));
            }

            let restored: (
                String,
                String,
                Option<String>,
                Option<chrono::DateTime<chrono::Utc>>,
            ) = sqlx::query_as(
                r#"
                SELECT status, runtime_config_status, runtime_config_last_reason, runtime_config_required_at
                FROM joysafeter_sandboxes
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after restart and destroy compensation");

            if write_newer_marker {
                assert_eq!(
                    restored,
                    (
                        "provisioning".to_string(),
                        "restart_required".to_string(),
                        Some("newer_provider_marker".to_string()),
                        Some(
                            "2026-08-21T14:15:16.777777Z"
                                .parse::<chrono::DateTime<chrono::Utc>>()
                                .expect("valid newer timestamp"),
                        ),
                    )
                );
            } else {
                assert_eq!(
                    restored,
                    (
                        "stopped".to_string(),
                        "restart_required".to_string(),
                        Some("original_provider_marker".to_string()),
                        Some(original_required_at),
                    )
                );
            }
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_restores_freshness_after_missing_runtime_and_destroy_failure() {
        assert_restart_failure_restores_runtime_configuration(
            RestartProviderFailure::RuntimeGone,
            false,
        )
        .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_restores_freshness_after_status_and_destroy_failures() {
        assert_restart_failure_restores_runtime_configuration(
            RestartProviderFailure::StatusError,
            false,
        )
        .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_restores_freshness_after_start_and_destroy_failures() {
        assert_restart_failure_restores_runtime_configuration(
            RestartProviderFailure::StartError,
            false,
        )
        .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_compensation_preserves_newer_freshness_marker() {
        assert_restart_failure_restores_runtime_configuration(
            RestartProviderFailure::StatusError,
            true,
        )
        .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_isolates_stale_creating_before_provider_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let stale_sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let image = format!("resolver-stale-creating-{unique}:latest");
        let external_id = format!("resolver-stale-creating-{stale_sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, 'resolver stale creating system', '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-stale-creating-agent-{unique}"))
            .bind(serde_json::json!({"id": "resolver-stale-creating-model"}))
            .execute(&pool)
            .await
            .expect("insert stale creating agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status)
                VALUES ($1, $2, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert stale creating session");

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: empty_network_policy_revision(),
            };
            let sandbox_config = provisioning_config(
                "stale_creating",
                0,
                "Stale creating sandbox should be isolated before provider destroy",
                false,
                &expected,
                Some("resolver-stale-creating-token"),
            );

            queries::create_sandbox(
                &pool,
                stale_sandbox_id,
                &external_id,
                "recording",
                &image,
                Some(session_id),
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("create stale creating sandbox");

            let provider = Arc::new(RecordingProvider {
                destroy_status_probe: Mutex::new(Some((pool.clone(), stale_sandbox_id))),
                ..Default::default()
            });
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            config.sandbox_image = image.clone();
            config.image_claude = image.clone();

            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);
            let resolved = resolver
                .resolve(
                    task_id,
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("resolve replacement after stale creating cleanup");
            assert_ne!(resolved.sandbox_id, stale_sandbox_id);

            let observed = provider.destroy_observed_statuses.lock().await.clone();
            assert_eq!(observed, vec!["stopping".to_string()]);

            let stale: (String, bool) = sqlx::query_as(
                "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(stale_sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load stale creating sandbox after cleanup");
            assert_eq!(stale.0, "destroyed");
            assert!(stale.1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn sandbox_resolver_uses_session_snapshot_for_image_network_and_env() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let agent_name = format!("resolver-snapshot-agent-{unique}");
        let environment_name = format!("resolver-snapshot-env-{unique}");
        let snapshot = serde_json::json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 3,
            "name": agent_name,
            "engine_kind": "claude",
            "model": {"id": "snapshot-model"},
            "env": {"AGENT_ENV": "snapshot-agent"},
            "mcp_servers": [],
            "tools": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "permission_mode": "bypassPermissions",
            "environment_id": environment_id.to_string(),
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": environment_name,
                "image_tag": "snapshot-image:1",
                "image_version": 1,
                "config": {
                    "env_vars": {"ENV_LEVEL": "snapshot-env"},
                    "networking": {
                        "type": "limited",
                        "allowed_hosts": ["api.openai.com"]
                    }
                }
            }
        });

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_environments
                    (id, name, description, config, image_tag, image_version)
                VALUES ($1, $2, 'resolver snapshot test env', $3, 'live-image:2', 2)
                "#,
            )
            .bind(environment_id)
            .bind(&environment_name)
            .bind(serde_json::json!({
                "env_vars": {"ENV_LEVEL": "live-env", "LIVE_ONLY": "must-not-appear"},
                "networking": {"type": "unrestricted"}
            }))
            .execute(&pool)
            .await
            .expect("insert live environment");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata,
                    version, environment_id
                )
                VALUES (
                    $1, $2, 'codex', $3, 'live system', $4, '[]'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'default', '{}'::jsonb, 4, $5
                )
                "#,
            )
            .bind(agent_id)
            .bind(&agent_name)
            .bind(serde_json::json!({"id": "live-model"}))
            .bind(serde_json::json!({"AGENT_ENV": "live-agent", "LIVE_AGENT_ONLY": "must-not-appear"}))
            .bind(environment_id)
            .execute(&pool)
            .await
            .expect("insert live agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, agent_version, agent_snapshot, environment_id
                )
                VALUES ($1, $2, 'idle', 3, $3, $4)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&snapshot)
            .bind(environment_id)
            .execute(&pool)
            .await
            .expect("insert snapshot session");

            let provider = Arc::new(RecordingProvider::default());
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.image_claude = "fallback-claude:latest".to_string();
            config.image_codex = "fallback-codex:latest".to_string();
            let resolver = recording_resolver(pool.clone(), provider.clone(), config);

            let resolved = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("resolve sandbox from snapshot");
            let sandbox_id = resolved.sandbox_id;

            let created = provider.created.lock().await;
            assert_eq!(created.len(), 1);
            let create_config = &created[0];
            assert_eq!(create_config.image, "snapshot-image:1");
            assert_eq!(create_config.network.as_deref(), Some("none"));
            assert_eq!(
                create_config.env.get("ENV_LEVEL").map(String::as_str),
                Some("snapshot-env")
            );
            assert_eq!(
                create_config.env.get("AGENT_ENV").map(String::as_str),
                Some("snapshot-agent")
            );
            assert!(!create_config.env.contains_key("LIVE_ONLY"));
            assert!(!create_config.env.contains_key("LIVE_AGENT_ONLY"));
            drop(created);

            let networking = provider.networking.lock().await;
            assert_eq!(networking.len(), 1);
            assert_eq!(networking[0].0, sandbox_id);
            assert_eq!(
                networking[0]
                    .1
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(|value| value.as_str()),
                Some("limited")
            );
            drop(networking);

            let sandbox_config: (String, serde_json::Value) =
                sqlx::query_as("SELECT image, config FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load created sandbox");
            assert_eq!(sandbox_config.0, "snapshot-image:1");
            assert_eq!(
                sandbox_config
                    .1
                    .get("fingerprint")
                    .and_then(|value| value.get("networking"))
                    .and_then(|value| value.get("type"))
                    .and_then(|value| value.as_str()),
                Some("limited")
            );
            assert!(sandbox_config
                .1
                .get("fingerprint")
                .and_then(|value| value.get("env"))
                .and_then(|value| value.get("ENV_LEVEL"))
                .is_some());
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
            .bind(environment_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn new_limited_sandbox_networking_failure_is_destroyed_and_not_returned() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let snapshot = serde_json::json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 1,
            "name": format!("network-failure-agent-{unique}"),
            "engine_kind": "claude",
            "model": {"id": "claude-sonnet"},
            "env": {},
            "mcp_servers": [],
            "tools": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "permission_mode": "bypassPermissions",
            "environment_id": environment_id.to_string(),
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": format!("network-failure-env-{unique}"),
                "image_tag": "network-failure:latest",
                "image_version": 1,
                "config": {"networking": {"type": "limited", "allowed_hosts": []}}
            }
        });

        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, permission_mode, metadata, version
            )
            VALUES (
                $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                'bypassPermissions', '{}'::jsonb, 1
            )
            "#,
        )
        .bind(agent_id)
        .bind(format!("network-failure-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert agent");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot)
            VALUES ($1, $2, 'idle', 1, $3)
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&snapshot)
        .execute(&pool)
        .await
        .expect("insert session");

        let provider = Arc::new(RecordingProvider {
            networking_error: Mutex::new(Some("synthetic Envoy rejection".to_string())),
            ..Default::default()
        });
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = true;
        config.image_claude = "network-failure:latest".to_string();
        let resolver = recording_resolver(pool.clone(), provider.clone(), config);

        let error = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("networking failure must reject new sandbox resolution");
        assert!(error
            .to_string()
            .contains("failed to setup Envoy networking"));
        assert_eq!(provider.destroyed.lock().await.len(), 1);

        let active_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1 AND destroyed_at IS NULL",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count active sandboxes");
        assert_eq!(active_count, 0);

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn new_sandbox_ack_persistence_error_runs_complete_compensation() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let function_name = format!("fail_network_ready_{unique}");
        let trigger_name = format!("trg_fail_network_ready_{unique}");
        let snapshot = serde_json::json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 1,
            "name": format!("ack-failure-agent-{unique}"),
            "engine_kind": "claude",
            "model": {"id": "claude-sonnet"},
            "env": {},
            "mcp_servers": [],
            "tools": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "permission_mode": "bypassPermissions",
            "environment_id": environment_id.to_string(),
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": format!("ack-failure-env-{unique}"),
                "image_tag": "ack-failure:latest",
                "image_version": 1,
                "config": {"networking": {"type": "limited", "allowed_hosts": []}}
            }
        });

        sqlx::query(
            r#"INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, permission_mode, metadata, version
            ) VALUES ($1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                'bypassPermissions', '{}'::jsonb, 1)"#,
        )
        .bind(agent_id)
        .bind(format!("ack-failure-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert ack failure agent");
        sqlx::query(
            "INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot) VALUES ($1, $2, 'idle', 1, $3)",
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&snapshot)
        .execute(&pool)
        .await
        .expect("insert ack failure session");
        sqlx::query(&format!(
            r#"CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.chat_session_id = '{session_uuid}'::uuid AND NEW.networking_status = 'ready' THEN
                    RAISE EXCEPTION 'synthetic ACK persistence failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql"#
        , session_uuid = session_id.as_uuid()))
        .execute(&pool)
        .await
        .expect("create ACK failure trigger function");
        sqlx::query(&format!(
            "CREATE TRIGGER {trigger_name} BEFORE UPDATE OF networking_status ON joysafeter_sandboxes FOR EACH ROW EXECUTE FUNCTION {function_name}()"
        ))
        .execute(&pool)
        .await
        .expect("create ACK failure trigger");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = true;
        config.image_claude = "ack-failure:latest".to_string();
        let resolver = recording_resolver(pool.clone(), provider.clone(), config);

        let error = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("ACK persistence failure must reject the new sandbox");
        assert!(
            format!("{error:#}").contains("failed to setup Envoy networking"),
            "unexpected error chain: {error:#}"
        );
        assert_eq!(provider.destroyed.lock().await.len(), 1);
        assert_eq!(provider.networking_teardowns.lock().await.len(), 1);
        let active_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1 AND destroyed_at IS NULL",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count active sandboxes after ACK failure");
        assert_eq!(active_count, 0);

        let _ = sqlx::query(&format!(
            "DROP TRIGGER IF EXISTS {trigger_name} ON joysafeter_sandboxes"
        ))
        .execute(&pool)
        .await;
        let _ = sqlx::query(&format!("DROP FUNCTION IF EXISTS {function_name}()"))
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn reused_limited_sandbox_networking_failure_is_not_returned() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let snapshot = serde_json::json!({
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "id": agent_id.to_string(),
            "version": 1,
            "name": format!("reuse-network-failure-agent-{unique}"),
            "engine_kind": "claude",
            "model": {"id": "claude-sonnet"},
            "env": {},
            "mcp_servers": [],
            "tools": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "permission_mode": "bypassPermissions",
            "environment_id": environment_id.to_string(),
            "environment": {
                "environment_id": environment_id.to_string(),
                "name": format!("reuse-network-failure-env-{unique}"),
                "image_tag": "reuse-network-failure:latest",
                "image_version": 1,
                "config": {"networking": {"type": "limited", "allowed_hosts": []}}
            }
        });

        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (
                id, name, engine_kind, model, system_prompt, env, mcp_servers,
                skills, tools, agents, commands, permission_mode, metadata, version
            )
            VALUES (
                $1, $2, 'claude', $3, '', '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                'bypassPermissions', '{}'::jsonb, 1
            )
            "#,
        )
        .bind(agent_id)
        .bind(format!("reuse-network-failure-agent-{unique}"))
        .bind(serde_json::json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert agent");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status, agent_version, agent_snapshot)
            VALUES ($1, $2, 'idle', 1, $3)
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&snapshot)
        .execute(&pool)
        .await
        .expect("insert session");

        let provider = Arc::new(RecordingProvider::default());
        let mut config = JoySafeterConfig::from_env();
        config.sandbox_provider = "recording".to_string();
        config.sandbox_pool_enabled = false;
        config.sandbox_workspace_root = None;
        config.envoy_enabled = true;
        config.image_claude = "reuse-network-failure:latest".to_string();
        let resolver = recording_resolver(pool.clone(), provider.clone(), config);

        let resolved = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect("create initial limited sandbox");
        assert!(queries::transition_sandbox_cas(
            &pool,
            resolved.sandbox_id,
            "provisioning",
            "idle",
        )
        .await
        .expect("mark initial sandbox idle"));
        resolver.network_policy_ready.remove(&resolved.sandbox_id);
        sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET networking_status = 'pending',
                networking_applied_hash = NULL,
                networking_applied_version = NULL,
                networking_ready_at = NULL
            WHERE id = $1
            "#,
        )
        .bind(resolved.sandbox_id)
        .execute(&pool)
        .await
        .expect("mark reused sandbox network policy pending");
        *provider.networking_error.lock().await =
            Some("synthetic Envoy refresh rejection".to_string());

        let error = resolver
            .resolve(
                TaskId::from_uuid(Uuid::now_v7()),
                Some(session_id),
                Some(agent_id),
                None,
            )
            .await
            .expect_err("networking refresh failure must reject sandbox reuse");
        assert!(error.to_string().contains("failed to refresh Envoy policy"));
        assert!(provider.destroyed.lock().await.is_empty());

        let networking_state: (String, Option<String>) = sqlx::query_as(
            "SELECT networking_status, networking_last_error FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(resolved.sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load failed reused sandbox networking state");
        assert_eq!(networking_state.0, "nacked");
        assert!(networking_state
            .1
            .as_deref()
            .is_some_and(|reason| reason.contains("synthetic Envoy refresh rejection")));

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
    }

    #[tokio::test]
    async fn sandbox_resolver_snapshot_session_file_injection_storage_missing_fails_resolve() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let file_id = FileId::from_uuid(Uuid::now_v7());
        let session_file_id = SessionResourceId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = OrganizationId::new();
        let project_id = ProjectId::new();
        let missing_storage_key = format!("missing-resolver-session-file-{unique}.txt");
        let workspace_root =
            std::env::temp_dir().join(format!("joysafeter-resolver-workspace-{unique}"));

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Resolver File Org {unique}"))
            .bind(format!("resolver-file-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Resolver File Project {unique}"))
            .bind(format!("resolver-file-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands, permission_mode,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("resolver-file-agent-{unique}"))
            .bind(serde_json::json!({"id": "claude-sonnet"}))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_files (
                    id, project_id, filename, purpose, content_type, size_bytes,
                    sha256, storage_key, downloadable
                )
                VALUES (
                    $1, $2, 'missing.txt', 'user_upload', 'text/plain', 12,
                    'missing-sha', $3, true
                )
                "#,
            )
            .bind(file_id)
            .bind(&project_id)
            .bind(&missing_storage_key)
            .execute(&pool)
            .await
            .expect("insert file metadata");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_files
                    (id, session_id, file_id, mount_path, access)
                VALUES ($1, $2, $3, '/workspace/missing.txt', 'read_only')
                "#,
            )
            .bind(session_file_id)
            .bind(session_id)
            .bind(file_id)
            .execute(&pool)
            .await
            .expect("insert session file mount");

            let provider = Arc::new(RecordingProvider::default());
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = Some(workspace_root.to_string_lossy().to_string());
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let err = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect_err("missing declared session file content must fail sandbox resolve");
            let message = err.to_string();
            assert!(
                message.contains("failed to inject session files"),
                "{message}"
            );
            assert!(message.contains(&missing_storage_key), "{message}");
            assert!(
                provider.created.lock().await.is_empty(),
                "sandbox provider must not create a sandbox after declared input load fails"
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_files WHERE id = $1")
            .bind(session_file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_files WHERE id = $1")
            .bind(file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;
        let _ = tokio::fs::remove_dir_all(&workspace_root).await;
    }
}
