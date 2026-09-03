use std::collections::{HashMap, HashSet};
use std::time::Duration;

use uuid::Uuid;

use super::NodeOwnershipRegistry;
use crate::ids::SandboxId;

#[tokio::test]
async fn node_scoped_delivery_waits_for_authoritative_assignment() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let waiting = {
        let registry = registry.clone();
        tokio::spawn(async move { registry.wait_for_delivery_owner_node(sandbox_id).await })
    };

    tokio::task::yield_now().await;
    registry.assign(sandbox_id, "node-a");

    let owner = tokio::time::timeout(Duration::from_secs(1), waiting)
        .await
        .expect("ownership wait timed out")
        .expect("ownership wait task failed")
        .expect("ownership wait returned an error");
    assert_eq!(owner.as_deref(), Some("node-a"));
}

#[tokio::test]
async fn unscoped_delivery_does_not_wait_for_assignment() {
    let registry = NodeOwnershipRegistry::unscoped();
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let owner = registry
        .wait_for_delivery_owner_node(sandbox_id)
        .await
        .expect("unscoped ownership lookup failed");

    assert_eq!(owner, None);
}

#[test]
fn assigned_node_names_are_deduplicated_and_follow_replacement() {
    let registry = NodeOwnershipRegistry::node_scoped();
    let first = SandboxId::from_uuid(Uuid::now_v7());
    let second = SandboxId::from_uuid(Uuid::now_v7());
    registry.assign(first, "node-a");
    registry.assign(second, "node-a");

    assert_eq!(
        registry.assigned_node_names(),
        HashSet::from(["node-a".to_string()])
    );

    registry.replace_all(HashMap::from([(second, "node-b".to_string())]));
    assert_eq!(
        registry.assigned_node_names(),
        HashSet::from(["node-b".to_string()])
    );
}
