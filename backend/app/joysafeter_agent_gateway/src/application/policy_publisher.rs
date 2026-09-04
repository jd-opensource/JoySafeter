use std::time::Duration;

use crate::domain::egress_policy::{
    validate_egress_policy, ListenerKind, ListenerSpec, SandboxEgressPolicy,
};
use crate::ids::SandboxId;
use crate::render::{encode_cluster_any, encode_listener_any};
use crate::xds::control_plane::XdsControlPlane;
use crate::xds::delivery::{DeliveryAttempt, DeliveryOutcome, DeliveryRequest};
use crate::xds::delta::RemovalDelivery;
use crate::xds::model::{DeliveryGeneration, ManagedXdsResource, ResourceOwner, ResourceType};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublishOutcome {
    AlreadyCurrent,
    Awaiting(DeliveryAttempt),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RemoveOutcome {
    Superseded,
    Current(PublishOutcome),
}

#[derive(Clone)]
pub struct PolicyPublisher {
    control_plane: XdsControlPlane,
}

impl PolicyPublisher {
    pub fn new(control_plane: XdsControlPlane) -> Self {
        Self { control_plane }
    }

    pub async fn publish(
        &self,
        authority_epoch: u64,
        sandbox_id: SandboxId,
        generation: DeliveryGeneration,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<PublishOutcome> {
        validate_egress_policy(&sandbox_id, &policy)?;

        let resources = self.compile(sandbox_id, &generation, &policy).await?;

        let attempt = self
            .control_plane
            .publish_sandbox_resources(
                DeliveryRequest {
                    authority_epoch,
                    sandbox_id,
                    generation,
                },
                resources,
            )
            .await?;
        Ok(match attempt {
            Some(attempt) => PublishOutcome::Awaiting(attempt),
            None => PublishOutcome::AlreadyCurrent,
        })
    }

    pub async fn compile(
        &self,
        sandbox_id: SandboxId,
        _generation: &DeliveryGeneration,
        policy: &SandboxEgressPolicy,
    ) -> anyhow::Result<Vec<ManagedXdsResource>> {
        validate_egress_policy(&sandbox_id, policy)?;
        let mut resources = policy
            .clusters(&sandbox_id)
            .iter()
            .map(|cluster| {
                Ok(ManagedXdsResource {
                    name: cluster.name.clone(),
                    resource_type: ResourceType::Cluster,
                    owner: ResourceOwner::Sandbox(sandbox_id),
                    payload: std::sync::Arc::new(encode_cluster_any(cluster)?),
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;
        let credentials = policy
            .credential_routes
            .iter()
            .map(|route| route.to_route_spec())
            .collect();
        let listener = ListenerSpec {
            sandbox_id,
            kind: ListenerKind::Http,
            allowed_hosts: policy.allowlist_hosts.clone(),
            credentials,
            proxy_auth_token: policy.proxy_auth_token.clone(),
        };
        resources.push(ManagedXdsResource {
            name: listener.resource_name(),
            resource_type: ResourceType::Listener,
            owner: ResourceOwner::Sandbox(sandbox_id),
            payload: std::sync::Arc::new(encode_listener_any(&listener)?),
        });

        Ok(resources)
    }

    pub async fn wait_for_delivery(
        &self,
        outcome: PublishOutcome,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        match outcome {
            PublishOutcome::AlreadyCurrent => Ok(()),
            PublishOutcome::Awaiting(attempt) => self
                .control_plane
                .wait_for_delivery(attempt, timeout)
                .await
                .map_err(anyhow::Error::new),
        }
    }

    pub async fn delivery_outcome(&self, outcome: PublishOutcome) -> Option<DeliveryOutcome> {
        match outcome {
            PublishOutcome::AlreadyCurrent => Some(DeliveryOutcome::Acked),
            PublishOutcome::Awaiting(attempt) => self.control_plane.delivery_outcome(attempt).await,
        }
    }

    pub async fn assign_node(
        &self,
        sandbox_id: SandboxId,
        node_id: impl Into<String>,
    ) -> anyhow::Result<()> {
        self.control_plane
            .assign_sandbox_node(sandbox_id, node_id)
            .await?;
        Ok(())
    }

    pub async fn remove(
        &self,
        sandbox_id: SandboxId,
        expected_generation: Option<DeliveryGeneration>,
    ) -> anyhow::Result<RemoveOutcome> {
        let delivery = self
            .control_plane
            .remove_sandbox_resources(sandbox_id, expected_generation)
            .await?;
        Ok(match delivery {
            RemovalDelivery::Superseded => RemoveOutcome::Superseded,
            RemovalDelivery::Current(Some(attempt)) => {
                RemoveOutcome::Current(PublishOutcome::Awaiting(attempt))
            }
            RemovalDelivery::Current(None) => {
                RemoveOutcome::Current(PublishOutcome::AlreadyCurrent)
            }
        })
    }

    pub async fn retire(&self, sandbox_id: SandboxId) {
        self.control_plane.retire_sandbox_delivery(sandbox_id).await;
        self.control_plane.remove_sandbox_node(sandbox_id).await;
    }

    pub async fn retire_delivery(&self, sandbox_id: SandboxId) {
        self.control_plane.retire_sandbox_delivery(sandbox_id).await;
    }
}

#[cfg(test)]
#[path = "../../tests/unit/application/policy_publisher_test.rs"]
mod tests;
