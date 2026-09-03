use super::model::{
    ReplicaEvent, ReplicaEventPayload, ReplicaMutation, ReplicatedSnapshot,
    REPLICATION_PROTOCOL_VERSION,
};

const SNAPSHOT_CHUNK_ITEMS: usize = 64;

pub(super) fn snapshot_events(
    source_instance: &str,
    term: &str,
    revision: u64,
    digest: &str,
    snapshot: &ReplicatedSnapshot,
) -> Vec<ReplicaEvent> {
    let chunks = snapshot_chunks(snapshot);
    let mut events = Vec::with_capacity(chunks.len() + 2);
    events.push(event(
        source_instance,
        term,
        revision,
        digest,
        ReplicaEventPayload::SnapshotBegin {
            chunk_count: chunks.len(),
        },
    ));
    for (chunk_index, snapshot) in chunks.into_iter().enumerate() {
        events.push(event(
            source_instance,
            term,
            revision,
            digest,
            ReplicaEventPayload::SnapshotChunk {
                chunk_index,
                snapshot,
            },
        ));
    }
    events.push(event(
        source_instance,
        term,
        revision,
        digest,
        ReplicaEventPayload::SnapshotEnd,
    ));
    events
}

pub(super) fn apply_mutation(
    snapshot: &mut ReplicatedSnapshot,
    mutation: ReplicaMutation,
) -> anyhow::Result<()> {
    match mutation {
        ReplicaMutation::UpsertPolicy { policy } => {
            snapshot
                .policies
                .retain(|current| current.sandbox_id != policy.sandbox_id);
            snapshot.policies.push(policy);
        }
        ReplicaMutation::RemovePolicy { sandbox_id } => {
            snapshot
                .policies
                .retain(|policy| policy.sandbox_id != sandbox_id);
            snapshot
                .placements
                .retain(|placement| placement.sandbox_id != sandbox_id);
        }
        ReplicaMutation::UpsertPlacement { placement } => {
            snapshot
                .placements
                .retain(|current| current.sandbox_id != placement.sandbox_id);
            snapshot.placements.push(placement);
        }
        ReplicaMutation::RemovePlacement { sandbox_id } => snapshot
            .placements
            .retain(|placement| placement.sandbox_id != sandbox_id),
        ReplicaMutation::ReplacePlacements { placements } => {
            let mut seen = std::collections::HashSet::with_capacity(placements.len());
            if placements
                .iter()
                .any(|placement| !seen.insert(placement.sandbox_id.as_str()))
            {
                anyhow::bail!("placement snapshot contains duplicate sandbox ids");
            }
            snapshot.placements = placements;
        }
    }
    Ok(())
}

pub(super) fn canonicalize(snapshot: &mut ReplicatedSnapshot) {
    snapshot
        .policies
        .sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
    snapshot
        .placements
        .sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
}

fn snapshot_chunks(snapshot: &ReplicatedSnapshot) -> Vec<ReplicatedSnapshot> {
    let mut chunks = Vec::new();
    for policies in snapshot.policies.chunks(SNAPSHOT_CHUNK_ITEMS) {
        chunks.push(ReplicatedSnapshot {
            policies: policies.to_vec(),
            placements: Vec::new(),
        });
    }
    for placements in snapshot.placements.chunks(SNAPSHOT_CHUNK_ITEMS) {
        chunks.push(ReplicatedSnapshot {
            policies: Vec::new(),
            placements: placements.to_vec(),
        });
    }
    if chunks.is_empty() {
        chunks.push(ReplicatedSnapshot::default());
    }
    chunks
}

fn event(
    source_instance: &str,
    term: &str,
    revision: u64,
    digest: &str,
    payload: ReplicaEventPayload,
) -> ReplicaEvent {
    ReplicaEvent {
        protocol_version: REPLICATION_PROTOCOL_VERSION,
        source_instance: source_instance.to_string(),
        term: term.to_string(),
        revision,
        snapshot_digest: digest.to_string(),
        payload,
    }
}
