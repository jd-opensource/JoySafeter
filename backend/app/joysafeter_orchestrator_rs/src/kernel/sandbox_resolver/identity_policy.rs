use std::time::Duration;

use anyhow::Context;
use async_trait::async_trait;
use sqlx::PgPool;

use crate::db::queries;
use crate::ids::{SandboxId, TaskId};
use crate::kernel::credentials::runtime_projection::sandbox_runner_token;

use super::context::ResolveContextBuilder;
use super::identity::{identity_lease_matches, identity_lease_refresh_after_seconds};
use super::lifecycle::SandboxLifecycleService;
use super::networking::{SandboxNetworkingService, TaskIdentityNetworkLease};

#[async_trait]
pub(crate) trait SandboxIdentityPolicy: Send + Sync {
    async fn refresh_delay(
        &self,
        sandbox_id: SandboxId,
        task_id: TaskId,
    ) -> anyhow::Result<Option<Duration>>;

    async fn refresh_policy(
        &self,
        task_id: TaskId,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<Option<u64>>;

    async fn clear_policy(&self, sandbox_id: SandboxId, task_id: TaskId) -> anyhow::Result<bool>;
}

#[derive(Clone)]
pub struct SandboxIdentityPolicyService {
    pool: PgPool,
    networking: SandboxNetworkingService,
    lifecycle: SandboxLifecycleService,
    context_builder: ResolveContextBuilder,
}

impl SandboxIdentityPolicyService {
    pub fn new(
        pool: PgPool,
        networking: SandboxNetworkingService,
        lifecycle: SandboxLifecycleService,
        context_builder: ResolveContextBuilder,
    ) -> Self {
        Self {
            pool,
            networking,
            lifecycle,
            context_builder,
        }
    }
}

#[async_trait]
impl SandboxIdentityPolicy for SandboxIdentityPolicyService {
    async fn refresh_delay(
        &self,
        sandbox_id: SandboxId,
        task_id: TaskId,
    ) -> anyhow::Result<Option<Duration>> {
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
            Duration::from_secs(seconds.max(1))
        } else {
            Duration::ZERO
        }))
    }

    async fn refresh_policy(
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
        let proxy_auth_token = sandbox_runner_token(&sandbox);
        let _ = sandbox
            .external_id
            .as_deref()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| anyhow::anyhow!("Agent Identity refresh sandbox has no external_id"))?;
        let context = self
            .context_builder
            .build(task_id, Some(session_id), Some(agent_id), task.project_id)
            .await?;
        if !context.has_task_identity() {
            anyhow::bail!("Agent Identity lease exists without a dynamic identity route");
        }
        let latest = queries::get_task(&self.pool, task_id).await?;
        if !matches!(latest, Some(ref current) if current.status == "running" && current.sandbox_id == Some(sandbox_id))
        {
            return Ok(None);
        }
        self.networking
            .refresh_reused(
                &sandbox,
                &context.expected,
                &context.credentials,
                Some(TaskIdentityNetworkLease {
                    task_id,
                    refresh_after_seconds: context.identity_refresh_after_seconds,
                }),
                proxy_auth_token,
            )
            .await?;
        Ok(context.identity_refresh_after_seconds)
    }

    async fn clear_policy(&self, sandbox_id: SandboxId, task_id: TaskId) -> anyhow::Result<bool> {
        let Some(sandbox) = queries::get_sandbox(&self.pool, sandbox_id).await? else {
            return Ok(false);
        };
        if !identity_lease_matches(sandbox.config.as_ref(), task_id) {
            return Ok(false);
        }

        let policy_hash = match self.networking.reconcile_base_policy(&sandbox).await {
            Ok(policy_hash) => policy_hash,
            Err(error) => {
                let reason = format!("Agent Identity cleanup failed: {error:#}");
                let _ = queries::mark_sandbox_error(&self.pool, sandbox_id, Some(&reason)).await;
                let destroyed = self
                    .lifecycle
                    .destroy_observed(&sandbox, "Agent Identity cleanup failure")
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
        self.networking.remember_ready(sandbox_id, policy_hash);
        Ok(true)
    }
}
