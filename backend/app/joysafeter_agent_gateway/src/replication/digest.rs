use sha2::{Digest, Sha256};

use super::model::ReplicatedSnapshot;

pub fn snapshot_digest(snapshot: &ReplicatedSnapshot) -> anyhow::Result<String> {
    let bytes = serde_json::to_vec(snapshot)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}
