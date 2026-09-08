use std::collections::HashSet;
use std::pin::Pin;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use futures::Stream;
use prost::Message;
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tokio::sync::{mpsc, OwnedSemaphorePermit, Semaphore};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Code, Request, Response, Status};

use super::management_grpc::MAX_REPLICATION_MESSAGE_BYTES;
use crate::proto::gateway_management::{
    gateway_replication_service_server::GatewayReplicationService, replication_stream_request,
    replication_stream_response, ReplicaAckAccepted, ReplicaEventBatch, ReplicationStreamRequest,
    ReplicationStreamResponse,
};
use crate::replication::model::{AckReplicaRequest, WatchReplicaQuery};
use crate::replication::{ReplicationCoordinator, ReplicationError};

const REPLICATION_WATCH_WAIT: Duration = Duration::from_secs(30);
const REPLICATION_ACK_WAIT: Duration = Duration::from_secs(10);

#[derive(Clone)]
pub struct GatewayReplicationServer {
    coordinator: ReplicationCoordinator,
    auth_digest: Option<[u8; 32]>,
    stream_permits: Arc<Semaphore>,
    active_replica_ids: Arc<StdMutex<HashSet<String>>>,
}

impl GatewayReplicationServer {
    pub fn new(coordinator: ReplicationCoordinator, token: Option<&str>) -> Self {
        Self::with_max_streams(coordinator, token, 32)
    }

    pub fn with_max_streams(
        coordinator: ReplicationCoordinator,
        token: Option<&str>,
        max_streams: usize,
    ) -> Self {
        Self {
            coordinator,
            auth_digest: token.map(|value| Sha256::digest(value.trim().as_bytes()).into()),
            stream_permits: Arc::new(Semaphore::new(max_streams)),
            active_replica_ids: Arc::new(StdMutex::new(HashSet::new())),
        }
    }

    #[allow(clippy::result_large_err)]
    fn authenticate<T>(&self, request: &Request<T>) -> Result<(), Status> {
        let expected = self.auth_digest.ok_or_else(|| {
            Status::new(
                Code::Unavailable,
                "replication is not enabled on this Gateway",
            )
        })?;
        let token = request
            .metadata()
            .get("authorization")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "))
            .ok_or_else(|| {
                Status::new(Code::Unauthenticated, "replication authentication failed")
            })?;
        let candidate: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        if bool::from(candidate.ct_eq(&expected)) {
            Ok(())
        } else {
            Err(Status::new(
                Code::Unauthenticated,
                "replication authentication failed",
            ))
        }
    }
}

#[tonic::async_trait]
impl GatewayReplicationService for GatewayReplicationServer {
    type ReplicateStream =
        Pin<Box<dyn Stream<Item = Result<ReplicationStreamResponse, Status>> + Send + 'static>>;

