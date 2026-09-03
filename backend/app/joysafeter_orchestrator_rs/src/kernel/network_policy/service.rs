use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;

use super::application::NetworkingReconcileOutcome;
use super::envoy_model::SandboxCredentials;
use super::material::NetworkPolicyMaterialResolver;
use super::ports::{NetworkPolicyRequestQueue, NetworkPolicyRuntime};
use super::{NetworkPolicyAction, NetworkPolicyGeneration, NetworkPolicyRequest};
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::SandboxId;
use crate::xds::authority::{MutationAuthorityGuard, RecoveryAuthorityGuard, XdsAuthority};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyCapability {
    Managed,
    Unsupported,
}

#[derive(Clone)]
struct ManagedNetworkPolicy {
    runtime: Arc<dyn NetworkPolicyRuntime>,
    material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    authority: XdsAuthority,
}

#[derive(Clone)]
pub struct NetworkPolicyService {
    pool: PgPool,
    managed: Option<ManagedNetworkPolicy>,
}

impl NetworkPolicyService {
    pub fn managed(
        pool: PgPool,
        runtime: Arc<dyn NetworkPolicyRuntime>,
        material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
        queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
        authority: XdsAuthority,
    ) -> Self {
        Self {
            pool,
            managed: Some(ManagedNetworkPolicy {
                runtime,
                material_resolver,
                queue,
                authority,
            }),
        }
    }

    pub fn unsupported(pool: PgPool) -> Self {
        Self {
            pool,
            managed: None,
        }
    }

    pub fn capability(&self) -> NetworkPolicyCapability {
        if self.managed.is_some() {
            NetworkPolicyCapability::Managed
        } else {
            NetworkPolicyCapability::Unsupported
        }
    }

    pub fn supports_ephemeral_credentials(&self) -> bool {
        self.managed.as_ref().is_some_and(|managed| {
            managed.queue.is_none() && managed.runtime.supports_ephemeral_credentials()
        })
    }

    pub fn can_reconcile_as_authority(&self) -> bool {
        self.managed
            .as_ref()
            .is_some_and(|managed| managed.authority.mutation_guard().is_some())
    }

    pub async fn initialize(&self) -> anyhow::Result<NetworkPolicyCapability> {
        let Some(managed) = self.managed.as_ref() else {
            return Ok(NetworkPolicyCapability::Unsupported);
        };
        managed.runtime.initialize().await?;
        Ok(NetworkPolicyCapability::Managed)
    }

    pub async fn ensure_ready(
        &self,
        sandbox_id: SandboxId,
        generation: &NetworkPolicyGeneration,
        timeout: Duration,
    ) -> anyhow::Result<queries::NetworkPolicyAckOutcome> {
        let managed = self.require_managed("ensure limited-network policy readiness")?;
        super::application::ensure_ready(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            managed.queue.as_deref(),
            &managed.authority,
            sandbox_id,
            generation,
            timeout,
        )
        .await
    }

    pub async fn apply_with_credentials(
        &self,
        sandbox_id: SandboxId,
        generation: &NetworkPolicyGeneration,
        credentials: SandboxCredentials,
    ) -> anyhow::Result<NetworkingReconcileOutcome> {
        let managed = self.require_managed("apply task-scoped network policy")?;
        if managed.queue.is_some() || !managed.runtime.supports_ephemeral_credentials() {
            anyhow::bail!(
                "task-scoped Agent Identity requires a direct-xDS runtime with secure ephemeral credential delivery"
            );
        }
        let _application_lock = managed.authority.lock_application().await;
        let guard = managed
            .authority
            .mutation_guard()
            .ok_or_else(|| anyhow::anyhow!("local xDS authority is not ready"))?;
        super::application::apply_generation_with_credentials_as_authority(
            &self.pool,
            managed.runtime.as_ref(),
            sandbox_id,
            generation,
            credentials,
            &guard,
        )
        .await
    }

    pub async fn reconcile(
        &self,
        sandbox: &JoySafeterSandbox,
    ) -> anyhow::Result<NetworkingReconcileOutcome> {
        let Some(managed) = self.managed.as_ref() else {
            if sandbox_requires_limited_networking(sandbox) {
                anyhow::bail!("limited networking is unsupported by the selected sandbox runtime");
            }
            return Ok(NetworkingReconcileOutcome::NotLimited);
        };
        super::application::request_reconcile(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            sandbox,
            managed.queue.as_deref(),
            &managed.authority,
        )
        .await
    }

