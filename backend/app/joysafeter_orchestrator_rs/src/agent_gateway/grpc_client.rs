use std::collections::HashSet;
use std::time::Duration;

use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, CompleteRecoveryRequest, GatewayStatusResponse,
    PolicyAcceptedResponse, PolicyGeneration,
};
use tonic::transport::{Channel, Endpoint};
use tonic::{Code, Request, Status};
use tracing::{debug, warn};

use crate::ids::SandboxId;

use super::client::{AgentGatewayApi, AgentGatewayResponseError};

// Include generated protobuf code
pub mod proto {
    tonic::include_proto!("joysafeter.gateway.v1");
}

use proto::gateway_management_service_client::GatewayManagementServiceClient;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_RETRIES: u32 = 3;

pub struct AgentGatewayGrpcClient {
    client: GatewayManagementServiceClient<Channel>,
    management_token: String,
}

impl AgentGatewayGrpcClient {
    pub async fn new(endpoint: String, management_token: String) -> anyhow::Result<Self> {
        let channel = Endpoint::from_shared(endpoint)?
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .connect()
            .await?;

        let client = GatewayManagementServiceClient::new(channel);

        Ok(Self {
            client,
            management_token,
        })
    }

    fn is_retryable_error(status: &Status) -> bool {
        matches!(
            status.code(),
            Code::Unavailable | Code::DeadlineExceeded | Code::ResourceExhausted
        )
    }

    async fn retry_with_backoff<F, Fut, T>(
        &self,
        operation: &'static str,
        mut f: F,
    ) -> Result<T, AgentGatewayResponseError>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = Result<T, Status>>,
    {
        let mut last_error = None;

        for attempt in 0..MAX_RETRIES {
            match f().await {
                Ok(result) => return Ok(result),
                Err(status) => {
                    if !Self::is_retryable_error(&status) || attempt == MAX_RETRIES - 1 {
                        return Err(AgentGatewayResponseError::from_grpc(
                            operation,
                            reqwest::StatusCode::from_u16(status.code() as u16)
                                .unwrap_or(reqwest::StatusCode::INTERNAL_SERVER_ERROR),
                            status.message().to_string(),
                        ));
                    }

                    warn!(
                        operation,
                        attempt,
                        error = %status.message(),
                        "gRPC call failed, retrying"
                    );

                    last_error = Some(status);
                    tokio::time::sleep(Duration::from_millis(100 * (attempt as u64 + 1))).await;
                }
            }
        }

        let status = last_error.unwrap();
        Err(AgentGatewayResponseError::from_grpc(
            operation,
            reqwest::StatusCode::from_u16(status.code() as u16)
                .unwrap_or(reqwest::StatusCode::INTERNAL_SERVER_ERROR),
            status.message().to_string(),
        ))
    }
}

#[async_trait]
impl AgentGatewayApi for AgentGatewayGrpcClient {
    async fn check_ready(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn status(&self) -> anyhow::Result<GatewayStatusResponse> {
        anyhow::bail!("status() not yet implemented for gRPC client")
    }

    async fn complete_recovery(&self, _request: CompleteRecoveryRequest) -> anyhow::Result<()> {
        Ok(())
    }

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> anyhow::Result<PolicyAcceptedResponse> {
        let generation = request.generation.clone();

        let grpc_request = proto::ApplyPolicyRequest {
            sandbox_id: sandbox_id.to_string(),
            generation: Some(proto::PolicyGeneration {
                policy_hash: generation.policy_hash.clone(),
                policy_version: generation.policy_version as u64,
            }),
            policy_payload: serde_json::to_vec(&request)?,
            authority_epoch: 0,
            trace_id: String::new(),
        };

        let client = self.client.clone();
        let token = self.management_token.clone();

        let response = self
            .retry_with_backoff("policy apply", || {
                let mut client = client.clone();
                let mut req = Request::new(grpc_request.clone());
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.apply_policy(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC apply_policy failed: {}", e))?;

        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!("Gateway rejected policy apply: {}", inner.error_message);
        }

        debug!(sandbox_id = %sandbox_id, applied_epoch = inner.applied_epoch, "Policy applied via gRPC");

        Ok(PolicyAcceptedResponse {
            sandbox_id: sandbox_id.to_string(),
            generation,
            status: "ready".to_string(),
        })
    }

    async fn remove_policy(
        &self,
        sandbox_id: SandboxId,
        generation: PolicyGeneration,
    ) -> anyhow::Result<()> {
        let grpc_request = proto::RemovePolicyRequest {
            sandbox_id: sandbox_id.to_string(),
            expected_generation: Some(proto::PolicyGeneration {
                policy_hash: generation.policy_hash.clone(),
                policy_version: generation.policy_version as u64,
            }),
            authority_epoch: 0,
            trace_id: String::new(),
        };

        let client = self.client.clone();
        let token = self.management_token.clone();

        let response = self
            .retry_with_backoff("policy removal", || {
                let mut client = client.clone();
                let mut req = Request::new(grpc_request.clone());
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.remove_policy(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC remove_policy failed: {}", e))?;

        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!("Gateway rejected policy removal: {}", inner.error_message);
        }

        debug!(sandbox_id = %sandbox_id, "Policy removed via gRPC");
        Ok(())
    }

    async fn prune_policies(
        &self,
        _live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<Vec<SandboxId>> {
        Ok(Vec::new())
    }

    async fn assign_placement(
        &self,
        _sandbox_id: SandboxId,
        _request: joysafeter_agent_gateway_contract::AssignSandboxPlacementRequest,
    ) -> anyhow::Result<()> {
        Ok(())
    }

    async fn remove_placement(&self, _sandbox_id: SandboxId) -> anyhow::Result<()> {
        Ok(())
    }

    async fn reconcile_placements(
        &self,
        _request: joysafeter_agent_gateway_contract::ReconcilePlacementsRequest,
    ) -> anyhow::Result<()> {
        Ok(())
    }
}
