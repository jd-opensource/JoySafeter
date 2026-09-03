use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::Mutex;

use crate::application::policy::ValidatedPolicy;
use crate::application::policy_publisher::PolicyPublisher;
use crate::application::PolicyProjectionRegistry;
use crate::ids::SandboxId;
use crate::xds::control_plane::XdsControlPlane;
use crate::xds::inventory::{RecoveredSandbox, RecoveryInventory};

use super::model::{ReplicaMutation, ReplicatedPolicy, ReplicatedSnapshot};

#[derive(Clone)]
pub struct ReplicaProjector {
    control_plane: XdsControlPlane,
    publisher: PolicyPublisher,
    projections: PolicyProjectionRegistry,
    mutation_gate: Arc<Mutex<()>>,
}

impl ReplicaProjector {
    pub fn new(
        control_plane: XdsControlPlane,
        publisher: PolicyPublisher,
        projections: PolicyProjectionRegistry,
        mutation_gate: Arc<Mutex<()>>,
    ) -> Self {
        Self {
            control_plane,
            publisher,
            projections,
            mutation_gate,
        }
    }

    pub fn mutation_gate(&self) -> Arc<Mutex<()>> {
        self.mutation_gate.clone()
    }

    pub async fn install_snapshot(&self, snapshot: &ReplicatedSnapshot) -> anyhow::Result<()> {
        let (resources, projections, assignments) = self.prepare(snapshot).await?;
        self.control_plane
            .install_replica_inventory(resources, assignments)
            .await?;
        self.projections.replace_with(&projections);
        Ok(())
    }

    pub async fn install_delta(&self, mutation: &ReplicaMutation) -> anyhow::Result<()> {
        match mutation {
            ReplicaMutation::UpsertPolicy { policy } => {
                let (sandbox_id, validated) = validate_policy(policy)?;
                let generation = validated.generation.clone();
                let staged = self
                    .projections
                    .stage_sandbox(sandbox_id, generation.clone())?;
                let resources = match self
                    .publisher
                    .compile(sandbox_id, &generation, &validated.policy)
                    .await
                {
                    Ok(resources) => resources,
                    Err(error) => {
                        self.projections.rollback(&staged);
                        return Err(error);
                    }
                };
                if let Err(error) = self
                    .control_plane
                    .install_replica_sandbox(sandbox_id, resources)
                    .await
                {
                    self.projections.rollback(&staged);
                    return Err(error);
                }
                self.projections.commit(&staged)?;
            }
            ReplicaMutation::RemovePolicy { sandbox_id } => {
                let sandbox_id = parse_sandbox_id(sandbox_id)?;
                self.control_plane.remove_replica_sandbox(sandbox_id).await;
                self.projections.remove_sandbox(sandbox_id);
            }
            ReplicaMutation::UpsertPlacement { placement } => {
                let sandbox_id = parse_sandbox_id(&placement.sandbox_id)?;
                validate_node(&placement.node_id)?;
                self.control_plane
                    .install_replica_placement(sandbox_id, placement.node_id.clone());
            }
            ReplicaMutation::RemovePlacement { sandbox_id } => {
                self.control_plane
                    .remove_replica_placement(parse_sandbox_id(sandbox_id)?);
            }
            ReplicaMutation::ReplacePlacements { placements } => {
                let assignments = parse_assignments(placements)?;
                self.control_plane
                    .install_replica_placements(assignments)
                    .await;
            }
        }
        Ok(())
    }

    pub async fn recovery_inventory(
        &self,
        snapshot: &ReplicatedSnapshot,
    ) -> anyhow::Result<RecoveryInventory> {
        let mut recovered = Vec::with_capacity(snapshot.policies.len());
        for policy in &snapshot.policies {
            let (sandbox_id, validated) = validate_policy(policy)?;
            recovered.push(RecoveredSandbox {
                sandbox_id,
                generation: validated.generation.clone(),
                resources: self
                    .publisher
                    .compile(sandbox_id, &validated.generation, &validated.policy)
                    .await?,
            });
        }
        RecoveryInventory::new(recovered)
    }

    async fn prepare(
        &self,
        snapshot: &ReplicatedSnapshot,
    ) -> anyhow::Result<(
        Vec<crate::xds::model::ManagedXdsResource>,
        PolicyProjectionRegistry,
        HashMap<SandboxId, String>,
    )> {
        let projections = PolicyProjectionRegistry::default();
        let mut resources = Vec::new();
        for policy in &snapshot.policies {
            let (sandbox_id, validated) = validate_policy(policy)?;
            let generation = validated.generation.clone();
            let staged = projections.stage_sandbox(sandbox_id, generation.clone())?;
            projections.commit(&staged)?;
            resources.extend(
                self.publisher
                    .compile(sandbox_id, &generation, &validated.policy)
                    .await?,
            );
        }
        Ok((
            resources,
            projections,
            parse_assignments(&snapshot.placements)?,
        ))
    }
}

fn validate_policy(policy: &ReplicatedPolicy) -> anyhow::Result<(SandboxId, ValidatedPolicy)> {
    let sandbox_id = parse_sandbox_id(&policy.sandbox_id)?;
    let validated = ValidatedPolicy::from_request(sandbox_id, policy.policy.clone())
        .map_err(anyhow::Error::msg)?;
    Ok((sandbox_id, validated))
}

fn parse_assignments(
    placements: &[joysafeter_agent_gateway_contract::SandboxPlacement],
) -> anyhow::Result<HashMap<SandboxId, String>> {
    let mut assignments = HashMap::with_capacity(placements.len());
    for placement in placements {
        let sandbox_id = parse_sandbox_id(&placement.sandbox_id)?;
        validate_node(&placement.node_id)?;
        if assignments
            .insert(sandbox_id, placement.node_id.clone())
            .is_some()
        {
            anyhow::bail!("duplicate sandbox placement in replica snapshot");
        }
    }
    Ok(assignments)
}

fn parse_sandbox_id(value: &str) -> anyhow::Result<SandboxId> {
    value
        .parse::<SandboxId>()
        .map_err(|_| anyhow::anyhow!("invalid sandbox id in replica state"))
}

fn validate_node(node: &str) -> anyhow::Result<()> {
    if node.trim().is_empty() || node.len() > 253 {
        anyhow::bail!("invalid node id in replica state");
    }
    Ok(())
}

#[cfg(test)]
#[path = "../../tests/unit/replication/projector_test.rs"]
mod tests;
