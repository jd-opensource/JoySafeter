use std::collections::HashMap;
use std::pin::Pin;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use futures::Stream;
use prost::Message;
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tokio::sync::{mpsc, OwnedSemaphorePermit, Semaphore};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Code, Request, Response, Status};
use tracing::{info, warn};

use joysafeter_agent_gateway_contract::{
    AssignSandboxPlacementRequest, CompleteRecoveryRequest, GatewayStatusResponse,
    PruneSandboxPoliciesRequest, PruneSandboxPoliciesResponse, ReconcilePlacementsRequest,
};

use crate::application::{GatewayApplication, GatewayApplicationError};
use crate::ids::SandboxId;
use crate::proto::gateway_management::{
    gateway_management_service_server::GatewayManagementService, policy_stream_request,
    GetStatusRequest, JsonRequest, JsonResponse, PlacementRequest,
    PolicyGeneration as ProtoPolicyGeneration, PolicyStreamRequest, PolicyStreamResponse,
    StreamApplyPolicy, StreamRemovePolicy,
};
use crate::xds::authority::{AuthorityPhase, XdsAuthority};

const ERROR_REASON_METADATA: &str = "x-joysafeter-error-reason";
const ERROR_RETRYABLE_METADATA: &str = "x-joysafeter-error-retryable";
const DEFAULT_POLICY_COMMAND_QUEUE_CAPACITY: usize = 128;
const DEFAULT_MAX_CONCURRENT_POLICY_COMMANDS: usize = 256;
const DEFAULT_MAX_OUTSTANDING_POLICY_COMMANDS: usize = 512;
#[cfg(test)]
const MAX_OUTSTANDING_POLICY_COMMANDS: usize = DEFAULT_MAX_OUTSTANDING_POLICY_COMMANDS;
const POLICY_LANE_IDLE_TIMEOUT: Duration = Duration::from_secs(30);
const LANE_REGISTRY_SWEEP_THRESHOLD: usize = 65_536;
pub(crate) const MAX_POLICY_STREAM_MESSAGE_BYTES: usize = 1024 * 1024;
// Administrative inventory RPCs can legitimately contain thousands of
// placements; they retain a bounded ceiling independent of the 1 MiB policy
// hot-path and 4 MiB replication-frame limits.
pub(crate) const MAX_MANAGEMENT_MESSAGE_BYTES: usize = 16 * 1024 * 1024;
pub(crate) const MAX_REPLICATION_MESSAGE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone, Copy)]
pub struct ManagementGrpcLimits {
    pub policy_lane_queue_capacity: usize,
    pub max_concurrent_policy_commands: usize,
    pub max_outstanding_policy_commands: usize,
    pub max_policy_streams: usize,
    pub max_replication_streams: usize,
}

impl Default for ManagementGrpcLimits {
    fn default() -> Self {
        Self {
            policy_lane_queue_capacity: DEFAULT_POLICY_COMMAND_QUEUE_CAPACITY,
            max_concurrent_policy_commands: DEFAULT_MAX_CONCURRENT_POLICY_COMMANDS,
            max_outstanding_policy_commands: DEFAULT_MAX_OUTSTANDING_POLICY_COMMANDS,
            max_policy_streams: 64,
            max_replication_streams: 32,
        }
    }
}

/// gRPC server implementing the GatewayManagementService.
///
/// Replaces the HTTP management API for all orchestrator→gateway operations
/// (apply/remove policy, status, recovery, prune, placement) with a type-safe,
/// high-performance gRPC surface.
pub struct GatewayManagementServer {
    application: GatewayApplication,
    policy_commands: PolicyCommandDispatcher,
    auth_digest: [u8; 32],
    instance_id: String,
    boot_id: String,
    authority: XdsAuthority,
    policy_stream_permits: Arc<Semaphore>,
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
        let policy_commands = PolicyCommandDispatcher::new(application.clone());
        Ok(Self {
            application,
            policy_commands,
            auth_digest: Sha256::digest(token.as_bytes()).into(),
            instance_id,
            boot_id,
            authority,
            policy_stream_permits: Arc::new(Semaphore::new(64)),
        })
    }

    #[allow(clippy::result_large_err)]
    fn authenticate<T>(&self, request: &Request<T>) -> Result<(), Status> {
        let token = request
            .metadata()
            .get("authorization")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "));

        let Some(token) = token else {
            return Err(public_status(
                Code::Unauthenticated,
                "unauthenticated",
                "management authentication failed",
                false,
            ));
        };

        let candidate: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        if bool::from(candidate.ct_eq(&self.auth_digest)) {
            Ok(())
        } else {
            Err(public_status(
                Code::Unauthenticated,
                "unauthenticated",
                "management authentication failed",
                false,
            ))
        }
    }
}

