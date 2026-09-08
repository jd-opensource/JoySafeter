use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, CompleteRecoveryRequest, CredentialRoute, EgressExposure,
    EgressKind, GatewayStatusResponse, PathMapping, PolicyAcceptedResponse, PolicyGeneration,
    PruneSandboxPoliciesRequest, PruneSandboxPoliciesResponse, RetryMode,
};
use prost::Message;
use rand::Rng;
use tokio::sync::{mpsc, oneshot, OwnedSemaphorePermit, Semaphore};
use tokio_stream::wrappers::ReceiverStream;
use tonic::transport::{Channel, Endpoint};
use tonic::{Code, Request, Status};
use tracing::{debug, info, warn};

use crate::ids::SandboxId;

use super::client::{AgentGatewayApi, AgentGatewayResponseError};

// Include generated protobuf code
pub mod proto {
    tonic::include_proto!("joysafeter.gateway.v1");
}

use proto::gateway_management_service_client::GatewayManagementServiceClient;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_RETRIES: u32 = 3;
const MAX_INFLIGHT_POLICY_COMMANDS: usize = 512;
const CIRCUIT_FAILURE_THRESHOLD: u32 = 5;
const CIRCUIT_OPEN_DURATION: Duration = Duration::from_secs(5);
const RECONNECT_BASE_DELAY: Duration = Duration::from_millis(100);
const RECONNECT_MAX_DELAY: Duration = Duration::from_secs(5);
const GRPC_KEEPALIVE_INTERVAL: Duration = Duration::from_secs(15);
const GRPC_KEEPALIVE_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_POLICY_STREAM_MESSAGE_BYTES: usize = 1024 * 1024;
const MAX_MANAGEMENT_MESSAGE_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Copy)]
pub struct AgentGatewayGrpcClientConfig {
    pub request_timeout: Duration,
    pub max_inflight_policy_commands: usize,
    pub circuit_failure_threshold: u32,
    pub circuit_open_duration: Duration,
    pub reconnect_base_delay: Duration,
    pub reconnect_max_delay: Duration,
    pub keepalive_interval: Duration,
    pub keepalive_timeout: Duration,
}

pub struct AgentGatewayGrpcClient {
    client: GatewayManagementServiceClient<Channel>,
    management_token: String,
    policy_stream: GatewayPolicyStream,
}

#[derive(Clone)]
struct GatewayPolicyStream {
    control_tx: mpsc::Sender<PolicyStreamControl>,
    request_timeout: Duration,
    admission: Arc<Semaphore>,
    circuit: CircuitBreaker,
}

enum PolicyStreamControl {
    Send {
        command: proto::PolicyStreamRequest,
        response_tx: oneshot::Sender<Result<proto::PolicyStreamResponse, String>>,
        _admission_permit: OwnedSemaphorePermit,
    },
    Cancel {
        command_id: String,
    },
}

struct PendingPolicyCommand {
    command: proto::PolicyStreamRequest,
    response_tx: oneshot::Sender<Result<proto::PolicyStreamResponse, String>>,
    attempts: u32,
    sequence: u64,
    _admission_permit: OwnedSemaphorePermit,
}

struct PolicyCommandReceipt {
    command_id: String,
    response_rx: oneshot::Receiver<Result<proto::PolicyStreamResponse, String>>,
    circuit_admission: CircuitAdmission,
    _inflight_guard: super::metrics::InflightGuard,
}

#[derive(Clone)]
struct CircuitBreaker {
    state: Arc<StdMutex<CircuitState>>,
    failure_threshold: u32,
    open_duration: Duration,
}

enum CircuitState {
    Closed { consecutive_failures: u32 },
    Open { until: Instant },
    HalfOpen,
}

struct CircuitAdmission {
    circuit: CircuitBreaker,
    half_open_probe: bool,
    completed: bool,
}

impl Default for CircuitBreaker {
    fn default() -> Self {
        Self {
            state: Arc::new(StdMutex::new(CircuitState::Closed {
                consecutive_failures: 0,
            })),
            failure_threshold: CIRCUIT_FAILURE_THRESHOLD,
            open_duration: CIRCUIT_OPEN_DURATION,
        }
    }
}

