use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;

use anyhow::Context;
use base64::Engine as _;
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Row};
use tracing::{debug, info, warn};
use url::Url;
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::{JoySafeterAgent, JoySafeterSandbox};
use crate::db::queries;
use crate::ids::{
    AgentId, CredentialId, EnvironmentId, FileId, SandboxId, SessionId, SessionResourceId, TaskId,
    VaultId,
};
use crate::kernel::harness_input_builder::VaultCipher;
use crate::kernel::run_spec::{agent_for_execution, environment_for_execution};
use crate::sandbox::lds_backend::{
    normalize_prefix, normalize_rewrite_base_prefix, EgressCredentialRoute, EgressExposure,
    EgressKind, SandboxCredentials, UpstreamTarget, GIT_EGRESS_HOST,
};
use crate::sandbox::mounts::{resolve_mount_resources, SandboxMount, SandboxMountFingerprint};
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

use super::llm_providers::llm_provider_registry;
#[cfg(test)]
use super::llm_providers::{CLAUDE_CODE_PLACEHOLDER_API_KEY, CODEX_PLACEHOLDER_OPENAI_API_KEY};

/// Hard client-side bound on a provider networking setup/refresh call (Envoy
/// socket prep + xDS push + ACK/socket-readiness wait). The individual steps are
/// bounded, but this outer bound guarantees the sandbox-provisioning path can
/// never block indefinitely on a wedged Envoy/xDS: on timeout the sandbox is
/// marked `failed` (fail-closed: it keeps network=none, no egress) and the
/// networking-reconcile loop retries it. Prevents a single stuck setup from
/// freezing task scheduling.
const SETUP_NETWORKING_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

fn mcp_credential_url_keys(raw: &str) -> Vec<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }

    let mut keys = vec![trimmed.to_string()];
    if let Ok(mut url) = Url::parse(trimmed) {
        if let Some(host) = url.host_str().map(|host| host.to_ascii_lowercase()) {
            let _ = url.set_host(Some(&host));
        }
        let path = url.path().to_string();
        if path != "/" {
            url.set_path(path.trim_end_matches('/'));
        }
        keys.push(url.to_string());
        if url.path() != "/" {
            let with_slash_path = format!("{}/", url.path().trim_end_matches('/'));
            url.set_path(&with_slash_path);
            keys.push(url.to_string());
        }
    }
    keys.sort();
    keys.dedup();
    keys
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
    config: JoySafeterConfig,
    /// Per-session locks to prevent concurrent resolution
    session_locks: dashmap::DashMap<SessionId, Arc<tokio::sync::Mutex<()>>>,
    /// In-process confirmation that this orchestrator has successfully pushed
    /// the sandbox's current Envoy policy. DB state alone is not enough after a
    /// process restart because xDS state is in-memory; the first reuse after
    /// restart refreshes Envoy and repopulates this cache.
    network_policy_ready: dashmap::DashMap<SandboxId, String>,
}

impl SandboxResolver {
    pub fn new(pool: PgPool, provider: Arc<dyn SandboxProvider>, config: JoySafeterConfig) -> Self {
        Self {
            pool,
            provider,
            config,
            session_locks: dashmap::DashMap::new(),
            network_policy_ready: dashmap::DashMap::new(),
        }
    }

