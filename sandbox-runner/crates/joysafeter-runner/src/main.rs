mod archive;
mod egress_bridge;
#[cfg(target_os = "linux")]
mod memory_fuse;
mod repos;
mod runner;
mod sandbox_files;
mod stream;
mod tool_policy;

pub mod proto {
    tonic::include_proto!("joysafeter");
}

use proto::agent_bridge_client::AgentBridgeClient;
use proto::{RunnerHarnessResult, RunnerHeartbeat, RunnerIdle, RunnerMessage};

use base64::Engine;
use joysafeter_runtime::AdapterRegistry;
use joysafeter_types::TaskId;
use std::os::unix::fs::FileTypeExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::{mpsc, oneshot, watch};
use tokio::task::JoinHandle;
use tokio_stream::wrappers::ReceiverStream;
use tonic::Streaming;
use tracing::{error, info, warn};

const GRPC_MAX_RECV_MESSAGE_SIZE: usize = 32 * 1024 * 1024;
const GRPC_MAX_SEND_MESSAGE_SIZE: usize = 128 * 1024 * 1024;

enum ConnectionResult {
    Shutdown,
    Disconnected,
}

struct SurvivingTask {
    task_id: TaskId,
    harness_session_id: Option<String>,
    work_dir: Option<String>,
    handle: JoinHandle<Result<runner::TaskMetadata, Box<dyn std::error::Error + Send + Sync>>>,
    cancel_tx: Option<oneshot::Sender<()>>,
    control_tx: mpsc::Sender<runner::RunnerControl>,
    /// Channel where the runner sends events — outlives the gRPC connection.
    /// Events accumulate here when no forwarder is draining them.
    event_rx: mpsc::Receiver<RunnerMessage>,
    /// Event that was consumed from event_rx but failed to send to gRPC.
    unsent_event: Option<RunnerMessage>,
}

#[derive(Clone, Default)]
struct HeartbeatRuntimeState {
    runtime_state: String,
    active_task_id: Option<TaskId>,
    harness_session_id: Option<String>,
}

impl HeartbeatRuntimeState {
    fn idle() -> Self {
        Self {
            runtime_state: "idle".to_string(),
            active_task_id: None,
            harness_session_id: None,
        }
    }

    fn busy(task_id: TaskId, harness_session_id: Option<String>) -> Self {
        Self {
            runtime_state: "busy".to_string(),
            active_task_id: Some(task_id),
            harness_session_id,
        }
    }
}

fn parse_start_task_id(value: &str) -> anyhow::Result<TaskId> {
    TaskId::from_public(value)
        .map_err(|error| anyhow::anyhow!("invalid StartTask.task_id: {error}"))
}

fn set_heartbeat_runtime_state(
    state: &Arc<Mutex<HeartbeatRuntimeState>>,
    value: HeartbeatRuntimeState,
) {
    match state.lock() {
        Ok(mut guard) => *guard = value,
        Err(poisoned) => *poisoned.into_inner() = value,
    }
}

fn get_heartbeat_runtime_state(state: &Arc<Mutex<HeartbeatRuntimeState>>) -> HeartbeatRuntimeState {
    match state.lock() {
        Ok(guard) => guard.clone(),
        Err(poisoned) => poisoned.into_inner().clone(),
    }
}