impl CircuitBreaker {
    fn admit(&self) -> Option<CircuitAdmission> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let half_open_probe = match &*state {
            CircuitState::Closed { .. } => false,
            CircuitState::Open { until } if *until > Instant::now() => return None,
            CircuitState::Open { .. } => {
                *state = CircuitState::HalfOpen;
                super::metrics::set_circuit_open(true);
                true
            }
            CircuitState::HalfOpen => return None,
        };
        Some(CircuitAdmission {
            circuit: self.clone(),
            half_open_probe,
            completed: false,
        })
    }

    fn record_success(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *state = CircuitState::Closed {
            consecutive_failures: 0,
        };
        super::metrics::set_circuit_open(false);
    }

    fn record_failure(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &mut *state {
            CircuitState::Closed {
                consecutive_failures,
            } => {
                *consecutive_failures = consecutive_failures.saturating_add(1);
                if *consecutive_failures >= self.failure_threshold {
                    *state = CircuitState::Open {
                        until: Instant::now() + self.open_duration,
                    };
                    super::metrics::set_circuit_open(true);
                }
            }
            CircuitState::Open { until } => {
                *until = Instant::now() + self.open_duration;
                super::metrics::set_circuit_open(true);
            }
            CircuitState::HalfOpen => {
                *state = CircuitState::Open {
                    until: Instant::now() + self.open_duration,
                };
                super::metrics::set_circuit_open(true);
            }
        }
    }
}

impl CircuitAdmission {
    fn success(mut self) {
        self.completed = true;
        self.circuit.record_success();
    }

    fn failure(mut self) {
        self.completed = true;
        self.circuit.record_failure();
    }
}

impl Drop for CircuitAdmission {
    fn drop(&mut self) {
        if self.half_open_probe && !self.completed {
            self.circuit.record_failure();
        }
    }
}

impl AgentGatewayGrpcClient {
    pub async fn new(
        endpoint: String,
        management_token: String,
        request_timeout: Duration,
    ) -> anyhow::Result<Self> {
        Self::new_with_config(
            endpoint,
            management_token,
            AgentGatewayGrpcClientConfig {
                request_timeout,
                max_inflight_policy_commands: MAX_INFLIGHT_POLICY_COMMANDS,
                circuit_failure_threshold: CIRCUIT_FAILURE_THRESHOLD,
                circuit_open_duration: CIRCUIT_OPEN_DURATION,
                reconnect_base_delay: RECONNECT_BASE_DELAY,
                reconnect_max_delay: RECONNECT_MAX_DELAY,
                keepalive_interval: GRPC_KEEPALIVE_INTERVAL,
                keepalive_timeout: GRPC_KEEPALIVE_TIMEOUT,
            },
        )
        .await
    }

