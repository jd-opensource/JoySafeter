use std::sync::Arc;

use sqlx::PgPool;
use tracing::{debug, info};

use crate::db::queries;
use crate::ids::{AgentId, ProjectId, SessionId, TaskId};
#[cfg(test)]
use crate::ids::{CredentialId, EnvironmentId, SandboxId, UserId};
#[cfg(test)]
use crate::kernel::credentials::error::CredentialRuntimeError;
#[cfg(test)]
use crate::kernel::credentials::runtime_projection::remove_agent_identity_routes;
#[cfg(test)]
use crate::kernel::mcp_url;
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::EgressCredentialRoute;
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::MCP_EGRESS_HOST;
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::{
    EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher, EgressRetryMode,
};
#[cfg(test)]
use crate::kernel::network_policy::material::{
    NetworkPolicyMaterialResolver, RejectingNetworkPolicyMaterialResolver,
};
#[cfg(test)]
use crate::kernel::network_policy::ports::{NetworkPolicyRequestQueue, NetworkPolicyRuntime};
#[cfg(test)]
use crate::kernel::network_policy::NetworkPolicyRequest;
use crate::kernel::runtime_auth;
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
#[cfg(test)]
use crate::kernel::task_identity::material::{
    TaskIdentityMaterialAdapter, TaskIdentityMaterialError,
};
#[cfg(test)]
use crate::kernel::task_identity::TaskIdentityService;

mod context;
mod identity_policy;
mod lifecycle;
mod model;
mod networking;
mod pool;
mod ports;
mod provisioning;
mod runtime_plan;

pub(crate) use self::context::ResolveContextBuilder;
#[cfg(test)]
use self::identity_policy::identity_lease_metadata;
pub(crate) use self::identity_policy::{SandboxIdentityPolicy, SandboxIdentityPolicyService};
pub(crate) use self::lifecycle::SandboxLifecycleService;
pub use self::model::ResolvedSandbox;
pub(crate) use self::networking::SandboxNetworkingService;
use self::networking::TaskIdentityNetworkLease;
pub(crate) use self::pool::{PoolSandboxProvisioner, SandboxPoolService};
pub(crate) use self::ports::SandboxResolution;
pub(crate) use self::provisioning::SandboxProvisioningService;
use self::runtime_plan::runtime_fingerprint_matches;

#[cfg(test)]
use super::llm_providers::{CLAUDE_CODE_PLACEHOLDER_API_KEY, CODEX_PLACEHOLDER_OPENAI_API_KEY};

/// Hard client-side bound on a provider networking setup/refresh call (Envoy
/// socket prep + xDS push + ACK/socket-readiness wait). The individual steps are
/// bounded, but this outer bound guarantees the sandbox-provisioning path can
/// never block indefinitely on a wedged Envoy/xDS: on timeout the sandbox is
/// marked `failed` (fail-closed: it keeps network=none, no egress) and the
/// networking-reconcile loop retries it. Prevents a single stuck setup from
/// freezing task scheduling.

/// Three-stage sandbox resolution:
/// 1. Reuse existing active sandbox for the session (with fingerprint check)
/// 1b. Restart stopped sandbox for the session
/// 2. Claim from warm pool (with liveness check)
/// 3. Create a new sandbox (with runner token, JOYSAFETER_* env vars)
///
pub struct SandboxResolver {
    pool: PgPool,
    networking: SandboxNetworkingService,
    lifecycle: SandboxLifecycleService,
    pool_service: SandboxPoolService,
    provisioning: SandboxProvisioningService,
    context_builder: ResolveContextBuilder,
    /// Per-session locks to prevent concurrent resolution
    session_locks: dashmap::DashMap<SessionId, Arc<tokio::sync::Mutex<()>>>,
}

impl SandboxResolver {
    pub fn new_with_services(
        pool: PgPool,
        networking: SandboxNetworkingService,
        lifecycle: SandboxLifecycleService,
        pool_service: SandboxPoolService,
        provisioning: SandboxProvisioningService,
        context_builder: ResolveContextBuilder,
    ) -> Self {
        Self {
            pool,
            networking,
            lifecycle,
            pool_service,
            provisioning,
            context_builder,
            session_locks: dashmap::DashMap::new(),
        }
    }

