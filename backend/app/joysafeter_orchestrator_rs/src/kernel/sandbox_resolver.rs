use std::collections::HashMap;
use std::sync::Arc;

use sha2::{Digest, Sha256};
use sqlx::{PgPool, Row};
use tracing::{debug, info, warn};
use url::Url;
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::{JoySafeterAgent, JoySafeterSandbox};
use crate::db::queries;
use crate::egress::credential::{
    build_external_egress, build_git_egress, build_mcp_egress, rewrite_shared_external_egress_env,
};
use crate::egress::enforcer::EgressEnforcer;
use crate::egress::llm::{extract_llm_egress, LlmCredentialProvenance, LlmSecretSource};
#[cfg(test)]
use crate::egress::policy::EgressCredentialRoute;
use crate::egress::policy::SandboxCredentials;
use crate::kernel::harness_input_builder::VaultCipher;
use crate::kernel::run_spec::{agent_for_execution, environment_for_execution};
use crate::sandbox::mounts::{resolve_mount_resources, SandboxMount, SandboxMountFingerprint};
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

use super::llm_providers::is_real_llm_secret_env;
#[cfg(test)]
use super::llm_providers::{CLAUDE_CODE_PLACEHOLDER_API_KEY, CODEX_PLACEHOLDER_OPENAI_API_KEY};

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
    /// Orchestrator-owned egress enforcer. `None` means egress cannot be
    /// mediated for this provider — the resolver then fails closed for
    /// secret-backed / limited-networking sandboxes.
    enforcer: Option<Arc<dyn EgressEnforcer>>,
    config: JoySafeterConfig,
    /// Per-session locks to prevent concurrent resolution
    session_locks: dashmap::DashMap<Uuid, Arc<tokio::sync::Mutex<()>>>,
}

