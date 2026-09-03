//! Composition root for the in-process xDS control plane.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use thiserror::Error;

use crate::ids::SandboxId;

use super::authority::{RecoveryAuthorityGuard, XdsAuthority};
use super::delivery::{DeliveryAttempt, DeliveryOutcome, DeliveryRequest, DeliveryTarget};
use super::delta::{DeltaXdsServer, RemovalDelivery};
use super::inventory::RecoveryInventory;
use super::metrics::{XdsMetrics, XdsMetricsSnapshot};
use super::model::{DeliveryGeneration, ManagedXdsResource, ResourceType};
use super::node_ownership::NodeOwnershipRegistry;
use super::resource_store::XdsResourceStore;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeVisibility {
    Unscoped,
    NodeScoped,
}

#[derive(Debug, Error)]
pub enum DeliveryWaitError {
    #[error("Envoy NACK'd {resource_type:?} xDS delivery for sandbox {sandbox_id}: {reason}")]
    Nacked {
        sandbox_id: SandboxId,
        resource_type: ResourceType,
        reason: String,
    },
    #[error("timed out waiting for exact Envoy xDS delivery for sandbox {sandbox_id}")]
    Timeout { sandbox_id: SandboxId },
}

#[derive(Clone)]
pub struct XdsControlPlane {
    node_ownership: NodeOwnershipRegistry,
    delta: Arc<DeltaXdsServer>,
}

impl XdsControlPlane {
    pub fn new(authority: XdsAuthority, visibility: NodeVisibility) -> Self {
        let resources = XdsResourceStore::new();
        let node_ownership = match visibility {
            NodeVisibility::Unscoped => NodeOwnershipRegistry::unscoped(),
            NodeVisibility::NodeScoped => NodeOwnershipRegistry::node_scoped(),
        };
        let delta = DeltaXdsServer::new(authority, resources.clone(), node_ownership.clone());
        Self {
            node_ownership,
            delta,
        }
    }

    pub fn ads_service(&self) -> Arc<DeltaXdsServer> {
        self.delta.clone()
    }

    pub(crate) fn metrics(&self) -> XdsMetrics {
        self.delta.metrics()
    }

    pub async fn metrics_snapshot(&self) -> XdsMetricsSnapshot {
        self.delta.metrics_snapshot().await
    }

    pub fn set_degraded_inventory(&self, count: usize) {
        self.delta.metrics().set_degraded_inventory(count);
    }

    pub async fn publish_sandbox_resources(
        &self,
        request: DeliveryRequest,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        let owner_node = self
            .node_ownership
            .delivery_owner_node(request.sandbox_id)?;
        let target = owner_node.map_or(DeliveryTarget::AnyNode, DeliveryTarget::Node);
        self.delta
            .publish_sandbox_resources(request, target, resources)
            .await
    }

    pub async fn wait_for_delivery_owner_node(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<Option<String>> {
        self.node_ownership
            .wait_for_delivery_owner_node(sandbox_id)
            .await
    }

    pub fn requires_node_assignment(&self) -> bool {
        self.node_ownership.requires_node_assignment()
    }

    pub async fn install_recovery_inventory(
        &self,
        authority: &RecoveryAuthorityGuard,
        inventory: RecoveryInventory,
    ) -> anyhow::Result<()> {
        self.delta
            .install_recovery_inventory(authority, inventory)
            .await
    }

    pub(crate) async fn install_replica_inventory(
        &self,
        resources: Vec<ManagedXdsResource>,
        assignments: HashMap<SandboxId, String>,
    ) -> anyhow::Result<()> {
        self.delta
            .install_replica_inventory(resources, assignments)
            .await
    }

    pub(crate) async fn install_replica_sandbox(
        &self,
        sandbox_id: SandboxId,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<()> {
        self.delta
            .install_replica_sandbox(sandbox_id, resources)
            .await
    }

    pub(crate) async fn remove_replica_sandbox(&self, sandbox_id: SandboxId) {
        self.delta.remove_replica_sandbox(sandbox_id).await;
    }

    pub(crate) fn install_replica_placement(&self, sandbox_id: SandboxId, node: String) {
        self.delta.install_replica_placement(sandbox_id, node);
    }

    pub(crate) fn remove_replica_placement(&self, sandbox_id: SandboxId) {
        self.delta.remove_replica_placement(sandbox_id);
    }

    pub(crate) async fn install_replica_placements(&self, assignments: HashMap<SandboxId, String>) {
        self.delta.install_replica_placements(assignments).await;
    }

    pub async fn remove_sandbox_resources(
        &self,
        sandbox_id: SandboxId,
        expected_generation: Option<DeliveryGeneration>,
    ) -> anyhow::Result<RemovalDelivery> {
        let target = match self.node_ownership.owner_node(sandbox_id) {
            Some(node) => DeliveryTarget::Node(node),
            None if self.node_ownership.requires_node_assignment() => DeliveryTarget::Unavailable,
            None => DeliveryTarget::AnyNode,
        };
        self.delta
            .remove_sandbox_resources(sandbox_id, expected_generation, target)
            .await
    }

    pub async fn configured_sandbox_ids(&self, resource_type: ResourceType) -> HashSet<SandboxId> {
        self.delta.configured_sandbox_ids(resource_type).await
    }

    pub async fn assign_sandbox_node(
        &self,
        sandbox_id: SandboxId,
        node: impl Into<String>,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        self.delta.assign_sandbox_node(sandbox_id, node).await
    }

    pub async fn remove_sandbox_node(&self, sandbox_id: SandboxId) {
        self.delta.remove_sandbox_node(sandbox_id).await;
    }

    pub fn owner_node(&self, sandbox_id: SandboxId) -> Option<String> {
        self.node_ownership.owner_node(sandbox_id)
    }

    pub async fn replace_node_assignments(
        &self,
        assignments: HashMap<SandboxId, String>,
    ) -> anyhow::Result<Vec<DeliveryAttempt>> {
        self.delta.replace_node_assignments(assignments).await
    }

    pub async fn wait_for_delivery(
        &self,
        attempt: DeliveryAttempt,
        timeout: Duration,
    ) -> Result<(), DeliveryWaitError> {
        let mut receiver = self.delta.delivery_notify();
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            match self.delta.delivery().lock().await.outcome(attempt) {
                Some(DeliveryOutcome::Acked) => return Ok(()),
                Some(DeliveryOutcome::Nacked {
                    resource_type,
                    reason,
                }) => {
                    return Err(DeliveryWaitError::Nacked {
                        sandbox_id: attempt.sandbox_id,
                        resource_type,
                        reason,
                    });
                }
                Some(DeliveryOutcome::Pending) | None => {}
            }
            if tokio::time::Instant::now() >= deadline
                || tokio::time::timeout_at(deadline, receiver.changed())
                    .await
                    .is_err()
            {
                return Err(DeliveryWaitError::Timeout {
                    sandbox_id: attempt.sandbox_id,
                });
            }
        }
    }

    pub async fn delivery_outcome(&self, attempt: DeliveryAttempt) -> Option<DeliveryOutcome> {
        self.delta.delivery().lock().await.outcome(attempt)
    }

    pub async fn retire_sandbox_delivery(&self, sandbox_id: SandboxId) {
        self.delta.delivery().lock().await.forget(sandbox_id);
        self.delta.notify_delivery_changed();
    }
}

#[cfg(test)]
#[path = "../../tests/unit/xds/control_plane_test.rs"]
mod tests;
