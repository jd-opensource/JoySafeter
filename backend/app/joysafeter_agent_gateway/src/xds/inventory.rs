//! Complete recovery inventory and per-sandbox recovery classification.

use std::collections::HashSet;

use crate::ids::SandboxId;

use super::model::{DeliveryGeneration, ManagedXdsResource, ResourceOwner};

#[derive(Debug, Clone)]
pub struct RecoveredSandbox {
    pub sandbox_id: SandboxId,
    pub generation: DeliveryGeneration,
    pub resources: Vec<ManagedXdsResource>,
}

#[derive(Debug, Clone)]
pub struct RecoveryInventory {
    pub recovered_sandboxes: Vec<RecoveredSandbox>,
}

impl RecoveryInventory {
    pub fn new(recovered_sandboxes: Vec<RecoveredSandbox>) -> anyhow::Result<Self> {
        let mut sandbox_ids = HashSet::new();
        for sandbox in &recovered_sandboxes {
            if !sandbox_ids.insert(sandbox.sandbox_id) {
                anyhow::bail!("duplicate recovered sandbox {}", sandbox.sandbox_id);
            }
            if sandbox.generation.policy_hash.is_empty() || sandbox.generation.policy_version <= 0 {
                anyhow::bail!(
                    "invalid recovered generation for sandbox {}",
                    sandbox.sandbox_id
                );
            }
            if sandbox.resources.is_empty() {
                anyhow::bail!(
                    "recovered sandbox {} has no xDS resources",
                    sandbox.sandbox_id
                );
            }
            let expected_owner = ResourceOwner::Sandbox(sandbox.sandbox_id);
            if sandbox
                .resources
                .iter()
                .any(|resource| resource.owner != expected_owner)
            {
                anyhow::bail!(
                    "recovered resource owner does not match sandbox {}",
                    sandbox.sandbox_id
                );
            }
        }
        Ok(Self {
            recovered_sandboxes,
        })
    }
}