#[derive(Clone)]
struct PolicyCommandDispatcher {
    application: GatewayApplication,
    execution_permits: Arc<Semaphore>,
    admission_permits: Arc<Semaphore>,
    lanes: Arc<StdMutex<HashMap<SandboxId, mpsc::WeakSender<PolicyCommandWork>>>>,
    metrics: crate::xds::metrics::XdsMetrics,
    lane_queue_capacity: usize,
}

struct PolicyCommandWork {
    command_id: String,
    command: PolicyCommand,
    response_tx: mpsc::Sender<Result<PolicyStreamResponse, Status>>,
    _admission_permit: OwnedSemaphorePermit,
}

enum PolicyCommand {
    Apply(StreamApplyPolicy),
    Remove(StreamRemovePolicy),
}

impl PolicyCommandDispatcher {
    fn new(application: GatewayApplication) -> Self {
        Self::with_limits(application, ManagementGrpcLimits::default())
    }

    fn with_limits(application: GatewayApplication, limits: ManagementGrpcLimits) -> Self {
        let metrics = application.metrics();
        Self {
            application,
            execution_permits: Arc::new(Semaphore::new(limits.max_concurrent_policy_commands)),
            admission_permits: Arc::new(Semaphore::new(limits.max_outstanding_policy_commands)),
            lanes: Arc::new(StdMutex::new(HashMap::new())),
            metrics,
            lane_queue_capacity: limits.policy_lane_queue_capacity,
        }
    }

    fn lane(&self, sandbox_id: SandboxId) -> mpsc::Sender<PolicyCommandWork> {
        let mut lanes = self
            .lanes
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if lanes.len() >= LANE_REGISTRY_SWEEP_THRESHOLD {
            lanes.retain(|_, lane| lane.strong_count() > 0);
        }
        if let Some(lane) = lanes.get(&sandbox_id).and_then(mpsc::WeakSender::upgrade) {
            return lane;
        }
        let (lane_tx, lane_rx) = mpsc::channel(self.lane_queue_capacity);
        lanes.insert(sandbox_id, lane_tx.downgrade());
        tokio::spawn(run_policy_lane(
            sandbox_id,
            lane_tx.clone(),
            lane_rx,
            self.lanes.clone(),
            self.application.clone(),
            self.execution_permits.clone(),
        ));
        lane_tx
    }

    async fn dispatch(
        &self,
        request: PolicyStreamRequest,
        response_tx: mpsc::Sender<Result<PolicyStreamResponse, Status>>,
    ) {
        if request.encoded_len() > MAX_POLICY_STREAM_MESSAGE_BYTES {
            let _ = response_tx
                .send(Ok(stream_error(
                    request.command_id,
                    "policy_too_large",
                    false,
                    "policy command exceeds the transport size limit",
                )))
                .await;
            return;
        }
        let command_id = request.command_id;
        if uuid::Uuid::parse_str(&command_id).is_err() {
            let _ = response_tx
                .send(Ok(stream_error(
                    command_id,
                    "invalid_command_id",
                    false,
                    "command_id must be a UUID",
                )))
                .await;
            return;
        }
        let (sandbox_id, command) = match request.command {
            Some(policy_stream_request::Command::ApplyPolicy(command)) => {
                (command.sandbox_id.clone(), PolicyCommand::Apply(command))
            }
            Some(policy_stream_request::Command::RemovePolicy(command)) => {
                (command.sandbox_id.clone(), PolicyCommand::Remove(command))
            }
            None => {
                let _ = response_tx
                    .send(Ok(stream_error(
                        command_id,
                        "missing_command",
                        false,
                        "policy command is required",
                    )))
                    .await;
                return;
            }
        };
        let sandbox_id = match sandbox_id.parse::<SandboxId>() {
            Ok(sandbox_id) => sandbox_id,
            Err(_) => {
                let _ = response_tx
                    .send(Ok(stream_error(
                        command_id,
                        "invalid_sandbox_id",
                        false,
                        "sandbox_id must be a UUID",
                    )))
                    .await;
                return;
            }
        };
        self.metrics.begin_policy_stream_command();
        let admission_permit = match self.admission_permits.clone().try_acquire_owned() {
            Ok(permit) => permit,
            Err(tokio::sync::TryAcquireError::NoPermits) => {
                self.metrics.record_policy_stream_queue_saturation();
                self.metrics.end_policy_stream_command();
                let _ = response_tx
                    .send(Ok(stream_error(
                        command_id,
                        "gateway_overloaded",
                        true,
                        "policy command capacity is exhausted",
                    )))
                    .await;
                return;
            }
            Err(tokio::sync::TryAcquireError::Closed) => {
                self.metrics.end_policy_stream_command();
                let _ = response_tx
                    .send(Ok(stream_error(
                        command_id,
                        "stream_unavailable",
                        true,
                        "policy command stream is unavailable",
                    )))
                    .await;
                return;
            }
        };
        let lane = self.lane(sandbox_id);
        let work = PolicyCommandWork {
            command_id,
            command,
            response_tx: response_tx.clone(),
            _admission_permit: admission_permit,
        };
        if let Err(error) = lane.send(work).await {
            self.metrics.end_policy_stream_command();
            let _ = response_tx
                .send(Ok(stream_error(
                    error.0.command_id,
                    "stream_unavailable",
                    true,
                    "policy command lane is unavailable",
                )))
                .await;
        }
    }
}

