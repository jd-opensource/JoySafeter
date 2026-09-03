use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::Duration;

use thiserror::Error;
use tokio::sync::{watch, Mutex};
use uuid::Uuid;

use super::digest::snapshot_digest;
use super::model::{
    AckReplicaRequest, HotSnapshotMetadata, ReplicaEvent, ReplicaEventPayload, ReplicaMutation,
    ReplicatedSnapshot, WatchReplicaQuery, WatchReplicaResponse, REPLICATION_PROTOCOL_VERSION,
};
use super::snapshot::{apply_mutation, canonicalize, snapshot_events};

const REPLICATION_LOG_LIMIT: usize = 1_024;

#[derive(Debug, Error)]
pub enum ReplicationError {
    #[error("replication is not in leader mode")]
    NotLeader,
    #[error("replication acknowledgement quorum timed out: {acked}/{required} replicas ACKed revision {revision}")]
    AckTimeout {
        acked: usize,
        required: usize,
        revision: u64,
    },
    #[error("replica acknowledgement is stale or does not match its active session")]
    InvalidAck,
    #[error("replication snapshot is invalid: {0}")]
    InvalidSnapshot(String),
}

#[derive(Clone)]
pub struct ReplicationCoordinator {
    instance_id: String,
    min_replica_acks: usize,
    ack_timeout: Duration,
    state: Arc<Mutex<CoordinatorState>>,
    changed: watch::Sender<u64>,
}

struct CoordinatorState {
    leader: Option<LeaderTerm>,
    snapshot: ReplicatedSnapshot,
    hot: Option<HotSnapshotMetadata>,
    log: VecDeque<ReplicaEvent>,
    sessions: HashMap<String, String>,
    acknowledgements: HashMap<String, ReplicaAck>,
}

struct LeaderTerm {
    epoch: u64,
    id: String,
    revision: u64,
    digest: String,
}

struct ReplicaAck {
    session_id: String,
    term: String,
    revision: u64,
}

impl ReplicationCoordinator {
    pub fn new(
        instance_id: impl Into<String>,
        min_replica_acks: usize,
        ack_timeout: Duration,
    ) -> Self {
        let (changed, _receiver) = watch::channel(0);
        Self {
            instance_id: instance_id.into(),
            min_replica_acks,
            ack_timeout,
            state: Arc::new(Mutex::new(CoordinatorState {
                leader: None,
                snapshot: ReplicatedSnapshot::default(),
                hot: None,
                log: VecDeque::new(),
                sessions: HashMap::new(),
                acknowledgements: HashMap::new(),
            })),
            changed,
        }
    }

    pub async fn begin_leader_term(
        &self,
        epoch: u64,
    ) -> anyhow::Result<Option<ReplicatedSnapshot>> {
        let mut state = self.state.lock().await;
        let hot = match &state.hot {
            Some(metadata) if snapshot_digest(&state.snapshot)? == metadata.snapshot_digest => {
                Some(state.snapshot.clone())
            }
            _ => None,
        };
        if hot.is_none() {
            state.snapshot = ReplicatedSnapshot::default();
        }
        let digest = snapshot_digest(&state.snapshot)?;
        state.leader = Some(LeaderTerm {
            epoch,
            id: Uuid::now_v7().to_string(),
            revision: 0,
            digest,
        });
        state.hot = None;
        state.log.clear();
        state.sessions.clear();
        state.acknowledgements.clear();
        self.notify();
        Ok(hot)
    }

    pub async fn demote(&self) {
        let mut state = self.state.lock().await;
        state.leader = None;
        state.hot = None;
        state.log.clear();
        state.sessions.clear();
        state.acknowledgements.clear();
        self.notify();
    }

    pub async fn is_leader_epoch(&self, epoch: u64) -> bool {
        self.state
            .lock()
            .await
            .leader
            .as_ref()
            .is_some_and(|leader| leader.epoch == epoch)
    }

    pub async fn is_leader_epoch_any(&self) -> bool {
        self.state.lock().await.leader.is_some()
    }