    /// Resolve a sandbox for the given task.
    /// Returns (sandbox_db_id, external_id).
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
    /// multi-instance HA, the CAS guard in `attach_sandbox_to_task` prevents
    /// double-attachment.
    pub async fn resolve(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<&str>,
    ) -> anyhow::Result<(SandboxId, String)> {
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
        project_id: Option<&str>,
    ) -> anyhow::Result<(SandboxId, String)> {
        let context = self
            .build_resolve_context(session_id, agent_id, project_id)
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
                                return Ok((sandbox.id, ext_id.clone()));
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
                                return Ok((sandbox.id, ext_id.clone()));
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
                                if self.restart_stopped_sandbox(sandbox.id, ext_id).await? {
                                    info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox");
                                    return Ok((sandbox.id, ext_id.clone()));
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
                    if self.restart_stopped_sandbox(sandbox.id, ext_id).await? {
                        info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox for session");
                        return Ok((sandbox.id, ext_id.clone()));
                    }
                }
            }
        }

        // Stage 2: Claim from warm pool
        let requires_persistent_workspace =
            context.session_id.is_some() && self.config.sandbox_workspace_root.is_some();
        if self.config.sandbox_pool_enabled
            && context.expected.env.is_empty()
            && !context.is_limited_networking()
            && !requires_persistent_workspace
        {
            let image = context.expected.image.as_str();
            if let Some(sandbox) = queries::claim_pool_sandbox(&self.pool, image).await? {
                if let Some(ref ext_id) = sandbox.external_id {
                    // Liveness check
                    match self.provider.status(ext_id).await {
                        Ok(SandboxStatus::Running) => {
                            if let Err(err) = self
                                .mark_pool_claimed(
                                    sandbox.id,
                                    session_id,
                                    &context.expected,
                                    "pool_claimed",
                                    80,
                                    "Claimed from warm pool, waiting for runner readiness",
                                )
                                .await
                            {
                                warn!(
                                    sandbox_id = %sandbox.id,
                                    error = %err,
                                    "Failed to attach claimed warm-pool sandbox metadata, destroying runtime"
                                );
                                if let Err(cleanup_err) = self
                                    .destroy_unattached_pool_claim(
                                        &sandbox,
                                        "pool claim session attach failure",
                                    )
                                    .await
                                {
                                    warn!(
                                        sandbox_id = %sandbox.id,
                                        error = %cleanup_err,
                                        "Failed to cleanup warm-pool claim after session attach failure"
                                    );
                                }
                                return Err(err);
                            }
                            info!(
                                sandbox_id = %sandbox.id,
                                task_id = %task_id,
                                "Claimed sandbox from warm pool"
                            );
                            // #21: inject session files after pool claim (Python L316-328).
                            // Pool claims intentionally use workspace_path=None so the
                            // strategy falls through to provider fallback instead of host mount.
                            if let Some(sid) = context.session_id {
                                let ctx = crate::sandbox::file_injection::FileInjectionContext {
                                    session_id: sid,
                                    external_id: ext_id.clone(),
                                    workspace_path: None,
                                    runner_capabilities: vec![],
                                    is_pool_sandbox: true,
                                };
                                if let Err(err) =
                                    crate::sandbox::file_injection::inject_session_files(
                                        &self.pool,
                                        &ctx,
                                        self.provider.as_ref(),
                                    )
                                    .await
                                {
                                    warn!(
                                        sandbox_id = %sandbox.id,
                                        session_id = %sid,
                                        "Failed to inject session files into pooled sandbox, destroying claimed sandbox: {err}"
                                    );
                                    let _ = self
                                        .destroy_observed_sandbox(
                                            &sandbox,
                                            "pooled session file injection failure",
                                        )
                                        .await;
                                    anyhow::bail!(
                                        "failed to inject session files into pooled sandbox {} for session {}: {err}",
                                        sandbox.id,
                                        sid
                                    );
                                }
                            }
                            return Ok((sandbox.id, ext_id.clone()));
                        }
                        Ok(SandboxStatus::Stopped) => {
                            // Try to start pooled sandbox
                            if self.provider.start(ext_id).await.is_ok() {
                                if let Err(err) = self
                                    .mark_pool_claimed(
                                        sandbox.id,
                                        session_id,
                                        &context.expected,
                                        "pool_restarting",
                                        75,
                                        "Claimed stopped pooled sandbox, restarting runtime",
                                    )
                                    .await
                                {
                                    warn!(
                                        sandbox_id = %sandbox.id,
                                        error = %err,
                                        "Failed to attach restarted warm-pool sandbox metadata, destroying runtime"
                                    );
                                    if let Err(cleanup_err) = self
                                        .destroy_unattached_pool_claim(
                                            &sandbox,
                                            "restarted pool claim session attach failure",
                                        )
                                        .await
                                    {
                                        warn!(
                                            sandbox_id = %sandbox.id,
                                            error = %cleanup_err,
                                            "Failed to cleanup restarted warm-pool claim after session attach failure"
                                        );
                                    }
                                    return Err(err);
                                }
                                info!(sandbox_id = %sandbox.id, "Started pooled sandbox");
                                return Ok((sandbox.id, ext_id.clone()));
                            }
                            // Broken pooled sandbox — destroy it
                            warn!(sandbox_id = %sandbox.id, "Destroying broken pooled sandbox");
                            let _ = self
                                .destroy_observed_sandbox(&sandbox, "stopped pooled runtime")
                                .await;
                        }
                        Err(err) => {
                            warn!(sandbox_id = %sandbox.id, external_id = %ext_id, error = %err, "Cannot query pooled sandbox status, destroying");
                            let _ = self
                                .destroy_observed_sandbox(&sandbox, "pool status error")
                                .await;
                        }
                        _ => {
                            warn!(sandbox_id = %sandbox.id, external_id = %ext_id, "Pooled sandbox has unexpected status, destroying");
                            let _ = self
                                .destroy_observed_sandbox(&sandbox, "unexpected pool status")
                                .await;
                        }
                    }
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
    ) -> anyhow::Result<(SandboxId, String)> {
        let sandbox_db_id = SandboxId::from_uuid(Uuid::now_v7());
        let expected = context.expected.clone();
        let image = expected.image.clone();
        let runner_token = generate_runner_token();

        // Build environment variables — both JOYSAFETER_* and JOYSAFETER_* variants
        let mut env = expected.env.clone();
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.as_uuid().to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());
        // Disable Claude Code telemetry — the sandbox has no route to
        // api.anthropic.com and telemetry attempts just produce NR 404 noise.
        env.entry("DISABLE_TELEMETRY".to_string())
            .or_insert_with(|| "1".to_string());

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
        if let Some(ref sid) = context.session_id {
            labels.insert("joysafeter.session_id".to_string(), sid.to_string());
        }
        if let Some(ref project_id) = context.project_id {
            labels.insert("joysafeter.project_id".to_string(), project_id.clone());
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

        let create_result = queries::create_sandbox(
            &self.pool,
            sandbox_db_id,
            &external_id,
            self.config.sandbox_provider.as_str(),
            &image,
            context.session_id,
            context.project_id.as_deref(),
            create_config.workspace_path.as_deref(),
            Some(&sandbox_config),
        )
        .await;
        if let Err(e) = create_result {
            let _ = self.provider.destroy(&external_id).await;
            let _ = self.teardown_networking(sandbox_db_id).await;
            return Err(e.into());
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
                self.network_policy_ready.remove(&sandbox_db_id);
                let _ = self.provider.destroy(&external_id).await;
                let _ = self.teardown_networking(sandbox_db_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_db_id).await;
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
                let _ = self.provider.destroy(&external_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_db_id).await;
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
            if let Err(e) = queries::prepare_sandbox_network_policy_push(
                &self.pool,
                sandbox_db_id,
                &context.expected.egress_policy_hash,
            )
            .await
            {
                let _ = self.provider.destroy(&external_id).await;
                let _ = queries::destroy_sandbox(&self.pool, sandbox_db_id).await;
                return Err(anyhow::anyhow!(
                    "failed to mark sandbox network policy pending: {e}"
                ));
            }
            info!(
                sandbox_id = %sandbox_db_id,
                external_id = %external_id,
                "Pushing Envoy networking (off the sandbox-start critical path)"
            );
            let setup_result = tokio::time::timeout(
                SETUP_NETWORKING_TIMEOUT,
                self.provider.setup_networking(
                    sandbox_db_id,
                    &external_id,
                    context.networking.as_ref(),
                    context
                        .credentials
                        .clone()
                        .with_proxy_auth_token(Some(runner_token.clone())),
                ),
            )
            .await
            .unwrap_or_else(|_| {
                Err(anyhow::anyhow!(
                    "setup_networking exceeded {SETUP_NETWORKING_TIMEOUT:?}"
                ))
            });
            if let Err(e) = setup_result {
                self.network_policy_ready.remove(&sandbox_db_id);
                warn!(
                    sandbox_id = %sandbox_db_id,
                    external_id = %external_id,
                    error = %e,
                    "Envoy egress networking setup failed; sandbox already started with degraded egress (runner control gRPC uses direct UDS). The networking reconcile loop will retry."
                );
                let _ = queries::update_sandbox_networking_status(
                    &self.pool,
                    sandbox_db_id,
                    "failed",
                    Some(&context.expected.egress_policy_hash),
                    None,
                    Some(&e.to_string()),
                )
                .await;
                let _ = self
                    .persist_network_policy_failure(sandbox_db_id, Some(task_id), &context, &e)
                    .await;
            } else {
                info!(
                    sandbox_id = %sandbox_db_id,
                    external_id = %external_id,
                    "Envoy networking ready"
                );
                self.network_policy_ready
                    .insert(sandbox_db_id, context.expected.egress_policy_hash.clone());
                if self.config.envoy_xds_mode != "grpc" {
                    let _ =
                        queries::mark_sandbox_network_policy_acked(&self.pool, sandbox_db_id).await;
                }
            }
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

        Ok((sandbox_db_id, external_id))
    }

    async fn build_resolve_context(
        &self,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<&str>,
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
        let agent = agent_for_execution(live_agent, session.as_ref());
        let project_id = project_id
            .map(ToOwned::to_owned)
            .or_else(|| session.as_ref().and_then(|s| s.project_id.clone()))
            .or_else(|| agent.as_ref().and_then(|a| a.project_id.clone()));
        let environment_ref = agent
            .as_ref()
            .and_then(|a| non_empty(a.environment_ref.as_deref()))
            .or_else(|| {
                session
                    .as_ref()
                    .and_then(|s| non_empty(s.environment_ref.as_deref()))
            });

        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else if let Some(ref env_ref) = environment_ref {
            self.load_environment(env_ref, project_id.as_deref())
                .await?
        } else {
            None
        };

        let engine_kind = agent
            .as_ref()
            .and_then(|a| a.engine_kind.clone())
            .unwrap_or_else(|| "claude".to_string());
        let image = match environment.as_ref().and_then(|env| env.image_tag.clone()) {
            Some(tag) => tag,
            None => self.config.image_for_provider(&engine_kind)?,
        };
        let mut env =
            Self::resolve_agent_env_from(&self.pool, agent.as_ref(), environment.as_ref()).await?;
        let configured_networking = environment
            .as_ref()
            .and_then(|env| env.config.get("networking").cloned());
        let networking = effective_networking_config(
            configured_networking,
            self.config.envoy_enabled,
            agent.as_ref(),
            environment.as_ref(),
        )?;
        let network = if networking_type(networking.as_ref()) == Some("limited") {
            Some("none".to_string())
        } else {
            None
        };

        // Egress credential injection only applies to limited-networking sandboxes
        // (those routed through Envoy). For those, pull the LLM key out of the
        // container env and repoint the base URL at the egress boundary so the
        // real key never enters the sandbox. Unrestricted sandboxes keep the
        // key in their environment because they do not route through Envoy.
        let mut credentials = SandboxCredentials::default();
        if network.as_deref() == Some("none") {
            let mut routes = Vec::new();
            routes.extend(Self::extract_llm_egress(
                &mut env,
                &self.config.llm_egress_allowed_hosts,
            ));
            routes.extend(Self::build_mcp_egress(&self.pool, session_id, agent.as_ref()).await?);
            routes.extend(Self::build_git_egress(&self.pool, session_id).await?);
            routes.extend(
                Self::build_external_egress(
                    &self.pool,
                    environment.as_ref(),
                    project_id.as_deref(),
                )
                .await,
            );
            credentials = SandboxCredentials {
                routes,
                proxy_auth_token: None,
            };
        }
        let egress_policy_hash = egress_policy_hash(networking.as_ref(), &credentials);

        let storage_catalog = self
            .load_storage_volume_catalog(project_id.as_deref())
            .await?;
        let (mounts, mount_fingerprint) = resolve_mount_resources(
            environment.as_ref().map(|env| &env.config),
            &storage_catalog,
            &self.config.sandbox_provider,
        )?;

        Ok(ResolveContext {
            session_id,
            project_id,
            networking: networking.clone(),
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
        })
    }

    async fn load_environment(
        &self,
        env_ref: &str,
        project_id: Option<&str>,
    ) -> anyhow::Result<Option<EnvironmentRow>> {
        if let Ok(env_id) = EnvironmentId::from_public(env_ref) {
            return sqlx::query_as::<_, EnvironmentRow>(
                r#"
                SELECT config, image_tag FROM joysafeter_environments
                WHERE id = $1 AND deleted_at IS NULL
                  AND ($2::text IS NULL OR project_id = $2)
                "#,
            )
            .bind(env_id)
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(Into::into);
        }
        sqlx::query_as::<_, EnvironmentRow>(
            r#"
            SELECT config, image_tag FROM joysafeter_environments
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            "#,
        )
        .bind(env_ref)
        .bind(project_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(Into::into)
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

        let _ = queries::prepare_sandbox_network_policy_push(
            &self.pool,
            sandbox.id,
            &context.expected.egress_policy_hash,
        )
        .await?;
        let refresh_result = tokio::time::timeout(
            SETUP_NETWORKING_TIMEOUT,
            self.provider.refresh_networking(
                sandbox.id,
                external_id,
                context.networking.as_ref(),
                context
                    .credentials
                    .clone()
                    .with_proxy_auth_token(sandbox_runner_token(sandbox)),
            ),
        )
        .await
        .unwrap_or_else(|_| {
            Err(anyhow::anyhow!(
                "refresh_networking exceeded {SETUP_NETWORKING_TIMEOUT:?}"
            ))
        })
        .with_context(|| format!("failed to refresh Envoy policy for sandbox {}", sandbox.id));
        if let Err(e) = refresh_result {
            self.network_policy_ready.remove(&sandbox.id);
            let _ = self
                .persist_network_policy_failure(sandbox.id, None, context, &e)
                .await;
            warn!(
                sandbox_id = %sandbox.id,
                error = %e,
                "Envoy policy refresh failed for reused sandbox; continuing with degraded networking"
            );
            return Ok(());
        }

        self.network_policy_ready
            .insert(sandbox.id, context.expected.egress_policy_hash.clone());
        if self.config.envoy_xds_mode != "grpc" {
            let _ = queries::mark_sandbox_network_policy_acked(&self.pool, sandbox.id).await;
        }

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

    async fn persist_network_policy_failure(
        &self,
        sandbox_id: SandboxId,
        task_id: Option<TaskId>,
        context: &ResolveContext,
        error: &anyhow::Error,
    ) -> anyhow::Result<()> {
        let desired_policy = serde_json::json!({
            "fingerprint": context.expected.to_json(),
            "networking": context.networking.clone().unwrap_or_else(|| serde_json::json!({})),
            "recorded_on": "failure",
        });
        let rendered_policy = context.credentials.to_policy(
            &sandbox_id,
            allowed_hosts_from_networking(context.networking.as_ref()),
        );
        let rendered_summary =
            crate::sandbox::lds_backend::egress_policy_summary(&sandbox_id, &rendered_policy);
        let reason = error.to_string();
        queries::record_network_policy_failure_detail(
            &self.pool,
            queries::UpsertNetworkPolicy {
                sandbox_id,
                session_id: context.session_id,
                task_id,
                policy_hash: &context.expected.egress_policy_hash,
                desired_policy_json: &desired_policy,
                rendered_summary_json: &rendered_summary,
            },
            &reason,
        )
        .await?;
        if task_id.is_none() {
            debug!(sandbox_id = %sandbox_id, "Recorded sandbox network policy failure without task context");
        }
        Ok(())
    }

    async fn load_storage_volume_catalog(
        &self,
        project_id: Option<&str>,
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

    async fn resolve_agent_env_from(
        pool: &PgPool,
        agent: Option<&JoySafeterAgent>,
        environment: Option<&EnvironmentRow>,
    ) -> anyhow::Result<HashMap<String, String>> {
        let mut env = HashMap::new();
        let Some(agent) = agent else {
            return Ok(env);
        };

        if let Some(environment) = environment {
            if let Some(env_vars) = environment
                .config
                .get("env_vars")
                .and_then(|v| v.as_object())
            {
                for (key, value) in env_vars {
                    let value = value
                        .as_str()
                        .map(ToOwned::to_owned)
                        .unwrap_or_else(|| value.to_string());
                    env.insert(key.clone(), value);
                }
            }

            if let Some(secret_refs) = environment
                .config
                .get("secret_refs")
                .and_then(|v| v.as_array())
            {
                for secret_ref in secret_refs.iter().filter_map(|v| v.as_str()) {
                    Self::merge_secret_ref_into_env(
                        pool,
                        &mut env,
                        secret_ref,
                        agent.project_id.as_deref(),
                        false,
                    )
                    .await?;
                }
            }
        }

        if let Some(secret_ref) = agent.secret_ref.as_deref().filter(|v| !v.trim().is_empty()) {
            Self::merge_secret_ref_into_env(
                pool,
                &mut env,
                secret_ref,
                agent.project_id.as_deref(),
                true,
            )
            .await?;
        }

        if let Some(obj) = agent.env.as_ref().and_then(|v| v.as_object()) {
            for (key, value) in obj {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                env.insert(key.clone(), value);
            }
        }

        apply_provider_aliases(&mut env);

        Ok(env)
    }

    /// Extract LLM egress credentials from the resolved env, removing the real
    /// key from the env map and repointing the base URL at the Envoy egress
    /// boundary. After this, the container env holds no LLM API key — the key is
    /// injected by Envoy at the egress boundary instead.
    ///
    /// Provider detection is data-driven via [`llm_provider_registry`]: the first
    /// spec whose detection key is present in `env` wins. The upstream host is
    /// derived from the corresponding `*_BASE_URL` (using the spec's default when
    /// unset), then the base URL is rewritten to the plaintext egress placeholder
    /// so the agent's HTTP client targets Envoy.
    fn extract_llm_egress(
        env: &mut HashMap<String, String>,
        allowed_hosts: &[String],
    ) -> Vec<EgressCredentialRoute> {
        // Find the first matching provider spec by scanning detection keys in
        // registry order (preserves the original if/else precedence).
        let registry = llm_provider_registry();
        let (spec, matched_key) = match registry.iter().find_map(|spec| {
            spec.detection_keys
                .iter()
                .find(|k| env.contains_key(**k))
                .map(|k| (spec, *k))
        }) {
            Some(pair) => pair,
            None => return vec![],
        };

        // Take the key value, removing it from env.
        let Some(key_value) = env.remove(matched_key) else {
            return vec![];
        };

        // Remove all extra keys associated with this provider (unconditional —
        // mirrors the original behavior where Anthropic vars are always removed
        // regardless of which one matched).
        for extra in spec.extra_keys_to_remove {
            env.remove(*extra);
        }

        let base_url_var = spec.base_url_var;
        let default_host = spec.default_host;

        // Parse the configured base URL to learn the real upstream
        // host/port/scheme/path. The sandbox is then repointed at the placeholder
        // egress host over plaintext http:// — it never learns the real address.
        // Envoy matches the placeholder, injects the key, host_rewrites to the
        // real upstream, and forwards via that upstream's STRICT_DNS cluster.
        let configured = env.get(base_url_var).cloned();
        let (upstream_host, upstream_port, upstream_prefix, upstream_tls) = match configured
            .as_deref()
        {
            Some(raw) => {
                let url = match Url::parse(raw) {
                    Ok(url) => url,
                    Err(e) => {
                        warn!(base_url_var, error = %e, "Invalid LLM base URL; skipping credential injection");
                        return vec![];
                    }
                };
                if url.scheme() != "http" && url.scheme() != "https" {
                    warn!(
                        base_url_var,
                        scheme = url.scheme(),
                        "Unsupported LLM base URL scheme; skipping credential injection"
                    );
                    return vec![];
                }
                let host = match (url.host_str(), default_host) {
                    (Some(h), _) => h.to_string(),
                    (None, Some(d)) => d.to_string(),
                    (None, None) => return vec![],
                };
                let tls = url.scheme() == "https";
                let port = url.port().unwrap_or(if tls { 443 } else { 80 });
                let prefix = normalize_llm_upstream_prefix(url.path());
                (host, port, prefix, tls)
            }
            // No base URL configured: use the provider default if it has one.
            // Providers without a fixed endpoint (Azure) require an explicit base
            // URL, so bail rather than inject a key toward an unknown host.
            None => match default_host {
                Some(d) => (d.to_string(), 443, "/".to_string(), true),
                None => {
                    warn!(
                        base_url_var,
                        "LLM provider requires an explicit base URL (no fixed \
                     endpoint); skipping credential injection"
                    );
                    return vec![];
                }
            },
        };

        if !is_llm_egress_host_allowed(&upstream_host, allowed_hosts) {
            warn!(
                base_url_var,
                upstream_host = %upstream_host,
                "LLM base URL host is not allowlisted; skipping credential injection"
            );
            return vec![];
        }

        // Insert non-secret placeholder so the agent CLI doesn't fall back to
        // interactive login. Envoy overwrites/removes auth headers at the egress
        // boundary and injects the real credential there.
        if let Some((placeholder_var, placeholder_val)) = spec.placeholder {
            env.insert(placeholder_var.to_string(), placeholder_val.to_string());
        }

        // Repoint the agent at the real upstream host but downgrade to plaintext
        // http:// so the request goes through the HTTP proxy as a normal request
        // (not a CONNECT tunnel). This lets Envoy see and inject headers. Envoy
        // does TLS origination via the shared dynamic_forward_proxy_tls cluster.
        let base_url_for_sandbox = if upstream_tls {
            format!(
                "http://{}:{}{}",
                upstream_host, upstream_port, upstream_prefix
            )
        } else {
            format!(
                "http://{}:{}{}",
                upstream_host, upstream_port, upstream_prefix
            )
        };
        env.insert(base_url_var.to_string(), base_url_for_sandbox);

        let header_value = if spec.is_bearer {
            format!("Bearer {key_value}")
        } else {
            key_value
        };

        vec![EgressCredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Transparent,
            match_host: upstream_host.clone(),
            match_prefix: "/".to_string(),
            exact_path: false,
            upstream_host,
            upstream_port,
            upstream_prefix: normalize_rewrite_base_prefix(&upstream_prefix),
            upstream_tls,
            cluster_name: String::new(),
            inject_headers: vec![(spec.header_name.to_string(), header_value)],
            remove_headers: vec![],
        }]
    }

    /// Build MCP egress credentials for a sandbox: for each remote MCP server the
    /// agent references, match a vault credential by URL, decrypt its token, and
    /// produce an [`EgressCredentialRoute`] keyed by the server name. The
    /// `.mcp.json` written
    /// into the sandbox points at `mcp-egress.internal/mcp/<name>/` with no token;
    /// Envoy injects the real `Authorization` here.
    async fn build_mcp_egress(
        pool: &PgPool,
        session_id: Option<SessionId>,
        agent: Option<&JoySafeterAgent>,
    ) -> anyhow::Result<Vec<EgressCredentialRoute>> {
        let Some(agent) = agent else {
            return Ok(vec![]);
        };
        let Some(session_id) = session_id else {
            return Ok(vec![]);
        };
        // Remote MCP servers (url present) declared by the agent.
        let mcp_servers: Vec<(String, String)> = agent
            .mcp_servers
            .as_ref()
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| {
                        let name = item.get("name").and_then(|v| v.as_str())?;
                        let url = item.get("url").and_then(|v| v.as_str())?;
                        if url.is_empty() {
                            None
                        } else {
                            Some((name.to_string(), url.to_string()))
                        }
                    })
                    .collect()
            })
            .unwrap_or_default();
        if mcp_servers.is_empty() {
            return Ok(vec![]);
        }

        // Load the session's vault credentials, keyed by mcp_server_url.
        let session = match queries::get_session(pool, session_id).await {
            Ok(Some(s)) => s,
            Ok(None) => return Ok(vec![]),
            Err(e) => {
                return Err(anyhow::anyhow!(
                    "failed to load session {session_id} while building MCP egress: {e}"
                ));
            }
        };
        let Some(vault_ids) = session.vault_ids.as_ref() else {
            return Ok(vec![]);
        };
        let ids: Vec<VaultId> = vault_ids
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str())
                    .filter_map(parse_vault_ref)
                    .collect()
            })
            .unwrap_or_default();
        if ids.is_empty() {
            return Ok(vec![]);
        }

        let cipher = VaultCipher::from_env();
        let mut token_by_url: HashMap<String, String> = HashMap::new();
        for vault_id in ids {
            let rows: Vec<(Option<String>, String)> = sqlx::query_as(
                r#"
                SELECT c.mcp_server_url, c.token_value
                FROM joysafeter_vault_credentials c
                JOIN joysafeter_vaults v ON v.id = c.vault_id
                WHERE c.vault_id = $1
                  AND c.deleted_at IS NULL
                  AND c.archived_at IS NULL
                  AND v.deleted_at IS NULL
                  AND v.archived_at IS NULL
                "#,
            )
            .bind(vault_id)
            .fetch_all(pool)
            .await
            .map_err(|e| {
                anyhow::anyhow!("failed to load vault credentials for vault {vault_id}: {e}")
            })?;
            for (url, token_value) in rows {
                if let Some(url) = url {
                    let tok = cipher.decrypt_or_passthrough(&token_value).map_err(|e| {
                        anyhow::anyhow!(
                            "failed to decrypt vault credential for MCP server '{url}' in vault {vault_id}: {e}"
                        )
                    })?;
                    for key in mcp_credential_url_keys(&url) {
                        token_by_url.insert(key, tok.clone());
                    }
                }
            }
        }

        let mut egress = Vec::new();
        for (name, url) in mcp_servers {
            let token = mcp_credential_url_keys(&url)
                .into_iter()
                .find_map(|key| token_by_url.get(&key));
            let Some(token) = token else {
                continue;
            };
            let upstream = UpstreamTarget::from_url(&url)
                .map_err(|e| anyhow::anyhow!("invalid MCP server URL '{url}': {e}"))?;
            egress.push(EgressCredentialRoute {
                id: format!("mcp:{name}"),
                kind: EgressKind::Mcp,
                exposure: EgressExposure::Transparent,
                match_host: upstream.host.clone(),
                match_prefix: normalize_prefix(&upstream.prefix),
                exact_path: false,
                upstream_host: upstream.host,
                upstream_port: upstream.port,
                upstream_prefix: normalize_prefix(&upstream.prefix),
                upstream_tls: upstream.tls,
                cluster_name: String::new(),
                inject_headers: vec![("authorization".to_string(), format!("Bearer {token}"))],
                remove_headers: vec![],
            });
        }
        Ok(egress)
    }

    /// Build git egress credentials: decrypt each session repo's clone token and
    /// produce an [`EgressCredentialRoute`] keyed by a stable slug ([`git_repo_slug`]). The
    /// sandbox clones from `git-egress.internal/git/<slug>/` (no token); Envoy
    /// rewrites to the real host + repo path, injects HTTP Basic auth, and
    /// forwards over the upstream scheme. The real token never enters the sandbox.
    async fn build_git_egress(
        pool: &PgPool,
        session_id: Option<SessionId>,
    ) -> anyhow::Result<Vec<EgressCredentialRoute>> {
        let Some(session_id) = session_id else {
            return Ok(vec![]);
        };
        let rows: Vec<(String, String, String)> = sqlx::query_as(
            r#"
            SELECT url, mount_name, encrypted_token
            FROM joysafeter_session_repos
            WHERE session_id = $1
            ORDER BY created_at
            "#,
        )
        .bind(session_id)
        .fetch_all(pool)
        .await
        .map_err(|e| {
            anyhow::anyhow!(
                "failed to load session repos for Git egress in session {session_id}: {e}"
            )
        })?;

        let cipher = VaultCipher::from_env();
        let mut egress = Vec::new();
        for (idx, (url, mount_name, encrypted_token)) in rows.into_iter().enumerate() {
            if encrypted_token.is_empty() {
                continue;
            }
            let token = cipher.decrypt_or_passthrough(&encrypted_token).map_err(|e| {
                anyhow::anyhow!(
                    "failed to decrypt Git token for repo '{mount_name}' in session {session_id}: {e}"
                )
            })?;
            if token.is_empty() {
                continue;
            }
            let upstream = UpstreamTarget::from_url(&url)
                .map_err(|e| anyhow::anyhow!("invalid Git repo URL '{url}': {e}"))?;
            // Preserve the repo path so Envoy rewrites /git/<slug>/ back to the
            // real repo path (e.g. /org/repo.git/), keeping git smart-HTTP happy.
            let mut prefix = upstream.prefix;
            if !prefix.ends_with('/') {
                prefix.push('/');
            }
            // HTTP Basic auth: username "x-access-token" (GitHub) / any (GitLab),
            // password = token. base64("x-access-token:<token>").
            let basic =
                base64::engine::general_purpose::STANDARD.encode(format!("x-access-token:{token}"));
            let slug = crate::sandbox::lds_backend::git_repo_slug(&mount_name, idx);
            egress.push(EgressCredentialRoute {
                id: format!("git:{slug}"),
                kind: EgressKind::Git,
                exposure: EgressExposure::Placeholder,
                match_host: GIT_EGRESS_HOST.to_string(),
                match_prefix: format!("/git/{slug}/"),
                exact_path: false,
                upstream_host: upstream.host,
                upstream_port: upstream.port,
                upstream_prefix: prefix,
                upstream_tls: upstream.tls,
                cluster_name: String::new(),
                inject_headers: vec![("authorization".to_string(), format!("Basic {basic}"))],
                remove_headers: vec![],
            });
        }
        Ok(egress)
    }

    /// Build external-service egress routes from `environment.config.egress_services`.
    ///
    /// For each service, emits a placeholder route (on `external-egress.internal`)
    /// and a transparent route (on the real host) so skills can use either URL
    /// pattern. The secret is decrypted and headers are built according to the
    /// `inject` config (bearer / api_key / cookie).
    async fn build_external_egress(
        pool: &PgPool,
        environment: Option<&EnvironmentRow>,
        project_id: Option<&str>,
    ) -> Vec<EgressCredentialRoute> {
        let Some(services) = environment
            .and_then(|environment| environment.config.get("egress_services"))
            .and_then(|value| value.as_array())
        else {
            return vec![];
        };

        let mut routes = Vec::new();
        for service in services {
            let Some(name) = service.get("name").and_then(|value| value.as_str()) else {
                continue;
            };
            let name = sanitize_external_service_name(name);
            if name.is_empty() {
                continue;
            }

            let Some(base_url) = service.get("base_url").and_then(|value| value.as_str()) else {
                continue;
            };
            let Ok(upstream) = UpstreamTarget::from_url(base_url) else {
                warn!(service = %name, "Invalid external egress service base_url");
                continue;
            };
            let host = upstream.host;
            let tls = upstream.tls;
            let port = upstream.port;
            let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);

            let Some(credential_ref) = service
                .get("credential_ref")
                .and_then(|value| value.as_str())
                .filter(|value| !value.trim().is_empty())
            else {
                continue;
            };
            let Some(inject) = service.get("inject").and_then(|value| value.as_object()) else {
                continue;
            };

            let secret = match Self::load_secret_data(pool, credential_ref, project_id).await {
                Ok(Some(secret)) => secret,
                Ok(None) => continue,
                Err(e) => {
                    warn!(service = %name, credential_ref, "Failed to load external egress secret: {e}");
                    continue;
                }
            };
            let headers = match build_external_inject_headers(&secret, inject) {
                Ok(headers) if !headers.is_empty() => headers,
                Ok(_) => continue,
                Err(e) => {
                    warn!(service = %name, credential_ref, "Failed to build external egress headers: {e}");
                    continue;
                }
            };

            let remove_headers = vec![
                "authorization".to_string(),
                "cookie".to_string(),
                "x-api-key".to_string(),
                "api-key".to_string(),
                "x-goog-api-key".to_string(),
            ];

            // Transparent route(s): sandbox calls the real host over plaintext http.
            // Envoy matches the real host vhost, injects the credential, and
            // TLS-originates to the real upstream when needed.
            let allowed_paths: Vec<String> = service
                .get("allowed_paths")
                .and_then(|value| value.as_array())
                .map(|values| {
                    values
                        .iter()
                        .filter_map(|value| value.as_str())
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect()
                })
                .unwrap_or_default();

            if allowed_paths.is_empty() {
                routes.push(EgressCredentialRoute {
                    id: format!("external-direct:{name}"),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Transparent,
                    match_host: host.clone(),
                    match_prefix: upstream_prefix.clone(),
                    exact_path: false,
                    upstream_host: host.clone(),
                    upstream_port: port,
                    upstream_prefix: upstream_prefix.clone(),
                    upstream_tls: tls,
                    cluster_name: String::new(),
                    inject_headers: headers.clone(),
                    remove_headers: remove_headers.clone(),
                });
            } else {
                for (idx, entry) in allowed_paths.iter().enumerate() {
                    let is_prefix = entry.ends_with('/');
                    let full_path = join_service_path(&upstream_prefix, entry);
                    routes.push(EgressCredentialRoute {
                        id: format!("external-direct:{name}:{idx}"),
                        kind: EgressKind::External,
                        exposure: EgressExposure::Transparent,
                        match_host: host.clone(),
                        match_prefix: full_path.clone(),
                        exact_path: !is_prefix,
                        upstream_host: host.clone(),
                        upstream_port: port,
                        upstream_prefix: full_path,
                        upstream_tls: tls,
                        cluster_name: String::new(),
                        inject_headers: headers.clone(),
                        remove_headers: remove_headers.clone(),
                    });
                }
            }
        }
        routes
    }

    async fn load_secret_data(
        pool: &PgPool,
        secret_ref: &str,
        project_id: Option<&str>,
    ) -> anyhow::Result<Option<HashMap<String, String>>> {
        let secret: Option<(serde_json::Value,)> = sqlx::query_as(
            r#"
            SELECT data FROM joysafeter_secrets
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(secret_ref)
        .bind(project_id)
        .fetch_optional(pool)
        .await?;

        let Some((data,)) = secret else {
            return Ok(None);
        };

        let cipher = VaultCipher::from_env();
        let mut out = HashMap::new();
        if let Some(obj) = data.as_object() {
            for (key, value) in obj {
                let value = value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .unwrap_or_else(|| value.to_string());
                out.insert(key.clone(), cipher.decrypt_or_passthrough(&value)?);
            }
        }
        Ok(Some(out))
    }

    async fn merge_secret_ref_into_env(
        pool: &PgPool,
        env: &mut HashMap<String, String>,
        secret_ref: &str,
        project_id: Option<&str>,
        override_existing: bool,
    ) -> anyhow::Result<()> {
        let secret: Option<(serde_json::Value,)> = sqlx::query_as(
            r#"
            SELECT data FROM joysafeter_secrets
            WHERE name = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            ORDER BY created_at DESC
            LIMIT 1
            "#,
        )
        .bind(secret_ref)
        .bind(project_id)
        .fetch_optional(pool)
        .await?;

        let Some((data,)) = secret else {
            return Ok(());
        };

        let cipher = VaultCipher::from_env();
        if let Some(obj) = data.as_object() {
            for (key, value) in obj {
                if override_existing || !env.contains_key(key) {
                    let value = value
                        .as_str()
                        .map(ToOwned::to_owned)
                        .unwrap_or_else(|| value.to_string());
                    env.insert(key.clone(), cipher.decrypt_or_passthrough(&value)?);
                }
            }
        }

        Ok(())
    }

    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.provider.teardown_networking(sandbox_id).await
    }

    async fn destroy_observed_sandbox(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
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
            sandbox.id,
            sandbox.external_id.as_deref(),
            &previous_status,
            reason,
        )
        .await
    }

    async fn restart_stopped_sandbox(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
    ) -> anyhow::Result<bool> {
        let claimed =
            queries::claim_stopped_sandbox_for_restart(&self.pool, sandbox_id, external_id).await?;
        if !claimed {
            if let Some(status) = self.active_sandbox_status(sandbox_id, external_id).await? {
                debug!(
                    sandbox_id = %sandbox_id,
                    status = %status,
                    "Stopped sandbox became active before restart claim"
                );
                return Ok(true);
            }
            anyhow::bail!("stopped sandbox {sandbox_id} changed state during restart");
        }

        if self.provider.start(external_id).await.is_err() {
            let _ = queries::restore_stopped_sandbox_after_restart_start_failure(
                &self.pool,
                sandbox_id,
                external_id,
            )
            .await;
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

    async fn mark_pool_claimed(
        &self,
        sandbox_id: SandboxId,
        session_id: Option<SessionId>,
        expected: &ExpectedFingerprint,
        stage: &str,
        progress: i64,
        message: &str,
    ) -> anyhow::Result<()> {
        let config = provisioning_config(stage, progress, message, false, expected, None);
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET chat_session_id = COALESCE($2, chat_session_id),
                config = COALESCE(config, '{}'::jsonb) || $3::jsonb,
                updated_at = NOW()
            WHERE id = $1
              AND status IN ('provisioning', 'idle')
              AND destroyed_at IS NULL
              AND (chat_session_id IS NULL OR chat_session_id = $2)
            "#,
        )
        .bind(sandbox_id)
        .bind(session_id)
        .bind(&config)
        .execute(&self.pool)
        .await?;
        if result.rows_affected() == 0 {
            anyhow::bail!("claimed pool sandbox {sandbox_id} changed state before session attach");
        }
        Ok(())
    }

    /// Provision a warm-pool sandbox (called from SandboxController).
    pub async fn provision_pool_sandbox(&self, image: &str) -> anyhow::Result<SandboxId> {
        let sandbox_db_id = SandboxId::from_uuid(Uuid::now_v7());
        let runner_token = generate_runner_token();

        let mut env = HashMap::new();
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.as_uuid().to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());

        let grpc_url = self.provider.orchestrator_url(self.config.grpc_port);
        env.insert("JOYSAFETER_ORCHESTRATOR_URL".to_string(), grpc_url.clone());

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
            engine_kind: String::new(),
            networking: None,
            env: create_config.env.clone(),
            mounts: vec![],
            egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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

/// Rebuild the egress credentials for a live sandbox during orchestrator startup
/// recovery. Re-derives the same LLM/MCP/git secrets that were injected at
/// creation time by decrypting the current DB rows, so a restarted orchestrator
/// (whose in-memory/gRPC xDS state was wiped) restores credential injection for
/// still-running sandboxes. Returns empty when the sandbox has no session/agent.
pub(crate) async fn rebuild_sandbox_credentials(
    pool: &PgPool,
    sandbox: &crate::db::models::JoySafeterSandbox,
    llm_egress_allowed_hosts: &[String],
) -> SandboxCredentials {
    let mut routes = Vec::new();

    let Some(session_id) = sandbox.chat_session_id else {
        return SandboxCredentials {
            routes,
            proxy_auth_token: sandbox_runner_token(sandbox),
        };
    };
    let session = match queries::get_session(pool, session_id).await {
        Ok(Some(s)) => s,
        _ => {
            return SandboxCredentials {
                routes,
                proxy_auth_token: sandbox_runner_token(sandbox),
            }
        }
    };
    let live_agent = match session.agent_id {
        Some(aid) => queries::get_agent(pool, aid).await.ok().flatten(),
        None => None,
    };
    let snapshot_environment = environment_for_execution(Some(&session));
    let agent = agent_for_execution(live_agent, Some(&session));

    // Re-resolve the agent env (with decrypted secrets) exactly as at creation,
    // then extract the LLM egress from it. We discard the env itself — only the
    // extracted egress credential is needed for recovery.
    if let Some(agent_ref) = agent.as_ref() {
        let environment = if let Some(snapshot_environment) = snapshot_environment {
            Some(EnvironmentRow {
                config: snapshot_environment.config,
                image_tag: snapshot_environment.image_tag,
            })
        } else {
            match agent_ref
                .environment_ref
                .as_deref()
                .filter(|v| !v.trim().is_empty())
            {
                Some(env_ref) => {
                    load_environment_row(pool, env_ref, agent_ref.project_id.as_deref())
                        .await
                        .ok()
                        .flatten()
                }
                None => None,
            }
        };
        if let Ok(mut env) =
            SandboxResolver::resolve_agent_env_from(pool, agent.as_ref(), environment.as_ref())
                .await
        {
            routes.extend(SandboxResolver::extract_llm_egress(
                &mut env,
                llm_egress_allowed_hosts,
            ));
        }
        routes.extend(
            SandboxResolver::build_external_egress(
                pool,
                environment.as_ref(),
                session
                    .project_id
                    .as_deref()
                    .or(agent_ref.project_id.as_deref()),
            )
            .await,
        );
    }

    match SandboxResolver::build_mcp_egress(pool, Some(session_id), agent.as_ref()).await {
        Ok(mcp) => routes.extend(mcp),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild MCP egress credentials during sandbox recovery: {e}"
        ),
    }
    match SandboxResolver::build_git_egress(pool, Some(session_id)).await {
        Ok(git) => routes.extend(git),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild Git egress credentials during sandbox recovery: {e}"
        ),
    }
    SandboxCredentials {
        routes,
        proxy_auth_token: sandbox_runner_token(sandbox),
    }
}