    pub async fn new_with_config(
        endpoint: String,
        management_token: String,
        config: AgentGatewayGrpcClientConfig,
    ) -> anyhow::Result<Self> {
        let channel = Endpoint::from_shared(endpoint)?
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(config.request_timeout)
            .tcp_keepalive(Some(config.keepalive_interval))
            .http2_keep_alive_interval(config.keepalive_interval)
            .keep_alive_timeout(config.keepalive_timeout)
            .keep_alive_while_idle(true)
            .connect()
            .await?;

        let client = GatewayManagementServiceClient::new(channel.clone())
            .max_decoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES)
            .max_encoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES);
        let policy_stream = GatewayPolicyStream::start(channel, management_token.clone(), config);

        Ok(Self {
            client,
            management_token,
            policy_stream,
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
                        return Err(AgentGatewayResponseError::new(
                            operation,
                            format!("grpc_{:?}", status.code()).to_ascii_lowercase(),
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
        Err(AgentGatewayResponseError::new(
            operation,
            format!("grpc_{:?}", status.code()).to_ascii_lowercase(),
        ))
    }
}

impl GatewayPolicyStream {
    fn start(
        channel: Channel,
        management_token: String,
        config: AgentGatewayGrpcClientConfig,
    ) -> Self {
        let (control_tx, control_rx) = mpsc::channel(1024);
        let circuit = CircuitBreaker {
            state: Arc::new(StdMutex::new(CircuitState::Closed {
                consecutive_failures: 0,
            })),
            failure_threshold: config.circuit_failure_threshold,
            open_duration: config.circuit_open_duration,
        };
        tokio::spawn(run_policy_stream(
            channel,
            management_token,
            control_rx,
            circuit.clone(),
            config.reconnect_base_delay,
            config.reconnect_max_delay,
        ));
        Self {
            control_tx,
            request_timeout: config.request_timeout,
            admission: Arc::new(Semaphore::new(config.max_inflight_policy_commands)),
            circuit,
        }
    }

    async fn send(
        &self,
        command: proto::PolicyStreamRequest,
    ) -> anyhow::Result<PolicyCommandReceipt> {
        if command.encoded_len() > MAX_POLICY_STREAM_MESSAGE_BYTES {
            super::metrics::record_oversize_rejection();
            anyhow::bail!("Agent Gateway policy command exceeds the transport size limit");
        }
        let circuit_admission = self.circuit.admit().ok_or_else(|| {
            super::metrics::record_circuit_rejection();
            anyhow::anyhow!("Agent Gateway policy stream circuit is open")
        })?;
        let admission_permit = self.admission.clone().try_acquire_owned().map_err(|_| {
            super::metrics::record_inflight_rejection();
            anyhow::anyhow!("Agent Gateway policy stream inflight limit reached")
        })?;
        let inflight_guard = super::metrics::InflightGuard::begin();
        let command_id = command.command_id.clone();
        let (response_tx, response_rx) = oneshot::channel();
        if self
            .control_tx
            .send(PolicyStreamControl::Send {
                command,
                response_tx,
                _admission_permit: admission_permit,
            })
            .await
            .is_err()
        {
            circuit_admission.failure();
            anyhow::bail!("Agent Gateway policy stream actor stopped");
        }
        Ok(PolicyCommandReceipt {
            command_id,
            response_rx,
            circuit_admission,
            _inflight_guard: inflight_guard,
        })
    }

    async fn wait(
        &self,
        receipt: PolicyCommandReceipt,
    ) -> anyhow::Result<proto::PolicyStreamResponse> {
        let PolicyCommandReceipt {
            command_id,
            response_rx,
            circuit_admission,
            _inflight_guard,
        } = receipt;
        match tokio::time::timeout(self.request_timeout, response_rx).await {
            Ok(Ok(Ok(response))) => {
                circuit_admission.success();
                Ok(response)
            }
            Ok(Ok(Err(error))) => {
                circuit_admission.failure();
                Err(anyhow::anyhow!(error))
            }
            Ok(Err(_)) => {
                circuit_admission.failure();
                anyhow::bail!("Agent Gateway policy stream response was dropped")
            }
            Err(_) => {
                let _ = self
                    .control_tx
                    .send(PolicyStreamControl::Cancel { command_id })
                    .await;
                circuit_admission.failure();
                anyhow::bail!("Agent Gateway policy command timed out")
            }
        }
    }

    async fn execute(
        &self,
        command: proto::PolicyStreamRequest,
    ) -> anyhow::Result<proto::PolicyStreamResponse> {
        let receipt = self.send(command).await?;
        self.wait(receipt).await
    }
}

async fn run_policy_stream(
    channel: Channel,
    management_token: String,
    mut control_rx: mpsc::Receiver<PolicyStreamControl>,
    circuit: CircuitBreaker,
    reconnect_base_delay: Duration,
    reconnect_max_delay: Duration,
) {
    let mut pending = HashMap::<String, PendingPolicyCommand>::new();
    let mut next_sequence = 0_u64;
    let mut reconnect_attempt = 0_u32;
    loop {
        drain_policy_controls(&mut control_rx, &mut pending, &mut next_sequence);
        let (outbound_tx, outbound_rx) = mpsc::channel(256);
        let mut request = Request::new(ReceiverStream::new(outbound_rx));
        let authorization = match format!("Bearer {management_token}").parse() {
            Ok(value) => value,
            Err(_) => {
                fail_pending(
                    &mut pending,
                    "invalid Agent Gateway management token metadata",
                );
                return;
            }
        };
        request
            .metadata_mut()
            .insert("authorization", authorization);
        let mut client = GatewayManagementServiceClient::new(channel.clone())
            .max_decoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES)
            .max_encoding_message_size(MAX_MANAGEMENT_MESSAGE_BYTES);
        let response = client.policy_stream(request).await;
        let mut inbound = match response {
            Ok(response) => {
                super::metrics::set_stream_connected(true);
                info!(
                    pending = pending.len(),
                    "Agent Gateway policy stream connected"
                );
                response.into_inner()
            }
            Err(status) => {
                super::metrics::set_stream_connected(false);
                super::metrics::record_reconnect();
                if matches!(
                    status.code(),
                    Code::Unauthenticated | Code::PermissionDenied
                ) {
                    fail_pending(
                        &mut pending,
                        "Agent Gateway policy stream authentication failed",
                    );
                    return;
                }
                circuit.record_failure();
                reconnect_attempt = reconnect_attempt.saturating_add(1);
                if !wait_for_policy_stream_reconnect(
                    &mut control_rx,
                    &mut pending,
                    &mut next_sequence,
                    reconnect_attempt,
                    reconnect_base_delay,
                    reconnect_max_delay,
                )
                .await
                {
                    return;
                }
                continue;
            }
        };

        let mut connection_failed = false;
        for command in replay_commands_in_sequence(&pending) {
            if outbound_tx.send(command).await.is_err() {
                connection_failed = true;
                break;
            }
        }
        if connection_failed {
            super::metrics::set_stream_connected(false);
            super::metrics::record_reconnect();
            circuit.record_failure();
            reconnect_attempt = reconnect_attempt.saturating_add(1);
            if !wait_for_policy_stream_reconnect(
                &mut control_rx,
                &mut pending,
                &mut next_sequence,
                reconnect_attempt,
                reconnect_base_delay,
                reconnect_max_delay,
            )
            .await
            {
                return;
            }
            continue;
        }

        loop {
            tokio::select! {
                control = control_rx.recv() => {
                    let Some(control) = control else {
                        fail_pending(&mut pending, "Agent Gateway policy stream client stopped");
                        return;
                    };
                    match control {
                        PolicyStreamControl::Send { command, response_tx, _admission_permit } => {
                            if !enqueue_pending(
                                &mut pending,
                                &mut next_sequence,
                                command.clone(),
                                response_tx,
                                _admission_permit,
                            ) {
                                continue;
                            }
                            if outbound_tx.send(command).await.is_err() {
                                break;
                            }
                        }
                        PolicyStreamControl::Cancel { command_id } => {
                            pending.remove(&command_id);
                        }
                    }
                }
                response = inbound.message() => {
                    match response {
                        Ok(Some(response)) => {
                            circuit.record_success();
                            reconnect_attempt = 0;
                            let command_id = response.command_id.clone();
                            let Some(mut command) = pending.remove(&command_id) else {
                                warn!(%command_id, "received response for unknown policy command");
                                continue;
                            };
                            if !response.success && response.retryable && command.attempts < MAX_RETRIES {
                                command.attempts += 1;
                                pending.insert(command_id, command);
                                // Recreate the stream so a retry can be routed to a
                                // newly elected Gateway authority. The same command
                                // id and durable generation are replayed.
                                reconnect_attempt = 1;
                                break;
                            }
                            let _ = command.response_tx.send(Ok(response));
                        }
                        Ok(None) => {
                            super::metrics::set_stream_connected(false);
                            super::metrics::record_reconnect();
                            circuit.record_failure();
                            reconnect_attempt = reconnect_attempt.saturating_add(1);
                            break;
                        }
                        Err(status) => {
                            super::metrics::set_stream_connected(false);
                            super::metrics::record_reconnect();
                            warn!(error = %status, pending = pending.len(), "Agent Gateway policy stream disconnected");
                            circuit.record_failure();
                            reconnect_attempt = reconnect_attempt.saturating_add(1);
                            break;
                        }
                    }
                }
            }
        }
        if !wait_for_policy_stream_reconnect(
            &mut control_rx,
            &mut pending,
            &mut next_sequence,
            reconnect_attempt,
            reconnect_base_delay,
            reconnect_max_delay,
        )
        .await
        {
            return;
        }
    }
}

fn replay_commands_in_sequence(
    pending: &HashMap<String, PendingPolicyCommand>,
) -> Vec<proto::PolicyStreamRequest> {
    let mut replay = pending.values().collect::<Vec<_>>();
    replay.sort_by_key(|command| command.sequence);
    replay
        .into_iter()
        .map(|command| command.command.clone())
        .collect()
}

fn drain_policy_controls(
    control_rx: &mut mpsc::Receiver<PolicyStreamControl>,
    pending: &mut HashMap<String, PendingPolicyCommand>,
    next_sequence: &mut u64,
) {
    while let Ok(control) = control_rx.try_recv() {
        match control {
            PolicyStreamControl::Send {
                command,
                response_tx,
                _admission_permit,
            } => {
                enqueue_pending(
                    pending,
                    next_sequence,
                    command,
                    response_tx,
                    _admission_permit,
                );
            }
            PolicyStreamControl::Cancel { command_id } => {
                pending.remove(&command_id);
            }
        }
    }
}

async fn wait_for_policy_stream_reconnect(
    control_rx: &mut mpsc::Receiver<PolicyStreamControl>,
    pending: &mut HashMap<String, PendingPolicyCommand>,
    next_sequence: &mut u64,
    reconnect_attempt: u32,
    reconnect_base_delay: Duration,
    reconnect_max_delay: Duration,
) -> bool {
    let delay = tokio::time::sleep(reconnect_delay_with_bounds(
        reconnect_attempt,
        reconnect_base_delay,
        reconnect_max_delay,
    ));
    tokio::pin!(delay);
    loop {
        tokio::select! {
            _ = &mut delay => return true,
            control = control_rx.recv() => match control {
                Some(PolicyStreamControl::Send { command, response_tx, _admission_permit }) => {
                    enqueue_pending(
                        pending,
                        next_sequence,
                        command,
                        response_tx,
                        _admission_permit,
                    );
                }
                Some(PolicyStreamControl::Cancel { command_id }) => {
                    pending.remove(&command_id);
                }
                None => {
                    fail_pending(pending, "Agent Gateway policy stream client stopped");
                    return false;
                }
            }
        }
    }
}

fn enqueue_pending(
    pending: &mut HashMap<String, PendingPolicyCommand>,
    next_sequence: &mut u64,
    command: proto::PolicyStreamRequest,
    response_tx: oneshot::Sender<Result<proto::PolicyStreamResponse, String>>,
    admission_permit: OwnedSemaphorePermit,
) -> bool {
    let command_id = command.command_id.clone();
    match pending.entry(command_id) {
        std::collections::hash_map::Entry::Vacant(entry) => {
            entry.insert(PendingPolicyCommand {
                command,
                response_tx,
                attempts: 1,
                sequence: *next_sequence,
                _admission_permit: admission_permit,
            });
            *next_sequence = next_sequence.wrapping_add(1);
            true
        }
        std::collections::hash_map::Entry::Occupied(_) => {
            let _ = response_tx.send(Err("duplicate in-flight policy command id".to_string()));
            false
        }
    }
}

#[cfg(test)]
fn reconnect_delay(attempt: u32) -> Duration {
    reconnect_delay_with_bounds(attempt, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY)
}

fn reconnect_delay_with_bounds(attempt: u32, base: Duration, max: Duration) -> Duration {
    let exponent = attempt.saturating_sub(1).min(6);
    let capped_ms = base
        .as_millis()
        .saturating_mul(1_u128 << exponent)
        .min(max.as_millis()) as u64;
    let floor_ms = (capped_ms.saturating_mul(3) / 4).max(1);
    Duration::from_millis(rand::thread_rng().gen_range(floor_ms..=capped_ms))
}

fn fail_pending(pending: &mut HashMap<String, PendingPolicyCommand>, message: &str) {
    for (_, command) in pending.drain() {
        let _ = command.response_tx.send(Err(message.to_string()));
    }
}

fn proto_generation(generation: &PolicyGeneration) -> anyhow::Result<proto::PolicyGeneration> {
    let policy_version = u64::try_from(generation.policy_version)
        .map_err(|_| anyhow::anyhow!("policy version must be positive"))?;
    if policy_version == 0 {
        anyhow::bail!("policy version must be positive");
    }
    Ok(proto::PolicyGeneration {
        policy_hash: generation.policy_hash.clone(),
        policy_version,
    })
}

fn proto_policy(policy: &ApplySandboxPolicyRequest) -> anyhow::Result<proto::SandboxPolicy> {
    Ok(proto::SandboxPolicy {
        generation: Some(proto_generation(&policy.generation)?),
        allowlist_hosts: policy.allowlist_hosts.clone(),
        credential_routes: policy
            .credential_routes
            .iter()
            .map(proto_credential_route)
            .collect(),
        proxy_auth_token: policy.proxy_auth_token.clone(),
    })
}

fn proto_credential_route(route: &CredentialRoute) -> proto::CredentialRoute {
    proto::CredentialRoute {
        id: route.id.clone(),
        kind: match route.kind {
            EgressKind::Llm => proto::EgressKind::Llm as i32,
            EgressKind::Mcp => proto::EgressKind::Mcp as i32,
            EgressKind::Git => proto::EgressKind::Git as i32,
            EgressKind::External => proto::EgressKind::External as i32,
        },
        exposure: match route.exposure {
            EgressExposure::Placeholder => proto::EgressExposure::Placeholder as i32,
            EgressExposure::Transparent => proto::EgressExposure::Transparent as i32,
        },
        match_host: route.match_host.clone(),
        path_mapping: Some(proto_path_mapping(&route.path_mapping)),
        retry_mode: match route.retry_mode {
            RetryMode::Disabled => proto::RetryMode::Disabled as i32,
            RetryMode::SafeIdempotent => proto::RetryMode::SafeIdempotent as i32,
        },
        upstream_host: route.upstream_host.clone(),
        upstream_port: u32::from(route.upstream_port),
        upstream_tls: route.upstream_tls,
        vetted_addresses: route.vetted_addresses.clone(),
        inject_headers: route
            .inject_headers
            .iter()
            .map(|header| proto::ResolvedHeader {
                name: header.name.clone(),
                value: header.value.clone(),
            })
            .collect(),
        remove_headers: route.remove_headers.clone(),
    }
}

fn proto_path_mapping(mapping: &PathMapping) -> proto::PathMapping {
    use proto::path_mapping::Mapping;
    let mapping = match mapping {
        PathMapping::PassthroughAny => Mapping::PassthroughAny(proto::Empty {}),
        PathMapping::PassthroughExact { path } => Mapping::PassthroughExact(path.clone()),
        PathMapping::PassthroughPrefix { path } => Mapping::PassthroughPrefix(path.clone()),
        PathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } => Mapping::RewriteExact(proto::RewriteExact {
            exposed_path: exposed_path.clone(),
            upstream_path: upstream_path.clone(),
        }),
        PathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        } => Mapping::RewritePrefix(proto::RewritePrefix {
            exposed_prefix: exposed_prefix.clone(),
            upstream_prefix: upstream_prefix.clone(),
        }),
    };
    proto::PathMapping {
        mapping: Some(mapping),
    }
}