    async fn replicate(
        &self,
        request: Request<tonic::Streaming<ReplicationStreamRequest>>,
    ) -> Result<Response<Self::ReplicateStream>, Status> {
        self.authenticate(&request)?;
        let stream_permit = self
            .stream_permits
            .clone()
            .try_acquire_owned()
            .map_err(|_| Status::resource_exhausted("replication stream capacity is exhausted"))?;
        let mut inbound = request.into_inner();
        let first = inbound
            .message()
            .await?
            .ok_or_else(|| Status::invalid_argument("replica open frame is required"))?;
        let open = match first.message {
            Some(replication_stream_request::Message::Open(open)) => open,
            _ => return Err(Status::invalid_argument("replica open frame must be first")),
        };
        if open.replica_id.trim().is_empty() || open.replica_id.len() > 128 {
            return Err(Status::invalid_argument("replica_id is invalid"));
        }
        let replica_guard = ActiveReplicaGuard::acquire(
            self.active_replica_ids.clone(),
            open.replica_id.clone(),
            stream_permit,
        )?;
        let mut cursor = WatchReplicaQuery {
            protocol_version: u16::try_from(open.protocol_version)
                .map_err(|_| Status::invalid_argument("invalid replication protocol version"))?,
            replica_id: open.replica_id,
            session_id: open.session_id,
            term: open.term,
            revision: open.revision,
            snapshot_digest: open.snapshot_digest,
        };
        let coordinator = self.coordinator.clone();
        let (response_tx, response_rx) = mpsc::channel(16);
        tokio::spawn(async move {
            let _replica_guard = replica_guard;
            loop {
                let watched = match coordinator
                    .watch(cursor.clone(), REPLICATION_WATCH_WAIT)
                    .await
                {
                    Ok(watched) => watched,
                    Err(error) => {
                        let _ = response_tx.send(Err(replication_status(error))).await;
                        return;
                    }
                };
                if watched.events.is_empty() {
                    continue;
                }
                let events = match watched
                    .events
                    .into_iter()
                    .map(crate::adapters::proto_conversion::replica_event_to_proto)
                    .collect::<anyhow::Result<Vec<_>>>()
                {
                    Ok(events) => events,
                    Err(_) => {
                        let _ = response_tx
                            .send(Err(Status::internal("failed to encode replication event")))
                            .await;
                        return;
                    }
                };
                let batches = match replication_batches(&watched.session_id, events) {
                    Ok(batches) => batches,
                    Err(status) => {
                        let _ = response_tx.send(Err(status)).await;
                        return;
                    }
                };
                for batch in batches {
                    let requires_ack = batch_requires_ack(&batch);
                    if response_tx
                        .send(Ok(ReplicationStreamResponse {
                            message: Some(replication_stream_response::Message::Events(batch)),
                        }))
                        .await
                        .is_err()
                    {
                        return;
                    }
                    if !requires_ack {
                        continue;
                    }
                    let ack =
                        match tokio::time::timeout(REPLICATION_ACK_WAIT, inbound.message()).await {
                            Ok(Ok(Some(frame))) => match frame.message {
                                Some(replication_stream_request::Message::Ack(ack)) => ack,
                                _ => {
                                    let _ = response_tx
                                        .send(Err(Status::invalid_argument(
                                            "replica acknowledgement frame is required",
                                        )))
                                        .await;
                                    return;
                                }
                            },
                            Ok(Ok(None)) => return,
                            Ok(Err(status)) => {
                                let _ = response_tx.send(Err(status)).await;
                                return;
                            }
                            Err(_) => {
                                let _ = response_tx
                                    .send(Err(Status::deadline_exceeded(
                                        "replica acknowledgement timed out",
                                    )))
                                    .await;
                                return;
                            }
                        };
                    let ack = match ack_from_proto(ack) {
                        Ok(ack) => ack,
                        Err(status) => {
                            let _ = response_tx.send(Err(status)).await;
                            return;
                        }
                    };
                    if let Err(error) = coordinator.acknowledge(ack.clone()).await {
                        let _ = response_tx.send(Err(replication_status(error))).await;
                        return;
                    }
                    cursor.session_id = Some(ack.session_id.clone());
                    cursor.term = Some(ack.term.clone());
                    cursor.revision = Some(ack.revision);
                    cursor.snapshot_digest = Some(ack.snapshot_digest.clone());
                    if response_tx
                        .send(Ok(ReplicationStreamResponse {
                            message: Some(replication_stream_response::Message::Acknowledged(
                                ReplicaAckAccepted {
                                    session_id: ack.session_id,
                                    term: ack.term,
                                    revision: ack.revision,
                                    snapshot_digest: ack.snapshot_digest,
                                },
                            )),
                        }))
                        .await
                        .is_err()
                    {
                        return;
                    }
                }
            }
        });
        Ok(Response::new(Box::pin(ReceiverStream::new(response_rx))))
    }
}

fn batch_requires_ack(batch: &ReplicaEventBatch) -> bool {
    batch.events.last().is_some_and(|event| {
        matches!(
            event.payload.as_ref(),
            Some(crate::proto::gateway_management::replica_event::Payload::SnapshotEnd(_))
                | Some(crate::proto::gateway_management::replica_event::Payload::Delta(_))
        )
    })
}

struct ActiveReplicaGuard {
    active_replica_ids: Arc<StdMutex<HashSet<String>>>,
    replica_id: String,
    _stream_permit: OwnedSemaphorePermit,
}

impl ActiveReplicaGuard {
    #[allow(clippy::result_large_err)]
    fn acquire(
        active_replica_ids: Arc<StdMutex<HashSet<String>>>,
        replica_id: String,
        stream_permit: OwnedSemaphorePermit,
    ) -> Result<Self, Status> {
        {
            let mut active = active_replica_ids
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if !active.insert(replica_id.clone()) {
                return Err(Status::already_exists(
                    "replica already has an active replication stream",
                ));
            }
        }
        Ok(Self {
            active_replica_ids,
            replica_id,
            _stream_permit: stream_permit,
        })
    }
}

impl Drop for ActiveReplicaGuard {
    fn drop(&mut self) {
        self.active_replica_ids
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.replica_id);
    }
}

