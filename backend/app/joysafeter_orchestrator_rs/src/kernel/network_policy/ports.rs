use async_trait::async_trait;
use std::collections::HashSet;

use super::envoy_model::SandboxEgressPolicy;
use super::request::NetworkPolicyRequest;
use crate::ids::SandboxId;

#[async_trait]
pub trait NetworkPolicyRuntime: Send + Sync {
    async fn initialize(&self) -> anyhow::Result<()>;

    async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize>;

    async fn apply(&self, sandbox_id: SandboxId, policy: SandboxEgressPolicy)
        -> anyhow::Result<()>;

    async fn remove(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;
}

/// Durable wakeup channel for the elected xDS authority.
///
/// PostgreSQL remains authoritative for desired policy and generation. Queue
/// messages may be duplicated or missed; authority recovery reconciles from DB.
#[async_trait]
pub trait NetworkPolicyRequestQueue: Send + Sync + 'static {
    async fn publish(&self, request: NetworkPolicyRequest) -> anyhow::Result<()>;
}

pub struct NoopNetworkPolicyRuntime;

#[async_trait]
impl NetworkPolicyRuntime for NoopNetworkPolicyRuntime {
    async fn initialize(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn prune(&self, _live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        Ok(0)
    }

    async fn apply(
        &self,
        _sandbox_id: SandboxId,
        _policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn remove(&self, _sandbox_id: SandboxId) -> anyhow::Result<()> {
        Ok(())
    }
}