fn ensure_policy_command_success(
    operation: &'static str,
    command_id: &str,
    response: &proto::PolicyStreamResponse,
) -> anyhow::Result<()> {
    if response.command_id != command_id {
        anyhow::bail!("Agent Gateway returned a mismatched policy command id");
    }
    if response.success {
        return Ok(());
    }
    let code = if response.error_code.is_empty() {
        "gateway_error".to_string()
    } else {
        response.error_code.clone()
    };
    Err(AgentGatewayResponseError::new(operation, code).into())
}

fn ensure_response_generation(
    expected: &PolicyGeneration,
    actual: Option<&proto::PolicyGeneration>,
) -> anyhow::Result<()> {
    let Some(actual) = actual else {
        anyhow::bail!("Agent Gateway policy response omitted the generation");
    };
    if actual.policy_hash != expected.policy_hash
        || i64::try_from(actual.policy_version).ok() != Some(expected.policy_version)
    {
        anyhow::bail!("Agent Gateway returned a mismatched policy generation");
    }
    Ok(())
}

#[async_trait]
impl AgentGatewayApi for AgentGatewayGrpcClient {
    async fn check_ready(&self) -> anyhow::Result<()> {
        Ok(())
    }

    async fn status(&self) -> anyhow::Result<GatewayStatusResponse> {
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("status query", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::GetStatusRequest {});
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.get_status(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC get_status failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!("Gateway status query failed: {}", inner.error_message);
        }
        serde_json::from_slice(&inner.payload)
            .map_err(|e| anyhow::anyhow!("invalid status payload from gateway: {}", e))
    }

