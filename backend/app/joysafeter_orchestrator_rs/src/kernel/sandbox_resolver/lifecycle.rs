use std::sync::Arc;

use sqlx::PgPool;
use tracing::debug;

use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::SandboxId;
use crate::kernel::network_policy::NetworkPolicyGeneration;
use crate::kernel::runtime_freshness::RuntimeFreshnessError;
use crate::sandbox::provider::{SandboxProvider, SandboxStatus};

use super::model::ResolveContext;
use super::networking::SandboxNetworkingService;

#[derive(Clone)]
pub struct SandboxLifecycleService {
    pool: PgPool,
    provider: Arc<dyn SandboxProvider>,
    networking: SandboxNetworkingService,
}

impl SandboxLifecycleService {
    pub fn new(
        pool: PgPool,
        provider: Arc<dyn SandboxProvider>,
        networking: SandboxNetworkingService,
    ) -> Self {
        Self {
            pool,
            provider,
            networking,
        }
    }

    #[cfg(test)]
    pub(crate) fn with_networking(mut self, networking: SandboxNetworkingService) -> Self {
        self.networking = networking;
        self
    }

    pub(crate) async fn cleanup_rejected_create(
        &self,
        sandbox_id: SandboxId,
        external_id: &str,
        generation: Option<&NetworkPolicyGeneration>,
    ) -> anyhow::Result<bool> {
        self.networking.forget_ready(sandbox_id);
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
                &self.networking,
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
                &self.networking,
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
            &self.networking,
            sandbox_id,
            "creating",
            Some(external_id),
            "rejected new sandbox",
        )
        .await
    }

    pub(crate) async fn destroy_observed(
        &self,
        sandbox: &JoySafeterSandbox,
        reason: &str,
    ) -> anyhow::Result<bool> {
        self.destroy_observed_state(
            sandbox.id,
            &sandbox.status,
            sandbox.external_id.as_deref(),
            reason,
        )
        .await
    }

    pub(crate) async fn destroy_observed_state(
        &self,
        sandbox_id: SandboxId,
        observed_status: &str,
        external_id: Option<&str>,
        reason: &str,
    ) -> anyhow::Result<bool> {
        crate::kernel::sandbox_lifecycle::destroy_observed_sandbox(
            &self.pool,
            &self.provider,
            &self.networking,
            sandbox_id,
            observed_status,
            external_id,
            reason,
        )
        .await
    }

    pub(crate) async fn restart_stopped(
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
                if let Some(status) = self.active_status(sandbox_id, external_id).await? {
                    debug!(sandbox_id = %sandbox_id, status, "Stopped sandbox became active before restart claim");
                    return Ok(true);
                }
                return Err(error.into());
            }
            Err(error) => return Err(error.into()),
        };

        match self.provider.status(external_id).await {
            Ok(SandboxStatus::NotFound | SandboxStatus::Unknown(_)) => {
                self.compensate_failed_restart(sandbox_id, external_id, &claim)
                    .await?;
                debug!(sandbox_id = %sandbox_id, "Cannot restart stopped sandbox because runtime is absent");
                return Ok(false);
            }
            Ok(SandboxStatus::Running | SandboxStatus::Stopped) => {}
            Err(_) => {
                self.compensate_failed_restart(sandbox_id, external_id, &claim)
                    .await?;
                return Ok(false);
            }
        }

        if self.provider.start(external_id).await.is_err() {
            self.compensate_failed_restart(sandbox_id, external_id, &claim)
                .await?;
            return Ok(false);
        }

        if let Some(status) = self.active_status(sandbox_id, external_id).await? {
            debug!(sandbox_id = %sandbox_id, status, "Restarted stopped sandbox remains active after provider start");
            return Ok(true);
        }

        anyhow::bail!("stopped sandbox {sandbox_id} changed state during restart")
    }

    async fn compensate_failed_restart(
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

    pub(crate) async fn active_status(
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
}