/// Outcome of a networking reconcile attempt for one sandbox.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum NetworkingReconcileOutcome {
    /// Sandbox is not limited-networking; nothing to do.
    NotLimited,
    /// Policy was (re)pushed and marked ready.
    Refreshed { policy_hash: String },
}

/// Rebuild a sandbox's egress policy from current DB state and (re)push it to
/// the provider's Envoy, marking it ready on success. This is the single shared
/// implementation behind both the API-triggered `network_policy_refresh` command
/// and the background networking-reconcile loop, so credential rotation and
/// self-healing follow identical, tested logic.
///
/// On provider failure the sandbox's networking status is recorded as `failed`
/// (fail-closed: it keeps `network=none` and simply has no egress) and the error
/// is returned so the caller can log/retry. The reconcile loop will pick it up
/// again on its next tick.
pub(crate) async fn reconcile_sandbox_networking(
    pool: &PgPool,
    provider: &dyn SandboxProvider,
    sandbox: &JoySafeterSandbox,
    llm_egress_allowed_hosts: &[String],
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let sandbox_id = sandbox.id;
    let Some(external_id) = sandbox
        .external_id
        .as_deref()
        .filter(|value| !value.is_empty())
    else {
        anyhow::bail!("sandbox {sandbox_id} has no external_id");
    };

    let networking = sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"));
    if networking
        .and_then(|value| value.get("type"))
        .and_then(|value| value.as_str())
        != Some("limited")
    {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    }

    let credentials = rebuild_sandbox_credentials(pool, sandbox, llm_egress_allowed_hosts).await;
    let policy = credentials.to_policy(&sandbox_id, allowed_hosts_from_networking(networking));
    crate::sandbox::lds_backend::validate_egress_policy(&sandbox_id, &policy)?;
    let summary = crate::sandbox::lds_backend::egress_policy_summary(&sandbox_id, &policy);
    let policy_hash = network_policy_hash(networking, &summary);

    queries::prepare_sandbox_network_policy_push(pool, sandbox_id, &policy_hash).await?;
    let refresh_result = tokio::time::timeout(
        SETUP_NETWORKING_TIMEOUT,
        provider.refresh_networking(sandbox_id, external_id, networking, credentials),
    )
    .await
    .unwrap_or_else(|_| {
        Err(anyhow::anyhow!(
            "refresh_networking exceeded {SETUP_NETWORKING_TIMEOUT:?}"
        ))
    });
    if let Err(e) = refresh_result {
        // Fail-closed: record the failure; the sandbox keeps network=none and
        // will be retried by the reconcile loop.
        let _ = queries::update_sandbox_networking_status(
            pool,
            sandbox_id,
            "failed",
            Some(&policy_hash),
            None,
            Some(&e.to_string()),
        )
        .await;
        return Err(e);
    }
    queries::mark_sandbox_network_policy_acked(pool, sandbox_id).await?;

    Ok(NetworkingReconcileOutcome::Refreshed { policy_hash })
}