async fn run_policy_lane(
    sandbox_id: SandboxId,
    keepalive_tx: mpsc::Sender<PolicyCommandWork>,
    mut lane_rx: mpsc::Receiver<PolicyCommandWork>,
    lanes: Arc<StdMutex<HashMap<SandboxId, mpsc::WeakSender<PolicyCommandWork>>>>,
    application: GatewayApplication,
    execution_permits: Arc<Semaphore>,
) {
    loop {
        let work = match tokio::time::timeout(POLICY_LANE_IDLE_TIMEOUT, lane_rx.recv()).await {
            Ok(Some(work)) => work,
            Ok(None) => return,
            Err(_) => {
                let mut registry = lanes
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                let can_retire = registry
                    .get(&sandbox_id)
                    .and_then(mpsc::WeakSender::upgrade)
                    .is_some_and(|current| {
                        current.same_channel(&keepalive_tx) && keepalive_tx.strong_count() == 2
                    });
                if can_retire {
                    registry.remove(&sandbox_id);
                    return;
                }
                continue;
            }
        };
        let permit = match execution_permits.clone().acquire_owned().await {
            Ok(permit) => permit,
            Err(_) => return,
        };
        let response = execute_policy_command(&application, work.command_id, work.command).await;
        drop(permit);
        application.metrics().end_policy_stream_command();
        // A disconnected caller must not cancel a mutation that has already
        // started. The caller can replay the durable generation.
        let _ = work.response_tx.send(Ok(response)).await;
    }
}

#[tonic::async_trait]
impl GatewayManagementService for GatewayManagementServer {
    type PolicyStreamStream =
        Pin<Box<dyn Stream<Item = Result<PolicyStreamResponse, Status>> + Send + 'static>>;