async fn wait_for_unix_socket(path: &Path, purpose: &str) -> bool {
    let mut last_status = "not checked".to_string();
    for _ in 0..50 {
        match tokio::fs::metadata(path).await {
            Ok(metadata) if metadata.file_type().is_socket() => return true,
            Ok(metadata) => {
                last_status = format!(
                    "path exists but is not a socket: {:?}",
                    metadata.file_type()
                );
            }
            Err(error) => {
                last_status = error.to_string();
            }
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    warn!(
        path = %path.display(),
        purpose = %purpose,
        status = %last_status,
        "Unix socket was not ready before startup; connection retry loop will continue"
    );
    false
}

fn local_proxy_url() -> String {
    format!("http://127.0.0.1:{}", egress_bridge::BRIDGE_PORT)
}

fn proxy_authorization(egress_proxy_token: Option<&str>) -> anyhow::Result<String> {
    let token = egress_proxy_token
        .filter(|token| !token.is_empty())
        .ok_or_else(|| anyhow::anyhow!("managed egress requires JOYSAFETER_EGRESS_PROXY_TOKEN"))?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(format!("sandbox:{token}"));
    Ok(format!("Basic {encoded}"))
}

fn configure_proxy_env() {
    let proxy = local_proxy_url();
    std::env::set_var("HTTP_PROXY", &proxy);
    std::env::set_var("HTTPS_PROXY", &proxy);
    std::env::set_var("http_proxy", &proxy);
    std::env::set_var("https_proxy", &proxy);
    std::env::set_var("ALL_PROXY", &proxy);
    std::env::set_var("all_proxy", &proxy);
}

/// Start the in-process HTTP egress bridge (replaces the external `socat`
/// sidecar). The TCP listener binds synchronously so the proxy endpoint is
/// reachable immediately; the accept/forward loop then connects to the Envoy
/// Unix socket lazily per connection, retrying until it appears. Returns whether
/// the listener bound successfully.
async fn start_http_proxy_bridge(http_sock: PathBuf, proxy_authorization: String) -> bool {
    match egress_bridge::bind().await {
        Ok(listener) => {
            tokio::spawn(egress_bridge::serve(
                listener,
                http_sock,
                proxy_authorization.into(),
            ));
            true
        }
        Err(e) => {
            warn!(
                error = %e,
                port = egress_bridge::BRIDGE_PORT,
                "Failed to bind in-process HTTP proxy bridge; egress will be unavailable"
            );
            false
        }
    }
}

async fn wait_for_http_proxy_bridge_ready(mut receiver: watch::Receiver<bool>) {
    if *receiver.borrow() {
        return;
    }
    while receiver.changed().await.is_ok() {
        if *receiver.borrow() {
            return;
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let orch_url = std::env::var("JOYSAFETER_ORCHESTRATOR_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:9090".into());
    let sandbox_id = std::env::var("JOYSAFETER_SANDBOX_ID").unwrap_or_default();
    let runner_token =
        read_runtime_credential("JOYSAFETER_RUNNER_TOKEN", "JOYSAFETER_RUNNER_TOKEN_FILE")?
            .ok_or_else(|| anyhow::anyhow!("runner session credential is required"))?;
    let egress_proxy_token = read_runtime_credential(
        "JOYSAFETER_EGRESS_PROXY_TOKEN",
        "JOYSAFETER_EGRESS_PROXY_TOKEN_FILE",
    )?;

    let grpc_sock_path = if orch_url.starts_with("unix://") {
        let grpc_path = orch_url.strip_prefix("unix://").unwrap();
        Some(PathBuf::from(grpc_path))
    } else {
        None
    };

    let http_sock_path = std::env::var("JOYSAFETER_EGRESS_HTTP_SOCKET_PATH")
        .ok()
        .filter(|path| !path.trim().is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            // Backward-compatible fallback for the old Envoy-proxied control
            // layout: unix:///sockets/{id}/grpc.sock -> /sockets/{id}/http.sock.
            grpc_sock_path.as_ref().map(|grpc_path| {
                let parent = grpc_path.parent().unwrap_or(Path::new("/tmp/proxy"));
                parent.join("http.sock")
            })
        });

    if let Some(ref grpc_sock) = grpc_sock_path {
        wait_for_unix_socket(grpc_sock, "orchestrator gRPC").await;
    }

    let http_proxy_ready = if let Some(ref http_sock) = http_sock_path {
        let proxy_authorization = proxy_authorization(egress_proxy_token.as_deref())?;
        configure_proxy_env();
        let http_sock = http_sock.clone();
        // Bind the bridge listener up front (synchronous, immediate) so the proxy
        // endpoint is ready before the agent starts. The accept loop connects to
        // the Envoy socket lazily, so we no longer block on socket materialization.
        let ready = start_http_proxy_bridge(http_sock, proxy_authorization).await;
        let (_ready_tx, ready_rx) = watch::channel(ready);
        // `_ready_tx` is dropped here; receivers read the initial `ready` value
        // via borrow(). A dropped sender just means no further transitions, which
        // is correct — readiness is decided once, at bind time.
        Some(ready_rx)
    } else {
        None
    };

    info!("Discovering available agent CLIs...");
    let adapters = Arc::new(AdapterRegistry::discover().await);
    let provider_names = adapters.provider_names();
    info!(providers = ?provider_names, "Available adapters");

    let mut session_config = runner::SessionConfig::default();
    let mut surviving_task: Option<SurvivingTask> = None;
    let mut retry_count: u32 = 0;
    let mut is_first_connect = true;

    loop {
        info!(url = %orch_url, attempt = retry_count, "Connecting to orchestrator...");

        let channel = if orch_url.starts_with("unix://") {
            let path = orch_url.strip_prefix("unix://").unwrap().to_string();
            info!(path = %path, "Connecting via Unix socket");
            let connect_path = path.clone();
            let endpoint = tonic::transport::Endpoint::from_static("http://[::]:50051")
                .connect_timeout(Duration::from_secs(5));
            let connect = endpoint.connect_with_connector(tower::service_fn(
                move |_: tonic::transport::Uri| {
                    let path = connect_path.clone();
                    async move {
                        match tokio::time::timeout(
                            Duration::from_secs(5),
                            tokio::net::UnixStream::connect(&path),
                        )
                        .await
                        {
                            Ok(Ok(stream)) => {
                                Ok::<_, std::io::Error>(hyper_util::rt::TokioIo::new(stream))
                            }
                            Ok(Err(error)) => {
                                warn!(path = %path, error = %error, "Unix socket connect attempt failed");
                                Err(error)
                            }
                            Err(_) => {
                                let error = std::io::Error::new(
                                    std::io::ErrorKind::TimedOut,
                                    "timed out connecting to Unix socket",
                                );
                                warn!(path = %path, error = %error, "Unix socket connect attempt timed out");
                                Err(error)
                            }
                        }
                    }
                },
            ));
            match connect.await {
                Ok(ch) => ch,
                Err(e) => {
                    error!(error = %e, "Failed to connect via Unix socket");
                    if handle_retry(&mut retry_count, &surviving_task).await {
                        continue;
                    }
                    break;
                }
            }
        } else {
            match tonic::transport::Channel::from_shared(orch_url.clone()) {
                Ok(endpoint) => {
                    // HTTP/2 keepalive on the long-lived bidirectional `session`
                    // stream. Without it, K8s kube-proxy/conntrack (and any LB in
                    // between) evict the idle-ish TCP flow after its idle timeout,
                    // surfacing as `h2 protocol error: error reading a body` and
                    // reaping in-flight tasks. Frequent PINGs keep the flow alive
                    // and detect a dead orchestrator quickly.
                    let endpoint = endpoint
                        .connect_timeout(Duration::from_secs(5))
                        .http2_keep_alive_interval(Duration::from_secs(20))
                        .keep_alive_timeout(Duration::from_secs(10))
                        .keep_alive_while_idle(true)
                        .tcp_keepalive(Some(Duration::from_secs(20)));
                    match endpoint.connect().await {
                        Ok(ch) => ch,
                        Err(e) => {
                            error!(error = %e, "Failed to connect to orchestrator");
                            if handle_retry(&mut retry_count, &surviving_task).await {
                                continue;
                            }
                            break;
                        }
                    }
                }
                Err(e) => {
                    error!(error = %e, "Invalid orchestrator URL");
                    break;
                }
            }
        };

        let mut client = AgentBridgeClient::new(channel)
            .max_decoding_message_size(GRPC_MAX_RECV_MESSAGE_SIZE)
            .max_encoding_message_size(GRPC_MAX_SEND_MESSAGE_SIZE);
        let (runner_tx, runner_rx) = mpsc::channel::<RunnerMessage>(256);
        let outbound = ReceiverStream::new(runner_rx);

        let response = match client.session(outbound).await {
            Ok(r) => r,
            Err(e) => {
                error!(error = %e, "Failed to establish gRPC session");
                if handle_retry(&mut retry_count, &surviving_task).await {
                    continue;
                }
                break;
            }
        };
        let inbound = response.into_inner();

        let is_reconnect = !is_first_connect;
        let active_task_id = surviving_task.as_ref().map(|task| task.task_id.to_string());

        let ready = RunnerMessage {
            payload: Some(proto::runner_message::Payload::Ready(proto::RunnerReady {
                runner_version: env!("CARGO_PKG_VERSION").to_string(),
                available_providers: provider_names.clone(),
                sandbox_id: sandbox_id.clone(),
                is_reconnect,
                active_task_id: active_task_id.clone(),
                capabilities: vec![
                    "file_mount".to_string(),
                    "url_download".to_string(),
                    "setup_ack_v1".to_string(),
                ],
                runner_token: Some(runner_token.clone()),
                applied_runtime_config_generation: session_config.runtime_config_generation,
            })),
        };
        if runner_tx.send(ready).await.is_err() {
            error!("Failed to send RunnerReady");
            if handle_retry(&mut retry_count, &surviving_task).await {
                continue;
            }
            break;
        }

        // Connected successfully
        retry_count = 0;
        is_first_connect = false;
        info!(
            sandbox_id = %sandbox_id,
            is_reconnect,
            active_task = ?active_task_id,
            "RunnerReady sent"
        );

        // If reconnecting with a surviving task, drain its buffered events first
        if let Some(ref mut task) = surviving_task {
            let mut replayed = 0usize;
            // Replay the event that failed to send last time, if any
            if let Some(msg) = task.unsent_event.take() {
                if runner_tx.send(msg).await.is_err() {
                    warn!("Lost connection while replaying unsent event");
                    continue; // will retry connection
                }
                replayed += 1;
            }
            while let Ok(msg) = task.event_rx.try_recv() {
                if runner_tx.send(msg).await.is_err() {
                    warn!("Lost connection while replaying buffer");
                    break;
                }
                replayed += 1;
            }
            if replayed > 0 {
                info!(
                    count = replayed,
                    "Replayed buffered events to new joysafeter"
                );
            }
        }

        let result = run_session(
            inbound,
            runner_tx,
            &sandbox_id,
            &adapters,
            &mut session_config,
            &mut surviving_task,
            http_proxy_ready.clone(),
        )
        .await;

        match result {
            ConnectionResult::Shutdown => {
                info!("Runner shutting down (explicit shutdown)");
                break;
            }
            ConnectionResult::Disconnected => {
                warn!("Disconnected from orchestrator");
                if handle_retry(&mut retry_count, &surviving_task).await {
                    continue;
                }
                break;
            }
        }
    }

    // If we still have a surviving task, cancel it before exit
    if let Some(mut task) = surviving_task.take() {
        warn!("Cancelling surviving task on final shutdown");
        if let Some(tx) = task.cancel_tx.take() {
            let _ = tx.send(());
        }
        let _ = task.handle.await;
    }

    info!("Runner shutting down");
    Ok(())
}

fn read_runtime_credential(value_name: &str, file_name: &str) -> anyhow::Result<Option<String>> {
    let inline = match std::env::var(value_name) {
        Ok(value) => Some(value),
        Err(std::env::VarError::NotPresent) => None,
        Err(error) => return Err(error.into()),
    };
    let file_path = match std::env::var(file_name) {
        Ok(path) => Some(path),
        Err(std::env::VarError::NotPresent) => None,
        Err(error) => return Err(error.into()),
    };

    std::env::remove_var(value_name);
    std::env::remove_var(file_name);

    match (inline, file_path) {
        (Some(_), Some(_)) => {
            anyhow::bail!("runtime credential {value_name} has ambiguous inline and file sources")
        }
        (Some(value), None) => validate_runtime_credential(value_name, value).map(Some),
        (None, Some(path)) => {
            let value = std::fs::read_to_string(&path)
                .map_err(|error| anyhow::anyhow!("read {file_name} path {path}: {error}"))?;
            std::fs::remove_file(&path).map_err(|error| {
                anyhow::anyhow!("remove consumed {file_name} path {path}: {error}")
            })?;
            validate_runtime_credential(value_name, value.trim().to_string()).map(Some)
        }
        (None, None) => Ok(None),
    }
}

fn validate_runtime_credential(name: &str, value: String) -> anyhow::Result<String> {
    if value.is_empty() {
        anyhow::bail!("runtime credential {name} must not be empty");
    }
    Ok(value)
}

async fn handle_retry(retry_count: &mut u32, surviving_task: &Option<SurvivingTask>) -> bool {
    *retry_count += 1;
    if *retry_count > 60 {
        error!("Max reconnection attempts (60) reached");
        return false;
    }

    let delay = Duration::from_secs((1u64 << (*retry_count).min(5)).min(30));
    warn!(
        attempt = *retry_count,
        delay_sec = delay.as_secs(),
        has_surviving_task = surviving_task.is_some(),
        "Reconnecting after delay..."
    );
    tokio::time::sleep(delay).await;
    true
}

/// Drain buffered events from the surviving task's event_rx into the gRPC channel.
/// Returns the number of events replayed.
async fn drain_event_buffer(
    event_rx: &mut mpsc::Receiver<RunnerMessage>,
    runner_tx: &mpsc::Sender<RunnerMessage>,
) -> usize {
    let mut count = 0;
    while let Ok(msg) = event_rx.try_recv() {
        if runner_tx.send(msg).await.is_err() {
            break;
        }
        count += 1;
    }
    count
}

async fn send_setup_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    setup_id: String,
    runtime_config_generation: i64,
    status: proto::SandboxSetupStatus,
    error: Option<String>,
    error_code: Option<String>,
    loaded_skills: Vec<proto::LoadedSkill>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    runner_tx
        .send(RunnerMessage {
            payload: Some(proto::runner_message::Payload::SetupResult(
                proto::SandboxSetupResult {
                    setup_id,
                    runtime_config_generation,
                    status: status as i32,
                    error,
                    error_code,
                    loaded_skills,
                },
            )),
        })
        .await
}

async fn send_task_failure_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    error: String,
    harness_session_id: Option<String>,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    send_failure_result(runner_tx, error, harness_session_id, work_dir).await
}

async fn send_rejected_start_task_result_and_idle(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    sandbox_id: &str,
    error: String,
    harness_session_id: Option<String>,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    send_task_failure_result(
        runner_tx,
        error,
        harness_session_id.clone(),
        work_dir.clone(),
    )
    .await?;
    runner_tx
        .send(RunnerMessage {
            payload: Some(proto::runner_message::Payload::Idle(RunnerIdle {
                sandbox_id: sandbox_id.to_string(),
                work_dir,
                harness_session_id,
            })),
        })
        .await
}

async fn send_failure_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    error: String,
    harness_session_id: Option<String>,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    runner_tx
        .send(RunnerMessage {
            payload: Some(proto::runner_message::Payload::Result(
                RunnerHarnessResult {
                    status: "failed".to_string(),
                    output: String::new(),
                    error: Some(error),
                    harness_session_id,
                    work_dir,
                    ..Default::default()
                },
            )),
        })
        .await
}