#[allow(clippy::result_large_err)]
fn replication_batches(
    session_id: &str,
    events: Vec<crate::proto::gateway_management::ReplicaEvent>,
) -> Result<Vec<ReplicaEventBatch>, Status> {
    let mut batches = Vec::new();
    let mut current = Vec::new();
    for event in events {
        let mut candidate = current.clone();
        candidate.push(event.clone());
        let response = ReplicationStreamResponse {
            message: Some(replication_stream_response::Message::Events(
                ReplicaEventBatch {
                    session_id: session_id.to_string(),
                    events: candidate,
                },
            )),
        };
        if response.encoded_len() > MAX_REPLICATION_MESSAGE_BYTES {
            if current.is_empty() {
                return Err(Status::resource_exhausted(
                    "one replication event exceeds the transport size limit",
                ));
            }
            batches.push(ReplicaEventBatch {
                session_id: session_id.to_string(),
                events: std::mem::take(&mut current),
            });
        }
        current.push(event);
    }
    if !current.is_empty() {
        batches.push(ReplicaEventBatch {
            session_id: session_id.to_string(),
            events: current,
        });
    }
    Ok(batches)
}

#[allow(clippy::result_large_err)]
fn ack_from_proto(
    ack: crate::proto::gateway_management::ReplicaAck,
) -> Result<AckReplicaRequest, Status> {
    Ok(AckReplicaRequest {
        protocol_version: u16::try_from(ack.protocol_version)
            .map_err(|_| Status::invalid_argument("invalid replication protocol version"))?,
        replica_id: ack.replica_id,
        session_id: ack.session_id,
        source_instance: ack.source_instance,
        term: ack.term,
        revision: ack.revision,
        snapshot_digest: ack.snapshot_digest,
    })
}