/// Hash the effective egress policy (networking allowlist + rendered credential
/// summary) into the `networking_policy_hash` used for drift detection and the
/// policy-version audit row. Shared by the refresh command and reconcile loop.
pub(crate) fn network_policy_hash(
    networking: Option<&serde_json::Value>,
    summary: &serde_json::Value,
) -> String {
    let material = serde_json::json!({
        "networking": networking.cloned().unwrap_or_else(|| serde_json::json!({})),
        "summary": summary,
    });
    let mut hasher = Sha256::new();
    hasher.update(material.to_string().as_bytes());
    hex::encode(hasher.finalize())
}

/// Standalone environment loader for recovery (mirrors `load_environment`).
async fn load_environment_row(
    pool: &PgPool,
    env_ref: &str,
    project_id: Option<&str>,
) -> anyhow::Result<Option<EnvironmentRow>> {
    if let Ok(env_id) = EnvironmentId::from_public(env_ref) {
        return Ok(sqlx::query_as::<_, EnvironmentRow>(
            r#"
            SELECT config, image_tag FROM joysafeter_environments
            WHERE id = $1 AND deleted_at IS NULL
              AND ($2::text IS NULL OR project_id = $2)
            "#,
        )
        .bind(env_id)
        .bind(project_id)
        .fetch_optional(pool)
        .await?);
    }
    Ok(None)
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
    project_id: Option<String>,
    networking: Option<serde_json::Value>,
    network: Option<String>,
    expected: ExpectedFingerprint,
    /// Memory store bind mounts: (host_path, container_mount_path).
    memory_mounts: Vec<(String, String)>,
    /// Platform-resolved sandbox mounts.
    mounts: Vec<SandboxMount>,
    /// Real secrets to inject at the Envoy egress boundary (never enter the
    /// sandbox). Built from decrypted DB rows at resolve time.
    credentials: SandboxCredentials,
}

