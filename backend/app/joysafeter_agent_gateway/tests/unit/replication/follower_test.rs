use super::*;

use std::sync::Arc;

use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, PolicyGeneration};
use tokio::sync::Mutex;

use crate::application::policy_publisher::PolicyPublisher;
use crate::application::PolicyProjectionRegistry;
use crate::ids::SandboxId;
use crate::replication::model::{ReplicaMutation, ReplicatedPolicy, WatchReplicaQuery};
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};

fn test_runner() -> FollowerRunner {
    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let projections = PolicyProjectionRegistry::default();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let projector = ReplicaProjector::new(
        control_plane,
        publisher,
        projections,
        Arc::new(Mutex::new(())),
    );
    let coordinator = ReplicationCoordinator::new("follower", 0, Duration::from_secs(1));
    FollowerRunner {
        channel: Endpoint::from_static("http://127.0.0.1:1").connect_lazy(),
        token: "replica-token".to_string(),
        replica_id: "replica-1".to_string(),
        coordinator,
        projector,
        cursor: ReplicaCursor::default(),
        staging: None,
        transport: FollowerTransportConfig::default(),
    }
}

fn event(revision: u64, payload: ReplicaEventPayload) -> ReplicaEvent {
    ReplicaEvent {
        protocol_version: REPLICATION_PROTOCOL_VERSION,
        source_instance: "leader-a".to_string(),
        term: "term-a".to_string(),
        revision,
        snapshot_digest: "digest-a".to_string(),
        payload,
    }
}

fn policy_with(sandbox_id: &SandboxId, version: i64) -> ReplicatedPolicy {
    ReplicatedPolicy {
        sandbox_id: sandbox_id.to_string(),
        policy: ApplySandboxPolicyRequest {
            generation: PolicyGeneration {
                policy_hash: format!("{version:064x}"),
                policy_version: version,
            },
            allowlist_hosts: vec!["api.openai.com".to_string()],
            credential_routes: Vec::new(),
            proxy_auth_token: None,
        },
    }
}

fn snapshot_with(sandbox_id: &SandboxId) -> ReplicatedSnapshot {
    ReplicatedSnapshot {
        policies: vec![policy_with(sandbox_id, 1)],
        placements: Vec::new(),
    }
}

#[test]
fn ensure_identity_matches_only_when_all_fields_agree() {
    let staging = StagingSnapshot {
        source_instance: "leader-a".to_string(),
        term: "term-a".to_string(),
        revision: 2,
        digest: "digest-a".to_string(),
        chunk_count: 1,
        next_chunk: 0,
        snapshot: ReplicatedSnapshot::default(),
    };
    let matching = event(2, ReplicaEventPayload::SnapshotEnd);
    assert!(ensure_identity(&staging, &matching).is_ok());

    for mismatched in [
        ReplicaEvent {
            source_instance: "leader-b".to_string(),
            ..matching.clone()
        },
        ReplicaEvent {
            term: "term-b".to_string(),
            ..matching.clone()
        },
        ReplicaEvent {
            revision: 3,
            ..matching.clone()
        },
        ReplicaEvent {
            snapshot_digest: "digest-b".to_string(),
            ..matching.clone()
        },
    ] {
        assert!(ensure_identity(&staging, &mismatched).is_err());
    }
}

#[test]
fn reconnect_delay_is_jittered_and_strictly_bounded() {
    for (attempt, lower_ms, upper_ms) in [
        (1, 75, 100),
        (2, 150, 200),
        (3, 300, 400),
        (7, 3_750, 5_000),
        (100, 3_750, 5_000),
    ] {
        for _ in 0..32 {
            let delay = reconnect_delay(attempt);
            assert!(delay >= Duration::from_millis(lower_ms));
            assert!(delay <= Duration::from_millis(upper_ms));
        }
    }
}

#[tokio::test]
async fn an_unsupported_protocol_version_is_rejected() {
    let mut runner = test_runner();
    let mut event = event(1, ReplicaEventPayload::SnapshotEnd);
    event.protocol_version = REPLICATION_PROTOCOL_VERSION + 1;
    assert!(runner.apply_event(event).await.is_err());
}

#[tokio::test]
async fn a_chunk_before_begin_is_rejected() {
    let mut runner = test_runner();
    let event = event(
        1,
        ReplicaEventPayload::SnapshotChunk {
            chunk_index: 0,
            snapshot: ReplicatedSnapshot::default(),
        },
    );
    assert!(runner.apply_event(event).await.is_err());
}

#[tokio::test]
async fn a_snapshot_end_before_begin_is_rejected() {
    let mut runner = test_runner();
    let event = event(1, ReplicaEventPayload::SnapshotEnd);
    assert!(runner.apply_event(event).await.is_err());
}

#[tokio::test]
async fn out_of_order_chunks_are_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(event(
            1,
            ReplicaEventPayload::SnapshotBegin { chunk_count: 2 },
        ))
        .await
        .expect("begin");
    // Chunk 0 is skipped; chunk 1 must be rejected.
    let event = event(
        1,
        ReplicaEventPayload::SnapshotChunk {
            chunk_index: 1,
            snapshot: ReplicatedSnapshot::default(),
        },
    );
    assert!(runner.apply_event(event).await.is_err());
}

