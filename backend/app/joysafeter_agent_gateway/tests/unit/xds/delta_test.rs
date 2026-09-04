use super::response::NONCE_TRACK_LIMIT;
use super::*;
use crate::xds::delivery::DeliveredResource;

impl DeltaXdsServer {
    pub(crate) fn resources(&self) -> &crate::xds::resource_store::XdsResourceStore {
        &self.resources
    }
}

#[test]
fn nack_diagnostic_never_contains_original_configuration() {
    let original = "typed_config contains authorization=secret";
    let diagnostic = sanitize_xds_nack(original);
    assert!(!diagnostic.contains(original));
    assert!(!diagnostic.contains("secret"));
    assert!(diagnostic.contains("details redacted"));
    assert!(diagnostic.contains(&format!("bytes={}", original.len())));
}
use envoy_types::pb::google::protobuf::Any;

#[test]
fn nonce_tracker_is_bounded_and_consuming() {
    let owner = ResourceOwner::Sandbox(SandboxId::new());
    let mut tracker = NonceTracker::default();
    for index in 0..(NONCE_TRACK_LIMIT + 50) {
        tracker.insert(
            format!("nonce-{index}"),
            (
                ResourceType::Listener,
                index as u64,
                vec![DeliveredResource {
                    name: format!("listener-{index}"),
                    owner,
                    removed: false,
                }],
            ),
        );
    }
    assert!(tracker.entries.len() <= NONCE_TRACK_LIMIT);
    assert!(tracker.take("nonce-0").is_none());
    let recent = format!("nonce-{}", NONCE_TRACK_LIMIT + 49);
    assert!(tracker.take(&recent).is_some());
    assert!(tracker.take(&recent).is_none());
}

#[test]
fn client_only_removals_are_not_attributed_to_delivery_attempts() {
    let mut tracker = NonceTracker::default();
    let (response, current) = snapshot_response(
        ResourceType::Listener,
        7,
        3,
        Vec::new(),
        &HashMap::from([("stale-listener".to_string(), "6".to_string())]),
        &HashSet::new(),
        true,
        &mut tracker,
    );

    assert!(current.is_empty());
    assert_eq!(response.removed_resources, vec!["stale-listener"]);
    let (_, _, delivered_resources) = tracker
        .take(&response.nonce)
        .expect("response nonce is tracked");
    assert!(delivered_resources.is_empty());
}

#[test]
fn recovery_snapshot_preserves_client_last_good_resources() {
    let mut tracker = NonceTracker::default();
    let (response, current) = snapshot_response(
        ResourceType::Listener,
        1,
        1,
        Vec::new(),
        &HashMap::from([("last-good-listener".to_string(), "9".to_string())]),
        &HashSet::new(),
        false,
        &mut tracker,
    );

    assert!(current.is_empty());
    assert!(response.removed_resources.is_empty());
}

#[tokio::test]
async fn node_move_removes_from_old_node_and_adds_to_new_node() {
    let resources = XdsResourceStore::new();
    let ownership = NodeOwnershipRegistry::node_scoped();
    let sandbox_id = SandboxId::new();
    let resource = ManagedXdsResource {
        name: "opaque-listener".to_string(),
        resource_type: ResourceType::Listener,
        owner: ResourceOwner::Sandbox(sandbox_id),
        payload: std::sync::Arc::new(Any {
            type_url: ResourceType::Listener.type_url().to_string(),
            value: vec![1],
        }),
    };
    resources
        .replace_inventory(vec![resource.clone()])
        .await
        .expect("seed resource world");
    ownership.assign(sandbox_id, "node-a");

    let (sender, mut receiver) = tokio::sync::mpsc::channel(4);
    let subscribed = HashSet::from([ResourceType::Listener]);
    let mut old_node_sent = HashMap::from([(
        ResourceType::Listener,
        HashMap::from([(resource.name.clone(), resource.owner)]),
    )]);
    let mut new_node_sent = HashMap::new();
    let mut old_node_nonces = NonceTracker::default();
    let mut new_node_nonces = NonceTracker::default();
    let node_health = EnvoyNodeHealthRegistry::default();
    let old_session = NodeSessionId::from_raw(1);
    let new_session = NodeSessionId::from_raw(2);
    node_health.connect("node-a", old_session);
    node_health.connect("node-b", new_session);

    ownership.assign(sandbox_id, "node-b");
    let old_node_responses = build_visibility_reconciliation(
        &resources,
        &ownership,
        "node-a",
        &subscribed,
        &mut old_node_sent,
        &mut old_node_nonces,
        1,
    )
    .await;
    flush_responses(&sender, &node_health, "node-a", old_session, old_node_responses)
        .await
        .expect("old-node reconciliation");
    let new_node_responses = build_visibility_reconciliation(
        &resources,
        &ownership,
        "node-b",
        &subscribed,
        &mut new_node_sent,
        &mut new_node_nonces,
        1,
    )
    .await;
    flush_responses(&sender, &node_health, "node-b", new_session, new_node_responses)
        .await
        .expect("new-node reconciliation");

    let old_node = receiver.recv().await.expect("old-node response").unwrap();
    let new_node = receiver.recv().await.expect("new-node response").unwrap();
    assert_eq!(old_node.removed_resources, vec!["opaque-listener"]);
    assert!(old_node.resources.is_empty());
    assert_eq!(new_node.resources.len(), 1);
    assert_eq!(new_node.resources[0].name, "opaque-listener");
    assert!(new_node.removed_resources.is_empty());
}
