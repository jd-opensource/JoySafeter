use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, AssignSandboxPlacementRequest, CompleteRecoveryRequest,
    GatewayStatusResponse, PruneSandboxPoliciesRequest, PruneSandboxPoliciesResponse,
    ReconcilePlacementsRequest,
};

use crate::application::{GatewayApplication, GatewayApplicationError};
use crate::ids::SandboxId;
use crate::proto::gateway_management::{
    gateway_management_service_server::GatewayManagementService, ApplyPolicyRequest,
    ApplyPolicyResponse, GetStatusRequest, JsonRequest, JsonResponse, PlacementRequest,
    PolicyGeneration as ProtoPolicyGeneration, RemovePolicyRequest, RemovePolicyResponse,
};
use crate::xds::authority::{AuthorityPhase, XdsAuthority};

/// gRPC server implementing the GatewayManagementService.
///
/// Replaces the HTTP management API for all orchestrator→gateway operations
/// (apply/remove policy, status, recovery, prune, placement) with a type-safe,
/// high-performance gRPC surface.
pub struct GatewayManagementServer {
    application: GatewayApplication,
    auth_digest: [u8; 32],
    instance_id: String,
    boot_id: String,
    authority: XdsAuthority,
}

impl GatewayManagementServer {
    pub fn new(
        application: GatewayApplication,
        management_token: &str,
        instance_id: String,
        boot_id: String,
        authority: XdsAuthority,
    ) -> anyhow::Result<Self> {
        let token = management_token.trim();
        if token.is_empty() {
            anyhow::bail!("management token must not be empty");
        }
        Ok(Self {
            application,
            auth_digest: Sha256::digest(token.as_bytes()).into(),
            instance_id,
            boot_id,
            authority,
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
                    // The applied epoch is owned internally by the mutation guard
                    // and is not surfaced through apply_policy; report 0 rather than
                    // echoing the client's (possibly stale) request epoch. (G1)
                    applied_epoch: 0,
                    applied_at: None,
                }))
            }
            Err(error) => {
                warn!(%sandbox_id, %error, "gRPC apply_policy failed");
                Err(app_error_to_status(&error))
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
                    removed_epoch: 0,
                }))
            }
            Err(error) => {
                warn!(%sandbox_id, %error, "gRPC remove_policy failed");
                Err(app_error_to_status(&error))
            }
        }
    }

    async fn get_status(
        &self,
        request: Request<GetStatusRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        // Snapshot the phase once so the epoch and phase string are consistent
        // (the phase can change between two separate reads). (Fixes G2.)
        let phase = self.authority.phase();
        let Some(authority_epoch) = phase.epoch() else {
            return Err(Status::unavailable("xDS authority has no active epoch"));
        };
        let status = GatewayStatusResponse {
            instance_id: self.instance_id.clone(),
            boot_id: self.boot_id.clone(),
            authority_epoch,
            authority_phase: match phase {
                AuthorityPhase::Standby => "standby",
                AuthorityPhase::Staging { .. } => "staging",
                AuthorityPhase::RecoveryServing { .. } => "recovery_serving",
                AuthorityPhase::Ready { .. } => "ready",
                AuthorityPhase::Revoked { .. } => "revoked",
            }
            .to_string(),
            generations: self.application.projections().inventory(),
        };
        match serde_json::to_vec(&status) {
            Ok(payload) => Ok(Response::new(JsonResponse {
                success: true,
                error_message: String::new(),
                payload,
            })),
            Err(e) => Err(Status::internal(format!("failed to serialize status: {e}"))),
        }
    }

    async fn complete_recovery(
        &self,
        request: Request<JsonRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req: CompleteRecoveryRequest = match serde_json::from_slice(&request.into_inner().payload)
        {
            Ok(r) => r,
            Err(e) => return Err(Status::invalid_argument(format!("invalid payload: {e}"))),
        };
        if req.boot_id != self.boot_id {
            return Err(Status::failed_precondition("Gateway restarted during recovery"));
        }
        match self
            .application
            .complete_recovery(req.authority_epoch, req.generations)
            .await
        {
            Ok(()) => Ok(Response::new(json_ok())),
            Err(error) => Err(app_error_to_status(&error)),
        }
    }

    async fn prune_policies(
        &self,
        request: Request<JsonRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req: PruneSandboxPoliciesRequest =
            match serde_json::from_slice(&request.into_inner().payload) {
                Ok(r) => r,
                Err(e) => return Err(Status::invalid_argument(format!("invalid payload: {e}"))),
            };
        match self.application.prune_policies(req.live_sandbox_ids).await {
            Ok(removed) => {
                let body = PruneSandboxPoliciesResponse {
                    removed_sandbox_ids: removed.into_iter().map(|id| id.to_string()).collect(),
                };
                match serde_json::to_vec(&body) {
                    Ok(payload) => Ok(Response::new(JsonResponse {
                        success: true,
                        error_message: String::new(),
                        payload,
                    })),
                    Err(e) => Err(Status::internal(format!("serialize failed: {e}"))),
                }
            }
            Err(error) => Err(app_error_to_status(&error)),
        }
    }

    async fn assign_placement(
        &self,
        request: Request<PlacementRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req = request.into_inner();
        let sandbox_id: SandboxId = match req.sandbox_id.parse() {
            Ok(id) => id,
            Err(_) => return Err(Status::invalid_argument("sandbox_id must be a UUID")),
        };
        let body: AssignSandboxPlacementRequest = match serde_json::from_slice(&req.payload) {
            Ok(b) => b,
            Err(e) => return Err(Status::invalid_argument(format!("invalid payload: {e}"))),
        };
        match self.application.assign_placement(sandbox_id, body.node_id).await {
            Ok(()) => Ok(Response::new(json_ok())),
            Err(error) => Err(app_error_to_status(&error)),
        }
    }

    async fn remove_placement(
        &self,
        request: Request<PlacementRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req = request.into_inner();
        let sandbox_id: SandboxId = match req.sandbox_id.parse() {
            Ok(id) => id,
            Err(_) => return Err(Status::invalid_argument("sandbox_id must be a UUID")),
        };
        match self.application.remove_placement(sandbox_id).await {
            Ok(()) => Ok(Response::new(json_ok())),
            Err(error) => Err(app_error_to_status(&error)),
        }
    }

    async fn reconcile_placements(
        &self,
        request: Request<JsonRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req: ReconcilePlacementsRequest =
            match serde_json::from_slice(&request.into_inner().payload) {
                Ok(r) => r,
                Err(e) => return Err(Status::invalid_argument(format!("invalid payload: {e}"))),
            };
        match self.application.reconcile_placements(req.assignments).await {
            Ok(()) => Ok(Response::new(json_ok())),
            Err(error) => Err(app_error_to_status(&error)),
        }
    }
}