    async fn complete_recovery(&self, request: CompleteRecoveryRequest) -> anyhow::Result<()> {
        let payload = serde_json::to_vec(&request)?;
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("recovery completion", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::JsonRequest {
                    payload: payload.clone(),
                });
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.complete_recovery(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC complete_recovery failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!(
                "Gateway recovery completion failed: {}",
                inner.error_message
            );
        }
        Ok(())
    }

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        request: ApplySandboxPolicyRequest,
    ) -> anyhow::Result<PolicyAcceptedResponse> {
        let generation = request.generation.clone();
        let command_id = uuid::Uuid::now_v7().to_string();
        let response = self
            .policy_stream
            .execute(proto::PolicyStreamRequest {
                command_id: command_id.clone(),
                command: Some(proto::policy_stream_request::Command::ApplyPolicy(
                    proto::StreamApplyPolicy {
                        sandbox_id: sandbox_id.to_string(),
                        policy: Some(proto_policy(&request)?),
                    },
                )),
            })
            .await?;
        ensure_policy_command_success("policy apply", &command_id, &response)?;
        ensure_response_generation(&generation, response.generation.as_ref())?;

        debug!(%sandbox_id, %command_id, "policy applied via bidirectional gRPC stream");

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
        let command_id = uuid::Uuid::now_v7().to_string();
        let response = self
            .policy_stream
            .execute(proto::PolicyStreamRequest {
                command_id: command_id.clone(),
                command: Some(proto::policy_stream_request::Command::RemovePolicy(
                    proto::StreamRemovePolicy {
                        sandbox_id: sandbox_id.to_string(),
                        expected_generation: Some(proto_generation(&generation)?),
                    },
                )),
            })
            .await?;
        ensure_policy_command_success("policy removal", &command_id, &response)?;
        ensure_response_generation(&generation, response.generation.as_ref())?;

        debug!(%sandbox_id, %command_id, "policy removed via bidirectional gRPC stream");
        Ok(())
    }

    async fn prune_policies(
        &self,
        live_sandbox_ids: &HashSet<SandboxId>,
    ) -> anyhow::Result<Vec<SandboxId>> {
        let mut ids = live_sandbox_ids
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        ids.sort();
        let payload = serde_json::to_vec(&PruneSandboxPoliciesRequest {
            live_sandbox_ids: ids,
        })?;
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("policy pruning", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::JsonRequest {
                    payload: payload.clone(),
                });
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.prune_policies(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC prune_policies failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!("Gateway policy pruning failed: {}", inner.error_message);
        }
        let parsed: PruneSandboxPoliciesResponse = serde_json::from_slice(&inner.payload)
            .map_err(|e| anyhow::anyhow!("invalid prune payload from gateway: {}", e))?;
        parsed
            .removed_sandbox_ids
            .into_iter()
            .map(|id| {
                id.parse()
                    .map_err(|_| anyhow::anyhow!("gateway prune response had invalid sandbox id"))
            })
            .collect()
    }

    async fn assign_placement(
        &self,
        sandbox_id: SandboxId,
        request: joysafeter_agent_gateway_contract::AssignSandboxPlacementRequest,
    ) -> anyhow::Result<()> {
        let payload = serde_json::to_vec(&request)?;
        let sandbox = sandbox_id.to_string();
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("placement assignment", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::PlacementRequest {
                    sandbox_id: sandbox.clone(),
                    payload: payload.clone(),
                });
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.assign_placement(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC assign_placement failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!(
                "Gateway placement assignment failed: {}",
                inner.error_message
            );
        }
        Ok(())
    }

    async fn remove_placement(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        let sandbox = sandbox_id.to_string();
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("placement removal", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::PlacementRequest {
                    sandbox_id: sandbox.clone(),
                    payload: Vec::new(),
                });
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.remove_placement(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC remove_placement failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!("Gateway placement removal failed: {}", inner.error_message);
        }
        Ok(())
    }

    async fn reconcile_placements(
        &self,
        request: joysafeter_agent_gateway_contract::ReconcilePlacementsRequest,
    ) -> anyhow::Result<()> {
        let payload = serde_json::to_vec(&request)?;
        let client = self.client.clone();
        let token = self.management_token.clone();
        let response = self
            .retry_with_backoff("placement reconcile", || {
                let mut client = client.clone();
                let mut req = Request::new(proto::JsonRequest {
                    payload: payload.clone(),
                });
                req.metadata_mut().insert(
                    "authorization",
                    format!("Bearer {}", token).parse().unwrap(),
                );
                async move { client.reconcile_placements(req).await }
            })
            .await
            .map_err(|e| anyhow::anyhow!("gRPC reconcile_placements failed: {}", e))?;
        let inner = response.into_inner();
        if !inner.success {
            anyhow::bail!(
                "Gateway placement reconcile failed: {}",
                inner.error_message
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_response_must_match_the_waiting_command_id() {
        let response = proto::PolicyStreamResponse {
            command_id: uuid::Uuid::now_v7().to_string(),
            success: true,
            error_code: String::new(),
            retryable: false,
            error_message: String::new(),
            generation: None,
        };
        assert!(ensure_policy_command_success(
            "policy apply",
            &uuid::Uuid::now_v7().to_string(),
            &response,
        )
        .is_err());
    }

    #[test]
    fn terminal_stream_error_keeps_the_stable_gateway_code() {
        let command_id = uuid::Uuid::now_v7().to_string();
        let response = proto::PolicyStreamResponse {
            command_id: command_id.clone(),
            success: false,
            error_code: "policy_nacked".to_string(),
            retryable: false,
            error_message: "safe public message".to_string(),
            generation: None,
        };
        let error = ensure_policy_command_success("policy apply", &command_id, &response)
            .expect_err("terminal failure");
        assert!(error.chain().any(|cause| {
            cause
                .downcast_ref::<AgentGatewayResponseError>()
                .is_some_and(|gateway| gateway.code() == "policy_nacked")
        }));
    }

    #[test]
    fn response_generation_is_strictly_correlated() {
        let expected = PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 9,
        };
        let actual = proto::PolicyGeneration {
            policy_hash: expected.policy_hash.clone(),
            policy_version: 10,
        };
        assert!(ensure_response_generation(&expected, Some(&actual)).is_err());
    }

    #[test]
    fn reconnect_replays_pending_commands_in_original_send_order() {
        let command_ids = [
            uuid::Uuid::now_v7().to_string(),
            uuid::Uuid::now_v7().to_string(),
            uuid::Uuid::now_v7().to_string(),
        ];
        let mut pending = HashMap::new();
        let mut next_sequence = 0;
        let admission = Arc::new(Semaphore::new(command_ids.len()));
        for command_id in &command_ids {
            let (response_tx, _response_rx) = oneshot::channel();
            assert!(enqueue_pending(
                &mut pending,
                &mut next_sequence,
                proto::PolicyStreamRequest {
                    command_id: command_id.clone(),
                    command: None,
                },
                response_tx,
                admission
                    .clone()
                    .try_acquire_owned()
                    .expect("test admission permit"),
            ));
        }

        let replayed = replay_commands_in_sequence(&pending)
            .into_iter()
            .map(|command| command.command_id)
            .collect::<Vec<_>>();
        assert_eq!(replayed, command_ids);
    }

    #[test]
    fn circuit_breaker_opens_at_threshold_and_recovers_after_cooldown() {
        let circuit = CircuitBreaker::default();
        for _ in 0..CIRCUIT_FAILURE_THRESHOLD - 1 {
            circuit.record_failure();
            assert!(circuit.admit().is_some());
        }
        circuit.record_failure();
        assert!(circuit.admit().is_none());

        {
            let mut state = circuit
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            *state = CircuitState::Open {
                until: Instant::now() - Duration::from_millis(1),
            };
        }
        let probe = circuit.admit().expect("one half-open probe");
        assert!(circuit.admit().is_none(), "second probe must be rejected");
        probe.success();
        circuit
            .admit()
            .expect("closed after successful probe")
            .success();
    }

    #[test]
    fn abandoned_half_open_probe_reopens_the_circuit() {
        let circuit = CircuitBreaker::default();
        {
            let mut state = circuit
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            *state = CircuitState::Open {
                until: Instant::now() - Duration::from_millis(1),
            };
        }
        let probe = circuit.admit().expect("half-open probe");
        assert!(circuit.admit().is_none());
        drop(probe);
        assert!(
            circuit.admit().is_none(),
            "dropped probe must reopen circuit"
        );
    }

    #[test]
    fn reconnect_delay_is_jittered_and_strictly_bounded() {
        for (attempt, lower_ms, upper_ms) in [
            (1, 75, 100),
            (2, 150, 200),
            (3, 300, 400),
            (7, 3_750, 5_000),
            (100, 3_750, 5_000),
        ] {
            for _ in 0..32 {
                let delay = reconnect_delay(attempt);
                assert!(delay >= Duration::from_millis(lower_ms));
                assert!(delay <= Duration::from_millis(upper_ms));
            }
        }
    }

    #[test]
    fn removing_a_pending_command_releases_its_inflight_permit() {
        let admission = Arc::new(Semaphore::new(1));
        let permit = admission
            .clone()
            .try_acquire_owned()
            .expect("initial admission permit");
        let command_id = uuid::Uuid::now_v7().to_string();
        let (response_tx, _response_rx) = oneshot::channel();
        let mut pending = HashMap::new();
        let mut next_sequence = 0;
        assert!(enqueue_pending(
            &mut pending,
            &mut next_sequence,
            proto::PolicyStreamRequest {
                command_id: command_id.clone(),
                command: None,
            },
            response_tx,
            permit,
        ));
        assert!(admission.clone().try_acquire_owned().is_err());

        pending.remove(&command_id);
        assert!(admission.try_acquire_owned().is_ok());
    }
}
