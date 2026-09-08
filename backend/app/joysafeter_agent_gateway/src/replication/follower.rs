use std::time::Duration;

use rand::Rng;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::ReceiverStream;
use tonic::transport::{Channel, Endpoint};
use tonic::Request;
use tracing::{debug, info};

use crate::adapters::management_grpc::MAX_REPLICATION_MESSAGE_BYTES;
use crate::bootstrap::shutdown::ShutdownSignal;
use crate::proto::gateway_management::{
    gateway_replication_service_client::GatewayReplicationServiceClient,
    replication_stream_request, replication_stream_response, ReplicaAck, ReplicaOpen,
    ReplicationStreamRequest,
};

use super::coordinator::ReplicationCoordinator;
use super::model::{
    HotSnapshotMetadata, ReplicaEvent, ReplicaEventPayload, ReplicatedSnapshot,
    REPLICATION_PROTOCOL_VERSION,
};
use super::projector::ReplicaProjector;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(10);
const KEEPALIVE_TIMEOUT: Duration = Duration::from_secs(5);
const RECONNECT_BASE_DELAY: Duration = Duration::from_millis(100);
const RECONNECT_MAX_DELAY: Duration = Duration::from_secs(5);

#[derive(Clone, Copy)]
pub struct FollowerTransportConfig {
    pub keepalive_interval: Duration,
    pub keepalive_timeout: Duration,
    pub reconnect_base_delay: Duration,
    pub reconnect_max_delay: Duration,
}

impl Default for FollowerTransportConfig {
    fn default() -> Self {
        Self {
            keepalive_interval: KEEPALIVE_INTERVAL,
            keepalive_timeout: KEEPALIVE_TIMEOUT,
            reconnect_base_delay: RECONNECT_BASE_DELAY,
            reconnect_max_delay: RECONNECT_MAX_DELAY,
        }
    }
}

pub struct FollowerHandle {
    task: JoinHandle<()>,
}

impl FollowerHandle {
    pub fn abort(&self) {
        self.task.abort();
    }
}

pub fn spawn(
    leader_endpoint: String,
    token: String,
    replica_id: String,
    coordinator: ReplicationCoordinator,
    projector: ReplicaProjector,
    shutdown: ShutdownSignal,
    transport: FollowerTransportConfig,
) -> anyhow::Result<FollowerHandle> {
    let channel = Endpoint::from_shared(leader_endpoint)?
        .connect_timeout(CONNECT_TIMEOUT)
        .tcp_keepalive(Some(transport.keepalive_interval))
        .http2_keep_alive_interval(transport.keepalive_interval)
        .keep_alive_timeout(transport.keepalive_timeout)
        .keep_alive_while_idle(true)
        .connect_lazy();
    let task = tokio::spawn(async move {
        let mut runner = FollowerRunner {
            channel,
            token,
            replica_id,
            coordinator,
            projector,
            cursor: ReplicaCursor::default(),
            staging: None,
            transport,
        };
        tokio::select! {
            () = runner.run() => {}
            () = shutdown.wait() => {}
        }
    });
    Ok(FollowerHandle { task })
}

#[derive(Default)]
struct ReplicaCursor {
    session_id: Option<String>,
    term: Option<String>,
    revision: Option<u64>,
    digest: Option<String>,
}

struct StagingSnapshot {
    source_instance: String,
    term: String,
    revision: u64,
    digest: String,
    chunk_count: usize,
    next_chunk: usize,
    snapshot: ReplicatedSnapshot,
}

struct FollowerRunner {
    channel: Channel,
    token: String,
    replica_id: String,
    coordinator: ReplicationCoordinator,
    projector: ReplicaProjector,
    cursor: ReplicaCursor,
    staging: Option<StagingSnapshot>,
    transport: FollowerTransportConfig,
}

impl FollowerRunner {
    async fn run(&mut self) {
        let mut reconnect_attempt = 0_u32;
        loop {
            if self.coordinator.is_leader_epoch_any().await {
                tokio::time::sleep(self.transport.reconnect_base_delay).await;
                reconnect_attempt = 0;
                continue;
            }
            match self.sync_stream().await {
                Ok(()) => reconnect_attempt = 0,
                Err(error) => {
                    self.staging = None;
                    reconnect_attempt = reconnect_attempt.saturating_add(1);
                    debug!(%error, reconnect_attempt, "Agent Gateway hot-standby gRPC stream interrupted");
                    tokio::time::sleep(reconnect_delay_with_bounds(
                        reconnect_attempt,
                        self.transport.reconnect_base_delay,
                        self.transport.reconnect_max_delay,
                    ))
                    .await;
                }
            }
        }
    }

