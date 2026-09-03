use std::time::Duration;

use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, PolicyGeneration};

use super::*;
use crate::replication::model::ReplicatedPolicy;

fn policy(id: &str, version: i64) -> ReplicatedPolicy {
    ReplicatedPolicy {
        sandbox_id: id.to_string(),
        policy: ApplySandboxPolicyRequest {
            generation: PolicyGeneration {
                policy_hash: format!("{version:064x}"),
                policy_version: version,
            },
            allowlist_hosts: Vec::new(),
            credential_routes: Vec::new(),
            proxy_auth_token: None,
        },
    }
}

#[tokio::test]
async fn a_new_session_receives_a_complete_chunked_snapshot() {
    let coordinator = ReplicationCoordinator::new("leader", 0, Duration::from_secs(1));
    coordinator.begin_leader_term(7).await.expect("leader term");
    coordinator
        .publish(
            7,
            ReplicaMutation::UpsertPolicy {
                policy: policy("sandbox-a", 1),
            },
        )
        .await
        .expect("publish");

    let response = coordinator
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "follower".to_string(),
                ..WatchReplicaQuery::default()
            },
            Duration::from_millis(1),
        )
        .await
        .expect("watch");

    assert!(matches!(
        response.events.first().map(|event| &event.payload),
        Some(ReplicaEventPayload::SnapshotBegin { .. })
    ));
    assert!(matches!(
        response.events.last().map(|event| &event.payload),
        Some(ReplicaEventPayload::SnapshotEnd)
    ));
}

#[tokio::test]
async fn delayed_ack_from_an_old_session_is_rejected() {
    let coordinator = ReplicationCoordinator::new("leader", 0, Duration::from_secs(1));
    coordinator.begin_leader_term(1).await.expect("leader term");
    let first = coordinator
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "follower".to_string(),
                ..WatchReplicaQuery::default()
            },
            Duration::from_millis(1),
        )
        .await
        .expect("first watch");
    let event = first.events.last().expect("snapshot end");

    coordinator
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "follower".to_string(),
                session_id: Some("wrong-session".to_string()),
                ..WatchReplicaQuery::default()
            },
            Duration::from_millis(1),
        )
        .await
        .expect("replace session");

    let error = coordinator
        .acknowledge(AckReplicaRequest {
            protocol_version: REPLICATION_PROTOCOL_VERSION,
            replica_id: "follower".to_string(),
            session_id: first.session_id,
            source_instance: event.source_instance.clone(),
            term: event.term.clone(),
            revision: event.revision,
            snapshot_digest: event.snapshot_digest.clone(),
        })
        .await
        .expect_err("old ACK must be fenced");
    assert!(matches!(error, ReplicationError::InvalidAck));
}

#[tokio::test]
async fn revision_gap_invalidates_the_hot_snapshot() {
    let coordinator = ReplicationCoordinator::new("follower", 0, Duration::from_secs(1));
    let snapshot = ReplicatedSnapshot::default();
    let digest = snapshot_digest(&snapshot).expect("digest");
    coordinator
        .install_follower_snapshot(
            snapshot,
            HotSnapshotMetadata {
                source_instance: "leader".to_string(),
                term: "term-a".to_string(),
                revision: 4,
                snapshot_digest: digest,
            },
        )
        .await
        .expect("snapshot");

    let error = coordinator
        .apply_follower_delta(
            ReplicaMutation::RemovePolicy {
                sandbox_id: "sandbox-a".to_string(),
            },
            HotSnapshotMetadata {
                source_instance: "leader".to_string(),
                term: "term-a".to_string(),
                revision: 6,
                snapshot_digest: "irrelevant".to_string(),
            },
        )
        .await
        .expect_err("gap must fail");
    assert!(error.to_string().contains("revision gap"));
}

