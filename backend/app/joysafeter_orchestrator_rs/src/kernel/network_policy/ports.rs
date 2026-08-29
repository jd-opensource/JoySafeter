use async_trait::async_trait;
use std::collections::HashSet;

use super::envoy_model::SandboxEgressPolicy;
use super::request::NetworkPolicyRequest;
use super::NetworkPolicyGeneration;
use crate::ids::SandboxId;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyApplyRequest {
    pub authority_epoch: u64,
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
}

#[derive(Clone)]
pub struct NetworkPolicyRecoveryEntry {
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
    pub policy: SandboxEgressPolicy,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyRecoveryFailure {
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
    pub reason: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NetworkPolicyRecoveryReport {
    pub ready: Vec<(SandboxId, NetworkPolicyGeneration)>,
    pub deferred: Vec<SandboxId>,
    pub failed: Vec<NetworkPolicyRecoveryFailure>,
}

#[async_trait]
pub trait NetworkPolicyRuntime: Send + Sync {
    async fn initialize(&self) -> anyhow::Result<()>;

    async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize>;

    async fn recover(
        &self,
        authority_epoch: u64,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport>;

    async fn apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()>;

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

    async fn recover(
        &self,
        _authority_epoch: u64,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport> {
        Ok(NetworkPolicyRecoveryReport {
            ready: entries
                .into_iter()
                .map(|entry| (entry.sandbox_id, entry.generation))
                .collect(),
            ..NetworkPolicyRecoveryReport::default()
        })
    }

    async fn apply(
        &self,
        _request: NetworkPolicyApplyRequest,
        _policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn remove(&self, _sandbox_id: SandboxId) -> anyhow::Result<()> {
        Ok(())
    }
}