    async fn sync_stream(&mut self) -> anyhow::Result<()> {
        let (outbound_tx, outbound_rx) = mpsc::channel(8);
        outbound_tx
            .send(ReplicationStreamRequest {
                message: Some(replication_stream_request::Message::Open(ReplicaOpen {
                    protocol_version: u32::from(REPLICATION_PROTOCOL_VERSION),
                    replica_id: self.replica_id.clone(),
                    session_id: self.cursor.session_id.clone(),
                    term: self.cursor.term.clone(),
                    revision: self.cursor.revision,
                    snapshot_digest: self.cursor.digest.clone(),
                })),
            })
            .await?;
        let mut request = Request::new(ReceiverStream::new(outbound_rx));
        request
            .metadata_mut()
            .insert("authorization", format!("Bearer {}", self.token).parse()?);
        let mut inbound = GatewayReplicationServiceClient::new(self.channel.clone())
            .max_decoding_message_size(MAX_REPLICATION_MESSAGE_BYTES)
            .max_encoding_message_size(MAX_REPLICATION_MESSAGE_BYTES)
            .replicate(request)
            .await?
            .into_inner();
        let mut pending_ack: Option<(String, HotSnapshotMetadata)> = None;
        loop {
            if self.coordinator.is_leader_epoch_any().await {
                anyhow::bail!("replica was promoted while the follower stream was active");
            }
            let response = tokio::select! {
                response = inbound.message() => response?
                    .ok_or_else(|| anyhow::anyhow!("replication stream closed"))?,
                () = tokio::time::sleep(Duration::from_millis(250)) => continue,
            };
            match response.message {
                Some(replication_stream_response::Message::Events(batch)) => {
                    if pending_ack.is_some() {
                        anyhow::bail!("leader sent events before acknowledging the previous batch");
                    }
                    if self.cursor.session_id.as_deref() != Some(batch.session_id.as_str()) {
                        self.cursor = ReplicaCursor {
                            session_id: Some(batch.session_id.clone()),
                            ..ReplicaCursor::default()
                        };
                        self.staging = None;
                    }
                    let mut latest = None;
                    for event in batch.events {
                        let event =
                            crate::adapters::proto_conversion::replica_event_from_proto(event)?;
                        if let Some(metadata) = self.apply_event(event).await? {
                            latest = Some(metadata);
                        }
                    }
                    let Some(metadata) = latest else {
                        // SnapshotBegin/Chunk frames may span multiple bounded
                        // transport batches. ACK only after SnapshotEnd (or a
                        // complete delta) has been durably applied.
                        continue;
                    };
                    outbound_tx
                        .send(ReplicationStreamRequest {
                            message: Some(replication_stream_request::Message::Ack(ReplicaAck {
                                protocol_version: u32::from(REPLICATION_PROTOCOL_VERSION),
                                replica_id: self.replica_id.clone(),
                                session_id: batch.session_id.clone(),
                                source_instance: metadata.source_instance.clone(),
                                term: metadata.term.clone(),
                                revision: metadata.revision,
                                snapshot_digest: metadata.snapshot_digest.clone(),
                            })),
                        })
                        .await?;
                    pending_ack = Some((batch.session_id, metadata));
                }
                Some(replication_stream_response::Message::Acknowledged(ack)) => {
                    let (session_id, metadata) = pending_ack
                        .take()
                        .ok_or_else(|| anyhow::anyhow!("unexpected replication acknowledgement"))?;
                    if session_id != ack.session_id
                        || metadata.term != ack.term
                        || metadata.revision != ack.revision
                        || metadata.snapshot_digest != ack.snapshot_digest
                    {
                        anyhow::bail!("replication acknowledgement correlation failed");
                    }
                    self.set_cursor(&session_id, metadata);
                }
                None => anyhow::bail!("replication response frame is empty"),
            }
        }
    }