    pub async fn publish(
        &self,
        epoch: u64,
        mutation: ReplicaMutation,
    ) -> Result<(), ReplicationError> {
        let (term, revision) = {
            let mut state = self.state.lock().await;
            let Some(leader) = state.leader.as_ref() else {
                return Err(ReplicationError::NotLeader);
            };
            if leader.epoch != epoch {
                return Err(ReplicationError::NotLeader);
            }
            apply_mutation(&mut state.snapshot, mutation.clone())
                .map_err(|error| ReplicationError::InvalidSnapshot(error.to_string()))?;
            canonicalize(&mut state.snapshot);
            let digest = snapshot_digest(&state.snapshot)
                .map_err(|error| ReplicationError::InvalidSnapshot(error.to_string()))?;
            let leader = state.leader.as_mut().expect("leader checked above");
            leader.revision = leader.revision.saturating_add(1);
            leader.digest.clone_from(&digest);
            let event = ReplicaEvent {
                protocol_version: REPLICATION_PROTOCOL_VERSION,
                source_instance: self.instance_id.clone(),
                term: leader.id.clone(),
                revision: leader.revision,
                snapshot_digest: digest,
                payload: ReplicaEventPayload::Delta { mutation },
            };
            let result = (leader.id.clone(), leader.revision);
            state.log.push_back(event);
            while state.log.len() > REPLICATION_LOG_LIMIT {
                state.log.pop_front();
            }
            result
        };
        self.notify();
        self.wait_for_acks(&term, revision).await
    }

    pub async fn watch(
        &self,
        query: WatchReplicaQuery,
        wait_timeout: Duration,
    ) -> Result<WatchReplicaResponse, ReplicationError> {
        let mut changed = self.changed.subscribe();
        loop {
            if let Some(response) = self.watch_now(&query).await? {
                return Ok(response);
            }
            if tokio::time::timeout(wait_timeout, changed.changed())
                .await
                .is_err()
            {
                let state = self.state.lock().await;
                let session_id = state
                    .sessions
                    .get(&query.replica_id)
                    .cloned()
                    .ok_or(ReplicationError::NotLeader)?;
                return Ok(WatchReplicaResponse {
                    session_id,
                    events: Vec::new(),
                });
            }
        }
    }

    async fn watch_now(
        &self,
        query: &WatchReplicaQuery,
    ) -> Result<Option<WatchReplicaResponse>, ReplicationError> {
        if query.replica_id.trim().is_empty() || query.replica_id == self.instance_id {
            return Err(ReplicationError::InvalidSnapshot(
                "replica_id is empty or identifies the leader".to_string(),
            ));
        }
        if query.protocol_version != REPLICATION_PROTOCOL_VERSION {
            return Err(ReplicationError::InvalidSnapshot(
                "unsupported replication protocol version".to_string(),
            ));
        }
        let mut state = self.state.lock().await;
        let Some(leader) = state.leader.as_ref() else {
            return Err(ReplicationError::NotLeader);
        };
        let term = leader.id.clone();
        let revision = leader.revision;
        let digest = leader.digest.clone();

        let active_session = state.sessions.get(&query.replica_id).cloned();
        let session_matches = query
            .session_id
            .as_ref()
            .zip(active_session.as_ref())
            .is_some_and(|(requested, active)| requested == active);
        let session_id = if session_matches {
            active_session.expect("matching optional sessions are populated")
        } else {
            let session_id = Uuid::now_v7().to_string();
            state
                .sessions
                .insert(query.replica_id.clone(), session_id.clone());
            state.acknowledgements.remove(&query.replica_id);
            session_id
        };

        let cursor_revision = query.revision.unwrap_or(0);
        let cursor_is_current = session_matches
            && query.term.as_deref() == Some(term.as_str())
            && query.snapshot_digest.as_deref() == Some(digest.as_str())
            && cursor_revision == revision;
        if cursor_is_current {
            return Ok(None);
        }

        let can_replay_log = session_matches
            && query.term.as_deref() == Some(term.as_str())
            && cursor_revision <= revision
            && state
                .log
                .front()
                .is_none_or(|first| cursor_revision.saturating_add(1) >= first.revision);
        if can_replay_log {
            let events = state
                .log
                .iter()
                .filter(|event| event.revision > cursor_revision)
                .cloned()
                .collect::<Vec<_>>();
            if !events.is_empty() {
                return Ok(Some(WatchReplicaResponse { session_id, events }));
            }
        }

        let events = snapshot_events(&self.instance_id, &term, revision, &digest, &state.snapshot);
        Ok(Some(WatchReplicaResponse { session_id, events }))
    }

    pub async fn acknowledge(&self, ack: AckReplicaRequest) -> Result<(), ReplicationError> {
        let mut state = self.state.lock().await;
        let Some(leader) = state.leader.as_ref() else {
            return Err(ReplicationError::NotLeader);
        };
        let session_matches = state
            .sessions
            .get(&ack.replica_id)
            .is_some_and(|session| session == &ack.session_id);
        let expected_digest = if ack.revision == leader.revision {
            Some(leader.digest.as_str())
        } else {
            state
                .log
                .iter()
                .find(|event| event.revision == ack.revision)
                .map(|event| event.snapshot_digest.as_str())
        };
        if ack.protocol_version != REPLICATION_PROTOCOL_VERSION
            || !session_matches
            || ack.source_instance != self.instance_id
            || ack.term != leader.id
            || ack.revision > leader.revision
            || expected_digest != Some(ack.snapshot_digest.as_str())
        {
            return Err(ReplicationError::InvalidAck);
        }
        let should_update = state
            .acknowledgements
            .get(&ack.replica_id)
            .is_none_or(|current| current.revision <= ack.revision);
        if should_update {
            state.acknowledgements.insert(
                ack.replica_id,
                ReplicaAck {
                    session_id: ack.session_id,
                    term: ack.term,
                    revision: ack.revision,
                },
            );
        }
        drop(state);
        self.notify();
        Ok(())
    }

