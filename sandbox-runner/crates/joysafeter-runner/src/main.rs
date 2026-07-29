mod archive;
#[cfg(target_os = "linux")]
mod memory_fuse;
mod repos;
mod runner;
mod sandbox_files;
mod stream;

pub mod proto {
    tonic::include_proto!("joysafeter");
}

use proto::agent_bridge_client::AgentBridgeClient;
use proto::{RunnerHarnessResult, RunnerHeartbeat, RunnerIdle, RunnerMessage};

use joysafeter_runtime::AdapterRegistry;
use std::os::unix::fs::FileTypeExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};
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
    task_id: String,
    session_id: Option<String>,
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
    active_task_id: Option<String>,
    session_id: Option<String>,
}

impl HeartbeatRuntimeState {
    fn idle() -> Self {
        Self {
            runtime_state: "idle".to_string(),
            active_task_id: None,
            session_id: None,
        }
    }

    fn busy(task_id: String, session_id: Option<String>) -> Self {
        Self {
            runtime_state: "busy".to_string(),
            active_task_id: Some(task_id),
            session_id,
        }
    }
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
    // Read the runner token from env or from a file (the entrypoint may have
    // moved it to a file and unset the env var to prevent leakage via
    // `docker exec env`).
    let runner_token = std::env::var("JOYSAFETER_RUNNER_TOKEN").ok().or_else(|| {
        std::env::var("JOYSAFETER_RUNNER_TOKEN_FILE")
            .ok()
            .and_then(|path| {
                let token = std::fs::read_to_string(&path).ok()?.trim().to_string();
                // Delete the file after reading — one-shot.
                let _ = std::fs::remove_file(&path);
                if token.is_empty() {
                    None
                } else {
                    Some(token)
                }
            })
    });

    let grpc_sock_path = if orch_url.starts_with("unix://") {
        let grpc_path = orch_url.strip_prefix("unix://").unwrap();
        Some(PathBuf::from(grpc_path))
    } else {
        None
    };

    // Derive http.sock path from orchestrator URL (e.g. unix:///sockets/{id}/grpc.sock → http.sock)
    let http_sock_path = grpc_sock_path.as_ref().map(|grpc_path| {
        let parent = grpc_path.parent().unwrap_or(Path::new("/tmp/proxy"));
        parent.join("http.sock")
    });

    if let Some(ref grpc_sock) = grpc_sock_path {
        wait_for_unix_socket(grpc_sock, "orchestrator gRPC").await;
    }