fn json_ok() -> JsonResponse {
    JsonResponse {
        success: true,
        error_message: String::new(),
        payload: Vec::new(),
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

/// Map an application error to a gRPC status so the caller can distinguish
/// retryable (transient) failures from terminal ones. Retryable variants use
/// codes the orchestrator client's retry/backoff treats as retryable
/// (`Unavailable`/`DeadlineExceeded`); terminal variants use `InvalidArgument`/
/// `FailedPrecondition`, which must not be retried. (Fixes G1.)
fn app_error_to_status(error: &GatewayApplicationError) -> Status {
    use GatewayApplicationError as E;
    let message = error.to_string();
    match error {
        // Transient — retrying (possibly against a new leader) can succeed.
        E::NodeNotReady
        | E::AuthorityUnavailable
        | E::AuthorityChanged
        | E::Replication(_)
        | E::Delivery(_)
        | E::Infrastructure(_) => Status::unavailable(message),
        E::DeliveryTimeout(_) => Status::deadline_exceeded(message),
        // Terminal — the request itself is malformed or stale; do not retry.
        E::InvalidPolicy(_) | E::InvalidPlacement(_) | E::InvalidInventory(_) => {
            Status::invalid_argument(message)
        }
        E::InvalidGeneration | E::RecoveryMismatch | E::DeliveryNack(_) => {
            Status::failed_precondition(message)
        }
    }
}

/// Start the gRPC management server. This replaces the HTTP management API for
/// policy apply/remove, providing type-safe, high-performance orchestrator calls.
pub async fn start_management_grpc_server(
    addr: std::net::SocketAddr,
    application: GatewayApplication,
    management_token: &str,
    instance_id: String,
    boot_id: String,
    authority: XdsAuthority,
    shutdown: crate::bootstrap::shutdown::ShutdownSignal,
) -> anyhow::Result<tokio::task::JoinHandle<anyhow::Result<()>>> {
    use crate::proto::gateway_management::gateway_management_service_server::GatewayManagementServiceServer;

    let server = GatewayManagementServer::new(
        application,
        management_token,
        instance_id,
        boot_id,
        authority,
    )?;
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
