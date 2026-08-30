//! Composition root for the in-process xDS control plane.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use crate::ids::SandboxId;

use super::authority::{RecoveryAuthorityGuard, XdsAuthority};
use super::delivery::{DeliveryAttempt, DeliveryOutcome, DeliveryRequest, DeliveryTarget};
use super::delta::DeltaXdsServer;
use super::inventory::{InstalledRecoveryInventory, RecoveryInventory};
use super::metrics::{XdsMetrics, XdsMetricsSnapshot};
use super::model::{ManagedXdsResource, ResourceType};
use super::node_ownership::NodeOwnershipRegistry;
use super::resource_store::XdsResourceStore;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeVisibility {
    Unscoped,
    NodeScoped,
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

    pub(crate) fn set_degraded_inventory(&self, count: usize) {
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

    pub async fn install_recovery_inventory(
        &self,
        authority: &RecoveryAuthorityGuard,
        inventory: RecoveryInventory,
    ) -> anyhow::Result<InstalledRecoveryInventory> {
        self.delta
            .install_recovery_inventory(authority, inventory)
            .await
    }

    pub async fn remove_sandbox_resources(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        let target = match self.node_ownership.owner_node(sandbox_id) {
            Some(node) => DeliveryTarget::Node(node),
            None if self.node_ownership.requires_node_assignment() => DeliveryTarget::Unavailable,
            None => DeliveryTarget::AnyNode,
        };
        self.delta
            .remove_sandbox_resources(sandbox_id, target)
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
    ) -> anyhow::Result<()> {
        let mut receiver = self.delta.delivery_notify();
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            match self.delta.delivery().lock().await.outcome(attempt) {
                Some(DeliveryOutcome::Acked) => return Ok(()),
                Some(DeliveryOutcome::Nacked {
                    resource_type,
                    reason,
                }) => anyhow::bail!(
                    "Envoy NACK'd {resource_type:?} xDS delivery for sandbox {}: {reason}",
                    attempt.sandbox_id
                ),
                Some(DeliveryOutcome::Pending) | None => {}
            }
            if tokio::time::Instant::now() >= deadline
                || tokio::time::timeout_at(deadline, receiver.changed())
                    .await
                    .is_err()
            {
                anyhow::bail!(
                    "timed out waiting for exact Envoy xDS delivery for sandbox {}",
                    attempt.sandbox_id
                );
            }
        }
    }

    pub async fn retire_sandbox_delivery(&self, sandbox_id: SandboxId) {
        self.delta.delivery().lock().await.forget(sandbox_id);
        self.delta.notify_delivery_changed();
    }
}

#[cfg(test)]
mod tests {
    use envoy_types::pb::google::protobuf::Any;

    use super::*;
    use crate::xds::inventory::{RecoveredSandbox, RecoveryInventory};
    use crate::xds::model::{DeliveryGeneration, ResourceOwner};

    #[tokio::test]
    async fn removal_without_a_live_node_retires_authoritative_inventory() {
        let authority = XdsAuthority::managed();
        let recovery = authority.begin_staging().expect("begin recovery");
        let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::NodeScoped);
        let sandbox_id = SandboxId::new();
        control_plane
            .assign_sandbox_node(sandbox_id, "node-a")
            .await
            .expect("assign sandbox node");
        control_plane
            .install_recovery_inventory(
                &recovery,
                RecoveryInventory::new(
                    vec![RecoveredSandbox {
                        sandbox_id,
                        generation: DeliveryGeneration {
                            policy_hash: "policy-1".to_string(),
                            policy_version: 1,
                        },
                        resources: vec![ManagedXdsResource {
                            name: "listener-1".to_string(),
                            resource_type: ResourceType::Listener,
                            owner: ResourceOwner::Sandbox(sandbox_id),
                            payload: Any {
                                type_url: ResourceType::Listener.type_url().to_string(),
                                value: vec![1],
                            },
                        }],
                    }],
                    Vec::new(),
                )
                .expect("recovery inventory"),
            )
            .await
            .expect("install recovery inventory");
        authority
            .begin_recovery_serving(&recovery)
            .expect("begin recovery serving");
        authority.mark_ready(&recovery).expect("mark ready");
        control_plane.remove_sandbox_node(sandbox_id).await;

        let attempt = control_plane
            .remove_sandbox_resources(sandbox_id)
            .await
            .expect("remove unassigned sandbox resources");

        assert_eq!(attempt, None);
        assert!(!control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await
            .contains(&sandbox_id));
    }
}