    #[cfg(test)]
    pub fn with_network_policy_runtime(mut self, runtime: Arc<dyn NetworkPolicyRuntime>) -> Self {
        self.networking = self
            .networking
            .map_policy(|policy| policy.with_test_runtime(runtime));
        self.pool_service = self.pool_service.with_networking(self.networking.clone());
        self.lifecycle = self.lifecycle.with_networking(self.networking.clone());
        self.provisioning = self
            .provisioning
            .with_networking(self.networking.clone(), self.lifecycle.clone());
        self.context_builder.set_networking(self.networking.clone());
        self
    }

    #[cfg(test)]
    pub fn with_network_policy_material_resolver(
        mut self,
        resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    ) -> Self {
        self.networking = self
            .networking
            .map_policy(|policy| policy.with_test_material_resolver(resolver));
        self.pool_service = self.pool_service.with_networking(self.networking.clone());
        self.lifecycle = self.lifecycle.with_networking(self.networking.clone());
        self.provisioning = self
            .provisioning
            .with_networking(self.networking.clone(), self.lifecycle.clone());
        self.context_builder.set_networking(self.networking.clone());
        self
    }

    #[cfg(test)]
    fn with_identity_provider(
        mut self,
        provider: Arc<dyn crate::kernel::agent_identity_provider::AgentIdentityProvider>,
    ) -> Self {
        self.context_builder.set_identity_provider(provider);
        self
    }

    #[cfg(test)]
    fn with_identity_allowed_hosts(mut self, allowed_hosts: Vec<String>) -> Self {
        self.context_builder
            .set_identity_allowed_hosts(allowed_hosts);
        self
    }

    #[cfg(test)]
    fn with_task_identity_material_adapter(
        mut self,
        material: TaskIdentityMaterialAdapter,
    ) -> Self {
        self.context_builder.set_task_identity_material(material);
        self
    }

    #[cfg(test)]
    fn identity_service(&self) -> &TaskIdentityService {
        self.context_builder.identity()
    }

    #[cfg(test)]
    fn identity_policy_service(&self) -> SandboxIdentityPolicyService {
        SandboxIdentityPolicyService::new(
            self.pool.clone(),
            self.networking.clone(),
            self.lifecycle.clone(),
            self.context_builder.clone(),
        )
    }

    /// Set the pool replenish notify (called from scheduler setup).
    pub fn with_pool_replenish_notify(mut self, notify: Arc<tokio::sync::Notify>) -> Self {
        self.pool_service = self.pool_service.with_replenish_notify(notify);
        self
    }

    /// Route networking changes through the elected xDS authority in multi mode.
    #[cfg(test)]
    pub fn with_network_policy_queue(mut self, queue: Arc<dyn NetworkPolicyRequestQueue>) -> Self {
        self.networking = self.networking.map_policy(|policy| {
            policy.with_test_control(
                crate::xds::authority::XdsAuthority::standalone(),
                Some(queue),
            )
        });
        self.pool_service = self.pool_service.with_networking(self.networking.clone());
        self.lifecycle = self.lifecycle.with_networking(self.networking.clone());
        self.provisioning = self
            .provisioning
            .with_networking(self.networking.clone(), self.lifecycle.clone());
        self.context_builder.set_networking(self.networking.clone());
        self
    }