    pub async fn reconcile_as_authority(
        &self,
        sandbox: &JoySafeterSandbox,
    ) -> anyhow::Result<NetworkingReconcileOutcome> {
        let managed = self.require_managed("reconcile limited networking as authority")?;
        let guard = managed
            .authority
            .mutation_guard()
            .ok_or_else(|| anyhow::anyhow!("local xDS authority is not ready"))?;
        let _application_lock = managed.authority.lock_application().await;
        guard.validate()?;
        super::application::reconcile_as_authority(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            sandbox,
            &guard,
        )
        .await
    }

    /// Replace a task-scoped Agent Identity policy with durable base material.
    /// The caller deliberately keeps the identity lease persisted until this
    /// method returns, so recovery remains fail-closed if delivery is lost.
    pub async fn reconcile_base_as_authority(
        &self,
        sandbox: &JoySafeterSandbox,
    ) -> anyhow::Result<NetworkingReconcileOutcome> {
        let managed = self.require_managed("restore the base limited-network policy")?;
        if managed.queue.is_some() || !managed.runtime.supports_ephemeral_credentials() {
            anyhow::bail!(
                "task-scoped Agent Identity cleanup requires a direct runtime with secure ephemeral credential delivery"
            );
        }
        let _application_lock = managed.authority.lock_application().await;
        let guard = managed
            .authority
            .mutation_guard()
            .ok_or_else(|| anyhow::anyhow!("local network-policy authority is not ready"))?;
        super::application::reconcile_base_as_authority(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            sandbox,
            &guard,
        )
        .await
    }

    pub async fn recover(&self, guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
        let managed = self.require_managed("recover limited networking")?;
        super::recovery::recover_as_authority(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            guard,
        )
        .await
    }

    pub async fn reconcile_inventory(
        &self,
        guard: &MutationAuthorityGuard,
    ) -> anyhow::Result<usize> {
        let managed = self.require_managed("reconcile network-policy inventory")?;
        if guard.validate().is_err() {
            anyhow::bail!("xDS authority changed before inventory reconciliation");
        }
        let live_sandbox_ids = queries::load_recovery_inventory(&self.pool)
            .await?
            .into_iter()
            .filter(sandbox_requires_limited_networking)
            .map(|sandbox| sandbox.id)
            .collect::<HashSet<_>>();
        if guard.validate().is_err() {
            anyhow::bail!("xDS authority changed before inventory pruning");
        }
        managed.runtime.prune(&live_sandbox_ids).await
    }

    pub async fn recover_runtime_if_required(&self) -> anyhow::Result<usize> {
        let managed = self.require_managed("recover remote network-policy runtime")?;
        if !managed.runtime.full_recovery_required().await? {
            return Ok(0);
        }
        let guard = managed
            .authority
            .mutation_guard()
            .ok_or_else(|| anyhow::anyhow!("local network-policy authority is not ready"))?;
        let _application_lock = managed.authority.lock_application().await;
        guard.validate()?;
        super::recovery::resync_as_authority(
            &self.pool,
            managed.runtime.as_ref(),
            managed.material_resolver.as_ref(),
            &guard,
        )
        .await
    }

    pub async fn apply_request(
        &self,
        request: NetworkPolicyRequest,
        guard: &MutationAuthorityGuard,
    ) -> anyhow::Result<()> {
        let managed = self.require_managed("apply network-policy authority request")?;
        if guard.validate().is_err() {
            anyhow::bail!("xDS authority changed before request application");
        }
        match request.action {
            NetworkPolicyAction::Reconcile => {
                let generation = request
                    .generation
                    .ok_or_else(|| anyhow::anyhow!("reconcile request is missing generation"))?;
                super::application::apply_generation_as_authority(
                    &self.pool,
                    managed.runtime.as_ref(),
                    managed.material_resolver.as_ref(),
                    request.sandbox_id,
                    &generation,
                    guard,
                )
                .await?;
            }
            NetworkPolicyAction::Remove => {
                let generation = request
                    .generation
                    .ok_or_else(|| anyhow::anyhow!("remove request is missing generation"))?;
                if !queries::network_policy_removal_is_current(&self.pool, request.sandbox_id)
                    .await?
                {
                    anyhow::bail!(
                        "stale xDS remove request for live limited-networking sandbox {}",
                        request.sandbox_id
                    );
                }
                if guard.validate().is_err() {
                    anyhow::bail!("xDS authority changed before networking removal");
                }
                managed
                    .runtime
                    .remove(request.sandbox_id, Some(&generation))
                    .await?;
                queries::mark_generation_removed(&self.pool, request.sandbox_id, &generation)
                    .await?;
            }
        }
        Ok(())
    }

