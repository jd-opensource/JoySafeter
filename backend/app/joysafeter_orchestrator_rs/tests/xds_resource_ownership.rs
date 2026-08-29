use std::collections::HashMap;

use envoy_types::pb::google::protobuf::Any;
use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::kernel::network_policy::NetworkPolicyGeneration;
use joysafeter_orchestrator::xds::model::{
    ManagedXdsResource, ResourceOwner, ResourceType, SandboxResourceBundle,
};
use joysafeter_orchestrator::xds::node_ownership::{NodeOwnershipRegistry, OwnershipTransition};
use joysafeter_orchestrator::xds::resource_store::{ManagedResourceChange, XdsResourceStore};

fn resource(name: &str, resource_type: ResourceType, owner: ResourceOwner) -> ManagedXdsResource {
    ManagedXdsResource {
        name: name.to_string(),
        resource_type,
        owner,
        payload: Any {
            type_url: resource_type.type_url().to_string(),
            value: name.as_bytes().to_vec(),
        },
    }
}

fn bundle(sandbox_id: SandboxId, cluster: &str, listener: &str) -> SandboxResourceBundle {
    SandboxResourceBundle {
        sandbox_id,
        generation: NetworkPolicyGeneration {
            policy_hash: "policy-hash".to_string(),
            policy_version: 1,
        },
        owner_node: Some("node-a".to_string()),
        resources: vec![
            resource(
                listener,
                ResourceType::Listener,
                ResourceOwner::Sandbox(sandbox_id),
            ),
            resource(
                cluster,
                ResourceType::Cluster,
                ResourceOwner::Sandbox(sandbox_id),
            ),
        ],
    }
}

#[tokio::test]
async fn sandbox_bundle_commits_clusters_before_listeners_in_one_revision() {
    let store = XdsResourceStore::new();
    let sandbox_id = SandboxId::new();

    let revision = store
        .apply_bundle(bundle(sandbox_id, "cluster-a", "listener-a"))
        .await
        .expect("apply bundle");

    assert_eq!(revision.version, 1);
    assert_eq!(revision.changes.len(), 2);
    assert!(matches!(
        &revision.changes[0],
        ManagedResourceChange::Upsert(resource)
            if resource.resource_type == ResourceType::Cluster
                && resource.owner == ResourceOwner::Sandbox(sandbox_id)
    ));
    assert!(matches!(
        &revision.changes[1],
        ManagedResourceChange::Upsert(resource)
            if resource.resource_type == ResourceType::Listener
                && resource.owner == ResourceOwner::Sandbox(sandbox_id)
    ));
}

#[tokio::test]
async fn sandbox_bundle_rejects_resources_owned_by_another_sandbox() {
    let store = XdsResourceStore::new();
    let sandbox_id = SandboxId::new();
    let other = SandboxId::new();
    let mut invalid = bundle(sandbox_id, "cluster-a", "listener-a");
    invalid.resources[0].owner = ResourceOwner::Sandbox(other);

    let error = store
        .apply_bundle(invalid)
        .await
        .expect_err("bundle ownership mismatch must fail closed");

    assert!(error.to_string().contains("owner"));
    assert_eq!(store.current_version().await, 0);
}

#[tokio::test]
async fn resource_payload_type_must_match_declared_resource_type() {
    let store = XdsResourceStore::new();
    let mut invalid = resource("listener-a", ResourceType::Listener, ResourceOwner::Shared);
    invalid.payload.type_url = ResourceType::Cluster.type_url().to_string();

    let error = store
        .replace_inventory(vec![invalid])
        .await
        .expect_err("payload type mismatch must fail closed");

    assert!(error.to_string().contains("type URL"));
    assert_eq!(store.current_version().await, 0);
}

#[tokio::test]
async fn replacing_bundle_removes_stale_owned_resources_without_parsing_names() {
    let store = XdsResourceStore::new();
    let sandbox_id = SandboxId::new();
    store
        .apply_bundle(bundle(sandbox_id, "opaque-old-cluster", "opaque-listener"))
        .await
        .expect("seed bundle");

    let revision = store
        .apply_bundle(bundle(sandbox_id, "opaque-new-cluster", "opaque-listener"))
        .await
        .expect("replace bundle");

    assert_eq!(revision.version, 2);
    assert!(revision.changes.iter().any(|change| matches!(
        change,
        ManagedResourceChange::Remove { name, owner, .. }
            if name == "opaque-old-cluster"
                && *owner == ResourceOwner::Sandbox(sandbox_id)
    )));
    assert_eq!(
        store
            .resources_owned_by(ResourceOwner::Sandbox(sandbox_id))
            .await
            .len(),
        2
    );
}

