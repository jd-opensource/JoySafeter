use std::collections::HashMap;
use std::sync::Arc;

use async_trait::async_trait;
use sqlx::PgPool;
use tracing::{info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::{SandboxId, SessionId, TaskId};
use crate::kernel::network_policy::envoy_model::SandboxCredentials;
use crate::kernel::network_policy::DesiredNetworkPolicy;
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::sandbox::provider::{SandboxCreateConfig, SandboxProvider, SandboxStatus};

use super::model::{ExpectedFingerprint, ResolveContext, ResolvedSandbox};
use super::networking::{SandboxNetworkingService, TaskIdentityNetworkLease};
use super::runtime_plan::{
    apply_claude_code_sandbox_privacy, apply_sandbox_timezone, generate_runner_token,
    provisioning_config,
};

#[async_trait]
pub(crate) trait PoolSandboxProvisioner: Send + Sync {
    async fn provision(&self, image: &str) -> anyhow::Result<SandboxId>;
}

#[derive(Clone)]
pub struct SandboxPoolService {
    pool: PgPool,
    provider: Arc<dyn SandboxProvider>,
    config: JoySafeterConfig,
    networking: SandboxNetworkingService,
    replenish_notify: Option<Arc<tokio::sync::Notify>>,
}

impl SandboxPoolService {
    pub fn new(
        pool: PgPool,
        provider: Arc<dyn SandboxProvider>,
        config: JoySafeterConfig,
        networking: SandboxNetworkingService,
    ) -> Self {
        Self {
            pool,
            provider,
            config,
            networking,
            replenish_notify: None,
        }
    }

    pub(crate) fn with_replenish_notify(mut self, notify: Arc<tokio::sync::Notify>) -> Self {
        self.replenish_notify = Some(notify);
        self
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

    pub(crate) async fn destroy_unattached_claim(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
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
            &self.networking,
            sandbox.id,
            sandbox.external_id.as_deref(),
            &previous_status,
            reason,
        )
        .await
    }

    #[cfg(test)]
    pub(crate) fn with_networking(mut self, networking: SandboxNetworkingService) -> Self {
        self.networking = networking;
        self
    }

    fn signal_claimed(&self) {
        if let Some(notify) = self.replenish_notify.as_ref() {
            notify.notify_one();
        }
    }

    pub(crate) async fn try_claim(
        &self,
        task_id: TaskId,
        context: &ResolveContext,
    ) -> anyhow::Result<Option<ResolvedSandbox>> {
        let requires_persistent_workspace =
            context.session_id.is_some() && self.config.sandbox_workspace_root.is_some();
        if !self.config.sandbox_pool_enabled
            || !context.expected.env.is_empty()
            || requires_persistent_workspace
            || context.session_id.is_none()
        {
            return Ok(None);
        }

        let Some(sandbox) =
            queries::claim_pool_sandbox(&self.pool, &context.expected.image).await?
        else {
            return Ok(None);
        };
        let Some(external_id) = sandbox.external_id.as_deref() else {
            warn!(sandbox_id = %sandbox.id, "Pooled sandbox has no external_id, destroying");
            let _ = self
                .destroy_unattached_claim(&sandbox, "pooled sandbox without external id")
                .await;
            return Ok(None);
        };
        let session_id = context
            .session_id
            .expect("pool eligibility requires session");
        let attachment = match queries::activate_reserved_pool_sandbox_guarded(
            &self.pool,
            sandbox.id,
            external_id,
            session_id,
            context.project_id,
            &context.expected.to_json(),
            context.runtime_config_generation,
        )
        .await
        {
            Ok(attachment) => attachment,
            Err(error) => {
                return match self
                    .destroy_unattached_claim(&sandbox, "pool activation guard rejection")
                    .await
                {
                    Ok(true) => Err(error.into()),
                    Ok(false) => Err(RuntimeFreshnessError::Conflict(format!(
                        "reserved pool sandbox {} changed before rejected activation cleanup",
                        sandbox.id
                    ))
                    .into()),
                    Err(cleanup_error) => Err(RuntimeFreshnessError::CleanupFailed(format!(
                        "failed to destroy rejected pool sandbox {}: {cleanup_error}",
                        sandbox.id
                    ))
                    .into()),
                };
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
            .patch_claimed_labels(external_id, session_id, context)
            .await
        {
            warn!(sandbox_id = %sandbox.id, external_id, error = %error, "Failed to patch labels for claimed pooled sandbox");
        }

        match self.provider.status(external_id).await {
            Ok(SandboxStatus::Running) => {}
            Ok(SandboxStatus::Stopped) => {
                if let Err(error) = self.provider.start(external_id).await {
                    self.cleanup_attached_claim(
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
                self.cleanup_attached_claim(
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
                self.cleanup_attached_claim(
                    &attachment,
                    "claimed pool sandbox provider status failed",
                )
                .await?;
                return Err(error.context("failed to inspect claimed pool sandbox"));
            }
        }

        if !self.attached_claim_is_current(&attachment).await? {
            return Err(RuntimeFreshnessError::Conflict(format!(
                "attached pool sandbox {} changed during provider activation",
                sandbox.id
            ))
            .into());
        }

        let injection = crate::sandbox::file_injection::FileInjectionContext {
            session_id,
            external_id: external_id.to_string(),
            workspace_path: None,
            runner_capabilities: vec![],
            is_pool_sandbox: true,
        };
        if let Err(error) = crate::sandbox::file_injection::inject_session_files(
            &self.pool,
            &injection,
            self.provider.as_ref(),
        )
        .await
        {
            self.cleanup_attached_claim(&attachment, "pooled session file injection failed")
                .await?;
            return Err(error.context(format!(
                "failed to inject session files into pooled sandbox {} for session {}",
                sandbox.id, session_id
            )));
        }

        if context.is_limited_networking() {
            if let Err(error) = self
                .networking
                .setup_pool_claim(
                    sandbox.id,
                    &context.expected,
                    &context.credentials,
                    context
                        .has_task_identity()
                        .then_some(TaskIdentityNetworkLease {
                            task_id,
                            refresh_after_seconds: context.identity_refresh_after_seconds,
                        }),
                )
                .await
            {
                self.cleanup_attached_claim(&attachment, "pooled sandbox networking setup failed")
                    .await?;
                return Err(error.context(format!(
                    "failed to setup networking for pooled sandbox {}",
                    sandbox.id
                )));
            }
        }

        info!(sandbox_id = %sandbox.id, task_id = %task_id, "Claimed sandbox from warm pool");
        self.signal_claimed();
        Ok(Some(context.resolved(sandbox.id, external_id.to_string())))
    }

    async fn patch_claimed_labels(
        &self,
        external_id: &str,
        session_id: SessionId,
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
        labels.insert("joysafeter.session_id".to_string(), session_id.to_string());
        if let Some(project_id) = context.project_id.as_ref() {
            labels.insert("joysafeter.project_id".to_string(), project_id.to_public());
        }
        self.provider.patch_labels(external_id, &labels).await
    }

    async fn cleanup_attached_claim(
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
        let _ = self.networking.teardown(claim.sandbox_id).await;
        Ok(())
    }

    async fn attached_claim_is_current(
        &self,
        claim: &queries::AttachedPoolSandboxClaim,
    ) -> anyhow::Result<bool> {
        let current = sqlx::query_as::<
            _,
            (
                Option<SessionId>,
                Option<crate::ids::ProjectId>,
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
}

#[async_trait]
impl PoolSandboxProvisioner for SandboxPoolService {
    async fn provision(&self, image: &str) -> anyhow::Result<SandboxId> {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let runner_token = generate_runner_token();

        let mut env = HashMap::new();
        apply_sandbox_timezone(&mut env, &self.config.sandbox_timezone);
        env.insert(
            "JOYSAFETER_SANDBOX_ID".to_string(),
            sandbox_id.as_uuid().to_string(),
        );
        env.insert("JOYSAFETER_RUNNER_TOKEN".to_string(), runner_token.clone());
        apply_claude_code_sandbox_privacy(&mut env);
        if !self.config.sandbox_timezone.trim().is_empty() {
            env.insert("TZ".to_string(), self.config.sandbox_timezone.clone());
        }
        env.insert(
            "JOYSAFETER_ORCHESTRATOR_URL".to_string(),
            self.provider.orchestrator_url(self.config.grpc_port),
        );

        let engine_kind = self.engine_kind_for_image(image);
        let create_config = SandboxCreateConfig {
            sandbox_id,
            image: image.to_string(),
            env,
            labels: [
                ("joysafeter".to_string(), "true".to_string()),
                ("joysafeter.managed".to_string(), "true".to_string()),
                (
                    "joysafeter.sandbox_id".to_string(),
                    sandbox_id.as_uuid().to_string(),
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
            workspace_path: None,
            memory_mounts: vec![],
            mounts: vec![],
        };

        let expected = ExpectedFingerprint {
            image: image.to_string(),
            engine_kind,
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

        let external_id = self.provider.create(&create_config).await?;
        let db_result = queries::create_sandbox(
            &self.pool,
            sandbox_id,
            &external_id,
            self.config.sandbox_provider.as_str(),
            image,
            None,
            None,
            create_config.workspace_path.as_deref(),
            Some(&sandbox_config),
        )
        .await;

        if let Err(error) = db_result {
            warn!(sandbox_id = %sandbox_id, "DB insert failed for pool sandbox, destroying container");
            let _ = self.provider.destroy(&external_id).await;
            return Err(error.into());
        }

        if !queries::mark_pool_sandbox_ready(&self.pool, sandbox_id).await? {
            warn!(sandbox_id = %sandbox_id, "Warm pool sandbox changed state before ready finalization");
            match queries::get_sandbox(&self.pool, sandbox_id).await? {
                Some(ref sandbox)
                    if sandbox.external_id.as_deref() == Some(external_id.as_str()) =>
                {
                    if let Err(cleanup_error) = self
                        .destroy_unattached_claim(sandbox, "pool ready finalization failure")
                        .await
                    {
                        warn!(sandbox_id = %sandbox_id, error = %cleanup_error, "Failed to cleanup warm-pool sandbox after ready finalization failure");
                    }
                }
                Some(_) => {
                    warn!(sandbox_id = %sandbox_id, "Skipped warm-pool provider destroy because external id changed before cleanup")
                }
                None => {
                    warn!(sandbox_id = %sandbox_id, "Skipped warm-pool provider destroy because DB row disappeared before cleanup")
                }
            }
            anyhow::bail!("warm pool sandbox {sandbox_id} changed state before ready finalization");
        }

        info!(sandbox_id = %sandbox_id, image, "Provisioned pool sandbox");
        Ok(sandbox_id)
    }
}