impl ResolveContext {
    fn is_limited_networking(&self) -> bool {
        self.network.as_deref() == Some("none")
    }
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

fn egress_policy_hash(
    networking: Option<&serde_json::Value>,
    credentials: &SandboxCredentials,
) -> String {
    let material = egress_policy_summary(networking, credentials);
    let mut hasher = Sha256::new();
    hasher.update(material.to_string().as_bytes());
    hex::encode(hasher.finalize())
}

fn egress_policy_summary(
    networking: Option<&serde_json::Value>,
    credentials: &SandboxCredentials,
) -> serde_json::Value {
    let mut route_hashes: Vec<serde_json::Value> = credentials
        .routes
        .iter()
        .map(|route| {
            let header_hashes: Vec<serde_json::Value> = route
                .inject_headers
                .iter()
                .map(|(name, value)| {
                    let mut hasher = Sha256::new();
                    hasher.update(value.as_bytes());
                    serde_json::json!({
                        "name": name.to_ascii_lowercase(),
                        "value_sha256": hex::encode(hasher.finalize()),
                    })
                })
                .collect();
            serde_json::json!({
                "kind": format!("{:?}", route.kind),
                "exposure": format!("{:?}", route.exposure),
                "match_host": route.match_host,
                "match_prefix": route.match_prefix,
                "exact_path": route.exact_path,
                "upstream_host": route.upstream_host,
                "upstream_port": route.upstream_port,
                "upstream_prefix": route.upstream_prefix,
                "upstream_tls": route.upstream_tls,
                "inject_headers": header_hashes,
                "remove_headers": route.remove_headers,
            })
        })
        .collect();
    route_hashes.sort_by(|a, b| a.to_string().cmp(&b.to_string()));

    serde_json::json!({
        "networking": networking.cloned().unwrap_or_else(|| serde_json::json!({})),
        "routes": route_hashes,
    })
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

fn sandbox_runner_token(sandbox: &crate::db::models::JoySafeterSandbox) -> Option<String> {
    sandbox
        .config
        .as_ref()?
        .get("runner_token")?
        .as_str()
        .filter(|token| !token.trim().is_empty())
        .map(ToOwned::to_owned)
}

/// Generate a random runner token (hex-encoded 32 bytes).
fn generate_runner_token() -> String {
    let random_bytes: [u8; 32] = rand::random();
    hex::encode(random_bytes)
}

fn parse_vault_ref(raw: &str) -> Option<VaultId> {
    // session.vault_ids is persisted canonically prefixed (Python list[VaultId] ->
    // str(vault_id)); only the prefixed form is accepted.
    VaultId::from_public(raw).ok()
}

fn non_empty(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn apply_provider_aliases(env: &mut HashMap<String, String>) {
    if env.contains_key("ANTHROPIC_AUTH_TOKEN") && !env.contains_key("ANTHROPIC_API_KEY") {
        if let Some(token) = env.get("ANTHROPIC_AUTH_TOKEN").cloned() {
            env.insert("ANTHROPIC_API_KEY".to_string(), token);
        }
    }
}

fn effective_networking_config(
    networking: Option<serde_json::Value>,
    envoy_enabled: bool,
    agent: Option<&JoySafeterAgent>,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<Option<serde_json::Value>> {
    match networking_type(networking.as_ref()) {
        Some("limited") => networking
            .map(|networking| merge_mcp_hosts(networking, agent, environment))
            .transpose(),
        Some("unrestricted") => Ok(networking),
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
            merge_mcp_hosts(effective, agent, environment).map(Some)
        }
        None => Ok(networking),
    }
}

fn networking_type(networking: Option<&serde_json::Value>) -> Option<&str> {
    networking.and_then(|value| {
        value
            .get("type")
            .or_else(|| value.get("net_type"))
            .and_then(|value| value.as_str())
    })
}

pub(crate) fn allowed_hosts_from_networking(networking: Option<&serde_json::Value>) -> Vec<String> {
    networking
        .and_then(|value| value.get("allowed_hosts"))
        .and_then(|value| value.as_array())
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(ToOwned::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

fn merge_mcp_hosts(
    mut networking: serde_json::Value,
    agent: Option<&JoySafeterAgent>,
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

    // Add MCP server hosts to allowlist.
    if let Some(mcp_servers) = agent
        .and_then(|a| a.mcp_servers.as_ref())
        .and_then(|value| value.as_array())
    {
        for config in mcp_servers {
            let Some(url) = config.get("url").and_then(|value| value.as_str()) else {
                continue;
            };
            if let Some(host) = extract_host(url) {
                if !allowed_hosts.iter().any(|existing| existing == &host) {
                    allowed_hosts.push(host);
                }
            }
        }
    }

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

fn normalize_llm_upstream_prefix(path: &str) -> String {
    if path.is_empty() || path == "/" {
        return "/".to_string();
    }

    let mut prefix = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

fn is_llm_egress_host_allowed(host: &str, allowed_hosts: &[String]) -> bool {
    let Some(host) = normalize_llm_host(host) else {
        return false;
    };

    if is_blocked_llm_host(&host) {
        return false;
    }

    allowed_hosts
        .iter()
        .filter_map(|entry| normalize_llm_host_pattern(entry))
        .any(|pattern| llm_host_matches_pattern(&host, &pattern))
}

fn normalize_llm_host(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, false)
}

fn normalize_llm_host_pattern(raw: &str) -> Option<String> {
    normalize_llm_host_inner(raw, true)
}

fn normalize_llm_host_inner(raw: &str, allow_wildcard: bool) -> Option<String> {
    let mut value = raw.trim().to_ascii_lowercase();
    if value.is_empty() {
        return None;
    }

    if value.contains("://") {
        value = Url::parse(&value).ok()?.host_str()?.to_string();
    } else {
        if let Some((before_path, _)) = value.split_once('/') {
            value = before_path.to_string();
        }
        if value.starts_with('[') {
            let end = value.find(']')?;
            value = value[1..end].to_string();
        } else if let Some((host, port)) = value.rsplit_once(':') {
            if !host.contains(':') && port.parse::<u16>().is_ok() {
                value = host.to_string();
            }
        }
    }

    value = value.trim_matches('.').to_string();
    if value.is_empty() {
        return None;
    }

    if value.starts_with("*.") {
        if !allow_wildcard {
            return None;
        }
        let suffix = value.trim_start_matches("*.");
        if suffix.is_empty() || suffix.contains('*') {
            return None;
        }
        return Some(format!("*.{suffix}"));
    }

    if value.contains('*') {
        return None;
    }

    Some(value)
}

fn llm_host_matches_pattern(host: &str, pattern: &str) -> bool {
    if let Some(suffix) = pattern.strip_prefix("*.") {
        return host != suffix && host.ends_with(&format!(".{suffix}"));
    }

    host == pattern
}

fn is_blocked_llm_host(host: &str) -> bool {
    if host == "localhost" || host.ends_with(".localhost") {
        return true;
    }

    host.parse::<IpAddr>()
        .map(is_blocked_llm_ip)
        .unwrap_or(false)
}

fn is_blocked_llm_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let octets = ip.octets();
            octets[0] == 0
                || octets[0] == 10
                || octets[0] == 127
                || (octets[0] == 100 && (64..=127).contains(&octets[1]))
                || (octets[0] == 169 && octets[1] == 254)
                || (octets[0] == 172 && (16..=31).contains(&octets[1]))
                || (octets[0] == 192 && octets[1] == 168)
                || (octets[0] == 198 && (18..=19).contains(&octets[1]))
                || octets[0] >= 224
        }
        IpAddr::V6(ip) => {
            let segments = ip.segments();
            let first = segments[0];
            ip.is_loopback()
                || ip.is_unspecified()
                || (first & 0xfe00) == 0xfc00
                || (first & 0xffc0) == 0xfe80
                || (first & 0xff00) == 0xff00
        }
    }
}

#[derive(Debug, sqlx::FromRow)]
struct EnvironmentRow {
    config: serde_json::Value,
    image_tag: Option<String>,
}

fn sanitize_external_service_name(name: &str) -> String {
    name.trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn normalize_external_upstream_prefix(path: &str) -> String {
    let mut prefix = if path.is_empty() {
        "/".to_string()
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if prefix != "/" && !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

/// Join a service base prefix with an allowlist entry into a full host path.
fn join_service_path(base_prefix: &str, entry: &str) -> String {
    if entry.starts_with('/') {
        return entry.to_string();
    }
    let base = base_prefix.strip_suffix('/').unwrap_or(base_prefix);
    format!("{base}/{entry}")
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

fn build_external_inject_headers(
    secret: &HashMap<String, String>,
    inject: &serde_json::Map<String, serde_json::Value>,
) -> anyhow::Result<Vec<(String, String)>> {
    let typ = inject
        .get("type")
        .and_then(|value| value.as_str())
        .unwrap_or("bearer");
    match typ {
        "bearer" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("ACCESS_TOKEN");
            let token = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?;
            let header = inject
                .get("header")
                .and_then(|value| value.as_str())
                .unwrap_or("authorization");
            Ok(vec![(header.to_string(), format!("Bearer {token}"))])
        }
        "api_key" | "raw_header" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("API_KEY");
            let value = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?;
            let header = inject
                .get("header")
                .and_then(|value| value.as_str())
                .unwrap_or("x-api-key");
            Ok(vec![(header.to_string(), value.clone())])
        }
        "cookie" => {
            let key = inject
                .get("secret_key")
                .and_then(|value| value.as_str())
                .unwrap_or("COOKIE_HEADER");
            let cookie_header = secret
                .get(key)
                .ok_or_else(|| anyhow::anyhow!("missing secret key {key}"))?
                .clone();
            Ok(vec![("cookie".to_string(), cookie_header)])
        }
        other => anyhow::bail!("unsupported external egress inject type {other}"),
    }
}

#[cfg(test)]
mod egress_tests {
    use super::*;
    use async_trait::async_trait;
    use sqlx::postgres::PgPoolOptions;
    use sqlx::PgPool;
    use std::env;
    use std::sync::Arc;
    use tokio::sync::Mutex;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    fn allow(hosts: &[&str]) -> Vec<String> {
        hosts.iter().map(|host| host.to_string()).collect()
    }

    /// Run `extract_llm_egress` and return the single LLM route it emits, if any.
    /// The builder now returns a `Vec<EgressCredentialRoute>`; LLM egress is
    /// always zero or one route.
    fn extract_llm_route(
        env: &mut HashMap<String, String>,
        allowed_hosts: &[String],
    ) -> Option<EgressCredentialRoute> {
        SandboxResolver::extract_llm_egress(env, allowed_hosts)
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

    #[test]
    fn mcp_credential_url_keys_matches_trailing_slash_variants() {
        let keys = mcp_credential_url_keys("https://AI-Legal-Test.JD.com/legal-mcp/mcp/");

        assert!(keys.contains(&"https://ai-legal-test.jd.com/legal-mcp/mcp".to_string()));
        assert!(keys.contains(&"https://ai-legal-test.jd.com/legal-mcp/mcp/".to_string()));
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
                match_prefix: "/svc/".to_string(),
                upstream_host: "api.example.com".to_string(),
                upstream_port: 443,
                upstream_prefix: "/".to_string(),
                upstream_tls: true,
                cluster_name: "external_svc".to_string(),
                exact_path: false,
                inject_headers: vec![("authorization".to_string(), "Bearer first".to_string())],
                remove_headers: vec![],
            }],
            proxy_auth_token: None,
        };
        let networking = serde_json::json!({"type": "limited"});

        let first = egress_policy_hash(Some(&networking), &credentials);
        credentials.routes[0].inject_headers[0].1 = "Bearer second".to_string();
        let second = egress_policy_hash(Some(&networking), &credentials);

        assert_ne!(first, second);
        assert!(!first.contains("first"));
        assert!(!second.contains("second"));
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

    #[derive(Default)]
    struct RecordingProvider {
        created: Mutex<Vec<SandboxCreateConfig>>,
        networking: Mutex<Vec<(SandboxId, Option<serde_json::Value>)>>,
        start_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
        start_observed_statuses: Mutex<Vec<String>>,
        start_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
        status_marks_idle: Mutex<Option<(PgPool, SandboxId)>>,
        status_marks_error: Mutex<Option<(PgPool, SandboxId)>>,
        status_result: Mutex<Option<SandboxStatus>>,
        destroy_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
        destroy_observed_statuses: Mutex<Vec<String>>,
        destroyed: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl SandboxProvider for RecordingProvider {
        async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
            self.created.lock().await.push(config.clone());
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

        async fn setup_networking(
            &self,
            sandbox_id: SandboxId,
            _sandbox_external_id: &str,
            networking: Option<&serde_json::Value>,
            _credentials: SandboxCredentials,
        ) -> anyhow::Result<()> {
            self.networking
                .lock()
                .await
                .push((sandbox_id, networking.cloned()));
            Ok(())
        }

        fn provider_name(&self) -> &'static str {
            "recording"
        }

        fn capabilities(&self) -> crate::sandbox::provider::ProviderCapabilities {
            crate::sandbox::provider::ProviderCapabilities {
                has_host_mount: false,
                has_egress_management: true,
                network_isolation: crate::sandbox::provider::NetworkIsolation::Envoy,
            }
        }
    }

    #[test]
    fn anthropic_auth_token_uses_bearer_and_leaves_no_key() {
        // Gateway / internal endpoint style: ANTHROPIC_AUTH_TOKEN → Bearer.
        // apply_provider_aliases would have also set ANTHROPIC_API_KEY; simulate that.
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "tok-123"),
            ("ANTHROPIC_API_KEY", "tok-123"),
            ("ANTHROPIC_BASE_URL", "https://llm.internal.example.com/v1"),
            ("DB_PASSWORD", "keepme"),
        ]);
        let egress =
            extract_llm_route(&mut e, &allow(&["llm.internal.example.com"])).expect("egress");

        // Bearer header, real host preserved in egress, TLS upstream.
        assert_eq!(egress.upstream_host, "llm.internal.example.com");
        assert_eq!(egress.upstream_port, 443);
        assert_eq!(egress.upstream_prefix, "/v1/");
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
    fn anthropic_api_key_uses_x_api_key() {
        // Official-style key (no AUTH_TOKEN) → x-api-key header.
        let mut e = env(&[
            ("ANTHROPIC_API_KEY", "sk-ant-xyz"),
            ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ]);
        let egress = extract_llm_route(&mut e, &allow(&["api.anthropic.com"])).expect("egress");
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

        assert!(SandboxResolver::extract_llm_egress(&mut e, &[]).is_empty());
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

        assert!(
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["api.anthropic.com"])).is_empty()
        );
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
        let egress = extract_llm_route(&mut e, &allow(&["ai-api.jdcloud.com"])).expect("egress");
        assert_eq!(egress.upstream_host, "ai-api.jdcloud.com");
        assert_eq!(egress.upstream_port, 80);
        assert_eq!(egress.upstream_prefix, "/anthropic/");
        assert!(!egress.upstream_tls);
    }

