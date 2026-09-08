use std::collections::HashSet;

use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, AssignSandboxPlacementRequest, CompleteRecoveryRequest,
    GatewayStatusResponse, PolicyAcceptedResponse, PolicyGeneration, ReconcilePlacementsRequest,
};
use thiserror::Error;

use crate::ids::SandboxId;

#[derive(Debug, Error)]
#[error("Agent Gateway {operation} failed ({code})")]
pub struct AgentGatewayResponseError {
    operation: &'static str,
    code: String,
}

impl AgentGatewayResponseError {
    pub fn code(&self) -> &str {
        &self.code
    }

    pub fn new(operation: &'static str, code: String) -> Self {
        Self { operation, code }
    }
}

/// Agent Gateway management boundary used by the Orchestrator.
///
/// Policy mutations on implementations of this trait must use the single
/// bidirectional `PolicyStream`; there is deliberately no HTTP policy client.
#[async_trait]
pub trait AgentGatewayApi: Send + Sync {
    async fn check_ready(&self) -> anyhow::Result<()>;

    async fn status(&self) -> anyhow::Result<GatewayStatusResponse>;

    async fn complete_recovery(&self, request: CompleteRecoveryRequest) -> anyhow::Result<()>;

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> anyhow::Result<PolicyAcceptedResponse>;

    async fn remove_policy(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> anyhow::Result<()>;

    async fn prune_policies(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<Vec<SandboxId>>;

    async fn assign_placement(
        &self,
        sandbox_id: SandboxId,
        request: AssignSandboxPlacementRequest,
    ) -> anyhow::Result<()>;

    async fn remove_placement(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;

    async fn reconcile_placements(&self, request: ReconcilePlacementsRequest)
        -> anyhow::Result<()>;
}