    async fn policy_stream(
        &self,
        request: Request<tonic::Streaming<PolicyStreamRequest>>,
    ) -> Result<Response<Self::PolicyStreamStream>, Status> {
        self.authenticate(&request)?;
        let stream_permit = self
            .policy_stream_permits
            .clone()
            .try_acquire_owned()
            .map_err(|_| {
                public_status(
                    Code::ResourceExhausted,
                    "policy_stream_capacity_exhausted",
                    "policy stream connection capacity is exhausted",
                    true,
                )
            })?;
        let mut inbound = request.into_inner();
        let dispatcher = self.policy_commands.clone();
        let metrics = self.application.metrics();
        metrics.begin_policy_stream();
        let (response_tx, response_rx) = mpsc::channel(DEFAULT_POLICY_COMMAND_QUEUE_CAPACITY);
        tokio::spawn(async move {
            let _stream_permit = stream_permit;
            loop {
                match inbound.message().await {
                    Ok(Some(command)) => dispatcher.dispatch(command, response_tx.clone()).await,
                    Ok(None) => break,
                    Err(error) => {
                        warn!(%error, "policy command stream receive failed");
                        break;
                    }
                }
            }
            metrics.end_policy_stream();
        });
        Ok(Response::new(Box::pin(ReceiverStream::new(response_rx))))
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
            return Err(public_status(
                Code::Unavailable,
                "authority_unavailable",
                "xDS authority is not ready",
                true,
            ));
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
            Err(error) => {
                warn!(%error, "failed to serialize gRPC status response");
                Err(public_status(
                    Code::Internal,
                    "response_serialization_failed",
                    "failed to build Gateway response",
                    true,
                ))
            }
        }
    }

    async fn complete_recovery(
        &self,
        request: Request<JsonRequest>,
    ) -> Result<Response<JsonResponse>, Status> {
        self.authenticate(&request)?;
        let req: CompleteRecoveryRequest =
            match serde_json::from_slice(&request.into_inner().payload) {
                Ok(r) => r,
                Err(error) => {
                    warn!(%error, "invalid gRPC recovery payload");
                    return Err(invalid_request_status(
                        "invalid_payload",
                        "invalid request payload",
                    ));
                }
            };
        if req.boot_id != self.boot_id {
            return Err(public_status(
                Code::Unavailable,
                "gateway_restarted",
                "Gateway restarted during recovery",
                true,
            ));
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
                Err(error) => {
                    warn!(%error, "invalid gRPC prune payload");
                    return Err(invalid_request_status(
                        "invalid_payload",
                        "invalid request payload",
                    ));
                }
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
                    Err(error) => {
                        warn!(%error, "failed to serialize gRPC prune response");
                        Err(public_status(
                            Code::Internal,
                            "response_serialization_failed",
                            "failed to build Gateway response",
                            true,
                        ))
                    }
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
            Err(_) => {
                return Err(invalid_request_status(
                    "invalid_sandbox_id",
                    "sandbox_id must be a UUID",
                ))
            }
        };
        let body: AssignSandboxPlacementRequest = match serde_json::from_slice(&req.payload) {
            Ok(b) => b,
            Err(error) => {
                warn!(%error, "invalid gRPC placement payload");
                return Err(invalid_request_status(
                    "invalid_payload",
                    "invalid request payload",
                ));
            }
        };
        match self
            .application
            .assign_placement(sandbox_id, body.node_id)
            .await
        {
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
            Err(_) => {
                return Err(invalid_request_status(
                    "invalid_sandbox_id",
                    "sandbox_id must be a UUID",
                ))
            }
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
                Err(error) => {
                    warn!(%error, "invalid gRPC placement reconciliation payload");
                    return Err(invalid_request_status(
                        "invalid_payload",
                        "invalid request payload",
                    ));
                }
            };
        match self.application.reconcile_placements(req.assignments).await {
            Ok(()) => Ok(Response::new(json_ok())),
            Err(error) => Err(app_error_to_status(&error)),
        }
    }
}

async fn execute_policy_command(
    application: &GatewayApplication,
    command_id: String,
    command: PolicyCommand,
) -> PolicyStreamResponse {
    match command {
        PolicyCommand::Apply(command) => {
            execute_apply_command(application, command_id, command).await
        }
        PolicyCommand::Remove(command) => {
            execute_remove_command(application, command_id, command).await
        }
    }
}

async fn execute_apply_command(
    application: &GatewayApplication,
    command_id: String,
    command: StreamApplyPolicy,
) -> PolicyStreamResponse {
    let sandbox_id = match command.sandbox_id.parse::<SandboxId>() {
        Ok(sandbox_id) => sandbox_id,
        Err(_) => {
            return stream_error(
                command_id,
                "invalid_sandbox_id",
                false,
                "sandbox_id must be a UUID",
            )
        }
    };
    let request = match command
        .policy
        .map(crate::adapters::proto_conversion::policy_from_proto)
        .transpose()
    {
        Ok(Some(request)) => request,
        Ok(None) | Err(_) => {
            return stream_error(
                command_id,
                "invalid_policy",
                false,
                "invalid policy payload",
            );
        }
    };
    match application.apply_policy(sandbox_id, request).await {
        Ok(generation) => {
            info!(%sandbox_id, %command_id, policy_version = generation.policy_version, "policy stream apply completed");
            stream_success(command_id, Some(generation))
        }
        Err(error) => {
            warn!(%sandbox_id, %command_id, %error, "policy stream apply failed");
            stream_application_error(command_id, &error)
        }
    }
}