#[tokio::test]
async fn removing_sandbox_keeps_shared_and_other_sandbox_resources() {
    let store = XdsResourceStore::new();
    let removed = SandboxId::new();
    let retained = SandboxId::new();
    store
        .replace_inventory(vec![
            resource("shared", ResourceType::Cluster, ResourceOwner::Shared),
            resource(
                "remove-me",
                ResourceType::Listener,
                ResourceOwner::Sandbox(removed),
            ),
            resource(
                "keep-me",
                ResourceType::Listener,
                ResourceOwner::Sandbox(retained),
            ),
        ])
        .await
        .expect("replace inventory");

    let revision = store.remove_sandbox(removed).await;

    assert_eq!(revision.changes.len(), 1);
    assert_eq!(
        store.resources_owned_by(ResourceOwner::Shared).await.len(),
        1
    );
    assert_eq!(
        store
            .resources_owned_by(ResourceOwner::Sandbox(retained))
            .await
            .len(),
        1
    );
}

#[test]
fn node_assignment_distinguishes_unchanged_and_moved_ownership() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let sandbox_id = SandboxId::new();

    assert!(matches!(
        registry.assign(sandbox_id, "node-a"),
        OwnershipTransition::Assigned { .. }
    ));
    assert!(matches!(
        registry.assign(sandbox_id, "node-a"),
        OwnershipTransition::Unchanged { .. }
    ));
    assert!(matches!(
        registry.assign(sandbox_id, "node-b"),
        OwnershipTransition::Moved {
            previous_node,
            new_node,
            ..
        } if previous_node == "node-a" && new_node == "node-b"
    ));
    assert!(registry.is_visible(ResourceOwner::Sandbox(sandbox_id), "node-b"));
    assert!(!registry.is_visible(ResourceOwner::Sandbox(sandbox_id), "node-a"));
}

#[test]
fn authoritative_relist_removes_absent_mappings_and_moves_changed_nodes() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let removed = SandboxId::new();
    let moved = SandboxId::new();
    let added = SandboxId::new();
    registry.assign(removed, "node-a");
    registry.assign(moved, "node-a");

    let transitions = registry.replace_all(HashMap::from([
        (moved, "node-b".to_string()),
        (added, "node-c".to_string()),
    ]));

    assert!(transitions.iter().any(|transition| matches!(
        transition,
        OwnershipTransition::Removed { sandbox_id, node }
            if *sandbox_id == removed && node == "node-a"
    )));
    assert!(transitions.iter().any(|transition| matches!(
        transition,
        OwnershipTransition::Moved { sandbox_id, previous_node, new_node }
            if *sandbox_id == moved && previous_node == "node-a" && new_node == "node-b"
    )));
    assert!(transitions.iter().any(|transition| matches!(
        transition,
        OwnershipTransition::Assigned { sandbox_id, node }
            if *sandbox_id == added && node == "node-c"
    )));
    assert_eq!(registry.owner_node(removed), None);
}

#[test]
fn node_scoped_visibility_is_fail_closed_but_shared_resources_remain_global() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let sandbox_id = SandboxId::new();

    assert!(registry.is_visible(ResourceOwner::Shared, "node-a"));
    assert!(!registry.is_visible(ResourceOwner::Sandbox(sandbox_id), "node-a"));
}

#[test]
fn unscoped_visibility_keeps_standalone_resources_permissive() {
    let registry = NodeOwnershipRegistry::unscoped();
    let sandbox_id = SandboxId::new();

    assert!(registry.is_visible(ResourceOwner::Shared, "standalone"));
    assert!(registry.is_visible(ResourceOwner::Sandbox(sandbox_id), "standalone"));
}

#[test]
fn unscoped_delivery_can_bind_to_the_first_live_node_session() {
    let registry = NodeOwnershipRegistry::unscoped();

    assert_eq!(
        registry
            .delivery_owner_node(SandboxId::new())
            .expect("unscoped delivery owner"),
        None
    );
}

#[test]
fn node_scoped_delivery_requires_an_authoritative_assignment() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let sandbox_id = SandboxId::new();

    assert!(registry.delivery_owner_node(sandbox_id).is_err());
    registry.assign(sandbox_id, "node-a");
    assert_eq!(
        registry
            .delivery_owner_node(sandbox_id)
            .expect("assigned delivery owner"),
        Some("node-a".to_string())
    );
}