    pub async fn install_follower_snapshot(
        &self,
        snapshot: ReplicatedSnapshot,
        metadata: HotSnapshotMetadata,
    ) -> Result<(), ReplicationError> {
        let mut snapshot = snapshot;
        canonicalize(&mut snapshot);
        let digest = snapshot_digest(&snapshot)
            .map_err(|error| ReplicationError::InvalidSnapshot(error.to_string()))?;
        if digest != metadata.snapshot_digest {
            return Err(ReplicationError::InvalidSnapshot(
                "snapshot digest does not match its envelope".to_string(),
            ));
        }
        let mut state = self.state.lock().await;
        if state.leader.is_some() {
            return Err(ReplicationError::NotLeader);
        }
        state.snapshot = snapshot;
        state.hot = Some(metadata);
        Ok(())
    }

    pub async fn apply_follower_delta(
        &self,
        mutation: ReplicaMutation,
        metadata: HotSnapshotMetadata,
    ) -> Result<bool, ReplicationError> {
        let mut state = self.state.lock().await;
        if state.leader.is_some() {
            return Err(ReplicationError::NotLeader);
        }
        let Some(current) = &state.hot else {
            return Err(ReplicationError::InvalidSnapshot(
                "delta arrived before a complete snapshot".to_string(),
            ));
        };
        if current.source_instance != metadata.source_instance || current.term != metadata.term {
            return Err(ReplicationError::InvalidSnapshot(
                "delta belongs to a different replication term".to_string(),
            ));
        }
        if metadata.revision <= current.revision {
            return Ok(false);
        }
        if metadata.revision != current.revision.saturating_add(1) {
            return Err(ReplicationError::InvalidSnapshot(
                "replication revision gap detected".to_string(),
            ));
        }
        apply_mutation(&mut state.snapshot, mutation)
            .map_err(|error| ReplicationError::InvalidSnapshot(error.to_string()))?;
        canonicalize(&mut state.snapshot);
        let digest = snapshot_digest(&state.snapshot)
            .map_err(|error| ReplicationError::InvalidSnapshot(error.to_string()))?;
        if digest != metadata.snapshot_digest {
            state.hot = None;
            return Err(ReplicationError::InvalidSnapshot(
                "delta digest does not match the resulting snapshot".to_string(),
            ));
        }
        state.hot = Some(metadata);
        Ok(true)
    }

    pub async fn hot_metadata(&self) -> Option<HotSnapshotMetadata> {
        self.state.lock().await.hot.clone()
    }

    pub async fn invalidate_hot_snapshot(&self) {
        self.state.lock().await.hot = None;
    }

    pub async fn current_snapshot(&self) -> ReplicatedSnapshot {
        self.state.lock().await.snapshot.clone()
    }

    async fn wait_for_acks(&self, term: &str, revision: u64) -> Result<(), ReplicationError> {
        if self.min_replica_acks == 0 {
            return Ok(());
        }
        let deadline = tokio::time::Instant::now() + self.ack_timeout;
        let mut changed = self.changed.subscribe();
        loop {
            let acked = {
                let state = self.state.lock().await;
                if state.leader.as_ref().map(|leader| leader.id.as_str()) != Some(term) {
                    return Err(ReplicationError::NotLeader);
                }
                state
                    .acknowledgements
                    .iter()
                    .filter(|(replica_id, ack)| {
                        ack.term == term
                            && ack.revision >= revision
                            && state
                                .sessions
                                .get(*replica_id)
                                .is_some_and(|session| session == &ack.session_id)
                    })
                    .count()
            };
            if acked >= self.min_replica_acks {
                return Ok(());
            }
            if tokio::time::timeout_at(deadline, changed.changed())
                .await
                .is_err()
            {
                return Err(ReplicationError::AckTimeout {
                    acked,
                    required: self.min_replica_acks,
                    revision,
                });
            }
        }
    }

    fn notify(&self) {
        let next = (*self.changed.borrow()).saturating_add(1);
        self.changed.send_replace(next);
    }
}

#[cfg(test)]
#[path = "../../tests/unit/replication/coordinator_test.rs"]
mod tests;
