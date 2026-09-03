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

/// A follower runner wired to inert, in-memory collaborators. The error paths
/// exercised here bail before any coordinator/projector/HTTP interaction, so the
/// collaborators are never actually driven.
fn test_runner() -> FollowerRunner {
    runner_with_ack(Url::parse("http://127.0.0.1/internal/v1/replication/ack").expect("ack url"))
}

/// A follower runner whose ack endpoint points at `ack_url` (a real test server),
/// used by the happy-path integration tests that drive `apply_event` end to end.
fn runner_with_ack(ack_url: Url) -> FollowerRunner {
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
        client: Client::builder().build().expect("client"),
        watch_url: Url::parse("http://127.0.0.1/internal/v1/replication/watch").expect("watch url"),
        ack_url,
        token: "replica-token".to_string(),
        replica_id: "replica-1".to_string(),
        coordinator,
        projector,
        cursor: ReplicaCursor::default(),
        staging: None,
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

#[tokio::test]
async fn an_unsupported_protocol_version_is_rejected() {
    let mut runner = test_runner();
    let mut event = event(1, ReplicaEventPayload::SnapshotEnd);
    event.protocol_version = REPLICATION_PROTOCOL_VERSION + 1;
    assert!(runner.apply_event("session-1", event).await.is_err());
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
    assert!(runner.apply_event("session-1", event).await.is_err());
}

#[tokio::test]
async fn a_snapshot_end_before_begin_is_rejected() {
    let mut runner = test_runner();
    let event = event(1, ReplicaEventPayload::SnapshotEnd);
    assert!(runner.apply_event("session-1", event).await.is_err());
}

#[tokio::test]
async fn out_of_order_chunks_are_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(
            "session-1",
            event(1, ReplicaEventPayload::SnapshotBegin { chunk_count: 2 }),
        )
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
    assert!(runner.apply_event("session-1", event).await.is_err());
}

#[tokio::test]
async fn a_snapshot_end_before_all_chunks_arrive_is_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(
            "session-1",
            event(1, ReplicaEventPayload::SnapshotBegin { chunk_count: 2 }),
        )
        .await
        .expect("begin");
    runner
        .apply_event(
            "session-1",
            event(
                1,
                ReplicaEventPayload::SnapshotChunk {
                    chunk_index: 0,
                    snapshot: ReplicatedSnapshot::default(),
                },
            ),
        )
        .await
        .expect("chunk 0");
    // Only 1 of 2 chunks delivered.
    assert!(runner
        .apply_event("session-1", event(1, ReplicaEventPayload::SnapshotEnd))
        .await
        .is_err());
}

#[tokio::test]
async fn a_chunk_with_changed_identity_is_rejected() {
    let mut runner = test_runner();
    runner
        .apply_event(
            "session-1",
            event(1, ReplicaEventPayload::SnapshotBegin { chunk_count: 2 }),
        )
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
    assert!(runner.apply_event("session-1", event).await.is_err());
}

#[tokio::test]
async fn chunks_reassemble_in_order_into_staging() {
    let mut runner = test_runner();
    let first = SandboxId::new();
    let second = SandboxId::new();
    runner
        .apply_event(
            "session-1",
            event(3, ReplicaEventPayload::SnapshotBegin { chunk_count: 2 }),
        )
        .await
        .expect("begin");
    runner
        .apply_event(
            "session-1",
            event(
                3,
                ReplicaEventPayload::SnapshotChunk {
                    chunk_index: 0,
                    snapshot: snapshot_with(&first),
                },
            ),
        )
        .await
        .expect("chunk 0");
    runner
        .apply_event(
            "session-1",
            event(
                3,
                ReplicaEventPayload::SnapshotChunk {
                    chunk_index: 1,
                    snapshot: snapshot_with(&second),
                },
            ),
        )
        .await
        .expect("chunk 1");

    let staging = runner.staging.as_ref().expect("staging retained");
    assert_eq!(staging.next_chunk, 2);
    assert_eq!(staging.snapshot.policies.len(), 2);
}

/// Stand up a minimal in-process leader that only serves the ack endpoint, and
/// return its base URL plus a receiver of the acks it observes.
async fn spawn_ack_server() -> (Url, tokio::sync::mpsc::UnboundedReceiver<AckReplicaRequest>) {
    use axum::extract::State;
    use axum::routing::post;
    use axum::{Json, Router};
    use tokio::net::TcpListener;
    use tokio::sync::mpsc::UnboundedSender;

    let (tx, rx) = tokio::sync::mpsc::unbounded_channel::<AckReplicaRequest>();
    let app = Router::new()
        .route(
            "/internal/v1/replication/ack",
            post(
                |State(tx): State<UnboundedSender<AckReplicaRequest>>,
                 Json(request): Json<AckReplicaRequest>| async move {
                    let _ = tx.send(request);
                    Json(AckReplicaResponse { accepted: true })
                },
            ),
        )
        .with_state(tx);
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let addr = listener.local_addr().expect("addr");
    tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    let base = Url::parse(&format!("http://{addr}")).expect("base url");
    (base, rx)
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
async fn happy_path_installs_a_snapshot_and_acknowledges_over_http() {
    let (base, mut acks) = spawn_ack_server().await;
    let ack_url = base.join("/internal/v1/replication/ack").expect("ack url");

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

    // The follower applies them end to end: install + HTTP ack.
    let mut runner = runner_with_ack(ack_url);
    for event in response.events {
        runner
            .apply_event(&response.session_id, event)
            .await
            .expect("apply event");
    }

    // Cursor advanced to the installed revision, and the leader saw the ack.
    assert_eq!(runner.cursor.revision, Some(1));
    assert!(runner.cursor.digest.is_some());
    assert_eq!(
        runner.cursor.session_id.as_deref(),
        Some(response.session_id.as_str())
    );

    let ack = tokio::time::timeout(Duration::from_secs(1), acks.recv())
        .await
        .expect("ack delivered promptly")
        .expect("ack sent");
    assert_eq!(ack.replica_id, "replica-1");
    assert_eq!(ack.revision, 1);
}

#[tokio::test]
async fn happy_path_applies_a_delta_after_a_snapshot() {
    let (base, mut acks) = spawn_ack_server().await;
    let ack_url = base.join("/internal/v1/replication/ack").expect("ack url");

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

    let mut runner = runner_with_ack(ack_url);
    let snapshot = leader
        .watch(fresh_watch_query(), Duration::from_millis(200))
        .await
        .expect("snapshot watch");
    for event in snapshot.events {
        runner
            .apply_event(&snapshot.session_id, event)
            .await
            .expect("apply snapshot");
    }
    let _snapshot_ack = acks.recv().await.expect("snapshot ack");
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
    for event in delta.events {
        runner
            .apply_event(&delta.session_id, event)
            .await
            .expect("apply delta");
    }

    assert_eq!(runner.cursor.revision, Some(2));
    let ack = tokio::time::timeout(Duration::from_secs(1), acks.recv())
        .await
        .expect("delta ack delivered promptly")
        .expect("delta ack sent");
    assert_eq!(ack.revision, 2);
}