async fn execute_remove_command(
    application: &GatewayApplication,
    command_id: String,
    command: StreamRemovePolicy,
) -> PolicyStreamResponse {
    let sandbox_id = match command.sandbox_id.parse::<SandboxId>() {
        Ok(sandbox_id) => sandbox_id,
        Err(_) => {
            return stream_error(
                command_id,
                "invalid_sandbox_id",
                false,
                "sandbox_id must be a UUID",
            )
        }
    };
    let generation = match command
        .expected_generation
        .and_then(checked_proto_generation)
    {
        Some(generation) => generation,
        None => {
            return stream_error(
                command_id,
                "invalid_generation",
                false,
                "a valid expected generation is required",
            )
        }
    };
    match application
        .remove_policy(sandbox_id, generation.clone())
        .await
    {
        Ok(()) => {
            info!(%sandbox_id, %command_id, "policy stream remove completed");
            stream_success(command_id, Some(generation))
        }
        Err(error) => {
            warn!(%sandbox_id, %command_id, %error, "policy stream remove failed");
            stream_application_error(command_id, &error)
        }
    }
}

fn checked_proto_generation(
    proto: ProtoPolicyGeneration,
) -> Option<joysafeter_agent_gateway_contract::PolicyGeneration> {
    let policy_version = i64::try_from(proto.policy_version).ok()?;
    if policy_version <= 0 || proto.policy_hash.is_empty() {
        return None;
    }
    Some(joysafeter_agent_gateway_contract::PolicyGeneration {
        policy_hash: proto.policy_hash,
        policy_version,
    })
}

fn stream_success(
    command_id: String,
    generation: Option<joysafeter_agent_gateway_contract::PolicyGeneration>,
) -> PolicyStreamResponse {
    PolicyStreamResponse {
        command_id,
        success: true,
        error_code: String::new(),
        retryable: false,
        error_message: String::new(),
        generation: generation.map(|generation| ProtoPolicyGeneration {
            policy_hash: generation.policy_hash,
            policy_version: generation.policy_version as u64,
        }),
    }
}

fn stream_application_error(
    command_id: String,
    error: &GatewayApplicationError,
) -> PolicyStreamResponse {
    let status = app_error_to_status(error);
    let reason = status
        .metadata()
        .get(ERROR_REASON_METADATA)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("gateway_error")
        .to_string();
    let retryable = status
        .metadata()
        .get(ERROR_RETRYABLE_METADATA)
        .and_then(|value| value.to_str().ok())
        == Some("true");
    stream_error(command_id, reason, retryable, status.message())
}

fn stream_error(
    command_id: String,
    error_code: impl Into<String>,
    retryable: bool,
    error_message: impl Into<String>,
) -> PolicyStreamResponse {
    PolicyStreamResponse {
        command_id,
        success: false,
        error_code: error_code.into(),
        retryable,
        error_message: error_message.into(),
        generation: None,
    }
}

fn json_ok() -> JsonResponse {
    JsonResponse {
        success: true,
        error_message: String::new(),
        payload: Vec::new(),
    }
}

/// Map an application error to a gRPC status so the caller can distinguish
/// retryable (transient) failures from terminal ones. Retryable variants use
/// codes the orchestrator client's retry/backoff treats as retryable
/// (`Unavailable`/`DeadlineExceeded`); terminal variants use `InvalidArgument`/
/// `FailedPrecondition`, which must not be retried. (Fixes G1.)
fn app_error_to_status(error: &GatewayApplicationError) -> Status {
    use GatewayApplicationError as E;
    match error {
        E::NodeNotReady => public_status(
            Code::Unavailable,
            "node_not_ready",
            "sandbox Envoy node is not ready",
            true,
        ),
        E::AuthorityUnavailable => public_status(
            Code::Unavailable,
            "authority_unavailable",
            "xDS authority is not ready",
            true,
        ),
        E::AuthorityChanged => public_status(
            Code::Unavailable,
            "authority_changed",
            "xDS authority changed during the operation",
            true,
        ),
        E::Replication(_) => public_status(
            Code::Unavailable,
            "replication_unavailable",
            "Gateway replication is temporarily unavailable",
            true,
        ),
        E::Delivery(_) => public_status(
            Code::Unavailable,
            "delivery_failed",
            "failed while waiting for Envoy to apply the policy",
            true,
        ),
        E::Infrastructure(_) => public_status(
            Code::Unavailable,
            "infrastructure_unavailable",
            "Gateway infrastructure is temporarily unavailable",
            true,
        ),
        E::DeliveryTimeout(_) => public_status(
            Code::DeadlineExceeded,
            "delivery_timeout",
            "timed out waiting for Envoy to apply the policy",
            true,
        ),
        E::InvalidPolicy(_) => public_status(
            Code::InvalidArgument,
            "invalid_policy",
            "policy validation failed",
            false,
        ),
        E::InvalidPlacement(_) => public_status(
            Code::InvalidArgument,
            "invalid_placement",
            "placement validation failed",
            false,
        ),
        E::InvalidInventory(_) => public_status(
            Code::InvalidArgument,
            "invalid_inventory",
            "inventory validation failed",
            false,
        ),
        E::InvalidGeneration => public_status(
            Code::FailedPrecondition,
            "invalid_generation",
            "policy generation is stale or conflicting",
            false,
        ),
        E::RecoveryMismatch => public_status(
            Code::FailedPrecondition,
            "recovery_mismatch",
            "recovery inventory does not match the active projection",
            false,
        ),
        E::DeliveryNack(_) => public_status(
            Code::FailedPrecondition,
            "policy_nacked",
            "Envoy rejected the policy change",
            false,
        ),
    }
}