async fn run_session(
    mut inbound: Streaming<proto::OrchestratorMessage>,
    runner_tx: mpsc::Sender<RunnerMessage>,
    sandbox_id: &str,
    adapters: &Arc<AdapterRegistry>,
    session_config: &mut runner::SessionConfig,
    surviving_task: &mut Option<SurvivingTask>,
    http_proxy_ready: Option<watch::Receiver<bool>>,
) -> ConnectionResult {
    let heartbeat_state = Arc::new(Mutex::new(HeartbeatRuntimeState::idle()));
    let heartbeat_tx = runner_tx.clone();
    let heartbeat_state_for_task = heartbeat_state.clone();
    let heartbeat_handle = tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(10));
        loop {
            interval.tick().await;
            let state = get_heartbeat_runtime_state(&heartbeat_state_for_task);
            let hb = RunnerMessage {
                payload: Some(proto::runner_message::Payload::Heartbeat(RunnerHeartbeat {
                    timestamp_ms: chrono::Utc::now().timestamp_millis(),
                    runtime_state: state.runtime_state,
                    active_task_id: state.active_task_id.map(|task_id| task_id.to_string()),
                    harness_session_id: state.harness_session_id,
                })),
            };
            if heartbeat_tx.send(hb).await.is_err() {
                break;
            }
        }
    });

    // If we have a surviving task from a previous connection, forward its events
    // through the new gRPC channel until it completes.
    if let Some(mut task) = surviving_task.take() {
        info!(task_id = %task.task_id, "Resuming surviving task on new connection");
        set_heartbeat_runtime_state(
            &heartbeat_state,
            HeartbeatRuntimeState::busy(task.task_id, task.harness_session_id.clone()),
        );

        let metadata = loop {
            tokio::select! {
                result = &mut task.handle => {
                    match result {
                        Ok(Ok(metadata)) => {
                            // Task finished — drain any remaining buffered events
                            let n = drain_event_buffer(&mut task.event_rx, &runner_tx).await;
                            if n > 0 {
                                info!(count = n, "Flushed remaining events after task completion");
                            }
                            break metadata;
                        }
                        Ok(Err(e)) => {
                            error!(error = %e, "Surviving task execution failed");
                            let error = format!("Task execution failed: {e}");
                            if let Err(send_err) = send_task_failure_result(
                                &runner_tx,
                                error,
                                task.harness_session_id.clone(),
                                task.work_dir.clone(),
                            )
                            .await
                            {
                                error!(error = %send_err, "Failed to send surviving task failure result");
                                heartbeat_handle.abort();
                                return ConnectionResult::Disconnected;
                            }
                            break runner::TaskMetadata {
                                work_dir: task.work_dir.clone().unwrap_or_default(),
                                harness_session_id: task.harness_session_id.clone(),
                            };
                        }
                        Err(e) => {
                            error!(error = %e, "Surviving task join error");
                            let error = format!("Task join error: {e}");
                            if let Err(send_err) = send_task_failure_result(
                                &runner_tx,
                                error,
                                task.harness_session_id.clone(),
                                task.work_dir.clone(),
                            )
                            .await
                            {
                                error!(error = %send_err, "Failed to send surviving task join failure result");
                                heartbeat_handle.abort();
                                return ConnectionResult::Disconnected;
                            }
                            break runner::TaskMetadata {
                                work_dir: task.work_dir.clone().unwrap_or_default(),
                                harness_session_id: task.harness_session_id.clone(),
                            };
                        }
                    }
                }
                // Forward events from runner to gRPC
                Some(msg) = task.event_rx.recv() => {
                    if runner_tx.send(msg.clone()).await.is_err() {
                        warn!("Lost connection while forwarding surviving task events");
                        task.unsent_event = Some(msg);
                        *surviving_task = Some(task);
                        heartbeat_handle.abort();
                        return ConnectionResult::Disconnected;
                    }
                }
                // Handle orchestrator messages during surviving task
                msg = inbound.message() => {
                    match msg {
                        Ok(Some(msg)) => {
                            match msg.payload {
                                Some(proto::orchestrator_message::Payload::Cancel(cancel)) => {
                                    info!(reason = %cancel.reason, "Received CancelTask for surviving task");
                                    if let Some(tx) = task.cancel_tx.take() {
                                        let _ = tx.send(());
                                    }
                                }
                                Some(proto::orchestrator_message::Payload::Input(input)) => {
                                    if let Err(e) = task
                                        .control_tx
                                        .send(runner::RunnerControl::SendInput(input.content))
                                        .await
                                    {
                                        warn!(error = %e, "Failed to forward input to surviving task");
                                    }
                                }
                                Some(proto::orchestrator_message::Payload::Shutdown(shutdown)) => {
                                    info!(reason = %shutdown.reason, "Received Shutdown during surviving task");
                                    if let Some(tx) = task.cancel_tx.take() {
                                        let _ = tx.send(());
                                    }
                                    heartbeat_handle.abort();
                                    return ConnectionResult::Shutdown;
                                }
                                Some(proto::orchestrator_message::Payload::SandboxFileRequest(request)) => {
                                    let response = sandbox_files::handle_request(request).await;
                                    let _ = runner_tx
                                        .send(RunnerMessage {
                                            payload: Some(proto::runner_message::Payload::SandboxFileResponse(response)),
                                        })
                                        .await;
                                }
                                _ => {}
                            }
                        }
                        Ok(None) | Err(_) => {
                            warn!("Orchestrator disconnected again while waiting for surviving task");
                            *surviving_task = Some(task);
                            heartbeat_handle.abort();
                            return ConnectionResult::Disconnected;
                        }
                    }
                }
            }
        };
        set_heartbeat_runtime_state(&heartbeat_state, HeartbeatRuntimeState::idle());

        let idle = RunnerMessage {
            payload: Some(proto::runner_message::Payload::Idle(RunnerIdle {
                sandbox_id: sandbox_id.to_string(),
                work_dir: if metadata.work_dir.is_empty() {
                    None
                } else {
                    Some(metadata.work_dir)
                },
                harness_session_id: metadata.harness_session_id,
            })),
        };
        if runner_tx.send(idle).await.is_err() {
            heartbeat_handle.abort();
            return ConnectionResult::Disconnected;
        }
    }

    // Normal message loop
    loop {
        let msg = match inbound.message().await {
            Ok(Some(msg)) => msg,
            Ok(None) => {
                info!("Orchestrator stream closed");
                heartbeat_handle.abort();
                return ConnectionResult::Disconnected;
            }
            Err(e) => {
                error!(error = %e, "Error reading from orchestrator stream");
                heartbeat_handle.abort();
                return ConnectionResult::Disconnected;
            }
        };

        match msg.payload {
            Some(proto::orchestrator_message::Payload::Start(start_task)) => {
                let task_id = match parse_start_task_id(&start_task.task_id) {
                    Ok(task_id) => task_id,
                    Err(error) => {
                        error!(task_id = %start_task.task_id, error = %error, "Rejected invalid StartTask task id");
                        if send_rejected_start_task_result_and_idle(
                            &runner_tx,
                            sandbox_id,
                            error.to_string(),
                            start_task.harness_session_id.clone(),
                            start_task.work_dir.clone(),
                        )
                        .await
                        .is_err()
                        {
                            heartbeat_handle.abort();
                            return ConnectionResult::Disconnected;
                        }
                        continue;
                    }
                };
                info!(
                    task_id = %task_id,
                    provider = %start_task.provider,
                    "Received StartTask"
                );

                let harness_session_id = start_task.harness_session_id.clone();
                set_heartbeat_runtime_state(
                    &heartbeat_state,
                    HeartbeatRuntimeState::busy(task_id, harness_session_id.clone()),
                );
                let task_work_dir = session_config
                    .work_dir
                    .as_ref()
                    .map(|path| path.to_string_lossy().to_string())
                    .or_else(|| start_task.work_dir.clone())
                    .or_else(|| Some("/workspace".to_string()));
                let (cancel_tx, cancel_rx) = oneshot::channel::<()>();
                let mut cancel_tx = Some(cancel_tx);
                let (control_tx, control_rx) = mpsc::channel::<runner::RunnerControl>(64);

                // Create an intermediary channel that outlives the gRPC connection.
                // Runner sends here; we forward to runner_tx (or buffer on disconnect).
                let (event_tx, mut event_rx) = mpsc::channel::<RunnerMessage>(512);

                let task_adapters = adapters.clone();
                let task_session_config = session_config.clone();
                let task_http_proxy_ready = http_proxy_ready.clone();
                let mut task_handle = tokio::spawn(async move {
                    if let Some(receiver) = task_http_proxy_ready {
                        wait_for_http_proxy_bridge_ready(receiver).await;
                    }
                    runner::handle_task(
                        start_task,
                        &task_session_config,
                        task_adapters,
                        event_tx, // runner sends to intermediary, not gRPC directly
                        cancel_rx,
                        control_rx,
                    )
                    .await
                });

                let mut shutdown = false;

                let metadata = loop {
                    tokio::select! {
                        result = &mut task_handle => {
                            // Task finished — drain remaining events
                            let n = drain_event_buffer(&mut event_rx, &runner_tx).await;
                            if n > 0 {
                                info!(count = n, "Flushed remaining events after task completion");
                            }
                            match result {
                                Ok(Ok(metadata)) => break metadata,
                                Ok(Err(e)) => {
                                    error!(error = %e, "Task execution failed");
                                    let error = format!("Task execution failed: {e}");
                                    if let Err(send_err) = send_task_failure_result(
                                        &runner_tx,
                                        error,
                                        harness_session_id.clone(),
                                        task_work_dir.clone(),
                                    )
                                    .await
                                    {
                                        error!(error = %send_err, "Failed to send task failure result");
                                        heartbeat_handle.abort();
                                        return ConnectionResult::Disconnected;
                                    }
                                    break runner::TaskMetadata {
                                        work_dir: task_work_dir.clone().unwrap_or_default(),
                                        harness_session_id: harness_session_id.clone(),
                                    };
                                }
                                Err(e) => {
                                    error!(error = %e, "Task join error");
                                    let error = format!("Task join error: {e}");
                                    if let Err(send_err) = send_task_failure_result(
                                        &runner_tx,
                                        error,
                                        harness_session_id.clone(),
                                        task_work_dir.clone(),
                                    )
                                    .await
                                    {
                                        error!(error = %send_err, "Failed to send task join failure result");
                                        heartbeat_handle.abort();
                                        return ConnectionResult::Disconnected;
                                    }
                                    break runner::TaskMetadata {
                                        work_dir: task_work_dir.clone().unwrap_or_default(),
                                        harness_session_id: harness_session_id.clone(),
                                    };
                                }
                            }
                        }
                        // Forward events from runner → gRPC
                        Some(msg) = event_rx.recv() => {
                            if runner_tx.send(msg.clone()).await.is_err() {
                                warn!("gRPC channel dead during event forward — preserving task for reconnect");
                                *surviving_task = Some(SurvivingTask {
                                    task_id,
                                    harness_session_id: harness_session_id.clone(),
                                    work_dir: task_work_dir.clone(),
                                    handle: task_handle,
                                    cancel_tx,
                                    control_tx: control_tx.clone(),
                                    event_rx,
                                    unsent_event: Some(msg),
                                });
                                heartbeat_handle.abort();
                                return ConnectionResult::Disconnected;
                            }
                        }
                        msg = inbound.message() => {
                            match msg {
                                Ok(Some(msg)) => {
                                    match msg.payload {
                                        Some(proto::orchestrator_message::Payload::Cancel(cancel)) => {
                                            info!(reason = %cancel.reason, "Received CancelTask");
                                            if let Some(tx) = cancel_tx.take() {
                                                let _ = tx.send(());
                                            }
                                        }
                                        Some(proto::orchestrator_message::Payload::Shutdown(shutdown_msg)) => {
                                            info!(reason = %shutdown_msg.reason, "Received Shutdown during task");
                                            if let Some(tx) = cancel_tx.take() {
                                                let _ = tx.send(());
                                            }
                                            shutdown = true;
                                        }
                                        Some(proto::orchestrator_message::Payload::Input(input)) => {
                                            let _ = control_tx
                                                .send(runner::RunnerControl::SendInput(input.content))
                                                .await;
                                        }
                                        Some(proto::orchestrator_message::Payload::MemoryUpdate(update)) => {
                                            runner::handle_memory_update(update, session_config).await;
                                        }
                                        Some(proto::orchestrator_message::Payload::SandboxFileRequest(request)) => {
                                            let response = sandbox_files::handle_request(request).await;
                                            let _ = runner_tx
                                                .send(RunnerMessage {
                                                    payload: Some(proto::runner_message::Payload::SandboxFileResponse(response)),
                                                })
                                                .await;
                                        }
                                        _ => {}
                                    }
                                }
                                Ok(None) => {
                                    warn!("Orchestrator stream closed during task — task continues running");
                                    *surviving_task = Some(SurvivingTask {
                                        task_id,
                                        harness_session_id: harness_session_id.clone(),
                                        work_dir: task_work_dir.clone(),
                                        handle: task_handle,
                                        cancel_tx,
                                        control_tx: control_tx.clone(),
                                        event_rx,
                                        unsent_event: None,
                                    });
                                    heartbeat_handle.abort();
                                    return ConnectionResult::Disconnected;
                                }
                                Err(e) => {
                                    error!(error = %e, "Error reading orchestrator stream during task — task continues running");
                                    *surviving_task = Some(SurvivingTask {
                                        task_id,
                                        harness_session_id: harness_session_id.clone(),
                                        work_dir: task_work_dir.clone(),
                                        handle: task_handle,
                                        cancel_tx,
                                        control_tx: control_tx.clone(),
                                        event_rx,
                                        unsent_event: None,
                                    });
                                    heartbeat_handle.abort();
                                    return ConnectionResult::Disconnected;
                                }
                            }
                        }
                    }
                };

                set_heartbeat_runtime_state(&heartbeat_state, HeartbeatRuntimeState::idle());

                if shutdown {
                    heartbeat_handle.abort();
                    return ConnectionResult::Shutdown;
                }

                let idle = RunnerMessage {
                    payload: Some(proto::runner_message::Payload::Idle(RunnerIdle {
                        sandbox_id: sandbox_id.to_string(),
                        work_dir: if metadata.work_dir.is_empty() {
                            None
                        } else {
                            Some(metadata.work_dir)
                        },
                        harness_session_id: metadata.harness_session_id,
                    })),
                };
                if let Err(e) = runner_tx.send(idle).await {
                    error!(error = %e, "Failed to send RunnerIdle");
                    heartbeat_handle.abort();
                    return ConnectionResult::Disconnected;
                }
            }
            Some(proto::orchestrator_message::Payload::Setup(setup)) => {
                info!("Received SetupSandbox");
                let setup_id = setup.setup_id.clone();
                let runtime_config_generation = setup.runtime_config_generation;
                match runner::handle_setup(setup, runner_tx.clone()).await {
                    Ok(outcome) => {
                        let wd = outcome.config.work_dir.clone().unwrap_or_default();
                        info!(work_dir = %wd.display(), "Setup complete");
                        *session_config = outcome.config;
                        if let Err(error) = send_setup_result(
                            &runner_tx,
                            setup_id,
                            runtime_config_generation,
                            proto::SandboxSetupStatus::Applied,
                            None,
                            None,
                            outcome.loaded_skills,
                        )
                        .await
                        {
                            error!(error = %error, "Failed to send SetupSandbox success result");
                            heartbeat_handle.abort();
                            return ConnectionResult::Disconnected;
                        }
                        let idle = RunnerMessage {
                            payload: Some(proto::runner_message::Payload::Idle(RunnerIdle {
                                sandbox_id: sandbox_id.to_string(),
                                work_dir: Some(wd.to_string_lossy().to_string()),
                                harness_session_id: None,
                            })),
                        };
                        if let Err(e) = runner_tx.send(idle).await {
                            error!(error = %e, "Failed to send RunnerIdle after setup");
                            heartbeat_handle.abort();
                            return ConnectionResult::Disconnected;
                        }
                    }
                    Err(e) => {
                        error!(error = %e, "SetupSandbox failed");
                        if let Err(send_err) = send_setup_result(
                            &runner_tx,
                            setup_id,
                            runtime_config_generation,
                            proto::SandboxSetupStatus::Failed,
                            Some(format!("SetupSandbox failed: {e}")),
                            Some("SETUP_FAILED".to_string()),
                            Vec::new(),
                        )
                        .await
                        {
                            error!(error = %send_err, "Failed to send SetupSandbox failure result");
                            heartbeat_handle.abort();
                            return ConnectionResult::Disconnected;
                        }
                    }
                }
            }
            Some(proto::orchestrator_message::Payload::Cancel(_)) => {
                warn!("Received CancelTask but no task is running");
            }
            Some(proto::orchestrator_message::Payload::Input(_)) => {}
            Some(proto::orchestrator_message::Payload::MemoryUpdate(update)) => {
                runner::handle_memory_update(update, session_config).await;
            }
            Some(proto::orchestrator_message::Payload::SandboxFileRequest(request)) => {
                let response = sandbox_files::handle_request(request).await;
                let _ = runner_tx
                    .send(RunnerMessage {
                        payload: Some(proto::runner_message::Payload::SandboxFileResponse(
                            response,
                        )),
                    })
                    .await;
            }
            Some(proto::orchestrator_message::Payload::Shutdown(shutdown)) => {
                info!(reason = %shutdown.reason, "Received Shutdown, exiting");
                heartbeat_handle.abort();
                return ConnectionResult::Shutdown;
            }
            None => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn managed_http_proxy_url_does_not_expose_egress_token() {
        let proxy = local_proxy_url();

        assert_eq!(
            proxy,
            format!("http://127.0.0.1:{}", egress_bridge::BRIDGE_PORT)
        );
        assert!(!proxy.contains("egress-token"));
    }

    #[test]
    fn proxy_authorization_uses_dedicated_egress_token() {
        assert_eq!(
            proxy_authorization(Some("egress-token")).expect("proxy authorization"),
            "Basic c2FuZGJveDplZ3Jlc3MtdG9rZW4="
        );
        assert!(proxy_authorization(None).is_err());
    }

    #[test]
    fn start_task_id_requires_canonical_platform_task_id() {
        let task_id = joysafeter_types::TaskId::new();

        assert_eq!(parse_start_task_id(&task_id.to_string()).unwrap(), task_id);
        assert!(parse_start_task_id(&task_id.as_uuid().to_string()).is_err());
        assert!(parse_start_task_id(&joysafeter_types::SessionId::new().to_string()).is_err());
    }

    #[tokio::test]
    async fn setup_failure_result_is_correlated_to_generation() {
        let (tx, mut rx) = mpsc::channel(1);

        send_setup_result(
            &tx,
            "setup-7".to_string(),
            7,
            proto::SandboxSetupStatus::Failed,
            Some("SetupSandbox failed: clone setup repos".to_string()),
            Some("SETUP_FAILED".to_string()),
            Vec::new(),
        )
        .await
        .expect("send setup failure result");

        let message = rx.recv().await.expect("failure result message");
        match message.payload {
            Some(proto::runner_message::Payload::SetupResult(result)) => {
                assert_eq!(result.setup_id, "setup-7");
                assert_eq!(result.runtime_config_generation, 7);
                assert_eq!(result.status, proto::SandboxSetupStatus::Failed as i32);
                assert_eq!(
                    result.error.as_deref(),
                    Some("SetupSandbox failed: clone setup repos")
                );
                assert_eq!(result.error_code.as_deref(), Some("SETUP_FAILED"));
            }
            other => panic!("unexpected runner message: {other:?}"),
        }
    }

    #[tokio::test]
    async fn task_failure_result_reports_failed_task_with_context() {
        let (tx, mut rx) = mpsc::channel(1);

        send_task_failure_result(
            &tx,
            "Task execution failed: StartTask setup command #1 failed".to_string(),
            Some("harness-session-1".to_string()),
            Some("/workspace/project".to_string()),
        )
        .await
        .expect("send task failure result");

        let message = rx.recv().await.expect("failure result message");
        match message.payload {
            Some(proto::runner_message::Payload::Result(result)) => {
                assert_eq!(result.status, "failed");
                assert_eq!(
                    result.error.as_deref(),
                    Some("Task execution failed: StartTask setup command #1 failed")
                );
                assert_eq!(
                    result.harness_session_id.as_deref(),
                    Some("harness-session-1")
                );
                assert_eq!(result.work_dir.as_deref(), Some("/workspace/project"));
            }
            other => panic!("unexpected runner message: {other:?}"),
        }
    }

    #[tokio::test]
    async fn rejected_start_task_reports_failure_then_idle() {
        let (tx, mut rx) = mpsc::channel(2);

        send_rejected_start_task_result_and_idle(
            &tx,
            "sbx_test",
            "invalid StartTask.task_id".to_string(),
            Some("harness-session-1".to_string()),
            Some("/workspace/project".to_string()),
        )
        .await
        .expect("send rejected task result and idle");

        match rx.recv().await.expect("failure result message").payload {
            Some(proto::runner_message::Payload::Result(result)) => {
                assert_eq!(result.status, "failed");
                assert_eq!(result.error.as_deref(), Some("invalid StartTask.task_id"));
                assert_eq!(
                    result.harness_session_id.as_deref(),
                    Some("harness-session-1")
                );
                assert_eq!(result.work_dir.as_deref(), Some("/workspace/project"));
            }
            other => panic!("unexpected runner message: {other:?}"),
        }

        match rx.recv().await.expect("idle message").payload {
            Some(proto::runner_message::Payload::Idle(idle)) => {
                assert_eq!(
                    idle.harness_session_id.as_deref(),
                    Some("harness-session-1")
                );
                assert_eq!(idle.work_dir.as_deref(), Some("/workspace/project"));
            }
            other => panic!("unexpected runner message: {other:?}"),
        }
    }
}