    if let Some(ref http_sock) = http_sock_path {
        let socket_ready = wait_for_unix_socket(http_sock, "restricted HTTP proxy").await;

        if socket_ready {
            info!("Restricted networking detected, starting socat HTTP proxy bridge");
            match tokio::process::Command::new("socat")
                .args([
                    "TCP-LISTEN:3128,fork,reuseaddr",
                    &format!("UNIX-CONNECT:{}", http_sock.display()),
                ])
                .spawn()
            {
                Ok(_child) => {
                    let proxy = runner_token
                        .as_ref()
                        .map(|token| format!("http://sandbox:{}@127.0.0.1:3128", url_escape(token)))
                        .unwrap_or_else(|| "http://127.0.0.1:3128".to_string());
                    std::env::set_var("HTTP_PROXY", &proxy);
                    std::env::set_var("HTTPS_PROXY", &proxy);
                    std::env::set_var("http_proxy", &proxy);
                    std::env::set_var("https_proxy", &proxy);
                    std::env::set_var("ALL_PROXY", &proxy);
                    std::env::set_var("all_proxy", &proxy);
                    info!("socat HTTP proxy bridge started on 127.0.0.1:3128");
                }
                Err(e) => {
                    warn!(error = %e, "Failed to start socat bridge, HTTP proxy will be unavailable");
                }
            }
        } else {
            warn!(path = %http_sock.display(), "Restricted networking socket was not ready; HTTP proxy will be unavailable");
        }
    }

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
            match tonic::transport::Endpoint::from_static("http://[::]:50051")
                .connect_with_connector(tower::service_fn(move |_: tonic::transport::Uri| {
                    let path = path.clone();
                    async move {
                        match tokio::net::UnixStream::connect(&path).await {
                            Ok(stream) => Ok::<_, std::io::Error>(hyper_util::rt::TokioIo::new(stream)),
                            Err(error) => {
                                warn!(path = %path, error = %error, "Unix socket connect attempt failed");
                                Err(error)
                            }
                        }
                    }
                }))
                .await
            {
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
                Ok(endpoint) => match endpoint.connect().await {
                    Ok(ch) => ch,
                    Err(e) => {
                        error!(error = %e, "Failed to connect to orchestrator");
                        if handle_retry(&mut retry_count, &surviving_task).await {
                            continue;
                        }
                        break;
                    }
                },
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
        let active_task_id = surviving_task.as_ref().map(|t| t.task_id.clone());

        let ready = RunnerMessage {
            payload: Some(proto::runner_message::Payload::Ready(proto::RunnerReady {
                runner_version: env!("CARGO_PKG_VERSION").to_string(),
                available_providers: provider_names.clone(),
                sandbox_id: sandbox_id.clone(),
                is_reconnect,
                active_task_id: active_task_id.clone(),
                capabilities: vec!["file_mount".to_string(), "url_download".to_string()],
                runner_token: runner_token.clone(),
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
        if is_first_connect {
            // Defense-in-depth: scrub the runner token from this process's env.
            // The entrypoint wrapper already removed it from the container-level
            // env (preventing `docker exec env` exposure), but this also covers
            // legacy images that run joysafeter-runner directly as ENTRYPOINT.
            std::env::remove_var("JOYSAFETER_RUNNER_TOKEN");
            std::env::remove_var("JOYSAFETER_RUNNER_TOKEN_FILE");
        }
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
            loop {
                match task.event_rx.try_recv() {
                    Ok(msg) => {
                        if runner_tx.send(msg).await.is_err() {
                            warn!("Lost connection while replaying buffer");
                            break;
                        }
                        replayed += 1;
                    }
                    Err(_) => break,
                }
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

fn url_escape(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                escaped.push(byte as char)
            }
            _ => escaped.push_str(&format!("%{byte:02X}")),
        }
    }
    escaped
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
    loop {
        match event_rx.try_recv() {
            Ok(msg) => {
                if runner_tx.send(msg).await.is_err() {
                    break;
                }
                count += 1;
            }
            Err(_) => break,
        }
    }
    count
}

async fn send_setup_failure_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    error: String,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    send_failure_result(runner_tx, error, None, work_dir).await
}

async fn send_task_failure_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    error: String,
    session_id: Option<String>,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    send_failure_result(runner_tx, error, session_id, work_dir).await
}

async fn send_failure_result(
    runner_tx: &mpsc::Sender<RunnerMessage>,
    error: String,
    session_id: Option<String>,
    work_dir: Option<String>,
) -> Result<(), mpsc::error::SendError<RunnerMessage>> {
    runner_tx
        .send(RunnerMessage {
            payload: Some(proto::runner_message::Payload::Result(
                RunnerHarnessResult {
                    status: "failed".to_string(),
                    output: String::new(),
                    error: Some(error),
                    session_id,
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
                    active_task_id: state.active_task_id,
                    session_id: state.session_id,
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
            HeartbeatRuntimeState::busy(task.task_id.clone(), task.session_id.clone()),
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
                                task.session_id.clone(),
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
                                session_id: task.session_id.clone(),
                                aborted: false,
                            };
                        }
                        Err(e) => {
                            error!(error = %e, "Surviving task join error");
                            let error = format!("Task join error: {e}");
                            if let Err(send_err) = send_task_failure_result(
                                &runner_tx,
                                error,
                                task.session_id.clone(),
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
                                session_id: task.session_id.clone(),
                                aborted: false,
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
                session_id: metadata.session_id,
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
                info!(
                    task_id = %start_task.task_id,
                    provider = %start_task.provider,
                    "Received StartTask"
                );

                let task_id_str = start_task.task_id.clone();
                let task_session_id = start_task.session_id.clone();
                set_heartbeat_runtime_state(
                    &heartbeat_state,
                    HeartbeatRuntimeState::busy(task_id_str.clone(), task_session_id.clone()),
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
                let mut task_handle = tokio::spawn(async move {
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
                                        task_session_id.clone(),
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
                                        session_id: task_session_id.clone(),
                                        aborted: false,
                                    };
                                }
                                Err(e) => {
                                    error!(error = %e, "Task join error");
                                    let error = format!("Task join error: {e}");
                                    if let Err(send_err) = send_task_failure_result(
                                        &runner_tx,
                                        error,
                                        task_session_id.clone(),
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
                                        session_id: task_session_id.clone(),
                                        aborted: false,
                                    };
                                }
                            }
                        }
                        // Forward events from runner → gRPC
                        Some(msg) = event_rx.recv() => {
                            if runner_tx.send(msg.clone()).await.is_err() {
                                warn!("gRPC channel dead during event forward — preserving task for reconnect");
                                *surviving_task = Some(SurvivingTask {
                                    task_id: task_id_str.clone(),
                                    session_id: task_session_id.clone(),
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
                                        task_id: task_id_str.clone(),
                                        session_id: task_session_id.clone(),
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
                                        task_id: task_id_str.clone(),
                                        session_id: task_session_id.clone(),
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
                        session_id: metadata.session_id,
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
                let setup_work_dir = setup.work_dir.clone();
                match runner::handle_setup(setup, runner_tx.clone()).await {
                    Ok(config) => {
                        let wd = config.work_dir.clone().unwrap_or_default();
                        info!(work_dir = %wd.display(), "Setup complete");
                        *session_config = config;
                        let idle = RunnerMessage {
                            payload: Some(proto::runner_message::Payload::Idle(RunnerIdle {
                                sandbox_id: sandbox_id.to_string(),
                                work_dir: Some(wd.to_string_lossy().to_string()),
                                session_id: None,
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
                        if let Err(send_err) = send_setup_failure_result(
                            &runner_tx,
                            format!("SetupSandbox failed: {e}"),
                            setup_work_dir,
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

    #[tokio::test]
    async fn setup_failure_result_reports_failed_setup_with_work_dir() {
        let (tx, mut rx) = mpsc::channel(1);

        send_setup_failure_result(
            &tx,
            "SetupSandbox failed: clone setup repos".to_string(),
            Some("/workspace".to_string()),
        )
        .await
        .expect("send setup failure result");

        let message = rx.recv().await.expect("failure result message");
        match message.payload {
            Some(proto::runner_message::Payload::Result(result)) => {
                assert_eq!(result.status, "failed");
                assert_eq!(
                    result.error.as_deref(),
                    Some("SetupSandbox failed: clone setup repos")
                );
                assert_eq!(result.work_dir.as_deref(), Some("/workspace"));
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
                assert_eq!(result.session_id.as_deref(), Some("harness-session-1"));
                assert_eq!(result.work_dir.as_deref(), Some("/workspace/project"));
            }
            other => panic!("unexpected runner message: {other:?}"),
        }
    }
}