    pub async fn teardown(&self, sandbox_id: SandboxId) -> anyhow::Result<NetworkPolicyCapability> {
        let Some(managed) = self.managed.as_ref() else {
            return Ok(NetworkPolicyCapability::Unsupported);
        };
        let generation = queries::prepare_generation_removal(&self.pool, sandbox_id).await?;
        match (managed.queue.as_ref(), generation.as_ref()) {
            (Some(queue), Some(generation)) => {
                queue
                    .publish(NetworkPolicyRequest::remove(sandbox_id, generation.clone()))
                    .await?;
            }
            (None, generation) => {
                managed.runtime.remove(sandbox_id, generation).await?;
                if let Some(generation) = generation {
                    queries::mark_generation_removed(&self.pool, sandbox_id, generation).await?;
                }
            }
            (Some(_), None) => {}
        }
        Ok(NetworkPolicyCapability::Managed)
    }

    fn require_managed(&self, operation: &str) -> anyhow::Result<&ManagedNetworkPolicy> {
        self.managed.as_ref().ok_or_else(|| {
            anyhow::anyhow!("network-policy capability is unsupported; cannot {operation}")
        })
    }

    #[cfg(test)]
    pub(crate) fn test_fixture(pool: PgPool) -> Self {
        Self::managed(
            pool,
            Arc::new(TestNetworkPolicyRuntime),
            Arc::new(super::material::RejectingNetworkPolicyMaterialResolver),
            None,
            XdsAuthority::standalone(),
        )
    }

    #[cfg(test)]
    pub(crate) fn with_test_runtime(mut self, runtime: Arc<dyn NetworkPolicyRuntime>) -> Self {
        self.managed.as_mut().expect("managed test fixture").runtime = runtime;
        self
    }

    #[cfg(test)]
    pub(crate) fn with_test_material_resolver(
        mut self,
        resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    ) -> Self {
        self.managed
            .as_mut()
            .expect("managed test fixture")
            .material_resolver = resolver;
        self
    }

    #[cfg(test)]
    pub(crate) fn with_test_control(
        mut self,
        authority: XdsAuthority,
        queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    ) -> Self {
        let managed = self.managed.as_mut().expect("managed test fixture");
        managed.authority = authority;
        managed.queue = queue;
        self
    }
}

fn sandbox_requires_limited_networking(sandbox: &JoySafeterSandbox) -> bool {
    sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"))
        .and_then(|networking| networking.get("type"))
        .and_then(serde_json::Value::as_str)
        == Some("limited")
}

#[cfg(test)]
struct TestNetworkPolicyRuntime;

#[cfg(test)]
#[async_trait::async_trait]
impl NetworkPolicyRuntime for TestNetworkPolicyRuntime {
    async fn initialize(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn prune(&self, _live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        Ok(0)
    }

    async fn recover(
        &self,
        _authority_epoch: u64,
        entries: Vec<super::ports::NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<super::ports::NetworkPolicyRecoveryReport> {
        Ok(super::ports::NetworkPolicyRecoveryReport {
            ready: entries
                .into_iter()
                .map(|entry| (entry.sandbox_id, entry.generation))
                .collect(),
            ..super::ports::NetworkPolicyRecoveryReport::default()
        })
    }

    async fn apply(
        &self,
        _request: super::ports::NetworkPolicyApplyRequest,
        _policy: super::envoy_model::SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn remove(
        &self,
        _sandbox_id: SandboxId,
        _generation: Option<&super::NetworkPolicyGeneration>,
    ) -> anyhow::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use sqlx::postgres::PgPoolOptions;

    use super::{NetworkPolicyCapability, NetworkPolicyService};
    use crate::ids::SandboxId;

    #[tokio::test]
    async fn unsupported_policy_service_reports_capability_instead_of_fake_success() {
        let pool = PgPoolOptions::new()
            .connect_lazy("postgresql://postgres:postgres@localhost/joysafeter")
            .expect("lazy pool");
        let service = NetworkPolicyService::unsupported(pool);

        assert_eq!(
            service.initialize().await.expect("capability result"),
            NetworkPolicyCapability::Unsupported
        );
        assert_eq!(
            service
                .teardown(SandboxId::new())
                .await
                .expect("capability result"),
            NetworkPolicyCapability::Unsupported
        );
    }
}