fn public_status(
    code: Code,
    reason: &'static str,
    message: &'static str,
    retryable: bool,
) -> Status {
    let mut status = Status::new(code, message);
    status.metadata_mut().insert(
        ERROR_REASON_METADATA,
        reason.parse().expect("static reason is valid metadata"),
    );
    status.metadata_mut().insert(
        ERROR_RETRYABLE_METADATA,
        if retryable { "true" } else { "false" }
            .parse()
            .expect("static retryable value is valid metadata"),
    );
    status
}

fn invalid_request_status(reason: &'static str, message: &'static str) -> Status {
    public_status(Code::InvalidArgument, reason, message, false)
}

/// Start the gRPC management server. This replaces the HTTP management API for
/// policy apply/remove, providing type-safe, high-performance orchestrator calls.
pub struct ManagementGrpcServerDependencies {
    pub addr: std::net::SocketAddr,
    pub application: GatewayApplication,
    pub management_token: String,
    pub instance_id: String,
    pub boot_id: String,
    pub authority: XdsAuthority,
    pub replication: crate::replication::ReplicationCoordinator,
    pub replication_token: Option<String>,
    pub limits: ManagementGrpcLimits,
    pub shutdown: crate::bootstrap::shutdown::ShutdownSignal,
}

pub async fn start_management_grpc_server(
    dependencies: ManagementGrpcServerDependencies,
) -> anyhow::Result<tokio::task::JoinHandle<anyhow::Result<()>>> {
    use crate::proto::gateway_management::gateway_management_service_server::GatewayManagementServiceServer;
    use crate::proto::gateway_management::gateway_replication_service_server::GatewayReplicationServiceServer;

    let ManagementGrpcServerDependencies {
        addr,
        application,
        management_token,
        instance_id,
        boot_id,
        authority,
        replication,
        replication_token,
        limits,
        shutdown,
    } = dependencies;
    let server = GatewayManagementServer::new(
        application,
        &management_token,
        instance_id,
        boot_id,
        authority,
    )?;
    let server = GatewayManagementServer {
        policy_commands: PolicyCommandDispatcher::with_limits(server.application.clone(), limits),
        policy_stream_permits: Arc::new(Semaphore::new(limits.max_policy_streams)),
        ..server
    };
    let service = GatewayManagementServiceServer::new(server)
        .max_decoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES)
        .max_encoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES);
    let replication_service = GatewayReplicationServiceServer::new(
        crate::adapters::replication_grpc::GatewayReplicationServer::with_max_streams(
            replication,
            replication_token.as_deref(),
            limits.max_replication_streams,
        ),
    )
    .max_decoding_message_size(MAX_REPLICATION_MESSAGE_BYTES)
    .max_encoding_message_size(MAX_REPLICATION_MESSAGE_BYTES);

    let handle = tokio::spawn(async move {
        info!(%addr, "Agent Gateway management gRPC server listening");
        tonic::transport::Server::builder()
            .add_service(service)
            .add_service(replication_service)
            .serve_with_shutdown(addr, shutdown.wait())
            .await
            .map_err(|e| anyhow::anyhow!("management gRPC server failed on {addr}: {e}"))
    });

    Ok(handle)
}

#[cfg(test)]
#[path = "../../tests/unit/adapters/management_grpc_test.rs"]
mod tests;