    async fn apply_event(
        &mut self,
        event: ReplicaEvent,
    ) -> anyhow::Result<Option<HotSnapshotMetadata>> {
        if event.protocol_version != REPLICATION_PROTOCOL_VERSION {
            anyhow::bail!("leader uses an unsupported replication protocol version");
        }
        match event.payload.clone() {
            ReplicaEventPayload::SnapshotBegin { chunk_count } => {
                self.staging = Some(StagingSnapshot {
                    source_instance: event.source_instance,
                    term: event.term,
                    revision: event.revision,
                    digest: event.snapshot_digest,
                    chunk_count,
                    next_chunk: 0,
                    snapshot: ReplicatedSnapshot::default(),
                });
                Ok(None)
            }
            ReplicaEventPayload::SnapshotChunk {
                chunk_index,
                snapshot,
            } => {
                let staging = self.matching_staging(&event)?;
                if chunk_index != staging.next_chunk {
                    anyhow::bail!("replica snapshot chunk is missing or out of order");
                }
                staging.snapshot.policies.extend(snapshot.policies);
                staging.snapshot.placements.extend(snapshot.placements);
                staging.next_chunk += 1;
                Ok(None)
            }
            ReplicaEventPayload::SnapshotEnd => {
                let staging = self
                    .staging
                    .take()
                    .ok_or_else(|| anyhow::anyhow!("replica snapshot ended before begin"))?;
                ensure_identity(&staging, &event)?;
                if staging.next_chunk != staging.chunk_count {
                    anyhow::bail!("replica snapshot ended before all chunks arrived");
                }
                let metadata = staging.metadata();
                let mutation_gate = self.projector.mutation_gate();
                let _gate = mutation_gate.lock().await;
                if self.coordinator.is_leader_epoch_any().await {
                    anyhow::bail!("replica was promoted while applying a snapshot");
                }
                self.coordinator
                    .install_follower_snapshot(staging.snapshot.clone(), metadata.clone())
                    .await?;
                if let Err(error) = self.projector.install_snapshot(&staging.snapshot).await {
                    self.coordinator.invalidate_hot_snapshot().await;
                    return Err(error);
                }
                drop(_gate);
                info!(
                    source = %event.source_instance,
                    term = %event.term,
                    revision = event.revision,
                    "Agent Gateway hot snapshot installed"
                );
                Ok(Some(metadata))
            }
            ReplicaEventPayload::Delta { mutation } => {
                let metadata = metadata(&event);
                let mutation_gate = self.projector.mutation_gate();
                let _gate = mutation_gate.lock().await;
                if self.coordinator.is_leader_epoch_any().await {
                    anyhow::bail!("replica was promoted while applying a delta");
                }
                let changed = self
                    .coordinator
                    .apply_follower_delta(mutation.clone(), metadata.clone())
                    .await?;
                if changed {
                    if let Err(error) = self.projector.install_delta(&mutation).await {
                        self.coordinator.invalidate_hot_snapshot().await;
                        return Err(error);
                    }
                }
                drop(_gate);
                Ok(Some(metadata))
            }
        }
    }

    fn matching_staging(&mut self, event: &ReplicaEvent) -> anyhow::Result<&mut StagingSnapshot> {
        let staging = self
            .staging
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("replica snapshot chunk arrived before begin"))?;
        ensure_identity(staging, event)?;
        Ok(staging)
    }

    fn set_cursor(&mut self, session_id: &str, metadata: HotSnapshotMetadata) {
        self.cursor = ReplicaCursor {
            session_id: Some(session_id.to_string()),
            term: Some(metadata.term),
            revision: Some(metadata.revision),
            digest: Some(metadata.snapshot_digest),
        };
    }
}

impl StagingSnapshot {
    fn metadata(&self) -> HotSnapshotMetadata {
        HotSnapshotMetadata {
            source_instance: self.source_instance.clone(),
            term: self.term.clone(),
            revision: self.revision,
            snapshot_digest: self.digest.clone(),
        }
    }
}

fn metadata(event: &ReplicaEvent) -> HotSnapshotMetadata {
    HotSnapshotMetadata {
        source_instance: event.source_instance.clone(),
        term: event.term.clone(),
        revision: event.revision,
        snapshot_digest: event.snapshot_digest.clone(),
    }
}

fn ensure_identity(staging: &StagingSnapshot, event: &ReplicaEvent) -> anyhow::Result<()> {
    if staging.source_instance != event.source_instance
        || staging.term != event.term
        || staging.revision != event.revision
        || staging.digest != event.snapshot_digest
    {
        anyhow::bail!("replica snapshot identity changed mid-transfer");
    }
    Ok(())
}

#[cfg(test)]
fn reconnect_delay(attempt: u32) -> Duration {
    reconnect_delay_with_bounds(attempt, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY)
}

fn reconnect_delay_with_bounds(attempt: u32, base: Duration, max: Duration) -> Duration {
    let exponent = attempt.saturating_sub(1).min(6);
    let capped_ms = base
        .as_millis()
        .saturating_mul(1_u128 << exponent)
        .min(max.as_millis()) as u64;
    let floor_ms = (capped_ms.saturating_mul(3) / 4).max(1);
    Duration::from_millis(rand::thread_rng().gen_range(floor_ms..=capped_ms))
}

#[cfg(test)]
#[path = "../../tests/unit/replication/follower_test.rs"]
mod tests;
