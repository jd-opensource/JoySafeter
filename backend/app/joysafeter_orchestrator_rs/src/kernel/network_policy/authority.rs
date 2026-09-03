//! Application handler for work executed by the elected xDS authority.

use async_trait::async_trait;

use super::service::NetworkPolicyService;
use super::NetworkPolicyRequest;
#[cfg(test)]
use crate::ids::SandboxId;
use crate::xds::authority::{MutationAuthorityGuard, RecoveryAuthorityGuard};
use crate::xds::authority_worker::AuthorityWork;

pub struct NetworkPolicyAuthorityHandler {
    service: NetworkPolicyService,
}

impl NetworkPolicyAuthorityHandler {
    pub fn new(service: NetworkPolicyService) -> Self {
        Self { service }
    }
}

#[async_trait]
impl AuthorityWork<NetworkPolicyRequest> for NetworkPolicyAuthorityHandler {
    async fn recover(&self, guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
        self.service.recover(guard).await
    }

    async fn reconcile_inventory(&self, guard: &MutationAuthorityGuard) -> anyhow::Result<usize> {
        self.service.reconcile_inventory(guard).await
    }

    async fn apply(
        &self,
        request: NetworkPolicyRequest,
        guard: &MutationAuthorityGuard,
    ) -> anyhow::Result<()> {
        self.service.apply_request(request, guard).await
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use super::*;
    use crate::kernel::network_policy::material::NetworkPolicyMaterialResolver;
    use crate::kernel::network_policy::ports::NetworkPolicyRuntime;
    use crate::kernel::network_policy::service::NetworkPolicyService;
    use crate::kernel::network_policy::DesiredNetworkPolicy;
    use crate::xds::authority::XdsAuthority;
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

        async fn recover(
            &self,
            _authority_epoch: u64,
            entries: Vec<super::super::ports::NetworkPolicyRecoveryEntry>,
        ) -> anyhow::Result<super::super::ports::NetworkPolicyRecoveryReport> {
            Ok(super::super::ports::NetworkPolicyRecoveryReport {
                ready: entries
                    .into_iter()
                    .map(|entry| (entry.sandbox_id, entry.generation))
                    .collect(),
                ..super::super::ports::NetworkPolicyRecoveryReport::default()
            })
        }

        async fn apply(
            &self,
            _request: super::super::ports::NetworkPolicyApplyRequest,
            _policy: super::super::envoy_model::SandboxEgressPolicy,
        ) -> anyhow::Result<()> {
            Ok(())
        }

        async fn remove(
            &self,
            _sandbox_id: SandboxId,
            _generation: Option<&super::super::NetworkPolicyGeneration>,
        ) -> anyhow::Result<()> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    #[tokio::test]
    async fn revoked_authority_cannot_remove_networking() {
        let authority = XdsAuthority::managed();
        let recovery = authority.begin_staging().expect("begin staging");
        authority
            .begin_recovery_serving(&recovery)
            .expect("begin recovery serving");
        authority.mark_ready(&recovery).expect("mark ready");
        let guard = authority.mutation_guard().expect("mutation guard");
        authority.revoke().expect("revoke authority");
        let runtime = Arc::new(TeardownRecordingRuntime {
            calls: AtomicUsize::new(0),
        });
        let pool = PgPoolOptions::new()
            .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
            .expect("lazy pool");
        let service = NetworkPolicyService::managed(
            pool,
            runtime.clone(),
            Arc::new(NeverMaterialResolver),
            None,
            authority.clone(),
        );
        let handler = NetworkPolicyAuthorityHandler::new(service);

        let error = handler
            .apply(
                NetworkPolicyRequest::remove(
                    SandboxId::new(),
                    super::super::NetworkPolicyGeneration {
                        policy_hash: "hash".to_string(),
                        policy_version: 1,
                    },
                ),
                &guard,
            )
            .await
            .expect_err("revoked authority must be fenced");

        assert!(error.to_string().contains("authority changed"));
        assert_eq!(runtime.calls.load(Ordering::SeqCst), 0);
    }
}
