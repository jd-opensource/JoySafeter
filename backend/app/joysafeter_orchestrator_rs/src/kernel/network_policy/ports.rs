use async_trait::async_trait;
use std::collections::HashSet;

use super::envoy_model::SandboxEgressPolicy;
use super::error::NetworkPolicyApplyError;
use super::request::NetworkPolicyRequest;
use super::NetworkPolicyGeneration;
use crate::ids::SandboxId;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyApplyRequest {
    pub authority_epoch: u64,
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NetworkPolicyApplyTicket {
    sandbox_id: SandboxId,
    delivery_attempt_id: Option<u64>,
}

impl NetworkPolicyApplyTicket {
    pub(crate) const fn completed(sandbox_id: SandboxId) -> Self {
        Self {
            sandbox_id,
            delivery_attempt_id: None,
        }
    }

    pub(crate) const fn pending(sandbox_id: SandboxId, delivery_attempt_id: u64) -> Self {
        Self {
            sandbox_id,
            delivery_attempt_id: Some(delivery_attempt_id),
        }
    }

    pub(crate) const fn sandbox_id(self) -> SandboxId {
        self.sandbox_id
    }

    pub(crate) const fn delivery_attempt_id(self) -> Option<u64> {
        self.delivery_attempt_id
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NetworkPolicyRemoveTicket {
    sandbox_id: SandboxId,
    delivery_attempt_id: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyPruneTicket {
    removed: usize,
    stale: usize,
    cleanup_sandbox_ids: Vec<SandboxId>,
    publication_failures: Vec<String>,
}

impl NetworkPolicyPruneTicket {
    pub(crate) const fn completed(removed: usize) -> Self {
        Self {
            removed,
            stale: removed,
            cleanup_sandbox_ids: Vec::new(),
            publication_failures: Vec::new(),
        }
    }

    pub(crate) fn published(
        stale: usize,
        cleanup_sandbox_ids: Vec<SandboxId>,
        publication_failures: Vec<String>,
    ) -> Self {
        Self {
            removed: cleanup_sandbox_ids.len(),
            stale,
            cleanup_sandbox_ids,
            publication_failures,
        }
    }

    pub(crate) const fn removed(&self) -> usize {
        self.removed
    }

    pub(crate) const fn stale(&self) -> usize {
        self.stale
    }

    pub(crate) fn cleanup_sandbox_ids(&self) -> &[SandboxId] {
        &self.cleanup_sandbox_ids
    }

    pub(crate) fn publication_failures(&self) -> &[String] {
        &self.publication_failures
    }
}

impl NetworkPolicyRemoveTicket {
    pub(crate) const fn completed(sandbox_id: SandboxId) -> Self {
        Self {
            sandbox_id,
            delivery_attempt_id: None,
        }
    }

    pub(crate) const fn pending(sandbox_id: SandboxId, delivery_attempt_id: u64) -> Self {
        Self {
            sandbox_id,
            delivery_attempt_id: Some(delivery_attempt_id),
        }
    }

    pub(crate) const fn sandbox_id(self) -> SandboxId {
        self.sandbox_id
    }

    pub(crate) const fn delivery_attempt_id(self) -> Option<u64> {
        self.delivery_attempt_id
    }
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
    pub error: NetworkPolicyApplyError,
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

    async fn publish_prune(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<NetworkPolicyPruneTicket>;

    async fn settle_prune(&self, ticket: NetworkPolicyPruneTicket) -> anyhow::Result<usize>;

    async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        let ticket = self.publish_prune(live_sandbox_ids).await?;
        self.settle_prune(ticket).await
    }

    async fn recover(
        &self,
        authority_epoch: u64,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport>;

    async fn prepare_apply(
        &self,
        _request: &NetworkPolicyApplyRequest,
        _policy: &SandboxEgressPolicy,
    ) -> Result<(), NetworkPolicyApplyError> {
        Ok(())
    }

    async fn publish_apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> Result<NetworkPolicyApplyTicket, NetworkPolicyApplyError> {
        let sandbox_id = request.sandbox_id;
        self.apply(request, policy).await?;
        Ok(NetworkPolicyApplyTicket::completed(sandbox_id))
    }

    async fn settle_apply(
        &self,
        _ticket: NetworkPolicyApplyTicket,
    ) -> Result<(), NetworkPolicyApplyError> {
        Ok(())
    }

    async fn apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> Result<(), NetworkPolicyApplyError>;

    async fn publish_remove(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<NetworkPolicyRemoveTicket> {
        self.remove(sandbox_id).await?;
        Ok(NetworkPolicyRemoveTicket::completed(sandbox_id))
    }

    async fn settle_remove(&self, _ticket: NetworkPolicyRemoveTicket) -> anyhow::Result<()> {
        Ok(())
    }

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
