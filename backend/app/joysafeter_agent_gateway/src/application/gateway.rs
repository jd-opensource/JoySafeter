use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use joysafeter_agent_gateway_contract::{
    AppliedSandboxGeneration, ApplySandboxPolicyRequest, PolicyGeneration, SandboxPlacement,
};
use thiserror::Error;
use tokio::sync::Mutex;

use crate::application::policy::ValidatedPolicy;
use crate::application::policy_publisher::{PolicyPublisher, RemoveOutcome};
use crate::domain::placement::SandboxPlacement as ValidatedPlacement;
use crate::ids::SandboxId;
use crate::replication::model::{ReplicaMutation, ReplicatedPolicy};
use crate::replication::ReplicationCoordinator;
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::{DeliveryWaitError, XdsControlPlane};
use crate::xds::delivery::DeliveryError;
use crate::xds::model::DeliveryGeneration;

use super::mutation_coordinator::MutationCoordinator;
use super::PolicyProjectionRegistry;

const MAX_INVENTORY_SANDBOXES: usize = 20_000;

#[derive(Debug, Error)]
pub enum GatewayApplicationError {
    #[error("invalid policy: {0}")]
    InvalidPolicy(String),
    #[error("invalid placement: {0}")]
    InvalidPlacement(String),
    #[error("invalid inventory: {0}")]
    InvalidInventory(String),
    #[error("xDS authority is not ready")]
    AuthorityUnavailable,
    #[error("sandbox has no Envoy node assignment yet")]
    NodeNotReady,
    #[error("xDS authority changed during mutation")]
    AuthorityChanged,
    #[error("Envoy did not accept the policy: {0}")]
    Delivery(#[source] anyhow::Error),
    #[error("Envoy NACK'd the policy: {0}")]
    DeliveryNack(#[source] anyhow::Error),
    #[error("timed out waiting for Envoy to acknowledge the policy: {0}")]
    DeliveryTimeout(#[source] anyhow::Error),
    #[error("Gateway resource operation failed: {0}")]
    Infrastructure(#[source] anyhow::Error),
    #[error("policy generation is stale or conflicts with the active generation")]
    InvalidGeneration,
    #[error("recovery inventory does not match the applied projection")]
    RecoveryMismatch,
    #[error("hot-standby replication failed: {0}")]
    Replication(#[source] crate::replication::ReplicationError),
}

#[derive(Clone)]
pub struct ApplicationReplication {
    pub coordinator: ReplicationCoordinator,
    pub mutation_gate: Arc<Mutex<()>>,
}

#[derive(Clone)]
pub struct GatewayRuntimeConfig {
    pub delivery_timeout: Duration,
    /// Max time `apply_policy` waits outside the mutation lanes for an Envoy
    /// node assignment before returning [`GatewayApplicationError::NodeNotReady`].
    pub node_assignment_timeout: Duration,
}

/// Default cap for the pre-lock owner-node wait. Node-scoped sandboxes whose
/// Envoy node has not connected within this window get a retryable `NodeNotReady`.
pub const DEFAULT_NODE_ASSIGNMENT_TIMEOUT: Duration = Duration::from_secs(5);

/// Coordinates control-plane mutations inside the Lease leader. Mutations for
/// one sandbox are serialized, while the shared recovery gate is held only for
/// short projection/publish/commit sections and never across Envoy ACK waits.
#[derive(Clone)]
pub struct GatewayApplication {
    authority: XdsAuthority,
    publisher: PolicyPublisher,
    control_plane: XdsControlPlane,
    projections: PolicyProjectionRegistry,
    runtime: GatewayRuntimeConfig,
    mutations: MutationCoordinator,
    replication: Option<ReplicationCoordinator>,
}

impl GatewayApplication {
    pub fn new(
        authority: XdsAuthority,
        publisher: PolicyPublisher,
        control_plane: XdsControlPlane,
        projections: PolicyProjectionRegistry,
        runtime: GatewayRuntimeConfig,
    ) -> Self {
        Self {
            authority,
            publisher,
            control_plane,
            projections,
            runtime,
            mutations: MutationCoordinator::new(Arc::new(Mutex::new(()))),
            replication: None,
        }
    }

    pub fn new_replicated(
        authority: XdsAuthority,
        publisher: PolicyPublisher,
        control_plane: XdsControlPlane,
        projections: PolicyProjectionRegistry,
        runtime: GatewayRuntimeConfig,
        replication: ApplicationReplication,
    ) -> Self {
        Self {
            authority,
            publisher,
            control_plane,
            projections,
            runtime,
            mutations: MutationCoordinator::new(replication.mutation_gate),
            replication: Some(replication.coordinator),
        }
    }

    pub fn projections(&self) -> &PolicyProjectionRegistry {
        &self.projections
    }

    pub async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> Result<PolicyGeneration, GatewayApplicationError> {
        let application = self.clone();
        finish_started_mutation(tokio::spawn(async move {
            application.apply_policy_inner(sandbox_id, request).await
        }))
        .await
    }

    async fn apply_policy_inner(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> Result<PolicyGeneration, GatewayApplicationError> {
        let replica_policy = ReplicatedPolicy {
            sandbox_id: sandbox_id.to_string(),
            policy: request.clone(),
        };
        let validated = ValidatedPolicy::from_request(sandbox_id, request)
            .map_err(GatewayApplicationError::InvalidPolicy)?;
        // Wait before taking the sandbox lane so the corresponding placement
        // operation can make progress. The assignment is revalidated after the
        // lane is acquired to close the wait/remove race.
        match tokio::time::timeout(
            self.runtime.node_assignment_timeout,
            self.control_plane.wait_for_delivery_owner_node(sandbox_id),
        )
        .await
        {
            Ok(Ok(_)) => {}
            Ok(Err(error)) => return Err(GatewayApplicationError::Infrastructure(error)),
            Err(_elapsed) => return Err(GatewayApplicationError::NodeNotReady),
        }
        // Serialize the complete transaction only with operations for this
        // sandbox. Envoy ACK waits must not block unrelated sandboxes.
        let _sandbox_lane = self.mutations.lock_sandbox(sandbox_id).await;
        if self.control_plane.requires_node_assignment()
            && self.control_plane.owner_node(sandbox_id).is_none()
        {
            return Err(GatewayApplicationError::NodeNotReady);
        }
        let generation = validated.generation.clone();
        let (guard, staged, outcome) = {
            let _recovery = self.mutations.lock_recovery().await;
            let guard = self.guard()?;
            let staged = self
                .projections
                .stage_sandbox(sandbox_id, generation.clone())
                .map_err(|_| GatewayApplicationError::InvalidGeneration)?;
            guard
                .validate()
                .map_err(|_| GatewayApplicationError::AuthorityChanged)?;
            let outcome = match self
                .publisher
                .publish(
                    guard.epoch(),
                    sandbox_id,
                    generation.clone(),
                    validated.policy,
                )
                .await
            {
                Ok(outcome) => outcome,
                Err(error) => {
                    self.projections.rollback(&staged);
                    return Err(classify_resource_error(error));
                }
            };
            (guard, staged, outcome)
        };
        if let Err(error) = self
            .publisher
            .wait_for_delivery(outcome, self.runtime.delivery_timeout)
            .await
        {
            let _recovery = self.mutations.lock_recovery().await;
            self.projections.rollback(&staged);
            return Err(classify_delivery_error(error));
        }
        {
            let _recovery = self.mutations.lock_recovery().await;
            if guard.validate().is_err() {
                self.projections.rollback(&staged);
                return Err(GatewayApplicationError::AuthorityChanged);
            }
            if let Err(error) = self.projections.commit(&staged) {
                self.projections.rollback(&staged);
                return Err(GatewayApplicationError::Infrastructure(error));
            }
            self.replicate(
                guard.epoch(),
                ReplicaMutation::UpsertPolicy {
                    policy: replica_policy,
                },
            )
            .await?;
            guard
                .validate()
                .map_err(|_| GatewayApplicationError::AuthorityChanged)?;
        }
        Ok(PolicyGeneration {
            policy_hash: generation.policy_hash,
            policy_version: generation.policy_version,
        })
    }

    pub async fn remove_policy(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> Result<(), GatewayApplicationError> {
        let application = self.clone();
        finish_started_mutation(tokio::spawn(async move {
            application
                .remove_policy_inner(sandbox_id, generation)
                .await
        }))
        .await
    }

    async fn remove_policy_inner(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> Result<(), GatewayApplicationError> {
        let generation = DeliveryGeneration {
            policy_hash: generation.policy_hash,
            policy_version: generation.policy_version,
        };
        if generation.policy_hash.is_empty() || generation.policy_version <= 0 {
            return Err(GatewayApplicationError::InvalidGeneration);
        }
        let _sandbox_lane = self.mutations.lock_sandbox(sandbox_id).await;
        let (guard, outcome) = {
            let _recovery = self.mutations.lock_recovery().await;
            let guard = self.guard()?;
            let outcome = self
                .publisher
                .remove(sandbox_id, Some(generation))
                .await
                .map_err(classify_resource_error)?;
            (guard, outcome)
        };
        let RemoveOutcome::Current(outcome) = outcome else {
            return Ok(());
        };
        self.publisher
            .wait_for_delivery(outcome, self.runtime.delivery_timeout)
            .await
            .map_err(classify_delivery_error)?;
        {
            let _recovery = self.mutations.lock_recovery().await;
            guard
                .validate()
                .map_err(|_| GatewayApplicationError::AuthorityChanged)?;
            self.projections.remove_sandbox(sandbox_id);
            self.publisher.retire(sandbox_id).await;
            self.replicate(
                guard.epoch(),
                ReplicaMutation::RemovePolicy {
                    sandbox_id: sandbox_id.to_string(),
                },
            )
            .await?;
            guard
                .validate()
                .map_err(|_| GatewayApplicationError::AuthorityChanged)?;
        }
        Ok(())
    }

    pub async fn assign_placement(
        &self,
        sandbox_id: SandboxId,
        node_id: String,
    ) -> Result<(), GatewayApplicationError> {
        let placement = ValidatedPlacement::new(sandbox_id, node_id)
            .map_err(GatewayApplicationError::InvalidPlacement)?;
        let _sandbox_lane = self.mutations.lock_sandbox(sandbox_id).await;
        let _lock = self.mutations.lock_recovery().await;
        let guard = self.guard()?;
        self.publisher
            .assign_node(placement.sandbox_id, placement.node_id)
            .await
            .map_err(GatewayApplicationError::Infrastructure)?;
        self.replicate(
            guard.epoch(),
            ReplicaMutation::UpsertPlacement {
                placement: SandboxPlacement {
                    sandbox_id: placement.sandbox_id.to_string(),
                    node_id: self
                        .control_plane
                        .owner_node(placement.sandbox_id)
                        .ok_or_else(|| {
                            GatewayApplicationError::Infrastructure(anyhow::anyhow!(
                                "placement disappeared before replication"
                            ))
                        })?,
                },
            },
        )
        .await?;
        guard
            .validate()
            .map_err(|_| GatewayApplicationError::AuthorityChanged)
    }

    pub async fn remove_placement(
        &self,
        sandbox_id: SandboxId,
    ) -> Result<(), GatewayApplicationError> {
        let _sandbox_lane = self.mutations.lock_sandbox(sandbox_id).await;
        let _lock = self.mutations.lock_recovery().await;
        let guard = self.guard()?;
        self.control_plane.remove_sandbox_node(sandbox_id).await;
        self.replicate(
            guard.epoch(),
            ReplicaMutation::RemovePlacement {
                sandbox_id: sandbox_id.to_string(),
            },
        )
        .await?;
        guard
            .validate()
            .map_err(|_| GatewayApplicationError::AuthorityChanged)
    }

    pub async fn reconcile_placements(
        &self,
        placements: Vec<SandboxPlacement>,
    ) -> Result<(), GatewayApplicationError> {
        if placements.len() > MAX_INVENTORY_SANDBOXES {
            return Err(GatewayApplicationError::InvalidInventory(
                "placement inventory contains too many entries".to_string(),
            ));
        }
        let replica_placements = placements.clone();
        let mut assignments = HashMap::with_capacity(placements.len());
        for placement in placements {
            let sandbox_id = placement.sandbox_id.parse::<SandboxId>().map_err(|_| {
                GatewayApplicationError::InvalidPlacement(
                    "placement contains an invalid sandbox_id".to_string(),
                )
            })?;
            let placement = ValidatedPlacement::new(sandbox_id, placement.node_id)
                .map_err(GatewayApplicationError::InvalidPlacement)?;
            if assignments
                .insert(placement.sandbox_id, placement.node_id)
                .is_some()
            {
                return Err(GatewayApplicationError::InvalidPlacement(
                    "placement contains a duplicate sandbox_id".to_string(),
                ));
            }
        }
        let _lock = self.mutations.lock_recovery().await;
        let guard = self.guard()?;
        self.control_plane
            .replace_node_assignments(assignments)
            .await
            .map_err(GatewayApplicationError::Infrastructure)?;
        self.replicate(
            guard.epoch(),
            ReplicaMutation::ReplacePlacements {
                placements: replica_placements,
            },
        )
        .await?;
        guard
            .validate()
            .map_err(|_| GatewayApplicationError::AuthorityChanged)
    }

    pub async fn prune_policies(
        &self,
        live_sandbox_ids: Vec<String>,
    ) -> Result<Vec<SandboxId>, GatewayApplicationError> {
        if live_sandbox_ids.len() > MAX_INVENTORY_SANDBOXES {
            return Err(GatewayApplicationError::InvalidInventory(
                "inventory contains too many sandbox ids".to_string(),
            ));
        }
        let mut live = HashSet::with_capacity(live_sandbox_ids.len());
        for raw_id in live_sandbox_ids {
            let sandbox_id = raw_id.parse::<SandboxId>().map_err(|_| {
                GatewayApplicationError::InvalidInventory(
                    "inventory contains an invalid sandbox_id".to_string(),
                )
            })?;
            if !live.insert(sandbox_id) {
                return Err(GatewayApplicationError::InvalidInventory(
                    "inventory contains a duplicate sandbox_id".to_string(),
                ));
            }
        }

        let _lock = self.mutations.lock_recovery().await;
        let guard = self.guard()?;
        let configured = self
            .control_plane
            .configured_sandbox_ids(crate::xds::model::ResourceType::Listener)
            .await;
        let mut stale = configured.difference(&live).copied().collect::<Vec<_>>();
        stale.sort_by_key(|sandbox_id| sandbox_id.as_uuid());
        for sandbox_id in &stale {
            let outcome = self
                .publisher
                .remove(*sandbox_id, None)
                .await
                .map_err(GatewayApplicationError::Infrastructure)?;
            let RemoveOutcome::Current(outcome) = outcome else {
                continue;
            };
            self.publisher
                .wait_for_delivery(outcome, self.runtime.delivery_timeout)
                .await
                .map_err(classify_delivery_error)?;
            guard
                .validate()
                .map_err(|_| GatewayApplicationError::AuthorityChanged)?;
            self.projections.remove_sandbox(*sandbox_id);
            self.publisher.retire(*sandbox_id).await;
            self.replicate(
                guard.epoch(),
                ReplicaMutation::RemovePolicy {
                    sandbox_id: sandbox_id.to_string(),
                },
            )
            .await?;
        }
        Ok(stale)
    }

    pub async fn complete_recovery(
        &self,
        epoch: u64,
        mut expected: Vec<AppliedSandboxGeneration>,
    ) -> Result<(), GatewayApplicationError> {
        let _lock = self.mutations.lock_recovery().await;
        if self.authority.phase().epoch() != Some(epoch) {
            return Err(GatewayApplicationError::AuthorityChanged);
        }
        expected.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
        if self.projections.inventory() != expected {
            return Err(GatewayApplicationError::RecoveryMismatch);
        }
        self.authority
            .mark_ready_epoch(epoch)
            .map_err(|_| GatewayApplicationError::AuthorityChanged)
    }

    fn guard(
        &self,
    ) -> Result<crate::xds::authority::MutationAuthorityGuard, GatewayApplicationError> {
        self.authority
            .mutation_guard()
            .ok_or(GatewayApplicationError::AuthorityUnavailable)
    }

    async fn replicate(
        &self,
        epoch: u64,
        mutation: ReplicaMutation,
    ) -> Result<(), GatewayApplicationError> {
        let Some(replication) = &self.replication else {
            return Ok(());
        };
        replication
            .publish(epoch, mutation)
            .await
            .map_err(GatewayApplicationError::Replication)
    }
}

async fn finish_started_mutation<T>(
    task: tokio::task::JoinHandle<Result<T, GatewayApplicationError>>,
) -> Result<T, GatewayApplicationError> {
    task.await.map_err(|error| {
        GatewayApplicationError::Infrastructure(
            anyhow::Error::new(error)
                .context("Agent Gateway mutation task terminated before reaching a terminal state"),
        )
    })?
}

fn classify_resource_error(error: anyhow::Error) -> GatewayApplicationError {
    if matches!(
        error.downcast_ref::<DeliveryError>(),
        Some(
            DeliveryError::InvalidGeneration
                | DeliveryError::StaleGeneration
                | DeliveryError::ConflictingGeneration
                | DeliveryError::RemovedGeneration
                | DeliveryError::RemovalGenerationAhead
        )
    ) {
        GatewayApplicationError::InvalidGeneration
    } else {
        GatewayApplicationError::Infrastructure(error)
    }
}

fn classify_delivery_error(error: anyhow::Error) -> GatewayApplicationError {
    match error.downcast_ref::<DeliveryWaitError>() {
        Some(DeliveryWaitError::Nacked { .. }) => GatewayApplicationError::DeliveryNack(error),
        Some(DeliveryWaitError::Timeout { .. }) => GatewayApplicationError::DeliveryTimeout(error),
        None => GatewayApplicationError::Delivery(error),
    }
}

#[cfg(test)]
#[path = "../../tests/unit/application/gateway_test.rs"]
mod tests;
