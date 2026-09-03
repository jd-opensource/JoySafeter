use std::collections::{HashMap, HashSet};
use std::sync::{Arc, RwLock};

use joysafeter_agent_gateway_contract::{AppliedSandboxGeneration, PolicyGeneration};

use crate::ids::SandboxId;
use crate::xds::model::DeliveryGeneration;

#[derive(Debug, Clone)]
pub struct StagedProjection {
    sandbox_id: SandboxId,
    generation: DeliveryGeneration,
}

#[derive(Clone, Default)]
struct SandboxProjection {
    active: Option<DeliveryGeneration>,
    versions: HashSet<DeliveryGeneration>,
}

/// Disposable, process-local index of policy generations installed in xDS.
#[derive(Clone, Default)]
pub struct PolicyProjectionRegistry {
    state: Arc<RwLock<HashMap<SandboxId, SandboxProjection>>>,
}

impl PolicyProjectionRegistry {
    pub fn stage_sandbox(
        &self,
        sandbox_id: SandboxId,
        generation: DeliveryGeneration,
    ) -> anyhow::Result<StagedProjection> {
        let mut state = self
            .state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let sandbox = state.entry(sandbox_id).or_default();
        reject_stale_or_conflicting_generation(sandbox, &generation)?;
        sandbox.versions.insert(generation.clone());
        Ok(StagedProjection {
            sandbox_id,
            generation,
        })
    }

    pub fn commit(&self, staged: &StagedProjection) -> anyhow::Result<()> {
        let mut state = self
            .state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let sandbox = state
            .get_mut(&staged.sandbox_id)
            .ok_or_else(|| anyhow::anyhow!("staged policy projection no longer exists"))?;
        reject_stale_or_conflicting_generation(sandbox, &staged.generation)?;
        if !sandbox.versions.contains(&staged.generation) {
            anyhow::bail!("staged policy generation no longer exists");
        }
        sandbox.active = Some(staged.generation.clone());
        sandbox
            .versions
            .retain(|generation| generation.policy_version >= staged.generation.policy_version);
        Ok(())
    }

    pub fn rollback(&self, staged: &StagedProjection) {
        let mut state = self
            .state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut remove_sandbox = false;
        if let Some(sandbox) = state.get_mut(&staged.sandbox_id) {
            if sandbox.active.as_ref() != Some(&staged.generation) {
                sandbox.versions.remove(&staged.generation);
            }
            remove_sandbox = sandbox.versions.is_empty();
        }
        if remove_sandbox {
            state.remove(&staged.sandbox_id);
        }
    }

    pub fn remove_sandbox(&self, sandbox_id: SandboxId) {
        self.state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&sandbox_id);
    }

    pub fn clear(&self) {
        self.state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clear();
    }

    pub(crate) fn replace_with(&self, replacement: &Self) {
        let replacement = replacement
            .state
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        *self
            .state
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = replacement;
    }

    pub fn inventory(&self) -> Vec<AppliedSandboxGeneration> {
        let state = self
            .state
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut inventory = state
            .iter()
            .filter_map(|(sandbox_id, sandbox)| {
                sandbox
                    .active
                    .as_ref()
                    .map(|generation| AppliedSandboxGeneration {
                        sandbox_id: sandbox_id.to_string(),
                        generation: PolicyGeneration {
                            policy_hash: generation.policy_hash.clone(),
                            policy_version: generation.policy_version,
                        },
                    })
            })
            .collect::<Vec<_>>();
        inventory.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
        inventory
    }

    #[cfg(test)]
    pub(crate) fn contains_state(&self, sandbox_id: SandboxId) -> bool {
        self.state
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .contains_key(&sandbox_id)
    }
}

fn reject_stale_or_conflicting_generation(
    sandbox: &SandboxProjection,
    candidate: &DeliveryGeneration,
) -> anyhow::Result<()> {
    let Some(active) = &sandbox.active else {
        return Ok(());
    };
    if candidate.policy_version < active.policy_version {
        anyhow::bail!("policy generation is stale");
    }
    if candidate.policy_version == active.policy_version
        && candidate.policy_hash != active.policy_hash
    {
        anyhow::bail!("policy generation conflicts with the active generation");
    }
    Ok(())
}
