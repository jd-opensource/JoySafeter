use std::collections::HashSet;

use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::kernel::network_policy::NetworkPolicyGeneration;
use joysafeter_orchestrator::xds::delivery::{
    DeliveredResource, DeliveryAttemptId, DeliveryCoordinator, DeliveryKey, DeliveryOutcome,
    DeliveryRequest, DeliveryTarget, DeliveryTracker, NodeSessionId, ReceiptOutcome,
    ResponseReceipt,
};
use joysafeter_orchestrator::xds::model::{ResourceOwner, ResourceType};

fn generation(hash: &str, version: i64) -> NetworkPolicyGeneration {
    NetworkPolicyGeneration {
        policy_hash: hash.to_string(),
        policy_version: version,
    }
}

fn key(
    sandbox_id: SandboxId,
    generation: NetworkPolicyGeneration,
    node: &str,
    session: u64,
    attempt: u64,
) -> DeliveryKey {
    DeliveryKey {
        authority_epoch: 7,
        sandbox_id,
        generation,
        owner_node: node.to_string(),
        node_session: NodeSessionId::from_raw(session),
        attempt_id: DeliveryAttemptId::from_raw(attempt),
    }
}

fn receipt(key: &DeliveryKey, resource_type: ResourceType, nonce: &str) -> ResponseReceipt {
    ResponseReceipt {
        nonce: nonce.to_string(),
        key: key.clone(),
        resource_type,
        transmitted_names: vec![format!("sent-{resource_type:?}")],
        removed_names: vec![],
    }
}