#[tokio::test]
async fn publish_waits_for_an_ack_from_the_active_follower_session() {
    let coordinator = ReplicationCoordinator::new("leader", 1, Duration::from_secs(1));
    coordinator.begin_leader_term(9).await.expect("leader term");
    let initial = coordinator
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "follower".to_string(),
                ..WatchReplicaQuery::default()
            },
            Duration::from_millis(1),
        )
        .await
        .expect("initial snapshot");
    let initial_end = initial.events.last().expect("snapshot end").clone();
    coordinator
        .acknowledge(AckReplicaRequest {
            protocol_version: REPLICATION_PROTOCOL_VERSION,
            replica_id: "follower".to_string(),
            session_id: initial.session_id.clone(),
            source_instance: initial_end.source_instance.clone(),
            term: initial_end.term.clone(),
            revision: initial_end.revision,
            snapshot_digest: initial_end.snapshot_digest.clone(),
        })
        .await
        .expect("initial ACK");

    let publisher = coordinator.clone();
    let publish = tokio::spawn(async move {
        publisher
            .publish(
                9,
                ReplicaMutation::UpsertPolicy {
                    policy: policy("sandbox-a", 1),
                },
            )
            .await
    });
    let delta = coordinator
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "follower".to_string(),
                session_id: Some(initial.session_id.clone()),
                term: Some(initial_end.term.clone()),
                revision: Some(initial_end.revision),
                snapshot_digest: Some(initial_end.snapshot_digest),
            },
            Duration::from_secs(1),
        )
        .await
        .expect("delta watch");
    let event = delta.events.last().expect("delta event");
    assert!(matches!(event.payload, ReplicaEventPayload::Delta { .. }));
    coordinator
        .acknowledge(AckReplicaRequest {
            protocol_version: REPLICATION_PROTOCOL_VERSION,
            replica_id: "follower".to_string(),
            session_id: delta.session_id,
            source_instance: event.source_instance.clone(),
            term: event.term.clone(),
            revision: event.revision,
            snapshot_digest: event.snapshot_digest.clone(),
        })
        .await
        .expect("delta ACK");
    publish.await.expect("publish task").expect("ACK quorum");
}

#[tokio::test]
async fn digest_mismatch_makes_a_follower_snapshot_non_promotable() {
    let coordinator = ReplicationCoordinator::new("follower", 0, Duration::from_secs(1));
    let error = coordinator
        .install_follower_snapshot(
            ReplicatedSnapshot::default(),
            HotSnapshotMetadata {
                source_instance: "leader".to_string(),
                term: "term".to_string(),
                revision: 0,
                snapshot_digest: "wrong".to_string(),
            },
        )
        .await
        .expect_err("digest mismatch");
    assert!(matches!(error, ReplicationError::InvalidSnapshot(_)));
    assert!(coordinator.hot_metadata().await.is_none());
}

#[tokio::test]
async fn promotion_preserves_only_a_complete_digest_verified_snapshot() {
    let coordinator = ReplicationCoordinator::new("follower", 0, Duration::from_secs(1));
    let snapshot = ReplicatedSnapshot {
        policies: vec![policy("sandbox-a", 1)],
        placements: Vec::new(),
    };
    let digest = snapshot_digest(&snapshot).expect("digest");
    coordinator
        .install_follower_snapshot(
            snapshot,
            HotSnapshotMetadata {
                source_instance: "leader".to_string(),
                term: "term".to_string(),
                revision: 3,
                snapshot_digest: digest,
            },
        )
        .await
        .expect("hot snapshot");

    let promoted = coordinator
        .begin_leader_term(2)
        .await
        .expect("promote")
        .expect("hot snapshot retained");
    assert_eq!(promoted.policies.len(), 1);
}

#[tokio::test]
async fn duplicate_revision_is_idempotent() {
    let coordinator = ReplicationCoordinator::new("follower", 0, Duration::from_secs(1));
    let snapshot = ReplicatedSnapshot::default();
    let digest = snapshot_digest(&snapshot).expect("digest");
    let metadata = HotSnapshotMetadata {
        source_instance: "leader".to_string(),
        term: "term".to_string(),
        revision: 2,
        snapshot_digest: digest,
    };
    coordinator
        .install_follower_snapshot(snapshot, metadata.clone())
        .await
        .expect("snapshot");

    let changed = coordinator
        .apply_follower_delta(
            ReplicaMutation::RemovePolicy {
                sandbox_id: "sandbox-a".to_string(),
            },
            metadata,
        )
        .await
        .expect("duplicate is accepted");
    assert!(!changed);
}

#[tokio::test]
async fn promotion_without_a_complete_snapshot_falls_back_to_empty_state() {
    let coordinator = ReplicationCoordinator::new("replica", 0, Duration::from_secs(1));
    coordinator.begin_leader_term(1).await.expect("first term");
    coordinator
        .publish(
            1,
            ReplicaMutation::UpsertPolicy {
                policy: policy("sandbox-a", 1),
            },
        )
        .await
        .expect("publish");
    coordinator.demote().await;

    let hot = coordinator.begin_leader_term(2).await.expect("new term");
    assert!(hot.is_none());
    assert!(coordinator.current_snapshot().await.policies.is_empty());
}
