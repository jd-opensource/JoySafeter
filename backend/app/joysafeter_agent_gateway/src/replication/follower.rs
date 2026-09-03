use std::time::Duration;

use reqwest::{Client, StatusCode, Url};
use tokio::task::JoinHandle;
use tracing::{debug, info};

use crate::bootstrap::shutdown::ShutdownSignal;

use super::coordinator::ReplicationCoordinator;
use super::model::{
    AckReplicaRequest, AckReplicaResponse, HotSnapshotMetadata, ReplicaEvent, ReplicaEventPayload,
    ReplicatedSnapshot, WatchReplicaResponse, REPLICATION_PROTOCOL_VERSION,
};
use super::projector::ReplicaProjector;

const RETRY_DELAY: Duration = Duration::from_millis(250);
const WATCH_TIMEOUT: Duration = Duration::from_secs(25);

pub struct FollowerHandle {
    task: JoinHandle<()>,
}

impl FollowerHandle {
    pub fn abort(&self) {
        self.task.abort();
    }
}

pub fn spawn(
    leader_url: Url,
    token: String,
    replica_id: String,
    coordinator: ReplicationCoordinator,
    projector: ReplicaProjector,
    shutdown: ShutdownSignal,
) -> anyhow::Result<FollowerHandle> {
    let watch_url = leader_url.join("/internal/v1/replication/watch")?;
    let ack_url = leader_url.join("/internal/v1/replication/ack")?;
    let client = Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(WATCH_TIMEOUT + Duration::from_secs(5))
        .build()?;
    let task = tokio::spawn(async move {
        let mut runner = FollowerRunner {
            client,
            watch_url,
            ack_url,
            token,
            replica_id,
            coordinator,
            projector,
            cursor: ReplicaCursor::default(),
            staging: None,
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
    client: Client,
    watch_url: Url,
    ack_url: Url,
    token: String,
    replica_id: String,
    coordinator: ReplicationCoordinator,
    projector: ReplicaProjector,
    cursor: ReplicaCursor,
    staging: Option<StagingSnapshot>,
}

impl FollowerRunner {
    async fn run(&mut self) {
        loop {
            if self.coordinator.is_leader_epoch_any().await {
                tokio::time::sleep(RETRY_DELAY).await;
                continue;
            }
            if let Err(error) = self.sync_once().await {
                self.staging = None;
                self.cursor = ReplicaCursor::default();
                debug!(%error, "Agent Gateway hot-standby synchronization interrupted");
                tokio::time::sleep(RETRY_DELAY).await;
            }
        }
    }

    async fn sync_once(&mut self) -> anyhow::Result<()> {
        let mut query = vec![
            ("protocol_version", REPLICATION_PROTOCOL_VERSION.to_string()),
            ("replica_id", self.replica_id.clone()),
        ];
        if let Some(value) = &self.cursor.session_id {
            query.push(("session_id", value.clone()));
        }
        if let Some(value) = &self.cursor.term {
            query.push(("term", value.clone()));
        }
        if let Some(value) = self.cursor.revision {
            query.push(("revision", value.to_string()));
        }
        if let Some(value) = &self.cursor.digest {
            query.push(("snapshot_digest", value.clone()));
        }
        let response = self
            .client
            .get(self.watch_url.clone())
            .bearer_auth(&self.token)
            .query(&query)
            .send()
            .await?;
        if response.status() == StatusCode::SERVICE_UNAVAILABLE {
            anyhow::bail!("replication leader is unavailable");
        }
        let response = response
            .error_for_status()?
            .json::<WatchReplicaResponse>()
            .await?;
        if self.cursor.session_id.as_deref() != Some(response.session_id.as_str()) {
            self.cursor = ReplicaCursor {
                session_id: Some(response.session_id.clone()),
                ..ReplicaCursor::default()
            };
            self.staging = None;
        }
        for event in response.events {
            self.apply_event(&response.session_id, event).await?;
        }
        Ok(())
    }

    async fn apply_event(&mut self, session_id: &str, event: ReplicaEvent) -> anyhow::Result<()> {
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
                self.ack(session_id, &metadata).await?;
                self.set_cursor(session_id, metadata);
                info!(
                    source = %event.source_instance,
                    term = %event.term,
                    revision = event.revision,
                    "Agent Gateway hot snapshot installed"
                );
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
                self.ack(session_id, &metadata).await?;
                self.set_cursor(session_id, metadata);
            }
        }
        Ok(())
    }

    fn matching_staging(&mut self, event: &ReplicaEvent) -> anyhow::Result<&mut StagingSnapshot> {
        let staging = self
            .staging
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("replica snapshot chunk arrived before begin"))?;
        ensure_identity(staging, event)?;
        Ok(staging)
    }

    async fn ack(&self, session_id: &str, metadata: &HotSnapshotMetadata) -> anyhow::Result<()> {
        let response = self
            .client
            .post(self.ack_url.clone())
            .bearer_auth(&self.token)
            .json(&AckReplicaRequest {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                replica_id: self.replica_id.clone(),
                session_id: session_id.to_string(),
                source_instance: metadata.source_instance.clone(),
                term: metadata.term.clone(),
                revision: metadata.revision,
                snapshot_digest: metadata.snapshot_digest.clone(),
            })
            .send()
            .await?
            .error_for_status()?
            .json::<AckReplicaResponse>()
            .await?;
        if !response.accepted {
            anyhow::bail!("leader rejected replica acknowledgement");
        }
        Ok(())
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
#[path = "../../tests/unit/replication/follower_test.rs"]
mod tests;
