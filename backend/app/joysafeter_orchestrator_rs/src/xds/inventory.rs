//! Complete recovery inventory and per-sandbox recovery classification.

use std::collections::HashSet;

use crate::ids::SandboxId;
use crate::kernel::network_policy::NetworkPolicyGeneration;

use super::delivery::DeliveryAttempt;
use super::model::{ManagedXdsResource, ResourceOwner};

#[derive(Debug, Clone)]
pub struct RecoveredSandbox {
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
    pub resources: Vec<ManagedXdsResource>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuarantinedSandbox {
    pub sandbox_id: SandboxId,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct RecoveryInventory {
    pub recovered_sandboxes: Vec<RecoveredSandbox>,
    pub quarantined_sandboxes: Vec<QuarantinedSandbox>,
}

impl RecoveryInventory {
    pub fn new(
        recovered_sandboxes: Vec<RecoveredSandbox>,
        quarantined_sandboxes: Vec<QuarantinedSandbox>,
    ) -> anyhow::Result<Self> {
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
        for sandbox in &quarantined_sandboxes {
            if !sandbox_ids.insert(sandbox.sandbox_id) {
                anyhow::bail!(
                    "sandbox {} has multiple recovery classifications",
                    sandbox.sandbox_id
                );
            }
            if sandbox.reason.trim().is_empty() {
                anyhow::bail!("quarantined sandbox {} has no reason", sandbox.sandbox_id);
            }
        }
        Ok(Self {
            recovered_sandboxes,
            quarantined_sandboxes,
        })
    }
}

#[derive(Debug, Clone)]
pub struct RecoveryDelivery {
    pub sandbox_id: SandboxId,
    pub generation: NetworkPolicyGeneration,
    pub state: RecoveryDeliveryState,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecoveryDeliveryState {
    Await(DeliveryAttempt),
    Deferred,
}

#[derive(Debug, Clone)]
pub struct InstalledRecoveryInventory {
    pub deliveries: Vec<RecoveryDelivery>,
    pub quarantined_sandboxes: Vec<QuarantinedSandbox>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RecoveryReport {
    pub ready_sandboxes: Vec<SandboxId>,
    pub deferred_sandboxes: Vec<SandboxId>,
    pub quarantined_sandboxes: Vec<QuarantinedSandbox>,
}
