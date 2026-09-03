use std::sync::Arc;

use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use joysafeter_agent_gateway_contract::ApplySandboxPolicyRequest;

use crate::application::GatewayApplication;
use crate::ids::SandboxId;
use crate::proto::gateway_management::{
    gateway_management_service_server::GatewayManagementService, ApplyPolicyRequest,
    ApplyPolicyResponse, PolicyGeneration as ProtoPolicyGeneration, RemovePolicyRequest,
    RemovePolicyResponse,
};

/// gRPC server implementing the GatewayManagementService.
///
/// This replaces the HTTP management API for policy apply/remove operations,
/// providing type-safe, high-performance communication with the orchestrator.
pub struct GatewayManagementServer {
    application: GatewayApplication,
    auth_digest: [u8; 32],
}

impl GatewayManagementServer {
    pub fn new(application: GatewayApplication, management_token: &str) -> anyhow::Result<Self> {
        let token = management_token.trim();
        if token.is_empty() {
            anyhow::bail!("management token must not be empty");
        }
        Ok(Self {
            application,
            auth_digest: Sha256::digest(token.as_bytes()).into(),
        })
    }

    fn authenticate<T>(&self, request: &Request<T>) -> Result<(), Status> {
        let token = request
            .metadata()
            .get("authorization")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "));

        let Some(token) = token else {
            return Err(Status::unauthenticated("missing authorization token"));
        };

        let candidate: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        if bool::from(candidate.ct_eq(&self.auth_digest)) {
            Ok(())
        } else {
            Err(Status::unauthenticated("invalid authorization token"))
        }
    }
}

#[tonic::async_trait]
impl GatewayManagementService for GatewayManagementServer {
    async fn apply_policy(
        &self,
        request: Request<ApplyPolicyRequest>,
    ) -> Result<Response<ApplyPolicyResponse>, Status> {
        self.authenticate(&request)?;
        let req = request.into_inner();

        let sandbox_id: SandboxId = req
            .sandbox_id
            .parse()
            .map_err(|_| Status::invalid_argument("sandbox_id must be a UUID"))?;

        // Deserialize the policy payload (JSON-encoded ApplySandboxPolicyRequest)
        let apply_request: ApplySandboxPolicyRequest = serde_json::from_slice(&req.policy_payload)
            .map_err(|e| Status::invalid_argument(format!("invalid policy payload: {}", e)))?;

        match self.application.apply_policy(sandbox_id, apply_request).await {
            Ok(generation) => {
                info!(
                    %sandbox_id,
                    policy_version = generation.policy_version,
                    "sandbox policy accepted via gRPC"
                );
                Ok(Response::new(ApplyPolicyResponse {
                    success: true,
                    error_message: String::new(),
                    applied_epoch: req.authority_epoch,
                    applied_at: None,
                }))
            }
            Err(error) => {
                warn!(%sandbox_id, %error, "gRPC apply_policy failed");
                Ok(Response::new(ApplyPolicyResponse {
                    success: false,
                    error_message: format!("{}", error),
                    applied_epoch: 0,
                    applied_at: None,
                }))
            }
        }
    }

    async fn remove_policy(
        &self,
        request: Request<RemovePolicyRequest>,
    ) -> Result<Response<RemovePolicyResponse>, Status> {
        self.authenticate(&request)?;
        let req = request.into_inner();

        let sandbox_id: SandboxId = req
            .sandbox_id
            .parse()
            .map_err(|_| Status::invalid_argument("sandbox_id must be a UUID"))?;

        let generation = req
            .expected_generation
            .map(proto_to_generation)
            .ok_or_else(|| Status::invalid_argument("expected_generation is required"))?;

        match self.application.remove_policy(sandbox_id, generation).await {
            Ok(()) => {
                info!(%sandbox_id, "sandbox policy removed via gRPC");
                Ok(Response::new(RemovePolicyResponse {
                    success: true,
                    error_message: String::new(),
                    removed_epoch: req.authority_epoch,
                }))
            }
            Err(error) => {
                warn!(%sandbox_id, %error, "gRPC remove_policy failed");
                Ok(Response::new(RemovePolicyResponse {
                    success: false,
                    error_message: format!("{}", error),
                    removed_epoch: 0,
                }))
            }
        }
    }
}

fn proto_to_generation(
    proto: ProtoPolicyGeneration,
) -> joysafeter_agent_gateway_contract::PolicyGeneration {
    joysafeter_agent_gateway_contract::PolicyGeneration {
        policy_hash: proto.policy_hash,
        policy_version: proto.policy_version as i64,
    }
}

/// Start the gRPC management server. This replaces the HTTP management API for
/// policy apply/remove, providing type-safe, high-performance orchestrator calls.
pub async fn start_management_grpc_server(
    addr: std::net::SocketAddr,
    application: GatewayApplication,
    management_token: &str,
    shutdown: crate::bootstrap::shutdown::ShutdownSignal,
) -> anyhow::Result<tokio::task::JoinHandle<anyhow::Result<()>>> {
    use crate::proto::gateway_management::gateway_management_service_server::GatewayManagementServiceServer;

    let server = GatewayManagementServer::new(application, management_token)?;
    let service = GatewayManagementServiceServer::new(server);

    let handle = tokio::spawn(async move {
        info!(%addr, "Agent Gateway management gRPC server listening");
        tonic::transport::Server::builder()
            .add_service(service)
            .serve_with_shutdown(addr, shutdown.wait())
            .await
            .map_err(|e| anyhow::anyhow!("management gRPC server failed on {addr}: {e}"))
    });

    Ok(handle)
}