    #[cfg(test)]
    pub fn with_network_policy_control(
        mut self,
        authority: crate::xds::authority::XdsAuthority,
        queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    ) -> Self {
        self.networking = self
            .networking
            .map_policy(|policy| policy.with_test_control(authority, queue));
        self.pool_service = self.pool_service.with_networking(self.networking.clone());
        self.lifecycle = self.lifecycle.with_networking(self.networking.clone());
        self.provisioning = self
            .provisioning
            .with_networking(self.networking.clone(), self.lifecycle.clone());
        self.context_builder.set_networking(self.networking.clone());
        self
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
            .context_builder
            .build(task_id, session_id, agent_id, project_id)
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
                        .lifecycle
                        .destroy_observed(&sandbox, "fingerprint mismatch")
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
                        // Do not reuse `creating` sandboxes: the provider runtime may not exist yet.
                        // For idle/running, only touch last_used_at (don't reset
                        //      provisioning timeout). For provisioning, return as-is.
                        "idle" | "running" => {
                            if let Some(ref ext_id) = sandbox.external_id {
                                if context.is_limited_networking() {
                                    self.networking
                                        .refresh_reused(
                                            &sandbox,
                                            &context.expected,
                                            &context.credentials,
                                            context.has_task_identity().then_some(
                                                TaskIdentityNetworkLease {
                                                    task_id,
                                                    refresh_after_seconds: context
                                                        .identity_refresh_after_seconds,
                                                },
                                            ),
                                            runtime_auth::egress_proxy_token(
                                                sandbox.config.as_ref(),
                                            ),
                                        )
                                        .await?;
                                }
                                info!(
                                    sandbox_id = %sandbox.id,
                                    task_id = %task_id,
                                    status = %sandbox.status,
                                    "Reusing existing sandbox for session"
                                );
                                // Only touch last_used_at; do not rewrite the lifecycle state.
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
                                // Do not touch last_used_at for provisioning:
                                // preserves provisioning timeout detection
                                return Ok(context.resolved(sandbox.id, ext_id.clone()));
                            }
                        }
                        "creating" => {
                            // Do not reuse a `creating` sandbox: the provider runtime
                            // may not exist yet. But we MUST destroy it first,
                            // otherwise the unique constraint
                            // `idx_csb_active_session_unique` blocks creating a
                            // replacement and the scheduler enters a retry loop.
                            if !self
                                .lifecycle
                                .destroy_observed(&sandbox, "stale creating")
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
                                    .lifecycle
                                    .restart_stopped(sandbox.id, ext_id, &context)
                                    .await?
                                {
                                    info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox");
                                    return Ok(context.resolved(sandbox.id, ext_id.clone()));
                                }
                                // Restart failed (e.g. pod deleted in K8s). Destroy the
                                // stale DB record so the unique-session constraint is freed
                                // and a fresh sandbox can be created below.
                                if !self
                                    .lifecycle
                                    .destroy_observed(&sandbox, "stopped restart failed")
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
                            if !self.lifecycle.destroy_observed(&sandbox, "error").await? {
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
                            if !self
                                .lifecycle
                                .destroy_observed(&sandbox, "stopping")
                                .await?
                            {
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
                        .lifecycle
                        .destroy_observed(&sandbox, "stopped fingerprint mismatch")
                        .await?
                    {
                        anyhow::bail!(
                            "stopped sandbox {} changed state before fingerprint cleanup",
                            sandbox.id
                        );
                    }
                    return self.provisioning.create(task_id, &context).await;
                }
                if let Some(ref ext_id) = sandbox.external_id {
                    if self
                        .lifecycle
                        .restart_stopped(sandbox.id, ext_id, &context)
                        .await?
                    {
                        info!(sandbox_id = %sandbox.id, "Restarted stopped sandbox for session");
                        return Ok(context.resolved(sandbox.id, ext_id.clone()));
                    }
                    // Restart failed — destroy stale record to free the unique-session
                    // constraint so a fresh sandbox can be created below.
                    if !self
                        .lifecycle
                        .destroy_observed(&sandbox, "stopped restart failed (session)")
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

        if let Some(sandbox) = self.pool_service.try_claim(task_id, &context).await? {
            return Ok(sandbox);
        }

        // Stage 3: Create new sandbox
        self.provisioning.create(task_id, &context).await
    }
}

#[async_trait::async_trait]
impl SandboxResolution for SandboxResolver {
    async fn resolve(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        agent_id: Option<AgentId>,
        project_id: Option<ProjectId>,
    ) -> anyhow::Result<ResolvedSandbox> {
        SandboxResolver::resolve(self, task_id, session_id, agent_id, project_id).await
    }
}

#[cfg(test)]
#[path = "sandbox_resolver_tests.rs"]
mod tests;