#[test]
fn listener_ack_does_not_complete_cluster_and_listener_delivery() {
    let sandbox_id = SandboxId::new();
    let key = key(sandbox_id, generation("g1", 1), "node-a", 11, 21);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(
            key.clone(),
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .unwrap();
    tracker
        .record_response(receipt(&key, ResourceType::Listener, "listener-nonce"))
        .unwrap();

    assert_eq!(
        tracker.acknowledge("listener-nonce"),
        ReceiptOutcome::Accepted
    );
    assert_eq!(tracker.outcome(&key), Some(DeliveryOutcome::Pending));

    tracker
        .record_response(receipt(&key, ResourceType::Cluster, "cluster-nonce"))
        .unwrap();
    assert_eq!(
        tracker.acknowledge("cluster-nonce"),
        ReceiptOutcome::Completed
    );
    assert_eq!(tracker.outcome(&key), Some(DeliveryOutcome::Acked));
}

#[test]
fn cluster_nack_after_listener_ack_fails_delivery() {
    let sandbox_id = SandboxId::new();
    let key = key(sandbox_id, generation("g1", 1), "node-a", 11, 21);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(
            key.clone(),
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .unwrap();
    tracker
        .record_response(receipt(&key, ResourceType::Listener, "listener-nonce"))
        .unwrap();
    tracker.acknowledge("listener-nonce");
    tracker
        .record_response(receipt(&key, ResourceType::Cluster, "cluster-nonce"))
        .unwrap();

    assert_eq!(
        tracker.reject("cluster-nonce", "invalid cluster"),
        ReceiptOutcome::Completed
    );
    assert_eq!(
        tracker.outcome(&key),
        Some(DeliveryOutcome::Nacked {
            resource_type: ResourceType::Cluster,
            reason: "invalid cluster".to_string(),
        })
    );
}

#[test]
fn superseded_generation_makes_old_nonce_stale() {
    let sandbox_id = SandboxId::new();
    let old = key(sandbox_id, generation("g1", 1), "node-a", 11, 21);
    let current = key(sandbox_id, generation("g2", 2), "node-a", 11, 22);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(old.clone(), HashSet::from([ResourceType::Listener]))
        .unwrap();
    tracker
        .record_response(receipt(&old, ResourceType::Listener, "old-nonce"))
        .unwrap();
    tracker
        .begin_attempt(current.clone(), HashSet::from([ResourceType::Listener]))
        .unwrap();

    assert_eq!(tracker.acknowledge("old-nonce"), ReceiptOutcome::Stale);
    assert_eq!(tracker.outcome(&old), None);
    assert_eq!(tracker.outcome(&current), Some(DeliveryOutcome::Pending));
}

#[test]
fn old_node_session_and_attempt_receipts_are_stale() {
    let sandbox_id = SandboxId::new();
    let current = key(sandbox_id, generation("g1", 1), "node-b", 12, 22);
    let stale_session = key(sandbox_id, generation("g1", 1), "node-b", 11, 22);
    let stale_attempt = key(sandbox_id, generation("g1", 1), "node-b", 12, 21);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(current.clone(), HashSet::from([ResourceType::Listener]))
        .unwrap();

    assert_eq!(
        tracker
            .record_response(receipt(
                &stale_session,
                ResourceType::Listener,
                "old-session"
            ))
            .unwrap(),
        ReceiptOutcome::Stale
    );
    assert_eq!(
        tracker
            .record_response(receipt(
                &stale_attempt,
                ResourceType::Listener,
                "old-attempt"
            ))
            .unwrap(),
        ReceiptOutcome::Stale
    );
}

#[test]
fn old_authority_epoch_and_owner_node_receipts_are_stale() {
    let sandbox_id = SandboxId::new();
    let current = key(sandbox_id, generation("g1", 1), "node-b", 12, 22);
    let mut old_epoch = current.clone();
    old_epoch.authority_epoch = 6;
    let mut old_node = current.clone();
    old_node.owner_node = "node-a".to_string();
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(current, HashSet::from([ResourceType::Listener]))
        .unwrap();

    assert_eq!(
        tracker
            .record_response(receipt(&old_epoch, ResourceType::Listener, "old-epoch"))
            .unwrap(),
        ReceiptOutcome::Stale
    );
    assert_eq!(
        tracker
            .record_response(receipt(&old_node, ResourceType::Listener, "old-node"))
            .unwrap(),
        ReceiptOutcome::Stale
    );
}

#[test]
fn removal_requires_matching_cds_and_lds_receipts() {
    let sandbox_id = SandboxId::new();
    let key = key(sandbox_id, generation("g3", 3), "node-a", 31, 41);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(
            key.clone(),
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .unwrap();
    let mut listener = receipt(&key, ResourceType::Listener, "remove-listener");
    listener.transmitted_names.clear();
    listener.removed_names = vec!["listener-a".to_string()];
    tracker.record_response(listener).unwrap();
    assert_eq!(
        tracker.acknowledge("remove-listener"),
        ReceiptOutcome::Accepted
    );
    assert_eq!(tracker.outcome(&key), Some(DeliveryOutcome::Pending));

    let mut cluster = receipt(&key, ResourceType::Cluster, "remove-cluster");
    cluster.transmitted_names.clear();
    cluster.removed_names = vec!["cluster-a".to_string()];
    tracker.record_response(cluster).unwrap();
    assert_eq!(
        tracker.acknowledge("remove-cluster"),
        ReceiptOutcome::Completed
    );
    assert_eq!(tracker.outcome(&key), Some(DeliveryOutcome::Acked));
}

#[test]
fn response_without_transmitted_or_removed_resources_is_rejected() {
    let sandbox_id = SandboxId::new();
    let key = key(sandbox_id, generation("g1", 1), "node-a", 1, 1);
    let mut tracker = DeliveryTracker::default();
    tracker
        .begin_attempt(key.clone(), HashSet::from([ResourceType::Listener]))
        .unwrap();
    let empty = ResponseReceipt {
        nonce: "empty".to_string(),
        key,
        resource_type: ResourceType::Listener,
        transmitted_names: vec![],
        removed_names: vec![],
    };

    assert!(tracker.record_response(empty).is_err());
}

#[test]
fn coordinator_binds_attempt_to_current_node_session_and_exact_quorum() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();
    let first_session = coordinator.open_node_session("node-a");
    let attempt = coordinator
        .begin_attempt(
            DeliveryRequest {
                authority_epoch: 9,
                sandbox_id,
                generation: generation("g9", 9),
            },
            DeliveryTarget::Node("node-a".to_string()),
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .unwrap();
    coordinator
        .mark_published(
            attempt,
            1,
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .unwrap();
    let delivered = |name: &str| DeliveredResource {
        name: name.to_string(),
        owner: ResourceOwner::Sandbox(sandbox_id),
        removed: false,
    };

    coordinator
        .record_response(
            "node-a",
            first_session,
            "listener-nonce",
            1,
            ResourceType::Listener,
            &[delivered("listener")],
        )
        .unwrap();
    assert_eq!(
        coordinator.acknowledge("node-a", first_session, "listener-nonce"),
        ReceiptOutcome::Accepted
    );
    assert_eq!(coordinator.outcome(attempt), Some(DeliveryOutcome::Pending));

    let current_session = coordinator.open_node_session("node-a");
    assert_eq!(
        coordinator.acknowledge("node-a", first_session, "listener-nonce"),
        ReceiptOutcome::Stale
    );
    coordinator
        .record_response(
            "node-a",
            current_session,
            "listener-current",
            1,
            ResourceType::Listener,
            &[delivered("listener")],
        )
        .unwrap();
    coordinator
        .record_response(
            "node-a",
            current_session,
            "cluster-current",
            1,
            ResourceType::Cluster,
            &[delivered("cluster")],
        )
        .unwrap();
    coordinator.acknowledge("node-a", current_session, "listener-current");
    assert_eq!(
        coordinator.acknowledge("node-a", current_session, "cluster-current"),
        ReceiptOutcome::Completed
    );
    assert_eq!(coordinator.outcome(attempt), Some(DeliveryOutcome::Acked));
}

#[test]
fn removal_supersedes_the_delivered_generation_with_a_new_attempt() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();
    let initial = coordinator
        .begin_attempt(
            DeliveryRequest {
                authority_epoch: 9,
                sandbox_id,
                generation: generation("g9", 9),
            },
            DeliveryTarget::Node("node-a".to_string()),
            HashSet::from([ResourceType::Listener]),
        )
        .expect("initial delivery");

    let removal = coordinator
        .begin_removal(
            sandbox_id,
            DeliveryTarget::Node("node-a".to_string()),
            HashSet::from([ResourceType::Cluster, ResourceType::Listener]),
        )
        .expect("removal delivery");

    assert_ne!(removal.attempt_id, initial.attempt_id);
    assert_eq!(removal.sandbox_id, sandbox_id);
    assert_eq!(coordinator.outcome(initial), None);
    assert_eq!(coordinator.outcome(removal), None);
}

#[test]
fn removal_without_a_known_generation_fails_closed() {
    let mut coordinator = DeliveryCoordinator::default();

    assert!(coordinator
        .begin_removal(
            SandboxId::new(),
            DeliveryTarget::Node("node-a".to_string()),
            HashSet::from([ResourceType::Listener]),
        )
        .is_err());
}

#[test]
fn suspended_delivery_rejects_old_node_and_can_retarget() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();
    let request = DeliveryRequest {
        authority_epoch: 11,
        sandbox_id,
        generation: generation("same-resources-new-generation", 4),
    };

    let old_attempt = coordinator
        .begin_attempt(
            request.clone(),
            DeliveryTarget::Node("node-b".to_string()),
            HashSet::from([ResourceType::Listener]),
        )
        .expect("begin current delivery");
    coordinator
        .mark_published(old_attempt, 4, HashSet::from([ResourceType::Listener]))
        .expect("publish current delivery");
    coordinator.suspend_current(sandbox_id);

    assert_eq!(coordinator.current_request(sandbox_id), Some(request));
    assert_eq!(coordinator.outcome(old_attempt), None);
    let new_attempt = coordinator
        .retarget_current(sandbox_id, DeliveryTarget::Node("node-c".to_string()), 4)
        .expect("retarget current delivery")
        .expect("current delivery context");
    assert_ne!(new_attempt.attempt_id, old_attempt.attempt_id);
}

#[test]
fn coordinator_rejects_a_response_older_than_the_published_world_revision() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();
    let session = coordinator.open_node_session("node-a");
    let attempt = coordinator
        .begin_attempt(
            DeliveryRequest {
                authority_epoch: 9,
                sandbox_id,
                generation: generation("g9", 9),
            },
            DeliveryTarget::Node("node-a".to_string()),
            HashSet::from([ResourceType::Listener]),
        )
        .expect("delivery attempt");
    coordinator
        .mark_published(attempt, 12, HashSet::from([ResourceType::Listener]))
        .expect("publish attempt");
    let delivered = [DeliveredResource {
        name: "listener".to_string(),
        owner: ResourceOwner::Sandbox(sandbox_id),
        removed: false,
    }];

    assert_eq!(
        coordinator
            .record_response(
                "node-a",
                session,
                "stale",
                11,
                ResourceType::Listener,
                &delivered,
            )
            .expect("stale response is valid but irrelevant"),
        ReceiptOutcome::Stale
    );
    assert_eq!(coordinator.outcome(attempt), None);
}
