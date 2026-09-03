use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, PolicyGeneration};

use crate::application::{GatewayApplication, GatewayApplicationError};
use crate::ids::SandboxId;
use crate::proto::policy_stream::{ApplySandboxPolicy, ReconcilePlacement, RemoveSandboxPolicy};

impl GatewayApplication {
    /// Apply a policy delivered over the policy stream (not the HTTP handler).
    ///
    /// The payload carries a JSON-serialized [`ApplySandboxPolicyRequest`], so
    /// the stream stays decoupled from the gateway's internal policy model.
    pub async fn apply_policy_from_stream(
        &self,
        apply: ApplySandboxPolicy,
    ) -> Result<(), GatewayApplicationError> {
        let sandbox_id: SandboxId = apply.sandbox_id.parse().map_err(|_| {
            GatewayApplicationError::InvalidPolicy("invalid sandbox_id in stream event".to_string())
        })?;

        let request: ApplySandboxPolicyRequest = serde_json::from_slice(&apply.policy_payload)
            .map_err(|error| GatewayApplicationError::InvalidPolicy(error.to_string()))?;

        self.apply_policy(sandbox_id, request).await?;
        Ok(())
    }

    /// Remove a policy delivered over the policy stream.
    pub async fn remove_policy_from_stream(
        &self,
        remove: RemoveSandboxPolicy,
    ) -> Result<(), GatewayApplicationError> {
        let sandbox_id: SandboxId = remove.sandbox_id.parse().map_err(|_| {
            GatewayApplicationError::InvalidPolicy("invalid sandbox_id in stream event".to_string())
        })?;

        let generation = remove
            .expected_generation
            .map(|g| PolicyGeneration {
                policy_hash: g.policy_hash,
                policy_version: g.policy_version as i64,
            })
            .ok_or(GatewayApplicationError::InvalidGeneration)?;

        self.remove_policy(sandbox_id, generation).await?;
        Ok(())
    }

    /// Reconcile placements delivered over the policy stream.
    pub async fn reconcile_placement_from_stream(
        &self,
        _placement: ReconcilePlacement,
    ) -> Result<(), GatewayApplicationError> {
        // TODO(stream): wire placement reconcile through the mutation coordinator.
        Ok(())
    }
}
