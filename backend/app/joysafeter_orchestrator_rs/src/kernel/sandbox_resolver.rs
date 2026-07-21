use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;

use base64::Engine as _;
use sha2::{Digest, Sha256};
use sqlx::PgPool;
use tracing::{debug, info, warn};
use url::Url;
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::JoySafeterAgent;
use crate::db::queries;
use crate::kernel::harness_input_builder::VaultCipher;
use crate::sandbox::lds_backend::{
    EgressCredentialRoute, EgressExposure, EgressKind, GitEgress, LlmEgress, McpEgress,
    SandboxCredentials, EXTERNAL_EGRESS_HOST,
};
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

const CLAUDE_CODE_PLACEHOLDER_API_KEY: &str = "joysafeter-placeholder-anthropic-api-key";
const CODEX_PLACEHOLDER_OPENAI_API_KEY: &str = "joysafeter-placeholder-openai-api-key";

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
    session_locks: dashmap::DashMap<Uuid, Arc<tokio::sync::Mutex<()>>>,
}

impl SandboxResolver {
    pub fn new(pool: PgPool, provider: Arc<dyn SandboxProvider>, config: JoySafeterConfig) -> Self {
        Self {
            pool,
            provider,
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
                    if let Some(ref ext_id) = sandbox.external_id {
                        let _ = self.provider.destroy(ext_id).await;
                    }
                    let _ = self.teardown_networking(sandbox.id).await;
                    let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
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
                            if let Some(ref ext_id) = sandbox.external_id {
                                let _ = self.provider.destroy(ext_id).await;
                            }
                            let _ = self.teardown_networking(sandbox.id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                            debug!(
                                sandbox_id = %sandbox.id,
                                "Destroyed stale creating sandbox before re-provisioning"
                            );
                        }
                        "stopped" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                if self.provider.start(ext_id).await.is_ok() {
                                    queries::transition_sandbox(
                                        &self.pool,
                                        sandbox.id,
                                        "provisioning",
                                    )
                                    .await?;
                                    // Touch last_used_at so provisioning timeout counts from NOW
                                    // (matching Python _restart_sandbox line 747: svc.touch())
                                    let _ = queries::touch_sandbox(&self.pool, sandbox.id).await;
                                    info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox");
                                    return Ok((sandbox.id, ext_id.clone()));
                                }
                            }
                        }
                        "error" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                let _ = self.provider.destroy(ext_id).await;
                            }
                            let _ = self.teardown_networking(sandbox.id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                        }
                        "stopping" => {
                            // M5 fix: A sandbox stuck in "stopping" blocks new
                            // session sandboxes indefinitely. Clean it up so the
                            // resolver can proceed to create a fresh one.
                            debug!(sandbox_id = %sandbox.id, "Sandbox is stopping, cleaning up and creating new");
                            if let Some(ref ext_id) = sandbox.external_id {
                                let _ = self.provider.destroy(ext_id).await;
                            }
                            let _ = self.teardown_networking(sandbox.id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
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
                    if let Some(ref ext_id) = sandbox.external_id {
                        let _ = self.provider.destroy(ext_id).await;
                    }
                    let _ = self.teardown_networking(sandbox.id).await;
                    let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                    return self.create_new_sandbox(task_id, &context).await;
                }
                if let Some(ref ext_id) = sandbox.external_id {
                    if self.provider.start(ext_id).await.is_ok() {
                        queries::transition_sandbox(&self.pool, sandbox.id, "provisioning").await?;
                        let _ = queries::touch_sandbox(&self.pool, sandbox.id).await;
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
                            self.mark_pool_claimed(
                                sandbox.id,
                                session_id,
                                &context.expected,
                                "pool_claimed",
                                80,
                                "Claimed from warm pool, waiting for runner readiness",
                            )
                            .await?;
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
                                let _ = crate::sandbox::file_injection::inject_session_files(
                                    &self.pool,
                                    &ctx,
                                    self.provider.as_ref(),
                                )
                                .await;
                            }
                            return Ok((sandbox.id, ext_id.clone()));
                        }
                        Ok(SandboxStatus::Stopped) => {
                            // Try to start pooled sandbox
                            if self.provider.start(ext_id).await.is_ok() {
                                self.mark_pool_claimed(
                                    sandbox.id,
                                    session_id,
                                    &context.expected,
                                    "pool_restarting",
                                    75,
                                    "Claimed stopped pooled sandbox, restarting runtime",
                                )
                                .await?;
                                info!(sandbox_id = %sandbox.id, "Started pooled sandbox");
                                return Ok((sandbox.id, ext_id.clone()));
                            }
                            // Broken pooled sandbox — destroy it
                            warn!(sandbox_id = %sandbox.id, "Destroying broken pooled sandbox");
                            let _ = self.provider.destroy(ext_id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                        }
                        Err(err) => {
                            warn!(sandbox_id = %sandbox.id, external_id = %ext_id, error = %err, "Cannot query pooled sandbox status, destroying");
                            let _ = self.provider.destroy(ext_id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                        }
                        _ => {
                            warn!(sandbox_id = %sandbox.id, external_id = %ext_id, "Pooled sandbox has unexpected status, destroying");
                            let _ = self.provider.destroy(ext_id).await;
                            let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
                        }
                    }
                } else {
                    warn!(sandbox_id = %sandbox.id, "Pooled sandbox has no external_id, destroying");
                    let _ = queries::destroy_sandbox(&self.pool, sandbox.id).await;
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
        };

        if create_config.network.as_deref() == Some("none") {
            if !self.provider.capabilities().has_egress_management {
                anyhow::bail!(
                    "limited sandbox networking requires egress management, but provider does not support it"
                );
            }
            let external_id = format!("joysafeter-{}", sandbox_db_id);
            self.provider
                .setup_networking(
                    sandbox_db_id,
                    &external_id,
                    context.networking.as_ref(),
                    context.credentials.clone(),
                )
                .await?;
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
            let _ = crate::sandbox::file_injection::inject_session_files(
                &self.pool,
                &ctx,
                self.provider.as_ref(),
            )
            .await;
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

        let _ = queries::transition_sandbox(&self.pool, sandbox_db_id, "provisioning").await;

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
        session_id: Option<Uuid>,
        agent_id: Option<Uuid>,
        project_id: Option<&str>,
    ) -> anyhow::Result<ResolveContext> {
        let agent = match agent_id {
            Some(aid) => queries::get_agent(&self.pool, aid).await?,
            None => None,
        };
        let session = match session_id {
            Some(sid) => queries::get_session(&self.pool, sid).await?,
            None => None,
        };
        let project_id = project_id
            .map(ToOwned::to_owned)
            .or_else(|| session.as_ref().and_then(|s| s.project_id.clone()))
            .or_else(|| agent.as_ref().and_then(|a| a.project_id.clone()));
        let environment_ref = session
            .as_ref()
            .and_then(|s| non_empty(s.environment_ref.as_deref()))
            .or_else(|| {
                agent
                    .as_ref()
                    .and_then(|a| non_empty(a.environment_ref.as_deref()))
            });

        let environment = if let Some(ref env_ref) = environment_ref {
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
        // real key never enters the sandbox. Non-limited sandboxes keep the
        // legacy behaviour (key stays in env) since they have no proxy.
        let mut credentials = SandboxCredentials::default();
        if network.as_deref() == Some("none") {
            credentials.llm =
                Self::extract_llm_egress(&mut env, &self.config.llm_egress_allowed_hosts);
            credentials.mcp = Self::build_mcp_egress(&self.pool, session_id, agent.as_ref()).await;
            credentials.git = Self::build_git_egress(&self.pool, session_id).await;
            credentials.external = Self::build_external_egress(
                &self.pool,
                environment.as_ref(),
                agent.as_ref().and_then(|a| a.project_id.as_deref()),
                &mut env,
            )
            .await;
        }

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
            },
            memory_mounts: vec![], // populated by caller when memory stores are resolved
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
    /// Recognises Anthropic (`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`) and
    /// OpenAI (`OPENAI_API_KEY`) style credentials. The upstream host is derived
    /// from the corresponding `*_BASE_URL` (default `api.anthropic.com` /
    /// `api.openai.com`), then the base URL is rewritten to the plaintext egress
    /// placeholder so the agent's HTTP client targets Envoy.
    fn extract_llm_egress(
        env: &mut HashMap<String, String>,
        allowed_hosts: &[String],
    ) -> Option<LlmEgress> {
        // Determine provider + auth scheme by which key variable is present.
        //
        // Anthropic supports two conventions and the header MUST match how the
        // token was issued, or a strict gateway rejects it:
        //   * ANTHROPIC_AUTH_TOKEN → `Authorization: Bearer <token>` — the form
        //     used by gateways / internal Anthropic-compatible endpoints.
        //   * ANTHROPIC_API_KEY    → `x-api-key: <key>` — official Anthropic.
        // OpenAI-compatible endpoints use `Authorization: Bearer <key>`.
        // Gemini (Google Generative Language API) uses `x-goog-api-key: <key>`.
        // Azure OpenAI uses `api-key: <key>` (raw, NOT Bearer).
        //
        // The env-var name is the signal: each vendor's SDK/CLI sets a well-known
        // variable and each vendor's API mandates a specific header — a fixed
        // per-vendor convention, not runtime detection.
        //
        // `default_host` is None for providers with no fixed endpoint (Azure:
        // every resource is `<name>.openai.azure.com`), which therefore require an
        // explicit base URL.
        //
        // Each tuple: (key var to take, base-URL var, default host, header, is_bearer).
        let (key_var, base_url_var, default_host, header_name, is_bearer): (
            &str,
            &str,
            Option<&str>,
            &str,
            bool,
        ) = if env.contains_key("ANTHROPIC_AUTH_TOKEN") {
            (
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                Some("api.anthropic.com"),
                "authorization",
                true,
            )
        } else if env.contains_key("ANTHROPIC_API_KEY") {
            (
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_BASE_URL",
                Some("api.anthropic.com"),
                "x-api-key",
                false,
            )
        } else if env.contains_key("OPENAI_API_KEY") {
            (
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                Some("api.openai.com"),
                "authorization",
                true,
            )
        } else if env.contains_key("GEMINI_API_KEY") || env.contains_key("GOOGLE_API_KEY") {
            (
                if env.contains_key("GEMINI_API_KEY") {
                    "GEMINI_API_KEY"
                } else {
                    "GOOGLE_API_KEY"
                },
                "GOOGLE_GEMINI_BASE_URL",
                Some("generativelanguage.googleapis.com"),
                "x-goog-api-key",
                false,
            )
        } else if env.contains_key("AZURE_OPENAI_API_KEY") {
            (
                "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_BASE_URL",
                None,
                "api-key",
                false,
            )
        } else {
            return None;
        };

        let is_anthropic = key_var == "ANTHROPIC_API_KEY" || key_var == "ANTHROPIC_AUTH_TOKEN";
        let is_openai = key_var == "OPENAI_API_KEY";
        let is_gemini = key_var == "GEMINI_API_KEY" || key_var == "GOOGLE_API_KEY";
        let is_azure = key_var == "AZURE_OPENAI_API_KEY";

        // Take the key value, removing it (and any Anthropic alias) from env so
        // no real LLM credential remains in the container.
        let key_value = env.remove(key_var)?;
        env.remove("ANTHROPIC_API_KEY");
        env.remove("ANTHROPIC_AUTH_TOKEN");
        if is_openai {
            env.remove("OPENAI_API_KEY");
        }
        if is_gemini {
            env.remove("GEMINI_API_KEY");
            env.remove("GOOGLE_API_KEY");
        }
        if is_azure {
            env.remove("AZURE_OPENAI_API_KEY");
        }

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
                        return None;
                    }
                };
                if url.scheme() != "http" && url.scheme() != "https" {
                    warn!(
                        base_url_var,
                        scheme = url.scheme(),
                        "Unsupported LLM base URL scheme; skipping credential injection"
                    );
                    return None;
                }
                let host = match (url.host_str(), default_host) {
                    (Some(h), _) => h.to_string(),
                    (None, Some(d)) => d.to_string(),
                    (None, None) => return None,
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
                    return None;
                }
            },
        };

        if !is_llm_egress_host_allowed(&upstream_host, allowed_hosts) {
            warn!(
                base_url_var,
                upstream_host = %upstream_host,
                "LLM base URL host is not allowlisted; skipping credential injection"
            );
            return None;
        }

        // Claude Code requires a local API-key signal in non-interactive mode.
        // The value is deliberately non-secret; Envoy overwrites/removes auth
        // headers at the egress boundary and injects the real credential there.
        if is_anthropic {
            env.insert(
                "ANTHROPIC_API_KEY".to_string(),
                CLAUDE_CODE_PLACEHOLDER_API_KEY.to_string(),
            );
        }
        if is_openai {
            env.insert(
                "OPENAI_API_KEY".to_string(),
                CODEX_PLACEHOLDER_OPENAI_API_KEY.to_string(),
            );
        }

        // Repoint the agent at the placeholder egress host (plaintext http://).
        // The real host/port/path is only known to Envoy via the egress route.
        env.insert(
            base_url_var.to_string(),
            format!("http://{}", crate::sandbox::lds_backend::LLM_EGRESS_HOST),
        );

        let header_value = if is_bearer {
            format!("Bearer {key_value}")
        } else {
            key_value
        };

        Some(LlmEgress {
            upstream_host,
            upstream_port,
            upstream_prefix,
            upstream_tls,
            headers: vec![(header_name.to_string(), header_value)],
        })
    }

    /// Build MCP egress credentials for a sandbox: for each remote MCP server the
    /// agent references, match a vault credential by URL, decrypt its token, and
    /// produce an [`McpEgress`] keyed by the server name. The `.mcp.json` written
    /// into the sandbox points at `mcp-egress.internal/mcp/<name>/` with no token;
    /// Envoy injects the real `Authorization` here.
    async fn build_mcp_egress(
        pool: &PgPool,
        session_id: Option<Uuid>,
        agent: Option<&JoySafeterAgent>,
    ) -> Vec<McpEgress> {
        let Some(agent) = agent else {
            return vec![];
        };
        let Some(session_id) = session_id else {
            return vec![];
        };
        // Remote MCP servers (url present) declared by the agent.
        let mcp_servers: Vec<(String, String)> = agent
            .mcp_configs
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
            return vec![];
        }

        // Load the session's vault credentials, keyed by mcp_server_url.
        let session = match queries::get_session(pool, session_id).await {
            Ok(Some(s)) => s,
            _ => return vec![],
        };
        let Some(vault_ids) = session.vault_ids.as_ref() else {
            return vec![];
        };
        let ids: Vec<Uuid> = vault_ids
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str())
                    .filter_map(|s| parse_prefixed_uuid(s, "vault_"))
                    .collect()
            })
            .unwrap_or_default();
        if ids.is_empty() {
            return vec![];
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
            .unwrap_or_default();
            for (url, token_value) in rows {
                if let Some(url) = url {
                    match cipher.decrypt_or_passthrough(&token_value) {
                        Ok(tok) => {
                            token_by_url.insert(url, tok);
                        }
                        Err(e) => warn!("Failed to decrypt vault credential: {e}"),
                    }
                }
            }
        }

        let mut egress = Vec::new();
        for (name, url) in mcp_servers {
            let Some(token) = token_by_url.get(&url) else {
                continue;
            };
            let Ok(parsed) = Url::parse(&url) else {
                continue;
            };
            let tls = parsed.scheme() == "https";
            let host = parsed.host_str().unwrap_or_default().to_string();
            let port = parsed.port().unwrap_or(if tls { 443 } else { 80 });
            let prefix = if parsed.path().is_empty() {
                "/".to_string()
            } else {
                parsed.path().to_string()
            };
            egress.push(McpEgress {
                name,
                upstream_host: host,
                upstream_port: port,
                upstream_prefix: prefix,
                upstream_tls: tls,
                headers: vec![("authorization".to_string(), format!("Bearer {token}"))],
            });
        }
        egress
    }

    /// Build git egress credentials: decrypt each session repo's clone token and
    /// produce a [`GitEgress`] keyed by a stable slug ([`git_repo_slug`]). The
    /// sandbox clones from `git-egress.internal/git/<slug>/` (no token); Envoy
    /// rewrites to the real host + repo path, injects HTTP Basic auth, and
    /// forwards over the upstream scheme. The real token never enters the sandbox.
    async fn build_git_egress(pool: &PgPool, session_id: Option<Uuid>) -> Vec<GitEgress> {
        let Some(session_id) = session_id else {
            return vec![];
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
        .unwrap_or_default();

        let cipher = VaultCipher::from_env();
        let mut egress = Vec::new();
        for (idx, (url, mount_name, encrypted_token)) in rows.into_iter().enumerate() {
            if encrypted_token.is_empty() {
                continue;
            }
            let token = match cipher.decrypt_or_passthrough(&encrypted_token) {
                Ok(t) if !t.is_empty() => t,
                _ => continue,
            };
            let Ok(parsed) = Url::parse(&url) else {
                continue;
            };
            let tls = parsed.scheme() == "https";
            let host = parsed.host_str().unwrap_or_default().to_string();
            let port = parsed.port().unwrap_or(if tls { 443 } else { 80 });
            // Preserve the repo path so Envoy rewrites /git/<slug>/ back to the
            // real repo path (e.g. /org/repo.git/), keeping git smart-HTTP happy.
            let mut prefix = parsed.path().to_string();
            if !prefix.ends_with('/') {
                prefix.push('/');
            }
            // HTTP Basic auth: username "x-access-token" (GitHub) / any (GitLab),
            // password = token. base64("x-access-token:<token>").
            let basic =
                base64::engine::general_purpose::STANDARD.encode(format!("x-access-token:{token}"));
            egress.push(GitEgress {
                slug: crate::sandbox::lds_backend::git_repo_slug(&mount_name, idx),
                upstream_host: host,
                upstream_port: port,
                upstream_prefix: prefix,
                upstream_tls: tls,
                headers: vec![("authorization".to_string(), format!("Basic {basic}"))],
            });
        }
        egress
    }

    /// Build external-service egress routes from `environment.config.egress_services`.
    ///
    /// First shape supported:
    /// ```json
    /// {
    ///   "egress_services": [{
    ///     "name": "crm",
    ///     "base_url": "https://crm.example.com/api/",
    ///     "credential_ref": "crm-prod",
    ///     "exposure": "placeholder",
    ///     "inject": { "type": "bearer", "secret_key": "CRM_ACCESS_TOKEN" }
    ///   }]
    /// }
    /// ```
    ///
    /// The sandbox receives only a non-secret `<NAME>_BASE_URL` pointing at
    /// `http://external-egress.internal/services/<name>/`; the real credential is
    /// rendered into Envoy's per-sandbox route.
    async fn build_external_egress(
        pool: &PgPool,
        environment: Option<&EnvironmentRow>,
        project_id: Option<&str>,
        env: &mut HashMap<String, String>,
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
            let Ok(parsed) = Url::parse(base_url) else {
                warn!(service = %name, "Invalid external egress service base_url");
                continue;
            };
            if parsed.scheme() != "http" && parsed.scheme() != "https" {
                warn!(service = %name, scheme = parsed.scheme(), "Unsupported external egress service scheme");
                continue;
            }
            let Some(host) = parsed.host_str().map(ToOwned::to_owned) else {
                continue;
            };
            let tls = parsed.scheme() == "https";
            let port = parsed.port().unwrap_or(if tls { 443 } else { 80 });
            let upstream_prefix = normalize_external_upstream_prefix(parsed.path());

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

            let match_prefix = format!("/services/{name}/");
            let placeholder_base = format!("http://{EXTERNAL_EGRESS_HOST}{match_prefix}");
            env.insert(
                format!("{}_BASE_URL", external_service_env_name(&name)),
                placeholder_base,
            );

            let remove_headers = vec![
                "authorization".to_string(),
                "cookie".to_string(),
                "x-api-key".to_string(),
                "api-key".to_string(),
                "x-goog-api-key".to_string(),
            ];

            // Placeholder route: sandbox targets http://external-egress.internal/services/<name>/;
            // Envoy rewrites host/path to the real upstream and injects the credential.
            routes.push(EgressCredentialRoute {
                id: format!("external:{name}"),
                kind: EgressKind::External,
                exposure: EgressExposure::Placeholder,
                match_host: EXTERNAL_EGRESS_HOST.to_string(),
                match_prefix,
                exact_path: false,
                upstream_host: host.clone(),
                upstream_port: port,
                upstream_prefix: upstream_prefix.clone(),
                upstream_tls: tls,
                cluster_name: String::new(),
                inject_headers: headers.clone(),
                remove_headers: remove_headers.clone(),
            });

            // Transparent route(s): sandbox may instead call the real host over
            // plaintext http (e.g. http://crm.example.com/api/...). Envoy matches
            // the real host vhost, injects the credential on the plaintext side,
            // and TLS-originates to the real upstream when it is https. Only
            // plaintext http requests hit L7; https goes through an opaque CONNECT
            // tunnel and is NOT injected.
            //
            // Path allowlist: when `allowed_paths` is set, emit one narrow route
            // per allowed path (exact match, or prefix when the entry ends with
            // `/`) so only whitelisted endpoints get credential injection —
            // everything else on the host falls through to deny_all (403). When
            // empty, keep the wide base-path prefix route (backward compatible).
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
                        // Transparent route does not rewrite the path; upstream_prefix
                        // mirrors the match so prefix routes are a no-op rewrite.
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

    async fn teardown_networking(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.provider.teardown_networking(sandbox_id).await
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
        sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET chat_session_id = COALESCE($2, chat_session_id),
                config = COALESCE(config, '{}'::jsonb) || $3::jsonb,
                updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .bind(session_id)
        .bind(&config)
        .execute(&self.pool)
        .await?;
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
            network: None,
            // Warm-pool sandboxes are not bound to a session yet. Mounting the
            // workspace root here would expose every persisted session
            // workspace under /workspace inside an otherwise idle pooled
            // container. Session sandboxes still mount root/session_id in
            // resolve_sandbox above.
            workspace_path: None,
            memory_mounts: vec![],
        };

        let expected = ExpectedFingerprint {
            image: image.to_string(),
            engine_kind: String::new(),
            networking: None,
            env: create_config.env.clone(),
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

        let _ = sqlx::query(
            "UPDATE joysafeter_sandboxes SET status = 'pooled', updated_at = NOW() WHERE id = $1",
        )
        .bind(sandbox_db_id)
        .execute(&self.pool)
        .await;

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
    let mut creds = SandboxCredentials::default();

    let Some(session_id) = sandbox.chat_session_id else {
        return creds;
    };
    let session = match queries::get_session(pool, session_id).await {
        Ok(Some(s)) => s,
        _ => return creds,
    };
    let agent = match session.agent_id {
        Some(aid) => queries::get_agent(pool, aid).await.ok().flatten(),
        None => None,
    };

    // Re-resolve the agent env (with decrypted secrets) exactly as at creation,
    // then extract the LLM egress from it. We discard the env itself — only the
    // extracted egress credential is needed for recovery.
    if let Some(agent_ref) = agent.as_ref() {
        let environment = match agent_ref
            .environment_ref
            .as_deref()
            .filter(|v| !v.trim().is_empty())
        {
            Some(env_ref) => load_environment_row(pool, env_ref, agent_ref.project_id.as_deref())
                .await
                .ok()
                .flatten(),
            None => None,
        };
        if let Ok(mut env) =
            SandboxResolver::resolve_agent_env_from(pool, agent.as_ref(), environment.as_ref())
                .await
        {
            creds.llm = SandboxResolver::extract_llm_egress(&mut env, llm_egress_allowed_hosts);
            creds.external = SandboxResolver::build_external_egress(
                pool,
                environment.as_ref(),
                agent_ref.project_id.as_deref(),
                &mut env,
            )
            .await;
        }
    }

    creds.mcp = SandboxResolver::build_mcp_egress(pool, Some(session_id), agent.as_ref()).await;
    creds.git = SandboxResolver::build_git_egress(pool, Some(session_id)).await;
    creds
}

/// Standalone environment loader for recovery (mirrors `load_environment`).
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
}

#[derive(Debug, Clone)]
struct ResolveContext {
    session_id: Option<Uuid>,
    project_id: Option<String>,
    networking: Option<serde_json::Value>,
    network: Option<String>,
    expected: ExpectedFingerprint,
    /// Memory store bind mounts: (host_path, container_mount_path).
    memory_mounts: Vec<(String, String)>,
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

fn external_service_env_name(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect()
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
///
/// - If the entry is an absolute path (starts with `/`) it is used as-is (it is
///   already the full path under the host).
/// - Otherwise it is treated as relative to the service base prefix.
/// Collapses the boundary so no double `//` appears. Trailing `/` on the entry
/// is preserved (it signals prefix matching upstream).
fn join_service_path(base_prefix: &str, entry: &str) -> String {
    if entry.starts_with('/') {
        return entry.to_string();
    }
    let base = base_prefix.strip_suffix('/').unwrap_or(base_prefix);
    format!("{base}/{entry}")
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

fn effective_networking_config(
    networking: Option<serde_json::Value>,
    envoy_enabled: bool,
    agent: Option<&JoySafeterAgent>,
    environment: Option<&EnvironmentRow>,
) -> anyhow::Result<Option<serde_json::Value>> {
    match networking_type(networking.as_ref()) {
        Some("limited") => networking
            .map(|networking| merge_egress_hosts(networking, agent, environment))
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
            merge_egress_hosts(effective, agent, environment).map(Some)
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

fn merge_egress_hosts(
    mut networking: serde_json::Value,
    agent: Option<&JoySafeterAgent>,
    _environment: Option<&EnvironmentRow>,
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

    let mut push_host = |host: String| {
        if !allowed_hosts.iter().any(|existing| existing == &host) {
            allowed_hosts.push(host);
        }
    };

    // MCP servers declared on the agent. MCP credential injection uses a
    // placeholder host (mcp-egress.internal), so allowlisting the real MCP host
    // is a safe fallback and never collides with a credential vhost.
    if let Some(mcp_configs) = agent
        .and_then(|agent| agent.mcp_configs.as_ref())
        .and_then(|value| value.as_array())
    {
        for config in mcp_configs {
            if let Some(host) = config
                .get("url")
                .and_then(|value| value.as_str())
                .and_then(extract_host)
            {
                push_host(host);
            }
        }
    }

    // NOTE: third-party egress-service hosts are deliberately NOT merged into
    // allowed_hosts. Each external service now emits a *transparent* credential
    // vhost keyed on the real host (see build_external_egress), which owns that
    // host's exact domain. Adding the same host to allowed_hosts would make the
    // `allowed` vhost declare a duplicate exact domain, and Envoy rejects a
    // RouteConfiguration with duplicate domains ("Only unique values for domains
    // are permitted"). The transparent vhost already handles injection + egress
    // for the service's base path.

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

#[cfg(test)]
mod egress_tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    fn allow(hosts: &[&str]) -> Vec<String> {
        hosts.iter().map(|host| host.to_string()).collect()
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
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["llm.internal.example.com"]))
                .expect("egress");

        // Bearer header, real host preserved in egress, TLS upstream.
        assert_eq!(egress.upstream_host, "llm.internal.example.com");
        assert_eq!(egress.upstream_port, 443);
        assert_eq!(egress.upstream_prefix, "/v1/");
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.headers,
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
        let egress = SandboxResolver::extract_llm_egress(&mut e, &allow(&["api.anthropic.com"]))
            .expect("egress");
        assert_eq!(
            egress.headers,
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

        assert!(SandboxResolver::extract_llm_egress(&mut e, &[]).is_none());
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
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["api.anthropic.com"])).is_none()
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
        let egress = SandboxResolver::extract_llm_egress(&mut e, &allow(&["ai-api.jdcloud.com"]))
            .expect("egress");
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
        let egress =
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["gw.internal"])).expect("egress");
        assert_eq!(egress.upstream_host, "gw.internal");
        assert_eq!(egress.upstream_prefix, "/v1/");
        assert_eq!(
            egress.headers,
            vec![("authorization".to_string(), "Bearer sk-oai".to_string())]
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
        assert!(SandboxResolver::extract_llm_egress(&mut e, &[]).is_none());
        assert_eq!(e.get("DB_PASSWORD").unwrap(), "x");
    }

    #[test]
    fn plaintext_base_url_keeps_http_upstream() {
        // If the configured endpoint is plain http, the cluster should not TLS.
        let mut e = env(&[
            ("ANTHROPIC_AUTH_TOKEN", "t"),
            ("ANTHROPIC_BASE_URL", "http://llm.internal:8080/v1"),
        ]);
        let egress =
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["llm.internal"])).expect("egress");
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
        let egress = SandboxResolver::extract_llm_egress(
            &mut e,
            &allow(&["generativelanguage.googleapis.com"]),
        )
        .expect("egress");
        assert_eq!(egress.upstream_host, "generativelanguage.googleapis.com");
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.headers,
            vec![("x-goog-api-key".to_string(), "AIzaXYZ".to_string())]
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
        let egress = SandboxResolver::extract_llm_egress(
            &mut e,
            &allow(&["generativelanguage.googleapis.com"]),
        )
        .expect("egress");
        assert_eq!(
            egress.headers,
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
        let egress = SandboxResolver::extract_llm_egress(&mut e, &allow(&["*.openai.azure.com"]))
            .expect("egress");
        assert_eq!(egress.upstream_host, "my-res.openai.azure.com");
        assert!(egress.upstream_tls);
        assert_eq!(
            egress.headers,
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
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["*.openai.azure.com"])).is_none()
        );
        assert!(!e.contains_key("AZURE_OPENAI_API_KEY"));
    }

    #[test]
    fn azure_without_base_url_bails() {
        // Azure has no fixed endpoint; without a base URL we must not inject the
        // key toward an unknown host.
        let mut e = env(&[("AZURE_OPENAI_API_KEY", "az-secret")]);
        assert!(
            SandboxResolver::extract_llm_egress(&mut e, &allow(&["*.openai.azure.com"])).is_none()
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
                SandboxResolver::extract_llm_egress(&mut e, &allow(&[host])).is_none(),
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

        assert!(SandboxResolver::extract_llm_egress(&mut e, &allow(&["api.openai.com"])).is_none());
        assert!(!e.contains_key("OPENAI_API_KEY"));
    }

    #[test]
    fn external_inject_headers_support_bearer_api_key_and_cookie() {
        let secret = env(&[
            ("ACCESS_TOKEN", "tok-123"),
            ("API_KEY", "key-456"),
            ("COOKIE_HEADER", "thor=abc; pin=user"),
        ]);

        let bearer = serde_json::json!({"type": "bearer", "secret_key": "ACCESS_TOKEN"});
        assert_eq!(
            build_external_inject_headers(&secret, bearer.as_object().unwrap()).unwrap(),
            vec![("authorization".to_string(), "Bearer tok-123".to_string())]
        );

        let api_key =
            serde_json::json!({"type": "api_key", "header": "x-crm-key", "secret_key": "API_KEY"});
        assert_eq!(
            build_external_inject_headers(&secret, api_key.as_object().unwrap()).unwrap(),
            vec![("x-crm-key".to_string(), "key-456".to_string())]
        );

        let cookies = serde_json::json!({"type": "cookie", "secret_key": "COOKIE_HEADER"});
        assert_eq!(
            build_external_inject_headers(&secret, cookies.as_object().unwrap()).unwrap(),
            vec![("cookie".to_string(), "thor=abc; pin=user".to_string())]
        );
    }

    #[test]
    fn external_service_names_and_prefixes_are_stable() {
        assert_eq!(sanitize_external_service_name(" CRM Prod! "), "crm-prod");
        assert_eq!(external_service_env_name("crm-prod"), "CRM_PROD");
        assert_eq!(normalize_external_upstream_prefix(""), "/");
        assert_eq!(normalize_external_upstream_prefix("/api"), "/api/");
        assert_eq!(normalize_external_upstream_prefix("api/v1/"), "/api/v1/");
    }

    #[test]
    fn join_service_path_handles_absolute_and_relative_entries() {
        // Absolute allowlist entry: used as-is (already full host path).
        assert_eq!(
            join_service_path("/api/", "/api/warning/get"),
            "/api/warning/get"
        );
        // Relative entry: joined to the base prefix without double slash.
        assert_eq!(join_service_path("/api/", "warning/get"), "/api/warning/get");
        assert_eq!(join_service_path("/api", "warning/get"), "/api/warning/get");
        // Trailing slash on entry (prefix intent) is preserved.
        assert_eq!(join_service_path("/api/", "work/"), "/api/work/");
    }
}