#[tokio::test]
async fn a_snapshot_end_before_all_chunks_arrive_is_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(event(
            1,
            ReplicaEventPayload::SnapshotBegin { chunk_count: 2 },
        ))
        .await
        .expect("begin");
    runner
        .apply_event(event(
            1,
            ReplicaEventPayload::SnapshotChunk {
                chunk_index: 0,
                snapshot: ReplicatedSnapshot::default(),
            },
        ))
        .await
        .expect("chunk 0");
    // Only 1 of 2 chunks delivered.
    assert!(runner
        .apply_event(event(1, ReplicaEventPayload::SnapshotEnd))
        .await
        .is_err());
}

#[tokio::test]
async fn a_chunk_with_changed_identity_is_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(event(
            1,
            ReplicaEventPayload::SnapshotBegin { chunk_count: 2 },
        ))
        .await
        .expect("begin");
    let mut event = event(
        1,
        ReplicaEventPayload::SnapshotChunk {
            chunk_index: 0,
            snapshot: ReplicatedSnapshot::default(),
        },
    );
    event.term = "a-different-term".to_string();
    assert!(runner.apply_event(event).await.is_err());
}

#[tokio::test]
async fn chunks_reassemble_in_order_into_staging() {
    let mut runner = test_runner();
    let first = SandboxId::new();
    let second = SandboxId::new();
    runner
        .apply_event(event(
            3,
            ReplicaEventPayload::SnapshotBegin { chunk_count: 2 },
        ))
        .await
        .expect("begin");
    runner
        .apply_event(event(
            3,
            ReplicaEventPayload::SnapshotChunk {
                chunk_index: 0,
                snapshot: snapshot_with(&first),
            },
        ))
        .await
        .expect("chunk 0");
    runner
        .apply_event(event(
            3,
            ReplicaEventPayload::SnapshotChunk {
                chunk_index: 1,
                snapshot: snapshot_with(&second),
            },
        ))
        .await
        .expect("chunk 1");

    let staging = runner.staging.as_ref().expect("staging retained");
    assert_eq!(staging.next_chunk, 2);
    assert_eq!(staging.snapshot.policies.len(), 2);
}

fn fresh_watch_query() -> WatchReplicaQuery {
    WatchReplicaQuery {
        protocol_version: REPLICATION_PROTOCOL_VERSION,
        replica_id: "replica-1".to_string(),
        session_id: None,
        term: None,
        revision: None,
        snapshot_digest: None,
    }
}

#[tokio::test]
async fn happy_path_installs_a_snapshot_and_produces_ack_metadata() {
    // A real leader produces correctly-digested snapshot events.
    let leader = ReplicationCoordinator::new("leader-1", 0, Duration::from_secs(1));
    leader.begin_leader_term(1).await.expect("leader term");
    leader
        .publish(
            1,
            ReplicaMutation::UpsertPolicy {
                policy: policy_with(&SandboxId::new(), 1),
            },
        )
        .await
        .expect("publish");
    let response = leader
        .watch(fresh_watch_query(), Duration::from_millis(200))
        .await
        .expect("watch");
    assert!(response.events.len() >= 3, "begin + chunk(s) + end");

    let mut runner = test_runner();
    let mut installed = None;
    for event in response.events {
        installed = runner
            .apply_event(event)
            .await
            .expect("apply event")
            .or(installed);
    }
    let installed = installed.expect("snapshot end produces acknowledgement metadata");
    runner.set_cursor(&response.session_id, installed);
    assert_eq!(runner.cursor.revision, Some(1));
    assert!(runner.cursor.digest.is_some());
    assert_eq!(
        runner.cursor.session_id.as_deref(),
        Some(response.session_id.as_str())
    );
}

#[tokio::test]
async fn happy_path_applies_a_delta_after_a_snapshot() {
    let leader = ReplicationCoordinator::new("leader-1", 0, Duration::from_secs(1));
    leader.begin_leader_term(1).await.expect("leader term");
    leader
        .publish(
            1,
            ReplicaMutation::UpsertPolicy {
                policy: policy_with(&SandboxId::new(), 1),
            },
        )
        .await
        .expect("publish snapshot policy");

    let mut runner = test_runner();
    let snapshot = leader
        .watch(fresh_watch_query(), Duration::from_millis(200))
        .await
        .expect("snapshot watch");
    let mut installed = None;
    for event in snapshot.events {
        installed = runner
            .apply_event(event)
            .await
            .expect("apply snapshot")
            .or(installed);
    }
    runner.set_cursor(
        &snapshot.session_id,
        installed.expect("snapshot acknowledgement metadata"),
    );
    assert_eq!(runner.cursor.revision, Some(1));

    // A follow-up placement delta.
    leader
        .publish(
            1,
            ReplicaMutation::UpsertPlacement {
                placement: joysafeter_agent_gateway_contract::SandboxPlacement {
                    sandbox_id: SandboxId::new().to_string(),
                    node_id: "node-a".to_string(),
                },
            },
        )
        .await
        .expect("publish delta");
    let delta = leader
        .watch(
            WatchReplicaQuery {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: "replica-1".to_string(),
                session_id: Some(snapshot.session_id.clone()),
                term: runner.cursor.term.clone(),
                revision: runner.cursor.revision,
                snapshot_digest: runner.cursor.digest.clone(),
            },
            Duration::from_millis(200),
        )
        .await
        .expect("delta watch");
    assert!(!delta.events.is_empty());
    let mut applied = None;
    for event in delta.events {
        applied = runner
            .apply_event(event)
            .await
            .expect("apply delta")
            .or(applied);
    }
    runner.set_cursor(
        &delta.session_id,
        applied.expect("delta acknowledgement metadata"),
    );
    assert_eq!(runner.cursor.revision, Some(2));
}
