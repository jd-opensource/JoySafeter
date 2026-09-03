use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, SandboxPlacement};
use serde::{Deserialize, Serialize};

pub const REPLICATION_PROTOCOL_VERSION: u16 = 1;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReplicatedPolicy {
    pub sandbox_id: String,
    pub policy: ApplySandboxPolicyRequest,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ReplicatedSnapshot {
    pub policies: Vec<ReplicatedPolicy>,
    pub placements: Vec<SandboxPlacement>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReplicaMutation {
    UpsertPolicy { policy: ReplicatedPolicy },
    RemovePolicy { sandbox_id: String },
    UpsertPlacement { placement: SandboxPlacement },
    RemovePlacement { sandbox_id: String },
    ReplacePlacements { placements: Vec<SandboxPlacement> },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReplicaEvent {
    pub protocol_version: u16,
    pub source_instance: String,
    pub term: String,
    pub revision: u64,
    pub snapshot_digest: String,
    #[serde(flatten)]
    pub payload: ReplicaEventPayload,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum ReplicaEventPayload {
    SnapshotBegin {
        chunk_count: usize,
    },
    SnapshotChunk {
        chunk_index: usize,
        snapshot: ReplicatedSnapshot,
    },
    SnapshotEnd,
    Delta {
        mutation: ReplicaMutation,
    },
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct WatchReplicaQuery {
    pub protocol_version: u16,
    pub replica_id: String,
    pub session_id: Option<String>,
    pub term: Option<String>,
    pub revision: Option<u64>,
    pub snapshot_digest: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WatchReplicaResponse {
    pub session_id: String,
    pub events: Vec<ReplicaEvent>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AckReplicaRequest {
    pub protocol_version: u16,
    pub replica_id: String,
    pub session_id: String,
    pub source_instance: String,
    pub term: String,
    pub revision: u64,
    pub snapshot_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AckReplicaResponse {
    pub accepted: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HotSnapshotMetadata {
    pub source_instance: String,
    pub term: String,
    pub revision: u64,
    pub snapshot_digest: String,
}

#[cfg(test)]
#[path = "../../tests/unit/replication/model_test.rs"]
mod tests;
