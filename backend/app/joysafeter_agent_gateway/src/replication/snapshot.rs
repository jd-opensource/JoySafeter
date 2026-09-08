use super::model::{
    ReplicaEvent, ReplicaEventPayload, ReplicaMutation, ReplicatedSnapshot,
    REPLICATION_PROTOCOL_VERSION,
};

const SNAPSHOT_CHUNK_MAX_BYTES: usize = 2 * 1024 * 1024;

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
    let mut current = ReplicatedSnapshot::default();
    for policy in &snapshot.policies {
        let mut candidate = current.clone();
        candidate.policies.push(policy.clone());
        if !current.policies.is_empty() && serialized_size(&candidate) > SNAPSHOT_CHUNK_MAX_BYTES {
            chunks.push(std::mem::take(&mut current));
        }
        current.policies.push(policy.clone());
    }
    for placement in &snapshot.placements {
        let mut candidate = current.clone();
        candidate.placements.push(placement.clone());
        if (!current.policies.is_empty() || !current.placements.is_empty())
            && serialized_size(&candidate) > SNAPSHOT_CHUNK_MAX_BYTES
        {
            chunks.push(std::mem::take(&mut current));
        }
        current.placements.push(placement.clone());
    }
    if !current.policies.is_empty() || !current.placements.is_empty() {
        chunks.push(current);
    }
    if chunks.is_empty() {
        chunks.push(ReplicatedSnapshot::default());
    }
    chunks
}

fn serialized_size(snapshot: &ReplicatedSnapshot) -> usize {
    serde_json::to_vec(snapshot)
        .map(|encoded| encoded.len())
        .unwrap_or(usize::MAX)
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