fn replication_status(error: ReplicationError) -> Status {
    match error {
        ReplicationError::NotLeader => Status::unavailable("replication leader is unavailable"),
        ReplicationError::InvalidAck => {
            Status::failed_precondition("replica acknowledgement is invalid")
        }
        ReplicationError::InvalidSnapshot(_) => {
            Status::invalid_argument("replica state is invalid")
        }
        ReplicationError::AckTimeout { .. } => {
            Status::deadline_exceeded("replica acknowledgement quorum timed out")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, PolicyGeneration};
    use tokio::net::TcpListener;
    use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
    use tonic::transport::Server;

    use crate::proto::gateway_management::{
        gateway_replication_service_client::GatewayReplicationServiceClient,
        gateway_replication_service_server::GatewayReplicationServiceServer,
        replication_stream_request, replication_stream_response, ReplicaAck, ReplicaOpen,
    };
    use crate::replication::model::{
        ReplicaMutation, ReplicatedPolicy, REPLICATION_PROTOCOL_VERSION,
    };

    #[test]
    fn replication_batches_never_exceed_the_transport_limit() {
        let events = (0..3)
            .map(|index| crate::proto::gateway_management::ReplicaEvent {
                protocol_version: 1,
                source_instance: "x".repeat(2 * 1024 * 1024),
                term: format!("term-{index}"),
                revision: index,
                snapshot_digest: "a".repeat(64),
                payload: Some(
                    crate::proto::gateway_management::replica_event::Payload::SnapshotEnd(
                        crate::proto::gateway_management::Empty {},
                    ),
                ),
            })
            .collect();
        let batches = replication_batches("session", events).expect("bounded batches");
        assert!(batches.len() > 1);
        for batch in batches {
            let response = ReplicationStreamResponse {
                message: Some(replication_stream_response::Message::Events(batch)),
            };
            assert!(response.encoded_len() <= MAX_REPLICATION_MESSAGE_BYTES);
        }
    }

    #[test]
    fn snapshot_chunks_ack_only_after_snapshot_end() {
        let chunk = ReplicaEventBatch {
            session_id: "session".to_string(),
            events: vec![crate::proto::gateway_management::ReplicaEvent {
                protocol_version: 1,
                source_instance: "leader".to_string(),
                term: "term".to_string(),
                revision: 1,
                snapshot_digest: "a".repeat(64),
                payload: Some(
                    crate::proto::gateway_management::replica_event::Payload::SnapshotChunk(
                        crate::proto::gateway_management::ReplicaSnapshotChunk {
                            chunk_index: 0,
                            snapshot: None,
                        },
                    ),
                ),
            }],
        };
        assert!(!batch_requires_ack(&chunk));
        let end = ReplicaEventBatch {
            events: vec![crate::proto::gateway_management::ReplicaEvent {
                payload: Some(
                    crate::proto::gateway_management::replica_event::Payload::SnapshotEnd(
                        crate::proto::gateway_management::Empty {},
                    ),
                ),
                ..chunk.events[0].clone()
            }],
            ..chunk
        };
        assert!(batch_requires_ack(&end));
    }

    #[test]
    fn only_one_stream_can_claim_a_replica_id() {
        let ids = Arc::new(StdMutex::new(HashSet::new()));
        let permits = Arc::new(Semaphore::new(2));
        let first = ActiveReplicaGuard::acquire(
            ids.clone(),
            "replica-a".to_string(),
            permits.clone().try_acquire_owned().expect("permit"),
        )
        .expect("first replica stream");
        let duplicate = ActiveReplicaGuard::acquire(
            ids.clone(),
            "replica-a".to_string(),
            permits.try_acquire_owned().expect("permit"),
        );
        assert!(duplicate.is_err());
        drop(first);
        assert!(ids.lock().expect("ids").is_empty());
    }

    #[tokio::test]
    async fn replication_stream_delivers_snapshot_and_confirms_ack() {
        let coordinator = ReplicationCoordinator::new("leader-a", 0, Duration::from_secs(1));
        coordinator.begin_leader_term(1).await.expect("leader term");
        let sandbox_id = uuid::Uuid::now_v7().to_string();
        coordinator
            .publish(
                1,
                ReplicaMutation::UpsertPolicy {
                    policy: ReplicatedPolicy {
                        sandbox_id,
                        policy: ApplySandboxPolicyRequest {
                            generation: PolicyGeneration {
                                policy_hash: "a".repeat(64),
                                policy_version: 1,
                            },
                            allowlist_hosts: vec!["api.example.test".to_string()],
                            credential_routes: Vec::new(),
                            proxy_auth_token: None,
                        },
                    },
                },
            )
            .await
            .expect("publish policy");

        let token = "r".repeat(32);
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let addr = listener.local_addr().expect("local address");
        let service = GatewayReplicationServiceServer::new(GatewayReplicationServer::new(
            coordinator,
            Some(&token),
        ));
        let server = tokio::spawn(async move {
            Server::builder()
                .add_service(service)
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
        });

        let mut client = GatewayReplicationServiceClient::connect(format!("http://{addr}"))
            .await
            .expect("connect replication client");
        let (outbound_tx, outbound_rx) = mpsc::channel(4);
        outbound_tx
            .send(ReplicationStreamRequest {
                message: Some(replication_stream_request::Message::Open(ReplicaOpen {
                    protocol_version: u32::from(REPLICATION_PROTOCOL_VERSION),
                    replica_id: "replica-a".to_string(),
                    session_id: None,
                    term: None,
                    revision: None,
                    snapshot_digest: None,
                })),
            })
            .await
            .expect("send open");
        let mut request = Request::new(ReceiverStream::new(outbound_rx));
        request.metadata_mut().insert(
            "authorization",
            format!("Bearer {token}").parse().expect("authorization"),
        );
        let mut inbound = client
            .replicate(request)
            .await
            .expect("open replication stream")
            .into_inner();

        let batch = match inbound
            .message()
            .await
            .expect("receive batch")
            .expect("batch frame")
            .message
            .expect("batch message")
        {
            replication_stream_response::Message::Events(batch) => batch,
            replication_stream_response::Message::Acknowledged(_) => {
                panic!("acknowledgement cannot precede a snapshot")
            }
        };
        assert!(batch.events.len() >= 3, "snapshot begin/chunk/end expected");
        let last = batch.events.last().expect("last snapshot event");
        outbound_tx
            .send(ReplicationStreamRequest {
                message: Some(replication_stream_request::Message::Ack(ReplicaAck {
                    protocol_version: u32::from(REPLICATION_PROTOCOL_VERSION),
                    replica_id: "replica-a".to_string(),
                    session_id: batch.session_id.clone(),
                    source_instance: last.source_instance.clone(),
                    term: last.term.clone(),
                    revision: last.revision,
                    snapshot_digest: last.snapshot_digest.clone(),
                })),
            })
            .await
            .expect("send ack");

        let acknowledged = match inbound
            .message()
            .await
            .expect("receive ack confirmation")
            .expect("ack confirmation frame")
            .message
            .expect("ack confirmation message")
        {
            replication_stream_response::Message::Acknowledged(ack) => ack,
            replication_stream_response::Message::Events(_) => {
                panic!("next batch cannot precede ACK confirmation")
            }
        };
        assert_eq!(acknowledged.session_id, batch.session_id);
        assert_eq!(acknowledged.term, last.term);
        assert_eq!(acknowledged.revision, last.revision);
        assert_eq!(acknowledged.snapshot_digest, last.snapshot_digest);

        server.abort();
    }
}
