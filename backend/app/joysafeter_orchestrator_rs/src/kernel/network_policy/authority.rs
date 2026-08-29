//! Application handler for work executed by the elected xDS authority.

use std::collections::HashSet;
use std::sync::Arc;

use async_trait::async_trait;
use sqlx::PgPool;

use super::application::apply_generation_as_authority;
use super::material::NetworkPolicyMaterialResolver;
use super::ports::NetworkPolicyRuntime;
use super::{NetworkPolicyAction, NetworkPolicyRequest};
use crate::db::queries;
#[cfg(test)]
use crate::ids::SandboxId;
use crate::xds::authority::XdsAuthorityGuard;
use crate::xds::authority_worker::AuthorityWork;

pub struct NetworkPolicyAuthorityHandler {
    pool: PgPool,
    runtime: Arc<dyn NetworkPolicyRuntime>,
    material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
}

impl NetworkPolicyAuthorityHandler {
    pub fn new(
        pool: PgPool,
        runtime: Arc<dyn NetworkPolicyRuntime>,
        material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    ) -> Self {
        Self {
            pool,
            runtime,
            material_resolver,
        }
    }
}

#[async_trait]
impl AuthorityWork<NetworkPolicyRequest> for NetworkPolicyAuthorityHandler {
    async fn recover(&self, guard: &XdsAuthorityGuard) -> anyhow::Result<usize> {
        super::recovery::recover_as_authority(
            &self.pool,
            self.runtime.as_ref(),
            self.material_resolver.as_ref(),
            guard,
        )
        .await
    }

    async fn reconcile_inventory(&self, guard: &XdsAuthorityGuard) -> anyhow::Result<usize> {
        if !guard.is_current() {
            anyhow::bail!("xDS authority changed before inventory reconciliation");
        }
        let live_sandbox_ids = queries::list_live_sandboxes_for_recovery(&self.pool)
            .await?
            .into_iter()
            .filter(is_limited_networking)
            .map(|sandbox| sandbox.id)
            .collect::<HashSet<_>>();
        if !guard.is_current() {
            anyhow::bail!("xDS authority changed before inventory pruning");
        }
        self.runtime.prune(&live_sandbox_ids).await
    }

    async fn apply(
        &self,
        request: NetworkPolicyRequest,
        guard: &XdsAuthorityGuard,
    ) -> anyhow::Result<()> {
        if !guard.is_current() {
            anyhow::bail!("xDS authority changed before request application");
        }
        match request.action {
            NetworkPolicyAction::Reconcile => {
                let generation = request
                    .generation
                    .ok_or_else(|| anyhow::anyhow!("reconcile request is missing generation"))?;
                apply_generation_as_authority(
                    &self.pool,
                    self.runtime.as_ref(),
                    self.material_resolver.as_ref(),
                    request.sandbox_id,
                    &generation,
                    guard,
                )
                .await?;
            }
            NetworkPolicyAction::Remove => {
                if !queries::network_policy_removal_is_current(&self.pool, request.sandbox_id)
                    .await?
                {
                    anyhow::bail!(
                        "stale xDS remove request for live limited-networking sandbox {}",
                        request.sandbox_id
                    );
                }
                if !guard.is_current() {
                    anyhow::bail!("xDS authority changed before networking removal");
                }
                self.runtime.remove(request.sandbox_id).await?;
            }
        }
        Ok(())
    }
}

fn is_limited_networking(sandbox: &crate::db::models::JoySafeterSandbox) -> bool {
    sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"))
        .and_then(|networking| networking.get("type"))
        .and_then(|kind| kind.as_str())
        == Some("limited")
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;
    use crate::kernel::network_policy::DesiredNetworkPolicy;
    use crate::xds::authority::XdsAuthorityState;
    use sqlx::postgres::PgPoolOptions;

    struct NeverMaterialResolver;

    #[async_trait]
    impl NetworkPolicyMaterialResolver for NeverMaterialResolver {
        async fn resolve(&self, _sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
            panic!("remove requests must not resolve policy material")
        }
    }

    struct TeardownRecordingRuntime {
        calls: AtomicUsize,
    }

    #[async_trait]
    impl NetworkPolicyRuntime for TeardownRecordingRuntime {
        async fn initialize(&self) -> anyhow::Result<()> {
            Ok(())
        }

        async fn prune(&self, _live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn apply(
            &self,
            _sandbox_id: SandboxId,
            _policy: super::super::envoy_model::SandboxEgressPolicy,
        ) -> anyhow::Result<()> {
            Ok(())
        }

        async fn remove(&self, _sandbox_id: SandboxId) -> anyhow::Result<()> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    #[tokio::test]
    async fn revoked_authority_cannot_remove_networking() {
        let authority = XdsAuthorityState::managed();
        let guard = authority.advertise();
        assert!(authority.mark_ready(&guard));
        authority.revoke();
        let runtime = Arc::new(TeardownRecordingRuntime {
            calls: AtomicUsize::new(0),
        });
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
            .expect("lazy pool");
        let handler = NetworkPolicyAuthorityHandler::new(
            pool,
            runtime.clone(),
            Arc::new(NeverMaterialResolver),
        );

        let error = handler
            .apply(NetworkPolicyRequest::remove(SandboxId::new()), &guard)
            .await
            .expect_err("revoked authority must be fenced");

        assert!(error.to_string().contains("authority changed"));
        assert_eq!(runtime.calls.load(Ordering::SeqCst), 0);
    }
}
