//! Envoy resource-delivery ports and xDS control-plane adapters.
//!
//! Rendering stays in [`super::envoy_render`], filesystem delivery stays in
//! [`super::envoy_filesystem`], and Delta ADS protocol/state lives in
//! [`crate::xds`]. This module defines the provider-facing delivery contract and
//! adapts it to the in-process [`XdsControlPlane`].

use std::collections::HashSet;
use std::time::Duration;

use async_trait::async_trait;

use crate::ids::SandboxId;
use crate::xds::authority::RecoveryAuthorityGuard;
use crate::xds::control_plane::XdsControlPlane;
use crate::xds::delivery::{DeliveryAttempt, DeliveryRequest};
use crate::xds::inventory::{InstalledRecoveryInventory, RecoveryInventory};
use crate::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};

use super::envoy_render::{encode_cluster_any, encode_listener_any};
use crate::kernel::network_policy::envoy_model::{ClusterSpec, ListenerSpec};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliverySubmission {
    AlreadyCurrent,
    Await(DeliveryAttempt),
}

#[async_trait]
pub trait EnvoyDelivery: Send + Sync {
    /// Prepare adapter-local state before authoritative recovery.
    async fn prepare_for_startup(&self) -> anyhow::Result<()>;

    async fn wait_for_delivery(
        &self,
        _attempt: DeliveryAttempt,
        _timeout: Duration,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn remove_sandbox_batch(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<DeliverySubmission>;

    async fn retire_sandbox_delivery(&self, _sandbox_id: SandboxId) {}

    fn set_degraded_inventory(&self, _count: usize) {}

    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId>;

    async fn apply_sandbox_batch(
        &self,
        delivery: DeliveryRequest,
        clusters: Vec<ClusterSpec>,
        listeners: Vec<ListenerSpec>,
    ) -> anyhow::Result<DeliverySubmission>;

    async fn install_recovery_inventory(
        &self,
        _authority: &RecoveryAuthorityGuard,
        _inventory: RecoveryInventory,
    ) -> anyhow::Result<InstalledRecoveryInventory> {
        anyhow::bail!("atomic recovery inventory is unsupported by this Envoy delivery adapter")
    }
}

pub struct ControlPlaneEnvoyDelivery {
    control_plane: XdsControlPlane,
}

impl ControlPlaneEnvoyDelivery {
    pub fn new(control_plane: XdsControlPlane) -> Self {
        Self { control_plane }
    }
}

#[async_trait]
impl EnvoyDelivery for ControlPlaneEnvoyDelivery {
    async fn prepare_for_startup(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await
    }

    async fn apply_sandbox_batch(
        &self,
        delivery: DeliveryRequest,
        clusters: Vec<ClusterSpec>,
        listeners: Vec<ListenerSpec>,
    ) -> anyhow::Result<DeliverySubmission> {
        let sandbox_id = delivery.sandbox_id;
        let mut resources = Vec::with_capacity(clusters.len() + listeners.len());
        for spec in &clusters {
            if spec.sandbox_id != sandbox_id {
                anyhow::bail!("cluster owner does not match sandbox batch");
            }
            resources.push(managed_cluster(spec)?);
        }
        for spec in &listeners {
            if spec.sandbox_id != sandbox_id {
                anyhow::bail!("listener owner does not match sandbox batch");
            }
            resources.push(managed_listener(spec)?);
        }
        let attempt = self
            .control_plane
            .publish_sandbox_resources(delivery, resources)
            .await?;
        Ok(match attempt {
            Some(attempt) => DeliverySubmission::Await(attempt),
            None => DeliverySubmission::AlreadyCurrent,
        })
    }

    async fn install_recovery_inventory(
        &self,
        authority: &RecoveryAuthorityGuard,
        inventory: RecoveryInventory,
    ) -> anyhow::Result<InstalledRecoveryInventory> {
        self.control_plane
            .install_recovery_inventory(authority, inventory)
            .await
    }

    async fn wait_for_delivery(
        &self,
        attempt: DeliveryAttempt,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        self.control_plane.wait_for_delivery(attempt, timeout).await
    }

    async fn remove_sandbox_batch(
        &self,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<DeliverySubmission> {
        Ok(
            match self
                .control_plane
                .remove_sandbox_resources(sandbox_id)
                .await?
            {
                Some(attempt) => DeliverySubmission::Await(attempt),
                None => DeliverySubmission::AlreadyCurrent,
            },
        )
    }

    async fn retire_sandbox_delivery(&self, sandbox_id: SandboxId) {
        self.control_plane.retire_sandbox_delivery(sandbox_id).await;
    }

    fn set_degraded_inventory(&self, count: usize) {
        self.control_plane.set_degraded_inventory(count);
    }
}

pub(crate) fn managed_listener(spec: &ListenerSpec) -> anyhow::Result<ManagedXdsResource> {
    Ok(ManagedXdsResource {
        name: spec.resource_name(),
        resource_type: ResourceType::Listener,
        owner: ResourceOwner::Sandbox(spec.sandbox_id),
        payload: encode_listener_any(spec)?,
    })
}

pub(crate) fn managed_cluster(spec: &ClusterSpec) -> anyhow::Result<ManagedXdsResource> {
    Ok(ManagedXdsResource {
        name: spec.name.clone(),
        resource_type: ResourceType::Cluster,
        owner: ResourceOwner::Sandbox(spec.sandbox_id),
        payload: encode_cluster_any(spec)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::network_policy::envoy_model::ListenerKind;
    use crate::kernel::network_policy::NetworkPolicyGeneration;
    use crate::xds::authority::XdsAuthority;
    use crate::xds::control_plane::NodeVisibility;
    use crate::xds::inventory::RecoveredSandbox;

    #[tokio::test]
    async fn control_plane_delivery_reports_explicit_resource_owners() {
        let authority = XdsAuthority::managed();
        let guard = authority.begin_staging().expect("begin recovery staging");
        let delivery = ControlPlaneEnvoyDelivery::new(XdsControlPlane::new(
            authority,
            NodeVisibility::Unscoped,
        ));
        let first = SandboxId::new();
        let second = SandboxId::new();

        delivery
            .install_recovery_inventory(
                &guard,
                RecoveryInventory::new(vec![recovered(first), recovered(second)], Vec::new())
                    .expect("build recovery inventory"),
            )
            .await
            .expect("install recovery inventory");

        assert_eq!(
            delivery.configured_sandbox_ids().await,
            HashSet::from([first, second])
        );
    }

    fn listener(sandbox_id: SandboxId) -> ListenerSpec {
        ListenerSpec {
            sandbox_id,
            kind: ListenerKind::Http,
            allowed_hosts: vec!["example.com".to_string()],
            credentials: vec![],
            proxy_auth_token: None,
        }
    }

    fn recovered(sandbox_id: SandboxId) -> RecoveredSandbox {
        RecoveredSandbox {
            sandbox_id,
            generation: NetworkPolicyGeneration {
                policy_hash: format!("policy-{sandbox_id}"),
                policy_version: 1,
            },
            resources: vec![managed_listener(&listener(sandbox_id)).expect("render listener")],
        }
    }
}
