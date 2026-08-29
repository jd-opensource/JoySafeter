use std::collections::HashSet;

use envoy_types::pb::google::protobuf::Any;
use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::kernel::network_policy::NetworkPolicyGeneration;
use joysafeter_orchestrator::xds::authority::{AuthorityPhase, XdsAuthority};
use joysafeter_orchestrator::xds::control_plane::{NodeVisibility, XdsControlPlane};
use joysafeter_orchestrator::xds::inventory::{
    QuarantinedSandbox, RecoveredSandbox, RecoveryDeliveryState, RecoveryInventory,
};
use joysafeter_orchestrator::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};

fn resource(sandbox_id: SandboxId, resource_type: ResourceType, name: &str) -> ManagedXdsResource {
    ManagedXdsResource {
        name: name.to_string(),
        resource_type,
        owner: ResourceOwner::Sandbox(sandbox_id),
        payload: Any {
            type_url: resource_type.type_url().to_string(),
            value: name.as_bytes().to_vec(),
        },
    }
}

fn recovered(sandbox_id: SandboxId, suffix: &str) -> RecoveredSandbox {
    RecoveredSandbox {
        sandbox_id,
        generation: NetworkPolicyGeneration {
            policy_hash: format!("policy-{suffix}"),
            policy_version: 1,
        },
        resources: vec![
            resource(
                sandbox_id,
                ResourceType::Cluster,
                &format!("cluster-{suffix}"),
            ),
            resource(
                sandbox_id,
                ResourceType::Listener,
                &format!("listener-{suffix}"),
            ),
        ],
    }
}

#[tokio::test]
async fn recovery_inventory_installs_one_complete_world_before_ads_serves() {
    let authority = XdsAuthority::managed();
    let guard = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let first = SandboxId::new();
    let second = SandboxId::new();

    let installed = control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(
                vec![recovered(first, "first"), recovered(second, "second")],
                vec![],
            )
            .expect("valid recovery inventory"),
        )
        .await
        .expect("install recovery inventory");

    assert_eq!(authority.phase(), AuthorityPhase::Staging { epoch: 1 });
    assert_eq!(installed.deliveries.len(), 2);
    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Cluster)
            .await,
        HashSet::from([first, second])
    );
    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await,
        HashSet::from([first, second])
    );

    authority
        .begin_recovery_serving(&guard)
        .expect("serve installed inventory");
    assert_eq!(
        authority.phase(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
}

#[tokio::test]
async fn quarantined_sandbox_does_not_block_healthy_inventory_installation() {
    let authority = XdsAuthority::managed();
    let guard = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let healthy = SandboxId::new();
    let invalid = SandboxId::new();
    let inventory = RecoveryInventory::new(
        vec![recovered(healthy, "healthy")],
        vec![QuarantinedSandbox {
            sandbox_id: invalid,
            reason: "invalid canonical policy".to_string(),
        }],
    )
    .expect("mixed inventory remains valid");

    let installed = control_plane
        .install_recovery_inventory(&guard, inventory)
        .await
        .expect("healthy inventory installs");

    assert_eq!(installed.quarantined_sandboxes.len(), 1);
    assert_eq!(installed.quarantined_sandboxes[0].sandbox_id, invalid);
    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await,
        HashSet::from([healthy])
    );
}

#[tokio::test]
async fn revoked_staging_guard_cannot_replace_existing_resource_world() {
    let authority = XdsAuthority::managed();
    let guard = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let existing = SandboxId::new();
    control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(vec![recovered(existing, "existing")], vec![])
                .expect("valid initial inventory"),
        )
        .await
        .expect("seed resource world");
    authority.revoke().expect("revoke authority");

    let error = control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(vec![recovered(SandboxId::new(), "replacement")], vec![])
                .expect("valid inventory"),
        )
        .await
        .expect_err("revoked staging guard must reject installation");

    assert!(error.to_string().contains("stale"));
    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await,
        HashSet::from([existing])
    );
}

#[tokio::test]
async fn invalid_inventory_cannot_partially_replace_the_resource_world() {
    let authority = XdsAuthority::managed();
    let guard = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let existing = SandboxId::new();
    control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(vec![recovered(existing, "existing")], vec![])
                .expect("valid initial inventory"),
        )
        .await
        .expect("seed resource world");
    let replacement = SandboxId::new();
    let mut invalid = recovered(replacement, "invalid");
    invalid.resources[0].payload.type_url = ResourceType::Listener.type_url().to_string();

    control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(vec![invalid], vec![]).expect("structurally valid inventory"),
        )
        .await
        .expect_err("invalid resource payload must reject the complete inventory");

    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Listener)
            .await,
        HashSet::from([existing])
    );
    assert_eq!(
        control_plane
            .configured_sandbox_ids(ResourceType::Cluster)
            .await,
        HashSet::from([existing])
    );
}

#[tokio::test]
async fn temporarily_unaddressable_recovery_entry_is_deferred() {
    let authority = XdsAuthority::managed();
    let guard = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::NodeScoped);
    let sandbox_id = SandboxId::new();

    let installed = control_plane
        .install_recovery_inventory(
            &guard,
            RecoveryInventory::new(vec![recovered(sandbox_id, "unassigned")], vec![])
                .expect("valid inventory"),
        )
        .await
        .expect("defer unaddressable inventory");

    assert_eq!(installed.deliveries.len(), 1);
    assert_eq!(
        installed.deliveries[0].state,
        RecoveryDeliveryState::Deferred
    );
    assert!(control_plane
        .configured_sandbox_ids(ResourceType::Listener)
        .await
        .is_empty());
    assert!(control_plane
        .configured_sandbox_ids(ResourceType::Cluster)
        .await
        .is_empty());
}
