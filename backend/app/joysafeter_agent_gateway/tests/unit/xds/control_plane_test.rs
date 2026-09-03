use envoy_types::pb::google::protobuf::Any;

use super::*;

impl XdsControlPlane {
    pub(crate) async fn snapshot_resources(
        &self,
        resource_type: crate::xds::model::ResourceType,
    ) -> Vec<crate::xds::model::ManagedXdsResource> {
        self.delta.resources().snapshot_type(resource_type).await
    }
}
use crate::xds::inventory::{RecoveredSandbox, RecoveryInventory};
use crate::xds::model::{DeliveryGeneration, ResourceOwner};

#[tokio::test]
async fn removal_without_a_live_node_retires_authoritative_inventory() {
    let authority = XdsAuthority::standalone();
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
            RecoveryInventory::new(vec![RecoveredSandbox {
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
            }])
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
        .remove_sandbox_resources(sandbox_id, None)
        .await
        .expect("remove unassigned sandbox resources");

    assert_eq!(attempt, RemovalDelivery::Current(None));
    assert!(!control_plane
        .configured_sandbox_ids(ResourceType::Listener)
        .await
        .contains(&sandbox_id));
}