impl SandboxResolver {
    pub fn new(
        pool: PgPool,
        provider: Arc<dyn SandboxProvider>,
        enforcer: Option<Arc<dyn EgressEnforcer>>,
        config: JoySafeterConfig,
    ) -> Self {
        Self {
            pool,
            provider,
            enforcer,
            config,
            session_locks: dashmap::DashMap::new(),
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
        task_id: Uuid,
        session_id: Option<Uuid>,
        agent_id: Option<Uuid>,
        project_id: Option<&str>,
    ) -> anyhow::Result<(Uuid, String)> {
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
        task_id: Uuid,
        session_id: Option<Uuid>,
        agent_id: Option<Uuid>,
        project_id: Option<&str>,
    ) -> anyhow::Result<(Uuid, String)> {
        let context = self
            .build_resolve_context(session_id, agent_id, project_id)
            .await?;
        self.ensure_egress_capability(&context)?;
        // Stage 1: Try to reuse existing sandbox for this session
        if let Some(sid) = session_id {
            if let Some(sandbox) = queries::find_sandbox_for_session(&self.pool, sid).await? {
                if !fingerprint_matches(
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
                if !fingerprint_matches(
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
        task_id: Uuid,
        context: &ResolveContext,
    ) -> anyhow::Result<(Uuid, String)> {
        let sandbox_db_id = Uuid::now_v7();
        let expected = context.expected.clone();
        let image = expected.image.clone();
        let runner_token = generate_runner_token();

        // Build environment variables — both JOYSAFETER_* and JOYSAFETER_* variants
        let mut env = expected.env.clone();
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());
        if let Some(plane) = crate::egress::plane::EgressPlane::resolve(
            self.config.egress_policy_authority_enabled,
            &self.config.sandbox_provider,
            self.config.egress_envoy_credential_url.clone(),
        ) {
            rewrite_shared_external_egress_env(
                &mut env,
                &context.credentials.routes,
                context.environment_config.as_ref(),
                &plane,
                sandbox_db_id,
                &runner_token,
            );
        }

        let grpc_url = self.provider.orchestrator_url(self.config.grpc_port);
        env.insert("JOYSAFETER_ORCHESTRATOR_URL".to_string(), grpc_url.clone());

        let mut labels = HashMap::new();
        labels.insert("joysafeter".to_string(), "true".to_string());
        labels.insert("joysafeter.managed".to_string(), "true".to_string());
        labels.insert(
            "joysafeter.sandbox_id".to_string(),
            sandbox_db_id.to_string(),
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

        let create_config = SandboxCreateConfig {
            sandbox_id: sandbox_db_id,
            image: image.clone(),
            env,
            labels,
            cpu_limit: self.config.sandbox_cpu,
            memory_limit_mb: self.config.sandbox_memory_mb,
            disk_limit_mb: self.config.sandbox_disk_mb,
            network: context.network.clone(),
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

        if create_config.network.as_deref() == Some("none") {
            self.ensure_egress_capability(context)?;
            if let Some(enforcer) = self.enforcer.as_ref() {
                enforcer
                    .enforce(
                        sandbox_db_id,
                        &runner_token,
                        context.networking.as_ref(),
                        context.credentials.clone(),
                    )
                    .await?;
                // Make the sandbox's credential routes resolvable by the
                // orchestrator resolution service (per-request injection).
                crate::kernel::credential_resolution::global_resolution_registry()
                    .install(sandbox_db_id, &context.credentials.routes);
            }
        }

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

    fn ensure_egress_capability(&self, context: &ResolveContext) -> anyhow::Result<()> {
        if context.requires_egress_management() && self.enforcer.is_none() {
            anyhow::bail!(
                "SANDBOX_EGRESS_MANAGER_REQUIRED: no egress enforcer configured for provider '{}'; cannot run secret-backed or limited-networking sandboxes",
                self.provider.provider_name()
            );
        }
        Ok(())
    }

    async fn build_resolve_context(
        &self,
        session_id: Option<Uuid>,
        agent_id: Option<Uuid>,
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
        let image = environment
            .as_ref()
            .and_then(|env| env.image_tag.clone())
            .unwrap_or_else(|| self.config.image_for_provider(&engine_kind));
        let (mut env, llm_provenance) =
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
        // SP-4: credential mediation is decoupled from the networking MODE. Any
        // sandbox that carries a real credential (or is limited) routes its
        // credentialed egress through the boundary so the real key never enters
        // the sandbox — regardless of limited vs unrestricted. The networking
        // mode only controls allowlist / L3 breadth (applied by the enforcer in
        // SP-4 Task 2), not whether mediation happens.
        let is_limited = networking_type(networking.as_ref()) == Some("limited");
        let has_llm_secret = env
            .iter()
            .any(|(key, value)| is_real_llm_secret_env(key, value));
        let mut routes = Vec::new();
        routes.extend(extract_llm_egress(
            &mut env,
            &llm_provenance,
            &self.config.llm_egress_allowed_hosts,
        ));
        routes.extend(build_mcp_egress(&self.pool, session_id, agent.as_ref()).await?);
        routes.extend(build_git_egress(&self.pool, session_id).await?);
        routes.extend(
            build_external_egress(
                &self.pool,
                environment.as_ref().map(|env| &env.config),
                project_id.as_deref(),
            )
            .await,
        );
        let should_mediate = is_limited || has_llm_secret || !routes.is_empty();
        // `network == "none"` now means "mediated / routed through the boundary".
        let network = if should_mediate {
            Some("none".to_string())
        } else {
            None
        };

        let credentials = if should_mediate {
            SandboxCredentials { routes }
        } else {
            SandboxCredentials::default()
        };

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
            environment_config: environment.as_ref().map(|value| value.config.clone()),
            networking: networking.clone(),
            network,
            expected: ExpectedFingerprint {
                image,
                engine_kind,
                networking,
                env,
                mounts: mount_fingerprint,
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
        if let Some(env_id) = parse_prefixed_uuid(env_ref, "env_") {
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

    /// Resolve the sandbox env plus the provenance of any Secret-backed LLM
    /// credential env vars. The provenance map (credential key → managed Secret)
    /// lets `extract_llm_egress` emit a non-secret `CredentialRef::Llm` instead
    /// of injecting a decrypted key; a credential key absent from it was a
    /// plaintext literal and will be refused (fail closed). The map holds no
    /// secret values — only Secret names + key names.
    async fn resolve_agent_env_from(
        pool: &PgPool,
        agent: Option<&JoySafeterAgent>,
        environment: Option<&EnvironmentRow>,
    ) -> anyhow::Result<(HashMap<String, String>, LlmCredentialProvenance)> {
        let mut env = HashMap::new();
        let mut provenance = LlmCredentialProvenance::new();
        let Some(agent) = agent else {
            return Ok((env, provenance));
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
                        &mut provenance,
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
                &mut provenance,
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

        Ok((env, provenance))
    }

    async fn merge_secret_ref_into_env(
        pool: &PgPool,
        env: &mut HashMap<String, String>,
        provenance: &mut LlmCredentialProvenance,
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
                    // Record that this LLM credential key came from a managed
                    // Secret so `extract_llm_egress` can reference it instead of
                    // shipping the decrypted value.
                    if crate::kernel::llm_providers::is_llm_credential_key(key) {
                        provenance.insert(
                            key.clone(),
                            LlmSecretSource {
                                secret_name: secret_ref.to_string(),
                                project_id: project_id.map(ToOwned::to_owned),
                            },
                        );
                    }
                }
            }
        }

        Ok(())
    }

    async fn teardown_networking(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        // Forget the sandbox's resolvable routes and evict its cached secrets so
        // a torn-down sandbox can no longer resolve credentials and none stay
        // resident. This is the create-failure rollback path; the steady-state
        // destroy path calls the same helper in sandbox_lifecycle.
        crate::kernel::credential_resolution::forget_sandbox_credentials(sandbox_id);
        match self.enforcer.as_ref() {
            Some(e) => e.teardown(sandbox_id).await,
            None => Ok(()),
        }
    }

    async fn destroy_observed_sandbox(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
            self.enforcer.as_ref(),
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
            self.enforcer.as_ref(),
            sandbox.id,
            sandbox.external_id.as_deref(),
            &previous_status,
            reason,
        )
        .await
    }

    async fn restart_stopped_sandbox(
        &self,
        sandbox_id: Uuid,
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
        sandbox_id: Uuid,
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
        sandbox_id: Uuid,
        session_id: Option<Uuid>,
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
    pub async fn provision_pool_sandbox(&self, image: &str) -> anyhow::Result<Uuid> {
        let sandbox_db_id = Uuid::now_v7();
        let runner_token = generate_runner_token();

        let mut env = HashMap::new();
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_db_id.to_string(),
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
                    sandbox_db_id.to_string(),
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
            disk_limit_mb: self.config.sandbox_disk_mb,
            network: None,
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
        return SandboxCredentials { routes };
    };
    let session = match queries::get_session(pool, session_id).await {
        Ok(Some(s)) => s,
        _ => return SandboxCredentials { routes },
    };
    let live_agent = match session.agent_id {
        Some(aid) => queries::get_agent(pool, aid).await.ok().flatten(),
        None => None,
    };
    let snapshot_environment = environment_for_execution(Some(&session));
    let agent = agent_for_execution(live_agent, Some(&session));
    let mut recovery_environment_config = None;

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
        recovery_environment_config = environment.as_ref().map(|value| value.config.clone());
        if let Ok((mut env, llm_provenance)) =
            SandboxResolver::resolve_agent_env_from(pool, agent.as_ref(), environment.as_ref())
                .await
        {
            routes.extend(extract_llm_egress(
                &mut env,
                &llm_provenance,
                llm_egress_allowed_hosts,
            ));
        }
    }

    match build_mcp_egress(pool, Some(session_id), agent.as_ref()).await {
        Ok(mcp) => routes.extend(mcp),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild MCP egress credentials during sandbox recovery: {e}"
        ),
    }
    match build_git_egress(pool, Some(session_id)).await {
        Ok(git) => routes.extend(git),
        Err(e) => warn!(
            session_id = %session_id,
            sandbox_id = %sandbox.id,
            "Failed to rebuild Git egress credentials during sandbox recovery: {e}"
        ),
    }
    routes.extend(
        build_external_egress(
            pool,
            recovery_environment_config.as_ref(),
            session
                .project_id
                .as_deref()
                .or_else(|| agent.as_ref().and_then(|value| value.project_id.as_deref())),
        )
        .await,
    );
    SandboxCredentials { routes }
}

async fn load_environment_row(
    pool: &PgPool,
    env_ref: &str,
    project_id: Option<&str>,
) -> anyhow::Result<Option<EnvironmentRow>> {
    if let Some(env_id) = parse_prefixed_uuid(env_ref, "env_") {
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
}

#[derive(Debug, Clone)]
struct ResolveContext {
    session_id: Option<Uuid>,
    project_id: Option<String>,
    environment_config: Option<serde_json::Value>,
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

    fn requires_egress_management(&self) -> bool {
        self.is_limited_networking()
            || !self.credentials.routes.is_empty()
            || self
                .expected
                .env
                .iter()
                .any(|(key, value)| is_real_llm_secret_env(key, value))
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
        })
    }
}

fn fingerprint_matches(
    config: Option<&serde_json::Value>,
    sandbox_image: Option<&str>,
    expected: &ExpectedFingerprint,
) -> bool {
    let Some(config) = config else {
        return sandbox_image == Some(expected.image.as_str());
    };
    match config.get("fingerprint") {
        Some(actual) => actual == &expected.to_json(),
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

fn parse_prefixed_uuid(raw: &str, prefix: &str) -> Option<Uuid> {
    raw.strip_prefix(prefix).unwrap_or(raw).parse().ok()
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
    if let Some(mcp_configs) = agent
        .and_then(|a| a.mcp_configs.as_ref())
        .and_then(|value| value.as_array())
    {
        for config in mcp_configs {
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

#[derive(Debug, sqlx::FromRow)]
struct EnvironmentRow {
    config: serde_json::Value,
    image_tag: Option<String>,
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
    use crate::egress::policy::{CredentialRef, InjectScheme};
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

    /// Build LLM credential provenance for every LLM credential key present in
    /// `env`, simulating that each was sourced from a managed Secret. Lets these
    /// unit tests exercise detection/allowlist/base-url logic without a DB.
    fn secret_backed(env: &HashMap<String, String>) -> LlmCredentialProvenance {
        env.keys()
            .filter(|k| crate::kernel::llm_providers::is_llm_credential_key(k))
            .map(|k| {
                (
                    k.clone(),
                    LlmSecretSource {
                        secret_name: "test-secret".to_string(),
                        project_id: None,
                    },
                )
            })
            .collect()
    }

    /// Run `extract_llm_egress` with Secret-backed provenance for all present
    /// LLM credential keys.
    fn extract_llm_routes(
        env: &mut HashMap<String, String>,
        allowed_hosts: &[String],
    ) -> Vec<EgressCredentialRoute> {
        let provenance = secret_backed(env);
        extract_llm_egress(env, &provenance, allowed_hosts)
    }

    /// Run `extract_llm_egress` and return the single LLM route it emits, if any.
    /// The builder now returns a `Vec<EgressCredentialRoute>`; LLM egress is
    /// always zero or one route.
    fn extract_llm_route(
        env: &mut HashMap<String, String>,
        allowed_hosts: &[String],
    ) -> Option<EgressCredentialRoute> {
        extract_llm_routes(env, allowed_hosts).into_iter().next()
    }

    /// Assert an LLM route carries the expected non-secret ref, inject header,
    /// and scheme (no secret value — that is the broker's job at request time).
    fn assert_llm_ref(
        route: &EgressCredentialRoute,
        header: &str,
        scheme: InjectScheme,
        secret_key: &str,
    ) {
        assert_eq!(route.inject_header, header);
        assert_eq!(route.inject_scheme, scheme);
        assert_eq!(
            route.credential_ref,
            CredentialRef::Llm {
                secret_name: "test-secret".to_string(),
                secret_key: secret_key.to_string(),
                project_id: None,
            }
        );
    }

    fn resolve_context_for_env(env: HashMap<String, String>) -> ResolveContext {
        ResolveContext {
            session_id: None,
            project_id: None,
            environment_config: None,
            networking: None,
            network: None,
            expected: ExpectedFingerprint {
                image: "joysafeter-test:latest".to_string(),
                engine_kind: "claude".to_string(),
                networking: None,
                env,
                mounts: vec![],
            },
            memory_mounts: vec![],
            mounts: vec![],
            credentials: SandboxCredentials::default(),
        }
    }

    #[test]
    fn resolve_context_requires_egress_for_real_llm_secret_env() {
        let context = resolve_context_for_env(env(&[("ANTHROPIC_API_KEY", "sk-real-secret")]));

        assert!(context.requires_egress_management());
    }

    #[test]
    fn resolve_context_requires_egress_for_limited_networking_even_without_secrets() {
        let mut context = resolve_context_for_env(env(&[]));
        context.network = Some("none".to_string());

        assert!(context.requires_egress_management());
    }

    #[test]
    fn resolve_context_allows_placeholder_without_egress_requirement() {
        let context = resolve_context_for_env(env(&[(
            "ANTHROPIC_API_KEY",
            CLAUDE_CODE_PLACEHOLDER_API_KEY,
        )]));

        assert!(!context.requires_egress_management());
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
        start_status_probe: Mutex<Option<(PgPool, Uuid)>>,
        start_observed_statuses: Mutex<Vec<String>>,
        start_marks_error: Mutex<Option<(PgPool, Uuid)>>,
        status_marks_idle: Mutex<Option<(PgPool, Uuid)>>,
        status_marks_error: Mutex<Option<(PgPool, Uuid)>>,
        status_result: Mutex<Option<SandboxStatus>>,
        destroy_status_probe: Mutex<Option<(PgPool, Uuid)>>,
        destroy_observed_statuses: Mutex<Vec<String>>,
        destroyed: Mutex<Vec<String>>,
    }

    /// Test double for [`EgressEnforcer`]. Reports Envoy-socket mediation and
    /// records the per-sandbox `enforce` calls so tests can assert the resolver
    /// drove egress setup. Passing `Some(RecordingEnforcer)` models "egress
    /// enabled"; passing `None` models "no enforcer configured" (fail-closed).
    #[derive(Default)]
    struct RecordingEnforcer {
        networking: Mutex<Vec<(Uuid, Option<serde_json::Value>)>>,
    }

    #[async_trait]
    impl crate::egress::enforcer::EgressEnforcer for RecordingEnforcer {
        async fn enforce(
            &self,
            sandbox_id: Uuid,
            _sandbox_token: &str,
            networking: Option<&serde_json::Value>,
            _credentials: SandboxCredentials,
        ) -> anyhow::Result<()> {
            self.networking
                .lock()
                .await
                .push((sandbox_id, networking.cloned()));
            Ok(())
        }

        async fn teardown(&self, _sandbox_id: Uuid) -> anyhow::Result<()> {
            Ok(())
        }
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

        fn provider_name(&self) -> &'static str {
            "recording"
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
        assert_llm_ref(
            &egress,
            "authorization",
            InjectScheme::Bearer,
            "ANTHROPIC_AUTH_TOKEN",
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
            "http://llm-egress.internal"
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
        assert_llm_ref(&egress, "x-api-key", InjectScheme::Raw, "ANTHROPIC_API_KEY");
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

        assert!(extract_llm_routes(&mut e, &[]).is_empty());
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

        assert!(extract_llm_routes(&mut e, &allow(&["api.anthropic.com"])).is_empty());
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
        assert_llm_ref(
            &egress,
            "authorization",
            InjectScheme::Bearer,
            "OPENAI_API_KEY",
        );
        assert_eq!(
            e.get("OPENAI_API_KEY").unwrap(),
            CODEX_PLACEHOLDER_OPENAI_API_KEY
        );
        assert!(!e.contains_key("ANTHROPIC_API_KEY"));
        assert_eq!(
            e.get("OPENAI_BASE_URL").unwrap(),
            "http://llm-egress.internal"
        );
    }

    #[test]
    fn no_llm_key_returns_none() {
        let mut e = env(&[("DB_PASSWORD", "x")]);
        assert!(extract_llm_routes(&mut e, &[]).is_empty());
        assert_eq!(e.get("DB_PASSWORD").unwrap(), "x");
    }

    #[test]
    fn llm_literal_key_without_secret_provenance_fails_closed() {
        // A plaintext LLM key that did not come from a managed Secret has no
        // resolvable credential ref, so it is refused (fail closed) and still
        // stripped from env so it cannot leak into the sandbox.
        let mut e = env(&[
            ("ANTHROPIC_API_KEY", "sk-literal"),
            ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        ]);
        let no_provenance = LlmCredentialProvenance::new();
        let routes = extract_llm_egress(&mut e, &no_provenance, &allow(&["api.anthropic.com"]));
        assert!(routes.is_empty());
        assert!(!e.contains_key("ANTHROPIC_API_KEY"));
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
            "http://llm-egress.internal"
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
        assert_llm_ref(
            &egress,
            "x-goog-api-key",
            InjectScheme::Raw,
            "GEMINI_API_KEY",
        );
        assert!(!e.contains_key("GEMINI_API_KEY"));
        // base URL is repointed at the plaintext egress placeholder host.
        assert_eq!(
            e.get("GOOGLE_GEMINI_BASE_URL").unwrap(),
            "http://llm-egress.internal"
        );
    }

    #[test]
    fn google_api_key_alias_also_works() {
        let mut e = env(&[("GOOGLE_API_KEY", "AIzaABC")]);
        let egress = extract_llm_route(&mut e, &allow(&["generativelanguage.googleapis.com"]))
            .expect("egress");
        assert_llm_ref(
            &egress,
            "x-goog-api-key",
            InjectScheme::Raw,
            "GOOGLE_API_KEY",
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
        assert_llm_ref(
            &egress,
            "api-key",
            InjectScheme::Raw,
            "AZURE_OPENAI_API_KEY",
        );
        assert!(!e.contains_key("AZURE_OPENAI_API_KEY"));
    }

    #[test]
    fn azure_wildcard_does_not_allow_parent_domain() {
        let mut e = env(&[
            ("AZURE_OPENAI_API_KEY", "az-secret"),
            ("AZURE_OPENAI_BASE_URL", "https://openai.azure.com"),
        ]);

        assert!(extract_llm_routes(&mut e, &allow(&["*.openai.azure.com"])).is_empty());
        assert!(!e.contains_key("AZURE_OPENAI_API_KEY"));
    }

    #[test]
    fn azure_without_base_url_bails() {
        // Azure has no fixed endpoint; without a base URL we must not inject the
        // key toward an unknown host.
        let mut e = env(&[("AZURE_OPENAI_API_KEY", "az-secret")]);
        assert!(extract_llm_routes(&mut e, &allow(&["*.openai.azure.com"])).is_empty());
    }

    #[test]
    fn localhost_and_private_ip_literals_are_rejected_even_if_allowlisted() {
        for host in ["localhost", "127.0.0.1", "10.0.0.1", "169.254.169.254"] {
            let mut e = env(&[
                ("OPENAI_API_KEY", "sk-oai"),
                ("OPENAI_BASE_URL", &format!("https://{host}/v1")),
            ]);

            assert!(
                extract_llm_routes(&mut e, &allow(&[host])).is_empty(),
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

        assert!(extract_llm_routes(&mut e, &allow(&["api.openai.com"])).is_empty());
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

        let resolver = SandboxResolver::new(
            pool.clone(),
            provider.clone(),
            Some(Arc::new(RecordingEnforcer::default())),
            config,
        );
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
                Some(&sandbox_id.to_string())
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
    async fn sandbox_resolver_rejects_real_llm_secret_before_provider_create_without_egress_manager(
    ) {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let unique = Uuid::now_v7().simple().to_string();

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (id, name, engine_kind, env, permission_mode, version)
                VALUES ($1, $2, 'claude', $3, 'bypassPermissions', 1)
                "#,
            )
            .bind(agent_id)
            .bind(format!("resolver-no-egress-agent-{unique}"))
            .bind(serde_json::json!({
                "ANTHROPIC_API_KEY": "sk-real-secret",
                "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic"
            }))
            .execute(&pool)
            .await
            .expect("insert no-egress agent");

            sqlx::query(
                "INSERT INTO joysafeter_sessions (id, agent_id, status) VALUES ($1, $2, 'idle')",
            )
            .bind(session_id)
            .bind(agent_id)
            .execute(&pool)
            .await
            .expect("insert no-egress session");

            let provider = Arc::new(RecordingProvider::default());
            let mut config = JoySafeterConfig::from_env();
            config.sandbox_provider = "recording".to_string();
            config.sandbox_pool_enabled = false;
            config.sandbox_workspace_root = None;
            config.envoy_enabled = false;
            let resolver = SandboxResolver::new(pool.clone(), provider.clone(), None, config);

            let err = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
                .await
                .expect_err("provider without egress manager must reject real LLM secrets");
            let message = err.to_string();
            assert!(
                message.contains("SANDBOX_EGRESS_MANAGER_REQUIRED"),
                "{message}"
            );
            assert!(
                provider.created.lock().await.is_empty(),
                "provider.create must not be called after secret boundary rejection"
            );

            let sandbox_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_sandboxes WHERE chat_session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count no-egress sandboxes");
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
        let resolver = SandboxResolver::new(
            pool.clone(),
            provider.clone(),
            Some(Arc::new(RecordingEnforcer::default())),
            config,
        );

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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
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
        let resolver = SandboxResolver::new(
            pool.clone(),
            provider.clone(),
            Some(Arc::new(RecordingEnforcer::default())),
            config,
        );

        let result = resolver
            .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
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
            let resolver = SandboxResolver::new(
                pool.clone(),
                provider.clone(),
                Some(Arc::new(RecordingEnforcer::default())),
                config,
            );

            let resolved = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
                .await
                .expect("pool claim should survive runner-ready idle race");
            assert_eq!(resolved, (sandbox_id, external_id.clone()));
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
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
            let resolver = SandboxResolver::new(
                pool.clone(),
                provider.clone(),
                Some(Arc::new(RecordingEnforcer::default())),
                config,
            );

            let resolved = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
                .await
                .expect("stopped pool claim should restart after DB claim");
            assert_eq!(resolved, (sandbox_id, external_id.clone()));

            assert_eq!(
                provider.start_observed_statuses.lock().await.as_slice(),
                &["provisioning".to_string()]
            );
            assert!(provider.destroyed.lock().await.is_empty());

            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
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
            let resolver = SandboxResolver::new(
                pool.clone(),
                provider.clone(),
                Some(Arc::new(RecordingEnforcer::default())),
                config,
            );

            let err = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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
    async fn sandbox_resolver_builds_mcp_egress_from_vlt_prefixed_vault_ids() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let vault_id = Uuid::now_v7();
        let credential_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
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
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
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
            .bind(serde_json::json!([format!("vlt_{vault_id}")]))
            .execute(&pool)
            .await
            .expect("insert session");

            let agent = queries::get_agent(&pool, agent_id)
                .await
                .expect("load agent")
                .expect("agent exists");
            let egress = build_mcp_egress(&pool, Some(session_id), Some(&agent))
                .await
                .expect("build mcp egress");

            assert_eq!(egress.len(), 1);
            assert_eq!(egress[0].id, "mcp:secure-mcp");
            assert_eq!(egress[0].match_prefix, "/mcp/secure-mcp/");
            assert_eq!(egress[0].upstream_host, "mcp.vault-alias.example");
            assert_eq!(egress[0].upstream_port, 443);
            assert_eq!(egress[0].upstream_prefix, "/api");
            assert!(egress[0].upstream_tls);
            assert_eq!(egress[0].inject_header, "authorization");
            assert_eq!(egress[0].inject_scheme, InjectScheme::Bearer);
            assert_eq!(
                egress[0].credential_ref,
                CredentialRef::Mcp {
                    vault_id,
                    mcp_server_url: mcp_url.to_string(),
                }
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let image = format!("resolver-race-image-{unique}:latest");
        let external_id = format!("resolver-race-{sandbox_id}");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
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

            let resolver = SandboxResolver::new(
                pool.clone(),
                provider,
                Some(Arc::new(RecordingEnforcer::default())),
                config,
            );
            let err = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let sandbox_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let image = format!("resolver-restart-ordering-{unique}:latest");
        let external_id = format!("resolver-restart-ordering-{sandbox_id}");

        async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
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

            let resolver = SandboxResolver::new(
            pool.clone(),
            provider.clone(),
            Some(Arc::new(RecordingEnforcer::default())),
            config,
        );
            let resolved = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let stale_sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let image = format!("resolver-stale-creating-{unique}:latest");
        let external_id = format!("resolver-stale-creating-{stale_sandbox_id}");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
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

            let resolver = SandboxResolver::new(
            pool.clone(),
            provider.clone(),
            Some(Arc::new(RecordingEnforcer::default())),
            config,
        );
            let (resolved_sandbox_id, _resolved_external_id) = resolver
                .resolve(task_id, Some(session_id), Some(agent_id), None)
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let environment_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let environment_ref = format!("env_{environment_id}");
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
            "mcp_configs": [],
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
                    id, name, engine_kind, model, system_prompt, env, mcp_configs,
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
            let enforcer = Arc::new(RecordingEnforcer::default());
            let resolver = SandboxResolver::new(
                pool.clone(),
                provider.clone(),
                Some(enforcer.clone()),
                config,
            );

            let (sandbox_id, _external_id) = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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

            let networking = enforcer.networking.lock().await;
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

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let file_id = Uuid::now_v7();
        let session_file_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
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
                    mcp_configs, skills, tools, agents, commands, permission_mode,
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
            let resolver = SandboxResolver::new(
                pool.clone(),
                provider.clone(),
                Some(Arc::new(RecordingEnforcer::default())),
                config,
            );

            let err = resolver
                .resolve(Uuid::now_v7(), Some(session_id), Some(agent_id), None)
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
