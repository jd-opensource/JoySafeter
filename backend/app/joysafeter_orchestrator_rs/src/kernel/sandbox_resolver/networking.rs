use std::sync::Arc;

use anyhow::Context;
use async_trait::async_trait;
use tracing::{debug, info};

use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::{SandboxId, TaskId};
use crate::kernel::network_policy::application::NetworkingReconcileOutcome;
use crate::kernel::network_policy::envoy_model::SandboxCredentials;
use crate::kernel::network_policy::service::NetworkPolicyService;
use crate::kernel::network_policy::NetworkPolicyGeneration;
use crate::kernel::sandbox_lifecycle::SandboxNetworkCleanup;

use super::identity_policy::identity_lease_metadata;
use super::model::ExpectedFingerprint;

#[derive(Debug, Clone, Copy)]
pub(crate) struct TaskIdentityNetworkLease {
    pub(crate) task_id: TaskId,
    pub(crate) refresh_after_seconds: Option<u64>,
}

pub(crate) struct PreparedSandboxNetworking<'a> {
    pub(crate) credentials: &'a SandboxCredentials,
    pub(crate) identity_lease: Option<TaskIdentityNetworkLease>,
    pub(crate) proxy_auth_token: Option<String>,
}

#[derive(Clone)]
pub struct SandboxNetworkingService {
    pool: sqlx::PgPool,
    policy: NetworkPolicyService,
    ready_generations: Arc<dashmap::DashMap<SandboxId, String>>,
}

impl SandboxNetworkingService {
    pub fn new(pool: sqlx::PgPool, policy: NetworkPolicyService) -> Self {
        Self {
            pool,
            policy,
            ready_generations: Arc::new(dashmap::DashMap::new()),
        }
    }

    #[cfg(test)]
    pub(crate) fn test_fixture(pool: sqlx::PgPool) -> Self {
        Self::new(pool.clone(), NetworkPolicyService::test_fixture(pool))
    }

    #[cfg(test)]
    pub(crate) fn map_policy(
        mut self,
        transform: impl FnOnce(NetworkPolicyService) -> NetworkPolicyService,
    ) -> Self {
        self.policy = transform(self.policy);
        self
    }

    #[cfg(test)]
    pub(crate) fn policy(&self) -> NetworkPolicyService {
        self.policy.clone()
    }

    pub(crate) async fn apply_prepared(
        &self,
        sandbox_id: SandboxId,
        generation: &NetworkPolicyGeneration,
        input: PreparedSandboxNetworking<'_>,
    ) -> anyhow::Result<()> {
        if let Some(identity_lease) = input.identity_lease {
            let mut credentials = input.credentials.clone();
            credentials.proxy_auth_token = input.proxy_auth_token;
            self.policy
                .apply_with_credentials(sandbox_id, generation, credentials)
                .await?;

            let lease = identity_lease_metadata(
                identity_lease.task_id,
                identity_lease.refresh_after_seconds,
            );
            if !queries::merge_sandbox_config(
                &self.pool,
                sandbox_id,
                &serde_json::json!({"agent_identity_lease": lease}),
            )
            .await?
            {
                anyhow::bail!("sandbox {sandbox_id} disappeared before identity lease persistence");
            }
        } else {
            self.policy
                .ensure_ready(
                    sandbox_id,
                    generation,
                    crate::kernel::network_policy::application::POLICY_APPLY_TIMEOUT,
                )
                .await?;
        }

        self.remember_ready(sandbox_id, generation.policy_hash.clone());
        Ok(())
    }

    pub(crate) fn supports_ephemeral_credentials(&self) -> bool {
        self.policy.supports_ephemeral_credentials()
    }

    pub(crate) async fn refresh_reused(
        &self,
        sandbox: &JoySafeterSandbox,
        expected: &ExpectedFingerprint,
        credentials: &SandboxCredentials,
        identity_lease: Option<TaskIdentityNetworkLease>,
        proxy_auth_token: Option<String>,
    ) -> anyhow::Result<()> {
        if sandbox.networking_status == "ready"
            && sandbox.networking_policy_hash.as_deref()
                == Some(expected.egress_policy_hash.as_str())
            && self
                .ready_generations
                .get(&sandbox.id)
                .is_some_and(|hash| hash.value() == &expected.egress_policy_hash)
        {
            debug!(sandbox_id = %sandbox.id, "Reusing ready Envoy policy without refresh");
            return Ok(());
        }

        let generation =
            queries::prepare_generation(&self.pool, sandbox.id, &expected.egress_policy_hash)
                .await?
                .into_generation();
        self.apply_prepared(
            sandbox.id,
            &generation,
            PreparedSandboxNetworking {
                credentials,
                identity_lease,
                proxy_auth_token,
            },
        )
        .await
        .with_context(|| format!("failed to refresh Envoy policy for sandbox {}", sandbox.id))?;

        queries::merge_sandbox_config(
            &self.pool,
            sandbox.id,
            &serde_json::json!({"fingerprint": expected.to_json()}),
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

    pub(crate) async fn setup_pool_claim(
        &self,
        sandbox_id: SandboxId,
        expected: &ExpectedFingerprint,
        credentials: &SandboxCredentials,
        identity_lease: Option<TaskIdentityNetworkLease>,
    ) -> anyhow::Result<()> {
        let generation =
            queries::prepare_generation(&self.pool, sandbox_id, &expected.egress_policy_hash)
                .await?
                .into_generation();
        self.apply_prepared(
            sandbox_id,
            &generation,
            PreparedSandboxNetworking {
                credentials,
                identity_lease,
                proxy_auth_token: None,
            },
        )
        .await
        .with_context(|| {
            format!("failed to setup Envoy policy for pool-claimed sandbox {sandbox_id}")
        })?;
        info!(
            sandbox_id = %sandbox_id,
            policy_hash = %expected.egress_policy_hash,
            "Setup networking for pool-claimed sandbox"
        );
        Ok(())
    }

    pub(crate) async fn reconcile_base_policy(
        &self,
        sandbox: &JoySafeterSandbox,
    ) -> anyhow::Result<String> {
        match self.policy.reconcile_base_as_authority(sandbox).await? {
            NetworkingReconcileOutcome::Refreshed { policy_hash }
            | NetworkingReconcileOutcome::AlreadyReady { policy_hash } => Ok(policy_hash),
            NetworkingReconcileOutcome::NotLimited => {
                anyhow::bail!("Agent Identity lease exists on a non-limited sandbox")
            }
        }
    }

    pub(crate) fn remember_ready(&self, sandbox_id: SandboxId, policy_hash: String) {
        self.ready_generations.insert(sandbox_id, policy_hash);
    }

    pub(crate) fn forget_ready(&self, sandbox_id: SandboxId) {
        self.ready_generations.remove(&sandbox_id);
    }

    pub(crate) async fn teardown(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.forget_ready(sandbox_id);
        self.policy.teardown(sandbox_id).await.map(|_| ())
    }
}

#[async_trait]
impl SandboxNetworkCleanup for SandboxNetworkingService {
    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.teardown(sandbox_id).await
    }
}