    #[test]
    fn openai_uses_bearer() {
        let mut e = env(&[
            ("OPENAI_API_KEY", "sk-oai"),
            ("OPENAI_BASE_URL", "https://gw.internal/v1"),
        ]);
        let egress = extract_llm_route(&mut e, &allow(&["gw.internal"])).expect("egress");
        assert_eq!(egress.upstream_host, "gw.internal");
        assert_eq!(egress.upstream_prefix, "/v1/");
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
        assert!(SandboxResolver::extract_llm_egress(&mut e, &[]).is_empty());
        assert_eq!(e.get("DB_PASSWORD").unwrap(), "x");
    }

    #[test]
    fn plaintext_base_url_keeps_http_upstream() {
        // If the configured endpoint is plain http, the cluster should not TLS.
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "t"),
            ("ANTHROPIC_BASE_URL", "http://llm.internal:8080/v1"),
        ]);
        let egress = extract_llm_route(&mut e, &allow(&["llm.internal"])).expect("egress");
        assert_eq!(egress.upstream_host, "llm.internal");
        assert_eq!(egress.upstream_port, 8080);
        assert_eq!(egress.upstream_prefix, "/v1/");
        assert!(!egress.upstream_tls);
        assert_eq!(
            e.get("ANTHROPIC_BASE_URL").unwrap(),
            "http://llm.internal:8080/v1/"
        );
    }

    #[test]
    fn gemini_uses_x_goog_api_key_and_default_host() {
        // Google Generative Language API: raw key in x-goog-api-key, default host.
        let mut e = env(&[("GEMINI_API_KEY", "AIzaXYZ")]);
        let egress = extract_llm_route(&mut e, &allow(&["generativelanguage.googleapis.com"]))
            .expect("egress");
        assert_eq!(egress.upstream_host, "generativelanguage.googleapis.com");
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.inject_headers,
            vec![("x-goog-api-key".to_string(), "AIzaXYZ".to_string())]
        );
        assert!(!e.contains_key("GEMINI_API_KEY"));
        // base URL is repointed at the plaintext egress placeholder host.
        assert_eq!(
            e.get("GOOGLE_GEMINI_BASE_URL").unwrap(),
            "http://generativelanguage.googleapis.com:443/"
        );
    }

    #[test]
    fn google_api_key_alias_also_works() {
        let mut e = env(&[("GOOGLE_API_KEY", "AIzaABC")]);
        let egress = extract_llm_route(&mut e, &allow(&["generativelanguage.googleapis.com"]))
            .expect("egress");
        assert_eq!(
            egress.inject_headers,
            vec![("x-goog-api-key".to_string(), "AIzaABC".to_string())]
        );
        assert!(!e.contains_key("GOOGLE_API_KEY"));
    }

    #[test]
    fn azure_uses_api_key_header_no_bearer() {
        // Azure OpenAI: `api-key` header, raw key (no Bearer). Host from base URL.
        let mut e = env(&[
            ("AZURE_OPENAI_API_KEY", "az-secret"),
            ("AZURE_OPENAI_BASE_URL", "https://my-res.openai.azure.com"),
        ]);
        let egress = extract_llm_route(&mut e, &allow(&["*.openai.azure.com"])).expect("egress");
        assert_eq!(egress.upstream_host, "my-res.openai.azure.com");
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.inject_headers,
            vec![("api-key".to_string(), "az-secret".to_string())]
        );
        assert!(!e.contains_key("AZURE_OPENAI_API_KEY"));
    }

    #[test]
    fn azure_wildcard_does_not_allow_parent_domain() {
        let mut e = env(&[
            ("AZURE_OPENAI_API_KEY", "az-secret"),
            ("AZURE_OPENAI_BASE_URL", "https://openai.azure.com"),
        ]);

        assert!(
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["*.openai.azure.com"])).is_empty()
        );
        assert!(!e.contains_key("AZURE_OPENAI_API_KEY"));
    }

    #[test]
    fn azure_without_base_url_bails() {
        // Azure has no fixed endpoint; without a base URL we must not inject the
        // key toward an unknown host.
        let mut e = env(&[("AZURE_OPENAI_API_KEY", "az-secret")]);
        assert!(
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["*.openai.azure.com"])).is_empty()
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
                SandboxResolver::extract_llm_egress(&mut e, &allow(&[host])).is_empty(),
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

        assert!(
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["api.openai.com"])).is_empty()
        );
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

            let expected = ExpectedFingerprint {
                image: image.clone(),
                engine_kind: "claude".to_string(),
                networking: None,
                env: HashMap::new(),
                mounts: vec![],
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
            assert_eq!(resolved, (sandbox_id, external_id.clone()));
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<SessionId>, serde_json::Value) = sqlx::query_as(
                "SELECT status, chat_session_id, config FROM joysafeter_sandboxes WHERE id = $1",
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
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
            assert_eq!(resolved, (sandbox_id, external_id.clone()));

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
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
                message.contains("changed state before session attach"),
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
            assert_eq!(sandbox.1, None);
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
    async fn sandbox_resolver_builds_mcp_egress_from_vault_prefixed_ids() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let vault_id = VaultId::from_uuid(Uuid::now_v7());
        let credential_id = CredentialId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let mcp_url = "https://mcp.vault-alias.example/api";

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_vaults (id, name, description)
                VALUES ($1, $2, '')
                "#,
            )
            .bind(vault_id)
            .bind(format!("resolver-vault-alias-{unique}"))
            .execute(&pool)
            .await
            .expect("insert vault");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_vault_credentials
                    (id, vault_id, name, credential_type, mcp_server_url, token_value)
                VALUES ($1, $2, 'resolver alias credential', 'static_bearer', $3, 'vault-token')
                "#,
            )
            .bind(credential_id)
            .bind(vault_id)
            .bind(mcp_url)
            .execute(&pool)
            .await
            .expect("insert vault credential");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_servers,
                    skills, tools, agents, commands, permission_mode, metadata, version
                )
                VALUES (
                    $1, $2, 'claude', $3, '', '{}'::jsonb, $4,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-vault-alias-agent-{unique}"))
            .bind(serde_json::json!({"id": "claude-sonnet"}))
            .bind(serde_json::json!([{
                "name": "secure-mcp",
                "type": "http",
                "url": mcp_url
            }]))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, status, vault_ids)
                VALUES ($1, $2, 'idle', $3)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(serde_json::json!([vault_id.to_string()]))
            .execute(&pool)
            .await
            .expect("insert session");

            let agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load agent")
                .expect("agent exists");
            let egress = SandboxResolver::build_mcp_egress(&pool, Some(session_id), Some(&agent))
                .await
                .expect("build mcp egress");

            assert_eq!(egress.len(), 1);
            assert_eq!(egress[0].id, "mcp:secure-mcp");
            assert_eq!(egress[0].match_prefix, "/mcp/secure-mcp/");
            assert_eq!(egress[0].upstream_host, "mcp.vault-alias.example");
            assert_eq!(egress[0].upstream_port, 443);
            assert_eq!(egress[0].upstream_prefix, "/api");
            assert!(egress[0].upstream_tls);
            assert_eq!(
                egress[0].inject_headers,
                vec![(
                    "authorization".to_string(),
                    "Bearer vault-token".to_string()
                )]
            );
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
        let _ = sqlx::query("DELETE FROM joysafeter_vault_credentials WHERE id = $1")
            .bind(credential_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_vaults WHERE id = $1")
            .bind(vault_id)
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
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
            assert_eq!(resolved, (sandbox_id, external_id.clone()));

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
                egress_policy_hash: egress_policy_hash(None, &SandboxCredentials::default()),
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
            let (resolved_sandbox_id, _resolved_external_id) = resolver
                .resolve(
                    task_id,
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("resolve replacement after stale creating cleanup");
            assert_ne!(resolved_sandbox_id, stale_sandbox_id);

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
        let environment_ref = environment_id.to_string();
        let agent_name = format!("resolver-snapshot-agent-{unique}");
        let environment_name = format!("resolver-snapshot-env-{unique}");
        let snapshot = serde_json::json!({
            "schema": "joysafeter.agent_execution_snapshot.v1",
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
            "environment_ref": environment_ref,
            "environment": {
                "ref": environment_ref,
                "id": environment_id.to_string(),
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
                    version, environment_ref
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
            .bind(&environment_ref)
            .execute(&pool)
            .await
            .expect("insert live agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (
                    id, agent_id, status, agent_version, agent_snapshot, environment_ref
                )
                VALUES ($1, $2, 'idle', 3, $3, $4)
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&snapshot)
            .bind(&environment_ref)
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
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), config);

            let (sandbox_id, _external_id) = resolver
                .resolve(
                    TaskId::from_uuid(Uuid::now_v7()),
                    Some(session_id),
                    Some(agent_id),
                    None,
                )
                .await
                .expect("resolve sandbox from snapshot");

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
    async fn sandbox_resolver_snapshot_session_file_injection_storage_missing_fails_resolve() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let file_id = FileId::from_uuid(Uuid::now_v7());
        let session_file_id = SessionResourceId::from_uuid(Uuid::now_v7());
        let unique = agent_id.as_uuid().simple().to_string();
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
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
