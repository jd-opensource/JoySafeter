use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use futures::Stream;
use serde_json::json;
use sha2::{Digest, Sha256};
use sqlx::PgPool;
use tokio::sync::{mpsc, Semaphore};
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tokio_stream::wrappers::ReceiverStream;
use tokio_stream::StreamExt as _;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::events::bus::EventBus;
use crate::events::envelope::EventEnvelope;
use crate::events::mapping;
use crate::grpc::proto;
use crate::grpc::proto::agent_bridge_server::{AgentBridge, AgentBridgeServer};
use crate::grpc::proto::{
    orchestrator_message, runner_message, OrchestratorMessage, RunnerMessage, Shutdown,
};
use crate::kernel::harness_input_builder::HarnessInputBuilder;
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::{BridgeRegistry, SandboxBridge};
use crate::runtime_config::RuntimeConfig;
use crate::sandbox::provider::SandboxProvider;

const HEARTBEAT_TIMEOUT_DEFAULT: u64 = 120;
const GRPC_MAX_RECV_MESSAGE_SIZE: usize = 128 * 1024 * 1024;
const GRPC_MAX_SEND_MESSAGE_SIZE: usize = 32 * 1024 * 1024;
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

/// The AgentBridge gRPC service implementation.
/// Full parity with Python `AgentBridgeServicer` (2753 lines).
pub struct AgentBridgeService {
    bridge_registry: BridgeRegistry,
    event_bus: EventBus,
    queue: TaskQueue,
    pool: PgPool,
    config: JoySafeterConfig,
    sandbox_provider: Arc<dyn SandboxProvider>,
    runtime_config: Arc<RuntimeConfig>,
    connection_semaphore: Arc<Semaphore>,
    execution_semaphore: Arc<Semaphore>,
    redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
}

impl AgentBridgeService {
    pub fn new(
        bridge_registry: BridgeRegistry,
        event_bus: EventBus,
        queue: TaskQueue,
        pool: PgPool,
        config: JoySafeterConfig,
        sandbox_provider: Arc<dyn SandboxProvider>,
        redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
        runtime_config: Arc<RuntimeConfig>,
    ) -> Self {
        let max_connections = config.grpc_max_connections;
        let max_executions = config.grpc_max_executions;
        Self {
            bridge_registry,
            event_bus,
            queue,
            pool,
            config,
            sandbox_provider,
            runtime_config,
            connection_semaphore: Arc::new(Semaphore::new(max_connections)),
            execution_semaphore: Arc::new(Semaphore::new(max_executions)),
            redis_coordinator,
            memory_subscribers,
        }
    }
}

#[tonic::async_trait]
impl AgentBridge for AgentBridgeService {
    type SessionStream =
        Pin<Box<dyn Stream<Item = Result<OrchestratorMessage, Status>> + Send + 'static>>;

    async fn session(
        &self,
        request: Request<Streaming<RunnerMessage>>,
    ) -> Result<Response<Self::SessionStream>, Status> {
        // Connection-level rate limiting
        let conn_permit = self
            .connection_semaphore
            .clone()
            .try_acquire_owned()
            .map_err(|_| Status::resource_exhausted("Too many concurrent connections"))?;

        let mut inbound = request.into_inner();
        let (tx, rx) = mpsc::channel::<OrchestratorMessage>(256);
        let outbound = ReceiverStream::new(rx);

        let bridge_registry = self.bridge_registry.clone();
        let event_bus = self.event_bus.clone();
        let queue = self.queue.clone();
        let pool = self.pool.clone();
        let config = self.config.clone();
        let sandbox_provider = self.sandbox_provider.clone();
        let runtime_config = self.runtime_config.clone();
        let redis_coordinator = self.redis_coordinator.clone();
        let memory_subscribers = self.memory_subscribers.clone();
        let execution_semaphore = self.execution_semaphore.clone();

        tokio::spawn(async move {
            // Fix 4.1: conn_permit lives for the duration of the spawned task
            let _conn_permit = conn_permit;
            // Now inside the spawned task, response headers have been sent.
            // The client can send RunnerReady.
            let ready = match wait_for_ready(&mut inbound).await {
                Ok(Some(r)) => r,
                Ok(None) => {
                    warn!("First message was not RunnerReady, closing");
                    return;
                }
                Err(e) => {
                    warn!("Failed to receive RunnerReady: {e}");
                    return;
                }
            };

            // Parse sandbox_id as UUID
            let sandbox_db_id = match ready.sandbox_id.parse::<Uuid>() {
                Ok(id) => id,
                Err(_) => {
                    warn!("Invalid sandbox_id: {}", ready.sandbox_id);
                    return;
                }
            };

            let sandbox_external_id = ready.sandbox_id.clone();
            info!(
                sandbox_id = %sandbox_external_id,
                runner_version = %ready.runner_version,
                providers = ?ready.available_providers,
                is_reconnect = ready.is_reconnect,
                "Runner connected"
            );

            // Authenticate runner token
            let sandbox_rec = match queries::get_sandbox(&pool, sandbox_db_id).await {
                Ok(r) => r,
                Err(e) => {
                    warn!("DB error looking up sandbox: {e}");
                    return;
                }
            };

            if let Some(ref sandbox) = sandbox_rec {
                let expected_token = sandbox
                    .config
                    .as_ref()
                    .and_then(|c| c.get("runner_token"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");

                if !expected_token.is_empty() {
                    let runner_token = ready.runner_token.as_deref().unwrap_or("");
                    if runner_token.is_empty() {
                        warn!(sandbox_id = %sandbox_db_id, "Runner connected without token, rejecting");
                        send_shutdown(
                            &tx,
                            "authentication required: missing runner token".to_string(),
                        )
                        .await;
                        return;
                    }
                    // Constant-time comparison (#29: Python uses hmac.compare_digest)
                    use subtle::ConstantTimeEq;
                    if expected_token
                        .as_bytes()
                        .ct_eq(runner_token.as_bytes())
                        .unwrap_u8()
                        == 0
                    {
                        warn!(sandbox_id = %sandbox_db_id, "Runner token mismatch, rejecting");
                        send_shutdown(
                            &tx,
                            "authentication failed: invalid runner token".to_string(),
                        )
                        .await;
                        return;
                    }
                }

                // Reject terminal sandboxes
                let status = sandbox.status.as_str();
                if matches!(status, "destroyed" | "error") {
                    warn!(sandbox_id = %sandbox_db_id, status = status, "Terminal sandbox, rejecting");
                    send_shutdown(&tx, format!("sandbox terminal: {status}")).await;
                    return;
                }
                if matches!(status, "stopping" | "stopped") {
                    warn!(sandbox_id = %sandbox_db_id, status = status, "Sandbox being stopped, rejecting");
                    send_shutdown(&tx, format!("sandbox stopped: {status}")).await;
                    return;
                }

                // CAS status transition (skip for pooled)
                if status != "pooled" {
                    let _ =
                        queries::transition_sandbox_cas(&pool, sandbox_db_id, status, "idle").await;
                }
                let _ = queries::touch_sandbox(&pool, sandbox_db_id).await;
                // Successful runner attach → clear any stale disconnect
                // marker left by a prior crash, so the fallback sweeper
                // doesn't reap a sandbox that just reconnected.
                let _ = queries::mark_bridge_connected(&pool, sandbox_db_id).await;
            } else if ready.runner_token.as_deref().unwrap_or("").is_empty() {
                warn!(sandbox_id = %sandbox_db_id, "Unknown sandbox with no token, rejecting");
                return;
            }

            // Create and register bridge
            let bridge = Arc::new(SandboxBridge::new(sandbox_db_id, tx.clone()));
            // Store capabilities
            {
                let mut caps = bridge.runner_capabilities.lock().await;
                *caps = ready.capabilities.clone();
            }
            bridge_registry.register(sandbox_external_id.clone(), bridge.clone());

            // #3: Register sandbox owner in Redis (Python L184)
            if let Some(ref coord) = redis_coordinator {
                let _ = coord.register_sandbox(sandbox_db_id).await;
            }

            // Resolve linked session_id
            let linked_session_id = sandbox_rec.as_ref().and_then(|s| s.chat_session_id);

            // Send SetupSandbox if not reconnect
            if !ready.is_reconnect {
                match send_setup(&pool, &bridge, sandbox_db_id, &tx).await {
                    Ok(true) => bridge.setup_done.store(true, Ordering::Relaxed),
                    Ok(false) => {
                        bridge.setup_done.store(false, Ordering::Relaxed);
                    }
                    Err(e) => {
                        warn!(sandbox_id = %sandbox_db_id, "Failed to send SetupSandbox: {e}");
                        bridge.setup_done.store(false, Ordering::Relaxed);
                    }
                }
            } else {
                bridge.setup_done.store(true, Ordering::Relaxed);
            }

            // Capture reconnect info for the spawned task
            let reconnect_active_task_id = if ready.is_reconnect {
                ready
                    .active_task_id
                    .as_ref()
                    .and_then(|s| s.parse::<Uuid>().ok())
            } else {
                None
            };
            let is_reconnect = ready.is_reconnect;

            // Spawn the multi-task loop
            let pool = pool.clone();
            let event_bus = event_bus.clone();
            let queue = queue.clone();
            let config = config.clone();
            let sandbox_provider = sandbox_provider.clone();
            let runtime_config = runtime_config.clone();
            let registry = bridge_registry.clone();
            let bridge_clone = bridge.clone();
            let exec_sem = execution_semaphore.clone();
            let redis_coord = redis_coordinator.clone();
            let memory_subscribers = memory_subscribers.clone();

            if let Some(sid) = linked_session_id {
                if let Ok(stores) = queries::list_session_memory_stores(&pool, sid).await {
                    for store in stores {
                        let mount_path = format!("/mnt/memory/{}", store.mount_name);
                        memory_subscribers
                            .register(
                                &store.store_id.to_string(),
                                sid,
                                sandbox_db_id,
                                &store.mount_name,
                                &mount_path,
                            )
                            .await;
                    }
                }
            }

            // Handle reconnect (inline, already inside spawned task)
            if let Some(active_task_id) = reconnect_active_task_id {
                // Run the reconnect event loop with the actual stream
                handle_reconnect_with_event_loop(
                    &mut inbound,
                    &tx,
                    &bridge_clone,
                    &pool,
                    &event_bus,
                    &config,
                    sandbox_db_id,
                    active_task_id,
                    linked_session_id,
                    &exec_sem,
                    redis_coord.as_deref(),
                    memory_subscribers.clone(),
                    &registry,
                    &runtime_config,
                )
                .await;
            } else if is_reconnect {
                // Rescue orphaned running tasks
                rescue_orphaned_tasks(&pool, &event_bus, sandbox_db_id, &queue).await;
            }

            let failure_ejected = multi_task_loop(
                &mut inbound,
                &tx,
                &bridge_clone,
                &pool,
                &event_bus,
                &queue,
                &config,
                &sandbox_provider,
                sandbox_db_id,
                &sandbox_external_id,
                linked_session_id,
                &exec_sem,
                redis_coord.as_deref(),
                memory_subscribers.clone(),
                &registry,
                &runtime_config,
            )
            .await;

            // Cleanup: remove from registry, then grace period
            registry.remove(&sandbox_external_id);

            // Stamp disconnected_at so the fallback sweeper can reap this
            // sandbox after the grace window if no reconnect arrives. Best
            // effort — a failure here means the sweeper waits for
            // idle_timeout / hard_timeout instead. Idempotent: if the
            // marker is already set, this is a no-op (we want the earliest
            // disconnect timestamp).
            let _ = queries::mark_bridge_disconnected(&pool, sandbox_db_id).await;

            // M2 fix: Release the connection permit before entering the 120s
            // grace period. Without this, batch disconnects can exhaust the
            // connection semaphore for 2 minutes even though the gRPC stream
            // is already closed.
            drop(_conn_permit);

            // Spawn grace period cleanup (120s reconnect window)
            let registry_for_grace = registry.clone();
            probe_and_grace_period_cleanup(
                &pool,
                sandbox_db_id,
                linked_session_id,
                failure_ejected,
                &registry_for_grace,
                Some(&queue),
                redis_coord.as_deref(),
                &config,
            )
            .await;

            if let Some(sid) = linked_session_id {
                memory_subscribers.unregister(sid, sandbox_db_id).await;
            }

            info!(sandbox_id = %sandbox_external_id, "Runner disconnected, cleanup complete");
        }); // end of outer tokio::spawn

        Ok(Response::new(
            Box::pin(outbound.map(Ok)) as Self::SessionStream
        ))
    }
}

// ---------------------------------------------------------------------------
// Multi-task loop
// ---------------------------------------------------------------------------

async fn multi_task_loop(
    inbound: &mut Streaming<RunnerMessage>,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    event_bus: &EventBus,
    queue: &TaskQueue,
    config: &JoySafeterConfig,
    sandbox_provider: &Arc<dyn SandboxProvider>,
    sandbox_db_id: Uuid,
    sandbox_external_id: &str,
    linked_session_id: Option<Uuid>,
    exec_sem: &Arc<Semaphore>,
    redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_registry: &BridgeRegistry,
    runtime_config: &RuntimeConfig,
) -> bool {
    let hb_sec = runtime_config.heartbeat_timeout_sec();
    let heartbeat_timeout = Duration::from_secs(if hb_sec > 0 {
        hb_sec
    } else {
        HEARTBEAT_TIMEOUT_DEFAULT
    });
    let mut heartbeat_deadline = Instant::now() + heartbeat_timeout;
    let mut consecutive_failures: u32 = 0;
    let mut idle_wait = Duration::from_secs(1);

    info!(sandbox_id = %sandbox_external_id, "Entering multi-task loop");

    loop {
        // Check if this bridge was displaced by a reconnecting runner.
        // If so, exit immediately — the new connection takes over.
        if bridge.displaced.load(std::sync::atomic::Ordering::Acquire) {
            info!(sandbox_id = %sandbox_external_id, "Bridge displaced by reconnect, exiting multi-task loop");
            return false;
        }

        // Try to claim a task from DB
        let task_id = match queries::claim_next_sandbox_task(
            pool,
            sandbox_db_id,
            &config.instance_id,
            config.task_lease_ttl_sec,
        )
        .await
        {
            Ok(Some(task)) => Some(task.id),
            _ => None,
        };

        let task_id = match task_id {
            Some(id) => {
                idle_wait = Duration::from_secs(1); // reset backoff on hit
                id
            }
            None => {
                // Wait for wakeup or heartbeat or stream message
                tokio::select! {
                    _ = bridge.task_available.notified() => {
                        match queries::claim_next_sandbox_task(
                            pool,
                            sandbox_db_id,
                            &config.instance_id,
                            config.task_lease_ttl_sec,
                        )
                        .await
                        {
                            Ok(Some(task)) => {
                                idle_wait = Duration::from_secs(1);
                                task.id
                            }
                            _ => continue,
                        }
                    }
                    msg = inbound.message() => {
                        match msg {
                            Ok(Some(runner_msg)) => {
                                match &runner_msg.payload {
                                    Some(runner_message::Payload::Heartbeat(heartbeat)) => {
                                        heartbeat_deadline = Instant::now() + heartbeat_timeout;
                                        bridge
                                            .record_runner_heartbeat(
                                                &heartbeat.runtime_state,
                                                heartbeat.active_task_id.clone(),
                                                heartbeat.session_id.clone(),
                                            )
                                            .await;
                                        // Heartbeats no longer touch last_used_at:
                                        // the idle sweep drives off idle_since
                                        // (set by RunnerIdle, precise even with
                                        // background sub-agents) plus a bridge-
                                        // disconnect / hard-timeout fallback, so
                                        // we don't need a per-heartbeat write.
                                        // This removes the row bloat on long-
                                        // running sandboxes.
                                    }
                                    Some(runner_message::Payload::Result(result))
                                        if is_setup_failure_result(result) =>
                                    {
                                        mark_idle_setup_failure(
                                            pool,
                                            bridge,
                                            sandbox_db_id,
                                            result,
                                        )
                                        .await;
                                        return true;
                                    }
                                    Some(runner_message::Payload::SandboxFileResponse(response)) => {
                                        if !bridge
                                            .complete_sandbox_file_response(response.clone())
                                            .await
                                        {
                                            debug!(sandbox_id = %sandbox_db_id, "Received unmatched sandbox file response while idle");
                                        }
                                    }
                                    Some(other) => {
                                        debug!(payload = ?other, "Ignoring runner message while idle");
                                    }
                                    None => {}
                                }
                                continue;
                            }
                            Ok(None) => {
                                info!(sandbox_id = %sandbox_external_id, "Stream closed during idle");
                                return false;
                            }
                            Err(_) => return false,
                        }
                    }
                    _ = tokio::time::sleep_until(heartbeat_deadline) => {
                        warn!(sandbox_id = %sandbox_external_id, "Heartbeat timeout while idle");
                        return false;
                    }
                    _ = tokio::time::sleep(idle_wait) => {
                        // Backoff: try claim again
                        idle_wait = std::cmp::min(
                            Duration::from_millis((idle_wait.as_millis() as u64 * 3) / 2),
                            Duration::from_secs(5),
                        );
                        continue;
                    }
                }
            }
        };

        info!(task_id = %task_id, sandbox_id = %sandbox_external_id, "Dispatching task");

        // #17: Acquire execution semaphore (blocking, matching Python L1014)
        // G2 fix: handle closed semaphore gracefully instead of panic
        let _exec_permit = match exec_sem.clone().acquire_owned().await {
            Ok(p) => p,
            Err(_) => {
                warn!(task_id = %task_id, "Execution semaphore closed, ejecting task");
                if let Ok(Some(task)) = queries::get_task(pool, task_id).await {
                    handle_dispatch_retryable_failure(
                        pool,
                        event_bus,
                        &task,
                        task.session_id.or(linked_session_id),
                        sandbox_db_id,
                        task.owner_epoch,
                        "Execution semaphore closed before StartTask",
                        Some(queue),
                    )
                    .await;
                }
                return false;
            }
        };

        // Get task details
        let task = match queries::get_task(pool, task_id).await {
            Ok(Some(t)) => t,
            _ => continue,
        };

        // Defensive check: task must be in RUNNING status (Python L1142)
        if task.status != "running" {
            warn!(
                task_id = %task_id,
                status = %task.status,
                "Task not in running status after claim, skipping dispatch"
            );
            continue;
        }
        let task_owner_epoch = task.owner_epoch;

        // Set task on bridge only after the DB task row still says it should run.
        *bridge.current_task_owner_epoch.lock().await = task_owner_epoch;
        *bridge.current_task_id.lock().await = Some(task_id);
        match queries::start_sandbox_task(pool, sandbox_db_id, task_id).await {
            Ok(true) => {}
            Ok(false) => {
                warn!(
                    task_id = %task_id,
                    sandbox_id = %sandbox_db_id,
                    "Sandbox is not dispatchable; retrying or failing task before StartTask"
                );
                *bridge.current_task_id.lock().await = None;
                *bridge.current_task_owner_epoch.lock().await = None;
                handle_dispatch_retryable_failure(
                    pool,
                    event_bus,
                    &task,
                    task.session_id.or(linked_session_id),
                    sandbox_db_id,
                    task_owner_epoch,
                    "Sandbox is not dispatchable before StartTask",
                    Some(queue),
                )
                .await;
                continue;
            }
            Err(e) => {
                error!(
                    task_id = %task_id,
                    sandbox_id = %sandbox_db_id,
                    error = %e,
                    "Failed to mark sandbox running for StartTask"
                );
                *bridge.current_task_id.lock().await = None;
                *bridge.current_task_owner_epoch.lock().await = None;
                handle_dispatch_retryable_failure(
                    pool,
                    event_bus,
                    &task,
                    task.session_id.or(linked_session_id),
                    sandbox_db_id,
                    task_owner_epoch,
                    "Failed to mark sandbox running before StartTask",
                    Some(queue),
                )
                .await;
                continue;
            }
        }

        // Redis: register task→sandbox mapping (Python L1107)
        if let Some(coord) = redis_coord {
            let _ = coord.map_task_to_sandbox(task_id, sandbox_db_id).await;
        }

        let session_id = task.session_id.or(linked_session_id);

        // #8: Check agent exists before dispatch (Python L1133-1140)
        if let Some(agent_id) = task.agent_id {
            if queries::get_agent(pool, agent_id)
                .await
                .ok()
                .flatten()
                .is_none()
            {
                error!(task_id = %task_id, agent_id = %agent_id, "Agent not found, marking task FAILED");
                fail_pre_start_task(
                    pool,
                    event_bus,
                    task_id,
                    task_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    "Agent not found",
                )
                .await;
                *bridge.current_task_id.lock().await = None;
                *bridge.current_task_owner_epoch.lock().await = None;
                continue;
            }
        }

        // Send SetupSandbox if not done yet (pool containers)
        if !bridge.setup_done.load(Ordering::Relaxed) {
            match send_setup(pool, bridge, sandbox_db_id, tx).await {
                Ok(true) => bridge.setup_done.store(true, Ordering::Relaxed),
                Ok(false) if session_id.is_none() => {
                    bridge.setup_done.store(true, Ordering::Relaxed)
                }
                Ok(false) => {
                    error!(
                        task_id = %task_id,
                        sandbox_id = %sandbox_db_id,
                        "Failed to send SetupSandbox because linked session was unavailable"
                    );
                    fail_pre_start_task(
                        pool,
                        event_bus,
                        task_id,
                        task_owner_epoch,
                        session_id,
                        sandbox_db_id,
                        "Failed to send SetupSandbox: linked session unavailable",
                    )
                    .await;
                    *bridge.current_task_id.lock().await = None;
                    *bridge.current_task_owner_epoch.lock().await = None;
                    continue;
                }
                Err(e) => {
                    let reason = format!("Failed to send SetupSandbox: {e}");
                    error!(
                        task_id = %task_id,
                        sandbox_id = %sandbox_db_id,
                        "Failed to send SetupSandbox, marking task failed: {e}",
                    );
                    fail_pre_start_task(
                        pool,
                        event_bus,
                        task_id,
                        task_owner_epoch,
                        session_id,
                        sandbox_db_id,
                        &reason,
                    )
                    .await;
                    *bridge.current_task_id.lock().await = None;
                    *bridge.current_task_owner_epoch.lock().await = None;
                    continue;
                }
            }
        }

        if let Err(e) = inject_session_files_before_start(
            pool,
            sandbox_provider,
            bridge,
            sandbox_external_id,
            session_id,
        )
        .await
        {
            error!(
                task_id = %task_id,
                sandbox_id = %sandbox_db_id,
                "Failed to inject session files before StartTask, marking task failed: {e}"
            );
            let reason = format!("Failed to inject session files before StartTask: {e}");
            fail_pre_start_task(
                pool,
                event_bus,
                task_id,
                task_owner_epoch,
                session_id,
                sandbox_db_id,
                &reason,
            )
            .await;
            *bridge.current_task_id.lock().await = None;
            *bridge.current_task_owner_epoch.lock().await = None;
            continue;
        }

        // Build and send StartTask (full field resolution from DB)
        let start_task = match build_start_task_full(pool, &task, sandbox_db_id, config).await {
            Ok(start_task) => start_task,
            Err(e) => {
                let reason = format!("Failed to build harness input before StartTask: {e}");
                error!(
                    task_id = %task_id,
                    sandbox_id = %sandbox_db_id,
                    "{reason}"
                );
                fail_pre_start_task(
                    pool,
                    event_bus,
                    task_id,
                    task_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    &reason,
                )
                .await;
                *bridge.current_task_id.lock().await = None;
                *bridge.current_task_owner_epoch.lock().await = None;
                if let Some(coord) = redis_coord {
                    let _ = coord.remove_task_sandbox(task_id).await;
                }
                continue;
            }
        };
        let msg = OrchestratorMessage {
            payload: Some(orchestrator_message::Payload::Start(start_task)),
        };
        if !send_start_task_or_handle_failure(
            pool,
            event_bus,
            tx,
            &task,
            session_id,
            sandbox_db_id,
            msg,
            Some(queue),
        )
        .await
        {
            *bridge.current_task_id.lock().await = None;
            *bridge.current_task_owner_epoch.lock().await = None;
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(task_id).await;
            }
            return false;
        }
        info!(task_id = %task_id, "StartTask sent");

        let _ = emit_session_running_status(
            pool,
            event_bus,
            task_id,
            session_id,
            sandbox_db_id,
            "multi_task_start",
        )
        .await;

        // G1 fix: get a snapshot of the current cancel token for this task.
        // reset_cancel() creates a fresh token so previous cancellations don't
        // leak into the next task.
        bridge.reset_cancel().await;
        let task_cancel = bridge.current_cancel_token().await;

        // Run the task event loop
        let result = run_single_task(
            inbound,
            tx,
            bridge,
            pool,
            event_bus,
            config,
            task_id,
            task_owner_epoch,
            session_id,
            sandbox_db_id,
            heartbeat_timeout,
            memory_subscribers.clone(),
            bridge_registry,
            &task_cancel,
            Some(queue),
        )
        .await;

        // Clear task on bridge
        *bridge.current_task_id.lock().await = None;
        *bridge.current_task_owner_epoch.lock().await = None;
        bridge
            .requires_action_pending
            .store(false, Ordering::Relaxed);
        bridge.reset_confirmation();
        let setup_failure = is_setup_failure_task_result(&result);
        if !matches!(result, TaskResult::Disconnected) && !setup_failure {
            if let Err(e) =
                crate::sandbox::artifacts::archive_task_artifacts(pool, bridge, task_id, session_id)
                    .await
            {
                warn!(task_id = %task_id, error = %e, "Failed to archive task artifacts");
            }
        }
        if !setup_failure {
            let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;
        }
        heartbeat_deadline = Instant::now() + heartbeat_timeout;

        // Remove task→sandbox mapping from Redis + publish complete event (Python L1876-1886)
        if let Some(coord) = redis_coord {
            // Publish "complete" event to Redis (Python L1876-1881: direct payload string)
            let complete_payload =
                serde_json::to_string(&json!({"type": "complete", "task_id": task_id.to_string()}))
                    .unwrap_or_default();
            let _ = coord.publish_task_event(task_id, &complete_payload).await;
            let _ = coord.remove_task_sandbox(task_id).await;
            // Refresh sandbox owner TTL (Python L1685)
            let _ = coord.refresh_sandbox(sandbox_db_id).await;
        }

        match result {
            TaskResult::Completed => {
                consecutive_failures = 0;
                *bridge.last_error.lock().await = None;
                info!(task_id = %task_id, "Task completed successfully");
            }
            TaskResult::Failed(ref reason) if is_setup_failure_error(reason) => {
                warn!(task_id = %task_id, "SetupSandbox failed during task dispatch: {reason}");
                return true;
            }
            TaskResult::Failed(ref reason) => {
                consecutive_failures += 1;
                *bridge.last_error.lock().await = Some(reason.clone());
                warn!(task_id = %task_id, failures = consecutive_failures, "Task failed: {reason}");
            }
            TaskResult::Timeout => {
                consecutive_failures += 1;
                warn!(task_id = %task_id, "Task timed out");
            }
            TaskResult::Cancelled => {
                info!(task_id = %task_id, "Task cancelled");
            }
            TaskResult::Disconnected => {
                warn!(task_id = %task_id, "Runner disconnected during task");
                return false;
            }
        }

        // Ejection check
        if consecutive_failures >= runtime_config.sandbox_failure_threshold() {
            warn!(
                sandbox_id = %sandbox_external_id,
                failures = consecutive_failures,
                "Sandbox exceeded failure threshold, ejecting"
            );
            return true; // failure_ejected
        }
    }
}

/// Result of a single task execution.
#[derive(Clone, Debug)]
enum TaskResult {
    Completed,
    Failed(String),
    Timeout,
    Cancelled,
    Disconnected,
}

#[derive(Default)]
struct TaskMessageOutcome {
    task_done: bool,
    runner_idle_seen: bool,
    terminal_idle_handled: bool,
    task_result: Option<TaskResult>,
}

// ---------------------------------------------------------------------------
// Single task event loop — with HITL support
// ---------------------------------------------------------------------------

async fn run_single_task(
    inbound: &mut Streaming<RunnerMessage>,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    event_bus: &EventBus,
    config: &JoySafeterConfig,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    heartbeat_timeout: Duration,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_registry: &BridgeRegistry,
    task_cancel: &tokio_util::sync::CancellationToken,
    queue: Option<&TaskQueue>,
) -> TaskResult {
    // I-NEW-2 fix: use per-task timeout_sec if set, else global default (matching Python)
    let timeout_secs = match queries::get_task(pool, task_id).await {
        Ok(Some(t)) => t.timeout_sec.unwrap_or(config.task_default_timeout as i32) as u64,
        _ => config.task_default_timeout,
    };

    // #38: Extract custom_names/mcp_names from agent for event routing
    let (custom_names, mcp_names) = if let Ok(Some(task)) = queries::get_task(pool, task_id).await {
        let session = match task.session_id {
            Some(sid) => queries::get_session(pool, sid).await.ok().flatten(),
            None => None,
        };
        let live_agent = match task.agent_id {
            Some(aid) => queries::get_agent(pool, aid).await.ok().flatten(),
            None => None,
        };
        if let Some(agent) =
            crate::kernel::run_spec::agent_for_execution(live_agent, session.as_ref())
        {
            crate::kernel::harness_input_builder::extract_tool_name_sets(&agent)
        } else {
            (
                std::collections::HashSet::new(),
                std::collections::HashSet::new(),
            )
        }
    } else {
        (
            std::collections::HashSet::new(),
            std::collections::HashSet::new(),
        )
    };

    let mut heartbeat_deadline = Instant::now() + heartbeat_timeout;
    let mut task_deadline = Instant::now() + Duration::from_secs(timeout_secs);
    let mut requires_action_pending = false;
    let mut buffered_events: Vec<(String, serde_json::Value)> = Vec::new();
    let mut task_done = false;
    let mut runner_idle_seen = false;
    let mut terminal_idle_handled = false;
    let mut authoritative_result: Option<TaskResult> = None;
    let mut task_completed = false;
    let mut task_error = false;
    let mut cancel_sent = false;

    loop {
        // Build select branches based on HITL state
        tokio::select! {
            // Cancel signal (per-task token — does not poison the bridge)
            // Guard: only fire once to prevent duplicate CancelTask/status_idle events
            _ = task_cancel.cancelled(), if !cancel_sent => {
                cancel_sent = true;
                info!(task_id = %task_id, "Cancel requested, sending CancelTask and waiting for Result+Idle");
                let cancel_msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Cancel(
                        proto::CancelTask { reason: "Cancelled by user".to_string() }
                    )),
                };
                let _ = tx.send(cancel_msg).await;
                let transitioned = transition_running_task_and_emit_idle(
                    pool,
                    event_bus,
                    task_id,
                    expected_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    "cancelled",
                    None,
                    json!({"type": "cancelled"}),
                    "cancel request",
                )
                .await;
                if transitioned {
                    authoritative_result = Some(TaskResult::Cancelled);
                    terminal_idle_handled = true;
                } else if let Some(result) = load_terminal_task_result(pool, task_id).await {
                    authoritative_result = Some(result);
                    terminal_idle_handled = true;
                }
                // Don't return — continue loop to drain runner's Result+Idle.
                continue;
            }

            // HITL confirmation (only when requires_action_pending)
            _ = bridge.wait_confirmation(), if requires_action_pending => {
                info!(task_id = %task_id, "HITL confirmation received, resuming");
                requires_action_pending = false;
                bridge.requires_action_pending.store(false, Ordering::Relaxed);
                bridge.reset_confirmation();

                // Drain control queue and send as SendInput
                {
                    let mut ctrl_rx = bridge.control_rx.lock().await;
                    while let Ok(content) = ctrl_rx.try_recv() {
                        let input_msg = OrchestratorMessage {
                            payload: Some(orchestrator_message::Payload::Input(
                                proto::SendInput { content }
                            )),
                        };
                        let _ = tx.send(input_msg).await;
                    }
                }

                let _ = emit_session_running_status(
                    pool,
                    event_bus,
                    task_id,
                    session_id,
                    sandbox_db_id,
                    "hitl_resume",
                )
                .await;

                // Flush buffered events
                if let Some(sid) = session_id {
                    for (event_type, payload) in buffered_events.drain(..) {
                        let envelope = EventEnvelope::new(sid, event_type, payload)
                            .with_task(task_id).with_sandbox(sandbox_db_id);
                        event_bus.publish(envelope).await;
                    }
                }
                buffered_events.clear();

                // Resume deadline
                task_deadline = Instant::now() + Duration::from_secs(timeout_secs);
                continue;
            }

            // Task deadline (only when NOT in HITL)
            _ = tokio::time::sleep_until(task_deadline), if !requires_action_pending => {
                warn!(task_id = %task_id, timeout = timeout_secs, "Task deadline exceeded");
                let cancel_msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Cancel(
                        proto::CancelTask { reason: format!("Server-side deadline exceeded ({timeout_secs}s)") }
                    )),
                };
                let _ = tx.send(cancel_msg).await;
                let timeout_error = format!("Task timed out after {timeout_secs}s");
                let stop_reason = json!({"type": "timeout"});
                let transitioned = transition_running_task_and_emit_idle(
                    pool,
                    event_bus,
                    task_id,
                    expected_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    "timeout",
                    Some(&timeout_error),
                    stop_reason,
                    "task deadline",
                )
                .await;
                if transitioned {
                    return TaskResult::Timeout;
                }
                if let Some(result) = authoritative_result.clone() {
                    return result;
                }
                if let Some(result) = load_terminal_task_result(pool, task_id).await {
                    return result;
                }
                return TaskResult::Timeout;
            }

            // #18: Heartbeat timeout — flush + failover_or_fail (Python L1367-1383)
            // Skip heartbeat timeout during HITL pause — runner is idle waiting
            // for user input and may legitimately stop heartbeating.
            _ = tokio::time::sleep_until(heartbeat_deadline) => {
                if requires_action_pending {
                    // HITL active: runner is waiting for user, not dead.
                    // Reset heartbeat deadline and keep waiting.
                    heartbeat_deadline = Instant::now() + heartbeat_timeout;
                    continue;
                }
                if let Some(result) = authoritative_result.clone() {
                    bridge.remove_task_subscribers(task_id).await;
                    return result;
                }
                if let Some(result) = load_terminal_task_result(pool, task_id).await {
                    bridge.remove_task_subscribers(task_id).await;
                    return result;
                }
                warn!(task_id = %task_id, "Heartbeat timeout during task");
                event_bus.flush().await;
                failover_or_fail_inline(
                    pool,
                    event_bus,
                    task_id,
                    expected_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    "Heartbeat timeout — sandbox unresponsive",
                    queue,
                )
                .await;
                bridge.remove_task_subscribers(task_id).await;
                return TaskResult::Disconnected;
            }

            // Incoming message from runner
            msg = inbound.message() => {
                // Check displaced before processing — a reconnect may have
                // replaced this bridge while we were waiting for a message.
                if bridge.displaced.load(std::sync::atomic::Ordering::Acquire) {
                    info!(task_id = %task_id, "Bridge displaced during task, aborting");
                    return TaskResult::Disconnected;
                }
                match msg {
                    Ok(Some(runner_msg)) => {
                        heartbeat_deadline = Instant::now() + heartbeat_timeout;
                        let outcome = handle_task_message(
                            &runner_msg, pool, event_bus, bridge,
                            task_id, expected_owner_epoch, session_id, sandbox_db_id, tx,
                            &mut requires_action_pending,
                            &mut buffered_events,
                            &mut task_completed, &mut task_error,
                            &custom_names, &mcp_names,
                            memory_subscribers.clone(), bridge_registry,
                            config.grpc_max_memories_per_store,
                        ).await;
                        if outcome.task_done { task_done = true; }
                        if outcome.runner_idle_seen { runner_idle_seen = true; }
                        if outcome.terminal_idle_handled { terminal_idle_handled = true; }
                        if outcome.task_result.is_some() {
                            authoritative_result = outcome.task_result;
                        }
                        if task_done { break; }
                    }
                    Ok(None) => {
                        info!(task_id = %task_id, "Stream closed during task");
                        if !task_done {
                            if let Some(result) = authoritative_result.clone() {
                                bridge.remove_task_subscribers(task_id).await;
                                return result;
                            }
                            if let Some(result) = load_terminal_task_result(pool, task_id).await {
                                bridge.remove_task_subscribers(task_id).await;
                                return result;
                            }
                            return handle_task_disconnect_before_result(
                                pool,
                                event_bus,
                                bridge,
                                task_id,
                                expected_owner_epoch,
                                session_id,
                                sandbox_db_id,
                                "Sandbox disconnected unexpectedly",
                                queue,
                            )
                            .await;
                        }
                        return TaskResult::Disconnected;
                    }
                    Err(e) => {
                        error!(task_id = %task_id, "Stream error: {e}");
                        if let Some(result) = authoritative_result.clone() {
                            bridge.remove_task_subscribers(task_id).await;
                            return result;
                        }
                        if let Some(result) = load_terminal_task_result(pool, task_id).await {
                            bridge.remove_task_subscribers(task_id).await;
                            return result;
                        }
                        let reason = format!("Sandbox stream error: {e}");
                        return handle_task_disconnect_before_result(
                            pool,
                            event_bus,
                            bridge,
                            task_id,
                            expected_owner_epoch,
                            session_id,
                            sandbox_db_id,
                            &reason,
                            queue,
                        )
                        .await;
                    }
                }
            }
        }
    }

    // Post-task handling (matches Python lines 1737-1802)
    if !task_done {
        // #18: Stream broke before result — failover_or_fail (Python L1746)
        event_bus.flush().await;
        let last_err = bridge.last_error.lock().await.clone();
        let reason = last_err
            .as_deref()
            .map(|e| format!("Sandbox disconnected unexpectedly (last error: {e})"))
            .unwrap_or_else(|| "Sandbox disconnected unexpectedly".to_string());
        failover_or_fail_inline(
            pool,
            event_bus,
            task_id,
            expected_owner_epoch,
            session_id,
            sandbox_db_id,
            &reason,
            queue,
        )
        .await;
        bridge.remove_task_subscribers(task_id).await;
        return TaskResult::Disconnected;
    }

    if task_done && !runner_idle_seen && !terminal_idle_handled {
        // Got result but runner didn't send idle — emit session idle event
        bridge.remove_task_subscribers(task_id).await;
        let stop_reason = if task_error {
            json!({"type": "error", "message": "Task failed"})
        } else {
            json!({"type": "end_turn"})
        };
        emit_session_idle_status(
            pool,
            event_bus,
            task_id,
            session_id,
            sandbox_db_id,
            stop_reason,
            "post-task fallback",
        )
        .await;
    }

    if let Some(result) = authoritative_result {
        result
    } else if task_completed {
        TaskResult::Completed
    } else if task_error {
        let reason = bridge
            .last_result_error
            .lock()
            .await
            .clone()
            .unwrap_or_else(|| "Task ended in error state".to_string());
        TaskResult::Failed(reason)
    } else {
        TaskResult::Completed
    }
}

/// Handle a single message during task execution.
async fn handle_task_message(
    msg: &RunnerMessage,
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    _tx: &mpsc::Sender<OrchestratorMessage>,
    requires_action_pending: &mut bool,
    buffered_events: &mut Vec<(String, serde_json::Value)>,
    task_completed: &mut bool,
    task_error: &mut bool,
    custom_names: &std::collections::HashSet<String>,
    mcp_names: &std::collections::HashSet<String>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_registry: &BridgeRegistry,
    max_memories_per_store: i64,
) -> TaskMessageOutcome {
    let payload = match &msg.payload {
        Some(p) => p,
        None => return TaskMessageOutcome::default(),
    };

    match payload {
        runner_message::Payload::Event(harness_event) => {
            if let Some(sid) = session_id {
                if let Some((event_type, payload)) =
                    mapping::map_harness_event(harness_event, Some(custom_names), Some(mcp_names))
                {
                    // Check for HITL control_request
                    let is_ctrl = mapping::is_control_request(harness_event);
                    let is_custom_tool = event_type == "agent.custom_tool_use";

                    // Update bridge.last_error on error events (Python L1461-1462)
                    if event_type == "session.error" {
                        let error_msg = payload
                            .get("error")
                            .and_then(|e| e.get("message"))
                            .and_then(|m| m.as_str())
                            .or_else(|| payload.get("message").and_then(|m| m.as_str()))
                            .unwrap_or("unknown error");
                        *bridge.last_error.lock().await = Some(error_msg.to_string());
                    }

                    if *requires_action_pending {
                        // Buffer events during HITL pause
                        if buffered_events.len() < 1000 {
                            buffered_events.push((event_type, payload));
                        }
                        return TaskMessageOutcome::default();
                    }

                    if is_ctrl || is_custom_tool {
                        // Enter HITL mode
                        let event_id = Uuid::now_v7();
                        let call_id = payload
                            .get("call_id")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();

                        // Persist immediately
                        let envelope = EventEnvelope::new(sid, &event_type, payload.clone())
                            .with_task(task_id)
                            .with_sandbox(sandbox_db_id)
                            .with_runner_seq(harness_event.seq as i64);
                        let mut env = envelope;
                        env.event_id = Some(event_id);
                        env.flush_immediately = true;
                        event_bus.publish(env).await;

                        // Track call_id → event_id
                        if !call_id.is_empty() {
                            bridge
                                .pending_control_request_ids
                                .lock()
                                .await
                                .insert(call_id, event_id);
                        }

                        // Set HITL state
                        *requires_action_pending = true;
                        bridge
                            .requires_action_pending
                            .store(true, Ordering::Relaxed);

                        // Emit session.status_idle with requires_action stop_reason
                        let stop_reason = json!({
                            "type": "requires_action",
                            "event_ids": [format!("evt_{event_id}")]
                        });
                        let payload = json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
                        let inserted = queries::update_session_status_and_insert_event(
                            pool,
                            sid,
                            "idle",
                            Some(&stop_reason),
                            "session.status_idle",
                            &payload,
                        )
                        .await
                        .ok()
                        .flatten();
                        if let Some((event_id, seq)) = inserted {
                            let envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                                .with_task(task_id)
                                .with_sandbox(sandbox_db_id)
                                .status_change(Some(stop_reason.clone()))
                                .with_db_persisted(event_id, seq);
                            event_bus.publish(envelope).await;
                        }

                        return TaskMessageOutcome::default();
                    }

                    // Normal event: publish through event bus
                    let is_status_event = event_type.starts_with("session.status_");
                    // Background sub-agent activity no longer touches
                    // last_used_at — idle_since (set by RunnerIdle) is the
                    // authoritative idle anchor now, and RunnerIdle is held
                    // back by the runtime until all background agents finish
                    // (cc: heldBackResult; codex multi-agent: aggregated
                    // child threads), so a sandbox can't be reaped mid-run.
                    let stop_reason = payload.get("stop_reason").cloned();
                    let mut envelope = EventEnvelope::new(sid, event_type, payload)
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .with_runner_seq(harness_event.seq as i64);
                    if is_status_event {
                        envelope = envelope.status_change(stop_reason);
                    }
                    event_bus.publish(envelope).await;
                }
            }
            TaskMessageOutcome::default()
        }

        runner_message::Payload::Result(harness_result) => {
            if is_setup_failure_result(harness_result) {
                return handle_task_setup_failure_result(
                    harness_result,
                    pool,
                    event_bus,
                    bridge,
                    task_id,
                    expected_owner_epoch,
                    session_id,
                    sandbox_db_id,
                    task_error,
                )
                .await;
            }

            let status = harness_result.status.as_str();
            match status {
                "completed" => *task_completed = true,
                "failed" | "aborted" | "timeout" => *task_error = true,
                _ => *task_error = true,
            }

            // Build usage JSON with correct field mapping
            let usage: Option<serde_json::Value> = harness_result.usage.as_ref().map(|u| {
                let by_model: serde_json::Map<String, serde_json::Value> = u
                    .by_model
                    .iter()
                    .map(|entry| {
                        (
                            entry.model.clone(),
                            json!({
                                "input_tokens": entry.input_tokens,
                                "output_tokens": entry.output_tokens,
                                "cache_creation_input_tokens": entry.cache_write_tokens,
                                "cache_read_input_tokens": entry.cache_read_tokens,
                            }),
                        )
                    })
                    .collect();

                json!({
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cache_creation_input_tokens": u.cache_write_tokens,
                    "cache_read_input_tokens": u.cache_read_tokens,
                    "by_model": by_model,
                })
            });

            let runner_task_result =
                task_result_from_status(status, harness_result.error.as_deref()).unwrap_or_else(
                    || {
                        TaskResult::Failed(
                            harness_result.error.clone().unwrap_or_else(|| {
                                "Task ended in unknown result state".to_string()
                            }),
                        )
                    },
                );

            // CAS task completion — only update output/usage if CAS succeeds (Python L1831-1849)
            let cas_result = if harness_result.error.is_some() {
                queries::transition_task_cas(
                    pool,
                    task_id,
                    "running",
                    status,
                    harness_result.error.as_deref(),
                    expected_owner_epoch,
                )
                .await
            } else {
                queries::transition_task_cas(
                    pool,
                    task_id,
                    "running",
                    status,
                    None,
                    expected_owner_epoch,
                )
                .await
            };
            let cas_ok = match cas_result {
                Ok(true) => true,
                Ok(false) => {
                    warn!(task_id = %task_id, "CAS conflict: task already terminal, ignoring runner result");
                    false
                }
                Err(error) => {
                    error!(task_id = %task_id, error = %error, "Failed to transition task from runner result");
                    false
                }
            };

            if cas_ok {
                let _ = queries::complete_task(
                    pool,
                    task_id,
                    status,
                    Some(&harness_result.output),
                    harness_result.error.as_deref(),
                    usage.as_ref(),
                )
                .await;
            }
            let task_result = if cas_ok {
                runner_task_result.clone()
            } else {
                load_terminal_task_result(pool, task_id)
                    .await
                    .unwrap_or_else(|| runner_task_result.clone())
            };

            // sandbox_svc.complete_task — update sandbox status + clear last_task_id (Python L1852)
            let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

            // Accumulate session usage
            if let (Some(sid), Some(ref usage_val)) = (session_id, &usage) {
                let _ = queries::accumulate_session_usage(pool, sid, usage_val).await;
            }

            // The runner usually streams the final answer as agent.message before Result.
            // Some adapters only include the final text in Result.output; in that case,
            // persist one fallback agent.message so the session conversation is not empty.
            if cas_ok && !harness_result.output.trim().is_empty() {
                if let Some(sid) = session_id {
                    let payload = json!({
                        "content": [{"type": "text", "text": harness_result.output}],
                        "task_id": task_id.to_string(),
                    });
                    match queries::insert_agent_message_from_task_output_if_missing(
                        pool, sid, task_id, &payload,
                    )
                    .await
                    {
                        Ok(Some((event_id, seq))) => {
                            let envelope = EventEnvelope::new(sid, "agent.message", payload)
                                .with_task(task_id)
                                .with_sandbox(sandbox_db_id)
                                .with_db_persisted(event_id, seq);
                            event_bus.publish(envelope).await;
                        }
                        Ok(None) => {}
                        Err(error) => {
                            error!(
                                task_id = %task_id,
                                session_id = %sid,
                                error = %error,
                                "Failed to persist fallback agent.message from task output"
                            );
                        }
                    }
                }
            }

            if cas_ok {
                event_bus.flush().await;
            }

            // Store result info for idle handler
            *bridge.last_result_status.lock().await = Some(status.to_string());
            *bridge.last_result_error.lock().await = harness_result.error.clone();

            // Broadcast "complete" to per-task WebSocket subscribers (Python L1871-1873)
            let result_payload = json!({
                "type": "complete",
                "status": status,
                "output": harness_result.output,
                "error": harness_result.error,
                "duration_ms": harness_result.duration_ms,
            });
            bridge.broadcast_to_task(task_id, result_payload).await;

            // Remove task subscribers
            bridge.remove_task_subscribers(task_id).await;

            if cas_ok {
                let stop_reason = if *task_error {
                    json!({"type": "error", "message": "Task failed"})
                } else {
                    json!({"type": "end_turn"})
                };
                emit_session_idle_status(
                    pool,
                    event_bus,
                    task_id,
                    session_id,
                    sandbox_db_id,
                    stop_reason,
                    "runner result",
                )
                .await;
            }

            info!(task_id = %task_id, status = status, "Task result received");
            TaskMessageOutcome {
                task_done: true,
                terminal_idle_handled: true,
                task_result: Some(task_result),
                ..Default::default()
            }
        }

        runner_message::Payload::Idle(idle_msg) => {
            bridge
                .record_runner_heartbeat("idle", None, idle_msg.session_id.clone())
                .await;

            // Update sandbox DB status
            let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

            // Update session sandbox info
            if let Some(sid) = session_id {
                let harness_session_id = idle_msg.session_id.as_deref();
                let work_dir = idle_msg.work_dir.as_deref();
                let _ = queries::update_session_sandbox_info(
                    pool,
                    sid,
                    sandbox_db_id,
                    harness_session_id,
                    work_dir,
                )
                .await;
            }

            // Flush event buffer before status change
            event_bus.flush().await;

            // Emit session.status_idle with computed stop_reason
            if let Some(sid) = session_id {
                if !bridge.requires_action_pending.load(Ordering::Relaxed) {
                    let last_status = bridge.last_result_status.lock().await.clone();
                    if last_status.is_none() {
                        debug!(task_id = %task_id, "Runner idle received before task result; keeping session running");
                        return TaskMessageOutcome {
                            runner_idle_seen: true,
                            ..Default::default()
                        };
                    }
                    let last_error = bridge.last_result_error.lock().await.clone();
                    let stop_reason =
                        compute_stop_reason(last_status.as_deref(), last_error.as_deref());

                    emit_session_idle_status(
                        pool,
                        event_bus,
                        task_id,
                        Some(sid),
                        sandbox_db_id,
                        stop_reason,
                        "runner idle",
                    )
                    .await;
                }
            }

            TaskMessageOutcome {
                runner_idle_seen: true,
                terminal_idle_handled: true,
                ..Default::default()
            }
        }

        runner_message::Payload::Heartbeat(heartbeat) => {
            bridge
                .record_runner_heartbeat(
                    &heartbeat.runtime_state,
                    heartbeat.active_task_id.clone(),
                    heartbeat.session_id.clone(),
                )
                .await;
            debug!(task_id = %task_id, "Heartbeat");
            TaskMessageOutcome::default()
        }

        runner_message::Payload::MemorySync(sync_msg) => {
            // Memory sync with path traversal protection + DB write
            let pool_clone = pool.clone();
            let memory_subscribers = memory_subscribers.clone();
            let bridge_registry = bridge_registry.clone();
            let session_id_clone = session_id;
            let mount_name = sync_msg.store_mount_name.clone();
            let rel_path = sync_msg.relative_path.clone();
            let content = sync_msg.content.clone();
            let operation = sync_msg.operation.clone();

            // Fire-and-forget DB write (matching Python's asyncio.create_task)
            tokio::spawn(async move {
                handle_memory_sync_db(
                    &pool_clone,
                    session_id_clone,
                    &mount_name,
                    &rel_path,
                    &content,
                    &operation,
                    max_memories_per_store,
                )
                .await;
                memory_subscribers
                    .notify_peers(
                        &mount_name,
                        &rel_path,
                        content.as_bytes(),
                        &operation,
                        sandbox_db_id,
                        &bridge_registry,
                    )
                    .await;
            });
            TaskMessageOutcome::default()
        }

        runner_message::Payload::SandboxFileResponse(response) => {
            if !bridge
                .complete_sandbox_file_response(response.clone())
                .await
            {
                debug!(task_id = %task_id, "Received unmatched sandbox file response");
            }
            TaskMessageOutcome::default()
        }

        runner_message::Payload::Ready(_) => {
            warn!(task_id = %task_id, "Unexpected RunnerReady during task");
            TaskMessageOutcome::default()
        }
    }
}

// ---------------------------------------------------------------------------
// Reconnect handling
// ---------------------------------------------------------------------------

fn payload_str<'a>(payload: &'a serde_json::Value, keys: &[&str]) -> Option<&'a str> {
    keys.iter()
        .find_map(|key| payload.get(*key).and_then(|value| value.as_str()))
        .filter(|value| !value.is_empty())
}

fn pending_control_live_input(
    event_type: &str,
    event_id: Uuid,
    payload: Option<&serde_json::Value>,
) -> Option<String> {
    let payload = payload?;
    let existing_content = payload.get("content").and_then(|value| value.as_str());
    if let Some(content) = existing_content.filter(|content| content.starts_with(LIVE_INPUT_PREFIX))
    {
        return Some(content.to_string());
    }

    let encoded = match event_type {
        "user.tool_confirmation" => {
            let call_id = payload_str(
                payload,
                &["call_id", "tool_use_call_id", "tool_use_id", "_call_id"],
            )?;
            let approved = payload
                .get("approved")
                .and_then(|value| value.as_bool())
                .or_else(|| {
                    payload
                        .get("result")
                        .and_then(|value| value.as_str())
                        .map(|value| value == "allow")
                })
                .unwrap_or(false);
            let mut body = json!({
                "type": "tool_confirmation",
                "tool_use_call_id": call_id,
                "approved": approved,
            });
            if let Some(deny_message) = payload_str(payload, &["deny_message"]) {
                body["deny_message"] = json!(deny_message);
            }
            serde_json::to_string(&body).ok()?
        }
        "user.custom_tool_result" => {
            let call_id = payload_str(
                payload,
                &["call_id", "tool_use_call_id", "tool_use_id", "_call_id"],
            )?;
            let content = existing_content.unwrap_or("");
            serde_json::to_string(&json!({
                "type": "custom_tool_result",
                "tool_use_call_id": call_id,
                "content": content,
            }))
            .ok()?
        }
        "user.interrupt" => serde_json::to_string(&json!({
            "type": "interrupt",
            "source_event_id": event_id.to_string(),
        }))
        .ok()?,
        _ => return None,
    };

    Some(format!("{LIVE_INPUT_PREFIX}{encoded}"))
}

async fn replay_pending_control_inputs(
    pool: &PgPool,
    session_id: Uuid,
    tx: &mpsc::Sender<OrchestratorMessage>,
    active_task_id: Uuid,
) -> Result<usize, sqlx::Error> {
    let pending: Vec<(Uuid, String, Option<serde_json::Value>)> = sqlx::query_as(
        r#"
        SELECT id, event_type, payload FROM joysafeter_session_events
        WHERE session_id = $1
          AND event_type IN ('user.tool_confirmation', 'user.custom_tool_result', 'user.interrupt')
          AND processed_at IS NULL
        ORDER BY created_at ASC, id ASC
        "#,
    )
    .bind(session_id)
    .fetch_all(pool)
    .await?;

    let mut replayed = 0usize;
    for (event_id, event_type, payload) in &pending {
        let Some(content) = pending_control_live_input(event_type, *event_id, payload.as_ref())
            .or_else(|| {
                payload
                    .as_ref()
                    .and_then(|value| value.get("content"))
                    .and_then(|value| value.as_str())
                    .filter(|value| !value.is_empty())
                    .map(str::to_string)
            })
        else {
            warn!(
                task_id = %active_task_id,
                event_id = %event_id,
                event_type = %event_type,
                "Skipping malformed pending control event without replayable input"
            );
            continue;
        };
        let input_msg = OrchestratorMessage {
            payload: Some(orchestrator_message::Payload::Input(proto::SendInput {
                content,
            })),
        };

        if let Err(e) = tx.send(input_msg).await {
            warn!(
                task_id = %active_task_id,
                event_id = %event_id,
                error = %e,
                "Control replay send failed; leaving event unprocessed for future reconnect"
            );
            break;
        }

        sqlx::query("UPDATE joysafeter_session_events SET processed_at = NOW() WHERE id = $1")
            .bind(event_id)
            .execute(pool)
            .await?;
        replayed += 1;
        info!(task_id = %active_task_id, event_id = %event_id, "Replayed unprocessed DB event on reconnect");
    }

    Ok(replayed)
}

#[cfg(test)]
mod tests {
    use std::env;

    use serde_json::{json, Value};
    use sqlx::postgres::PgPoolOptions;

    use super::*;

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres control replay test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(5)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    async fn create_agent_and_session(pool: &PgPool) -> (Uuid, Uuid) {
        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, permission_mode, version)
            VALUES ($1, $2, 'claude', 'bypassPermissions', 1)
            "#,
        )
        .bind(agent_id)
        .bind(format!("control-replay-agent-{agent_id}"))
        .execute(pool)
        .await
        .expect("insert test agent");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status)
            VALUES ($1, $2, 'running')
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .execute(pool)
        .await
        .expect("insert test session");

        (agent_id, session_id)
    }

    async fn cleanup(pool: &PgPool, agent_id: Uuid, session_id: Uuid) {
        let _ =
            sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
                .bind(session_id)
                .bind(agent_id)
                .execute(pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(pool)
            .await;
    }

    async fn create_mounted_memory_store(pool: &PgPool, session_id: Uuid) -> Uuid {
        let store_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_memory_stores (id, name, description)
            VALUES ($1, $2, '')
            "#,
        )
        .bind(store_id)
        .bind(format!("memory-sync-store-{store_id}"))
        .execute(pool)
        .await
        .expect("insert memory store");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_session_memory_stores
                (id, session_id, store_id, access, mount_name)
            VALUES ($1, $2, $3, 'read_write', 'main')
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(store_id)
        .execute(pool)
        .await
        .expect("insert session memory store mount");

        store_id
    }

    async fn cleanup_memory_store(pool: &PgPool, session_id: Uuid, store_id: Uuid) {
        let _ = sqlx::query("DELETE FROM joysafeter_session_memory_stores WHERE session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_memory_versions WHERE store_id = $1")
            .bind(store_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_memories WHERE store_id = $1")
            .bind(store_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_memory_stores WHERE id = $1")
            .bind(store_id)
            .execute(pool)
            .await;
    }

    fn test_event_bus(pool: PgPool) -> EventBus {
        let config = JoySafeterConfig::from_env();
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client = redis::Client::open(
            config
                .redis_url
                .clone()
                .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
        )
        .expect("build redis client");
        EventBus::new(pool, &config, runtime_config, redis_client)
    }

    async fn create_running_sandbox_task(
        pool: &PgPool,
        agent_id: Uuid,
        session_id: Uuid,
        label: &str,
        retry_count: i32,
        max_retries: i32,
    ) -> (Uuid, Uuid) {
        let sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        queries::create_sandbox(
            pool,
            sandbox_id,
            &format!("{label}-{sandbox_id}"),
            "recording",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("insert linked sandbox");
        let _ = queries::transition_sandbox(pool, sandbox_id, "idle")
            .await
            .expect("sandbox idle");
        let _ = queries::transition_sandbox(pool, sandbox_id, "running")
            .await
            .expect("sandbox running");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(pool)
            .await
            .expect("set sandbox last task");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, $5, $6)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .bind(retry_count)
        .bind(max_retries)
        .execute(pool)
        .await
        .expect("insert running task");

        (sandbox_id, task_id)
    }

    #[tokio::test]
    async fn pending_control_replay_marks_processed_only_after_send_succeeds() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;

        let result = async {
            let confirmation_event_id = Uuid::now_v7();
            let custom_result_event_id = Uuid::now_v7();
            let interrupt_event_id = Uuid::now_v7();
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.tool_confirmation', $3, 1)
                "#,
            )
            .bind(confirmation_event_id)
            .bind(session_id)
            .bind(json!({"call_id": "req_1", "approved": true}))
            .execute(&pool)
            .await
            .expect("insert pending confirmation event");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.custom_tool_result', $3, 2)
                "#,
            )
            .bind(custom_result_event_id)
            .bind(session_id)
            .bind(json!({"call_id": "req_2", "content": "tool output"}))
            .execute(&pool)
            .await
            .expect("insert pending custom result event");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.interrupt', $3, 3)
                "#,
            )
            .bind(interrupt_event_id)
            .bind(session_id)
            .bind(json!({}))
            .execute(&pool)
            .await
            .expect("insert pending interrupt event");

            let (closed_tx, closed_rx) = mpsc::channel(1);
            drop(closed_rx);
            let replayed =
                replay_pending_control_inputs(&pool, session_id, &closed_tx, Uuid::now_v7())
                    .await
                    .expect("closed replay should not fail DB query");
            assert_eq!(replayed, 0);

            let processed_after_failed_send: Option<chrono::DateTime<chrono::Utc>> =
                sqlx::query_scalar(
                    "SELECT processed_at FROM joysafeter_session_events WHERE id = $1",
                )
                .bind(confirmation_event_id)
                .fetch_one(&pool)
                .await
                .expect("load processed_at after failed send");
            assert_eq!(processed_after_failed_send, None);

            let (tx, mut rx) = mpsc::channel(8);
            let replayed = replay_pending_control_inputs(&pool, session_id, &tx, Uuid::now_v7())
                .await
                .expect("open replay succeeds");
            assert_eq!(replayed, 3);

            let mut replayed_inputs = Vec::new();
            for _ in 0..3 {
                let msg = rx.recv().await.expect("receive replayed control input");
                match msg.payload {
                    Some(orchestrator_message::Payload::Input(input)) => {
                        replayed_inputs.push(input.content);
                    }
                    other => panic!("unexpected replay message: {other:?}"),
                }
            }
            assert_eq!(replayed_inputs.len(), 3);

            let confirmation_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[0]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("confirmation uses live input prefix"),
            )
            .expect("decode confirmation live input");
            assert_eq!(
                confirmation_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("tool_confirmation")
            );
            assert_eq!(
                confirmation_payload
                    .get("tool_use_call_id")
                    .and_then(|value| value.as_str()),
                Some("req_1")
            );
            assert_eq!(
                confirmation_payload
                    .get("approved")
                    .and_then(|value| value.as_bool()),
                Some(true)
            );

            let custom_result_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[1]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("custom result uses live input prefix"),
            )
            .expect("decode custom result live input");
            assert_eq!(
                custom_result_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("custom_tool_result")
            );
            assert_eq!(
                custom_result_payload
                    .get("tool_use_call_id")
                    .and_then(|value| value.as_str()),
                Some("req_2")
            );
            assert_eq!(
                custom_result_payload
                    .get("content")
                    .and_then(|value| value.as_str()),
                Some("tool output")
            );

            let interrupt_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[2]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("interrupt uses live input prefix"),
            )
            .expect("decode interrupt live input");
            assert_eq!(
                interrupt_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("interrupt")
            );
            assert_eq!(
                interrupt_payload
                    .get("source_event_id")
                    .and_then(|value| value.as_str())
                    .map(str::to_string),
                Some(interrupt_event_id.to_string())
            );

            let processed_after_success: i64 =
                sqlx::query_scalar(
                    "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1 AND processed_at IS NOT NULL",
                )
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load processed_at after successful send");
            assert_eq!(processed_after_success, 3);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn send_setup_waits_for_late_session_link_before_marking_done() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            let sandbox_config = json!({});
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("setup-late-link-{sandbox_id}"),
                "recording",
                "test-image:latest",
                None,
                None,
                None,
                Some(&sandbox_config),
            )
            .await
            .expect("insert unlinked sandbox");

            let (tx, mut rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
            let link_pool = pool.clone();
            let link_task = tokio::spawn(async move {
                tokio::time::sleep(Duration::from_millis(25)).await;
                sqlx::query("UPDATE joysafeter_sandboxes SET chat_session_id = $2 WHERE id = $1")
                    .bind(sandbox_id)
                    .bind(session_id)
                    .execute(&link_pool)
                    .await
                    .expect("link sandbox to session");
            });

            let sent = send_setup(&pool, &bridge, sandbox_id, &tx)
                .await
                .expect("send setup after late session link");
            link_task.await.expect("late link task joined");
            assert!(sent);
            assert!(!bridge.setup_done.load(Ordering::Relaxed));

            let msg = tokio::time::timeout(Duration::from_secs(1), rx.recv())
                .await
                .expect("setup message should arrive")
                .expect("setup channel open");
            match msg.payload {
                Some(orchestrator_message::Payload::Setup(setup)) => {
                    assert!(!setup.provider.is_empty());
                }
                other => panic!("unexpected setup message: {other:?}"),
            }
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn idle_setup_failure_result_marks_sandbox_error_and_clears_setup_done() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("setup-failed-{sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert linked sandbox");

            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));
            bridge.setup_done.store(true, Ordering::Relaxed);
            let setup_failure = proto::RunnerHarnessResult {
                status: "failed".to_string(),
                error: Some(
                    "SetupSandbox failed: clone setup repos to /workspace: clone repo missing"
                        .to_string(),
                ),
                ..Default::default()
            };

            assert!(is_setup_failure_result(&setup_failure));
            mark_idle_setup_failure(&pool, &bridge, sandbox_id, &setup_failure).await;

            assert!(!bridge.setup_done.load(Ordering::Relaxed));
            let (status, setup_error): (String, Option<String>) = sqlx::query_as(
                "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after setup failure");
            assert_eq!(status, "error");
            assert_eq!(setup_error, setup_failure.error);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn task_setup_failure_result_marks_task_failed_and_keeps_sandbox_error() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("task-setup-failed-{sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert linked sandbox");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set sandbox last task");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert running task");

            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client = redis::Client::open(
                config
                    .redis_url
                    .clone()
                    .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
            )
            .expect("build redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));
            bridge.setup_done.store(true, Ordering::Relaxed);
            let setup_failure = proto::RunnerHarnessResult {
                status: "failed".to_string(),
                error: Some(
                    "SetupSandbox failed: clone setup repos to /workspace: clone repo missing"
                        .to_string(),
                ),
                ..Default::default()
            };
            let mut task_error = false;

            let outcome = handle_task_setup_failure_result(
                &setup_failure,
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                &mut task_error,
            )
            .await;

            assert!(outcome.task_done);
            assert!(!outcome.runner_idle_seen);
            assert!(outcome.terminal_idle_handled);
            assert!(matches!(outcome.task_result, Some(TaskResult::Failed(_))));
            assert!(task_error);
            assert!(!bridge.setup_done.load(Ordering::Relaxed));
            assert!(is_setup_failure_task_result(&TaskResult::Failed(
                setup_failure.error.clone().unwrap()
            )));

            let (task_status, task_error_msg): (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after setup failure");
            assert_eq!(task_status, "failed");
            assert_eq!(task_error_msg, setup_failure.error);

            let (sandbox_status, setup_error, last_task_id): (String, Option<String>, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, config->>'setup_error', last_task_id FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after task setup failure");
            assert_eq!(sandbox_status, "error");
            assert_eq!(setup_error, setup_failure.error);
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after task setup failure");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                setup_failure.error.as_deref()
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn build_start_task_full_propagates_harness_input_error_without_minimal_fallback() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();
        let file_id = Uuid::now_v7();
        let session_file_id = Uuid::now_v7();
        let unique = agent_id.simple().to_string();
        let org_id = format!("org-{unique}");
        let project_id = format!("proj-{unique}");
        let missing_storage_key = format!("grpc-missing-session-file-{unique}.txt");

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
            )
            .bind(&org_id)
            .bind(format!("Grpc Harness Org {unique}"))
            .bind(format!("grpc-harness-org-{unique}"))
            .execute(&pool)
            .await
            .expect("insert organization");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
            )
            .bind(&project_id)
            .bind(&org_id)
            .bind(format!("Grpc Harness Project {unique}"))
            .bind(format!("grpc-harness-project-{unique}"))
            .execute(&pool)
            .await
            .expect("insert project");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_configs, skills, tools, agents, commands, permission_mode,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
            )
            .bind(agent_id)
            .bind(&project_id)
            .bind(format!("grpc-harness-agent-{unique}"))
            .bind(json!({"id": "claude-sonnet"}))
            .execute(&pool)
            .await
            .expect("insert agent");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
            )
            .bind(session_id)
            .bind(agent_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert session");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_files (
                    id, project_id, filename, purpose, content_type, size_bytes,
                    sha256, storage_key, downloadable
                )
                VALUES (
                    $1, $2, 'missing.txt', 'user_upload', 'text/plain', 12,
                    'missing-sha', $3, true
                )
                "#,
            )
            .bind(file_id)
            .bind(&project_id)
            .bind(&missing_storage_key)
            .execute(&pool)
            .await
            .expect("insert file metadata");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_files
                    (id, session_id, file_id, mount_path, access)
                VALUES ($1, $2, $3, '/workspace/missing.txt', 'read_only')
                "#,
            )
            .bind(session_file_id)
            .bind(session_id)
            .bind(file_id)
            .execute(&pool)
            .await
            .expect("insert session file mount");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, project_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'use declared file', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(&project_id)
            .execute(&pool)
            .await
            .expect("insert task");

            let task = queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let err =
                build_start_task_full(&pool, &task, Uuid::now_v7(), &JoySafeterConfig::from_env())
                    .await
                    .expect_err("harness input build failure must not produce fallback StartTask")
                    .to_string();

            assert!(err.contains("failed to prepare session file"), "{err}");
            assert!(err.contains(&missing_storage_key), "{err}");
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_session_files WHERE id = $1")
            .bind(session_file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_files WHERE id = $1")
            .bind(file_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(&org_id)
            .execute(&pool)
            .await;

        result
    }

    #[tokio::test]
    async fn pre_start_failure_marks_task_failed_and_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("pre-start-failed-{sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert linked sandbox");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set sandbox last task");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert running task");

            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client = redis::Client::open(
                config
                    .redis_url
                    .clone()
                    .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
            )
            .expect("build redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
            let reason = "Failed to build harness input before StartTask: missing declared file";

            fail_pre_start_task(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                reason,
            )
            .await;

            let (task_status, task_error): (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after pre-start failure");
            assert_eq!(task_status, "failed");
            assert_eq!(task_error.as_deref(), Some(reason));

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after pre-start failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after pre-start failure");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some(reason)
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = $3
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .bind(reason)
            .fetch_one(&pool)
            .await
            .expect("count pre-start idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn pre_start_failure_does_not_release_sandbox_on_terminal_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "pre-start-terminal", 0, 2)
                .await;

        let result = async {
            let cancelled =
                queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                    .await
                    .expect("cancel running task before stale pre-start failure");
            assert!(cancelled);

            let event_bus = test_event_bus(pool.clone());
            fail_pre_start_task(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "stale pre-start failure",
            )
            .await;

            let task_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after stale pre-start failure");
            assert_eq!(task_status, "cancelled");

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale pre-start failure");
            assert_eq!(sandbox_status, "running");
            assert_eq!(last_task_id, Some(task_id));

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale pre-start idle events");
            assert_eq!(idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn pre_start_failure_does_not_fail_pending_task_on_stale_observation() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "pre-start-pending", 0, 2)
                .await;

        let result = async {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("simulate task already pending before stale pre-start failure");
            queries::complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("release sandbox for pending task");

            let event_bus = test_event_bus(pool.clone());
            fail_pre_start_task(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "stale pre-start failure",
            )
            .await;

            let (task_status, task_error, task_sandbox_id): (String, Option<String>, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, error, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after stale pre-start pending failure");
            assert_eq!(task_status, "pending");
            assert_eq!(task_error, None);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale pre-start pending failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale pre-start pending idle events");
            assert_eq!(idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn terminal_transition_helper_does_not_rewrite_session_on_cas_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "terminal-cas-conflict", 0, 2)
                .await;

        let result = async {
            let cancelled =
                queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                    .await
                    .expect("cancel running task");
            assert!(cancelled);

            let cancelled_reason = json!({"type": "cancelled"});
            let cancelled_payload =
                json!({"task_id": task_id.to_string(), "stop_reason": cancelled_reason.clone()});
            queries::update_session_status_and_insert_event(
                &pool,
                session_id,
                "idle",
                Some(&cancelled_reason),
                "session.status_idle",
                &cancelled_payload,
            )
            .await
            .expect("write cancel idle")
            .expect("insert cancel idle event");

            let event_bus = test_event_bus(pool.clone());
            let transitioned = transition_running_task_and_emit_idle(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "timeout",
                Some("deadline should not overwrite cancelled task"),
                json!({"type": "timeout"}),
                "test timeout conflict",
            )
            .await;
            assert!(!transitioned);

            let task_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task status");
            assert_eq!(task_status, "cancelled");

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session status");
            assert_eq!(session_status, "idle");
            assert_eq!(stop_reason, Some(cancelled_reason));

            let cancel_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'cancelled'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count cancel idle events");
            assert_eq!(cancel_idle_events, 1);

            let timeout_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'timeout'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count timeout idle events");
            assert_eq!(timeout_idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn late_runner_result_after_cancel_keeps_cancelled_session_authority() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "late-result-cancel", 0, 2)
                .await;

        let result = async {
            let cancelled =
                queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                    .await
                    .expect("cancel running task");
            assert!(cancelled);

            let cancelled_reason = json!({"type": "cancelled"});
            let cancelled_payload =
                json!({"task_id": task_id.to_string(), "stop_reason": cancelled_reason.clone()});
            queries::update_session_status_and_insert_event(
                &pool,
                session_id,
                "idle",
                Some(&cancelled_reason),
                "session.status_idle",
                &cancelled_payload,
            )
            .await
            .expect("write cancel idle")
            .expect("insert cancel idle event");

            let event_bus = test_event_bus(pool.clone());
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
            let runner_result = RunnerMessage {
                payload: Some(runner_message::Payload::Result(
                    proto::RunnerHarnessResult {
                        status: "completed".to_string(),
                        output: "late success".to_string(),
                        ..Default::default()
                    },
                )),
            };
            let mut requires_action_pending = false;
            let mut buffered_events = Vec::new();
            let mut task_completed = false;
            let mut task_error = false;
            let custom_names = std::collections::HashSet::new();
            let mcp_names = std::collections::HashSet::new();

            let outcome = handle_task_message(
                &runner_result,
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                &tx,
                &mut requires_action_pending,
                &mut buffered_events,
                &mut task_completed,
                &mut task_error,
                &custom_names,
                &mcp_names,
                Arc::new(MemoryStoreSubscribers::new()),
                &BridgeRegistry::new(),
                2000,
            )
            .await;

            assert!(outcome.task_done);
            assert!(outcome.terminal_idle_handled);
            assert!(matches!(outcome.task_result, Some(TaskResult::Cancelled)));
            assert!(task_completed);
            assert!(!task_error);

            let (task_status, task_output): (String, String) =
                sqlx::query_as("SELECT status, output FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after late result");
            assert_eq!(task_status, "cancelled");
            assert_eq!(task_output, "");

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after late result");
            assert_eq!(session_status, "idle");
            assert_eq!(stop_reason, Some(cancelled_reason));

            let cancel_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'cancelled'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count cancel idle events after late result");
            assert_eq!(cancel_idle_events, 1);

            let end_turn_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count end_turn idle events after late result");
            assert_eq!(end_turn_idle_events, 0);

            let late_agent_messages: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'agent.message'
                  AND payload::text LIKE '%late success%'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count late fallback messages");
            assert_eq!(late_agent_messages, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn completed_runner_result_output_persists_visible_agent_message_before_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "result-output-fallback",
            0,
            2,
        )
        .await;

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'session.status_running', $3, 1)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"task_id": task_id.to_string()}))
            .execute(&pool)
            .await
            .expect("insert running status event");

            let event_bus = test_event_bus(pool.clone());
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
            let runner_result = RunnerMessage {
                payload: Some(runner_message::Payload::Result(
                    proto::RunnerHarnessResult {
                        status: "completed".to_string(),
                        output: "FORMAL_SESSION_K3S_OK".to_string(),
                        ..Default::default()
                    },
                )),
            };
            let mut requires_action_pending = false;
            let mut buffered_events = Vec::new();
            let mut task_completed = false;
            let mut task_error = false;
            let custom_names = std::collections::HashSet::new();
            let mcp_names = std::collections::HashSet::new();

            let outcome = handle_task_message(
                &runner_result,
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                &tx,
                &mut requires_action_pending,
                &mut buffered_events,
                &mut task_completed,
                &mut task_error,
                &custom_names,
                &mcp_names,
                Arc::new(MemoryStoreSubscribers::new()),
                &BridgeRegistry::new(),
                2000,
            )
            .await;

            assert!(outcome.task_done);
            assert!(outcome.terminal_idle_handled);
            assert!(task_completed);
            assert!(!task_error);

            let rows: Vec<(String, Value, i64)> = sqlx::query_as(
                r#"
                SELECT event_type, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load session events");

            assert_eq!(rows.len(), 3);
            assert_eq!(rows[0].0, "session.status_running");
            assert_eq!(rows[1].0, "agent.message");
            assert_eq!(rows[1].2, 2);
            assert_eq!(
                rows[1]
                    .1
                    .get("content")
                    .and_then(Value::as_array)
                    .and_then(|items| {
                        items
                            .first()
                            .and_then(|item| item.get("text"))
                            .and_then(Value::as_str)
                    }),
                Some("FORMAL_SESSION_K3S_OK")
            );
            let task_id_text = task_id.to_string();
            assert_eq!(
                rows[1].1.get("task_id").and_then(Value::as_str),
                Some(task_id_text.as_str())
            );
            assert_eq!(rows[2].0, "session.status_idle");
            assert_eq!(rows[2].2, 3);
            assert_eq!(
                rows[2]
                    .1
                    .get("stop_reason")
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("end_turn")
            );
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn completed_runner_result_output_does_not_duplicate_streamed_agent_message() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "result-output-no-dup", 0, 2)
                .await;

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES
                    ($1, $2, 'session.status_running', $3, 1),
                    ($4, $2, 'agent.message', $5, 2)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"task_id": task_id.to_string()}))
            .bind(Uuid::now_v7())
            .bind(json!({"content": [{"type": "text", "text": "streamed answer"}]}))
            .execute(&pool)
            .await
            .expect("insert running status and streamed agent output");

            let event_bus = test_event_bus(pool.clone());
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
            let runner_result = RunnerMessage {
                payload: Some(runner_message::Payload::Result(
                    proto::RunnerHarnessResult {
                        status: "completed".to_string(),
                        output: "fallback should not duplicate".to_string(),
                        ..Default::default()
                    },
                )),
            };
            let mut requires_action_pending = false;
            let mut buffered_events = Vec::new();
            let mut task_completed = false;
            let mut task_error = false;
            let custom_names = std::collections::HashSet::new();
            let mcp_names = std::collections::HashSet::new();

            let outcome = handle_task_message(
                &runner_result,
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                &tx,
                &mut requires_action_pending,
                &mut buffered_events,
                &mut task_completed,
                &mut task_error,
                &custom_names,
                &mcp_names,
                Arc::new(MemoryStoreSubscribers::new()),
                &BridgeRegistry::new(),
                2000,
            )
            .await;

            assert!(outcome.task_done);

            let agent_messages: Vec<Value> = sqlx::query_scalar(
                r#"
                SELECT payload
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'agent.message'
                ORDER BY seq
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load agent messages");

            assert_eq!(agent_messages.len(), 1);
            assert_eq!(
                agent_messages[0]
                    .get("content")
                    .and_then(Value::as_array)
                    .and_then(|items| {
                        items
                            .first()
                            .and_then(|item| item.get("text"))
                            .and_then(Value::as_str)
                    }),
                Some("streamed answer")
            );

            let fallback_messages: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'agent.message'
                  AND payload::text LIKE '%fallback should not duplicate%'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count fallback messages");
            assert_eq!(fallback_messages, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn start_task_send_failure_retries_and_marks_session_rescheduling() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("start-send-retry-{sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert linked sandbox");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set sandbox last task");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 0, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert running task");

            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client = redis::Client::open(
                config
                    .redis_url
                    .clone()
                    .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
            )
            .expect("build redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
            let (closed_tx, closed_rx) = mpsc::channel(1);
            drop(closed_rx);
            let task = queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Start(
                    proto::StartTask::default(),
                )),
            };

            let sent = send_start_task_or_handle_failure(
                &pool,
                &event_bus,
                &closed_tx,
                &task,
                Some(session_id),
                sandbox_id,
                msg,
                None,
            )
            .await;
            assert!(!sent);

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after send failure");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 1);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after send failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after send failure");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(|value| value.as_str()),
                Some("sandbox_failed")
            );

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count rescheduling events");
            assert_eq!(rescheduling_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn dispatch_retry_failure_does_not_release_sandbox_on_terminal_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "dispatch-terminal-retry",
            0,
            2,
        )
        .await;

        let result = async {
            let stale_task = queries::get_task(&pool, task_id)
                .await
                .expect("load stale running task")
                .expect("task exists");
            let completed = queries::transition_task_cas(
                &pool,
                task_id,
                "running",
                "completed",
                Some("result won before retry"),
                None,
            )
            .await
            .expect("complete task before stale dispatch retry");
            assert!(completed);

            let event_bus = test_event_bus(pool.clone());
            handle_dispatch_retryable_failure(
                &pool,
                &event_bus,
                &stale_task,
                Some(session_id),
                sandbox_id,
                stale_task.owner_epoch,
                "stale dispatch retry",
                None,
            )
            .await;

            let (task_status, retry_count): (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after stale dispatch retry");
            assert_eq!(task_status, "completed");
            assert_eq!(retry_count, 0);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale dispatch retry");
            assert_eq!(sandbox_status, "running");
            assert_eq!(last_task_id, Some(task_id));

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale dispatch retry events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn dispatch_retry_failure_does_not_retry_pending_task_on_stale_snapshot() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "dispatch-pending-retry",
            0,
            2,
        )
        .await;

        let result = async {
            let stale_task = queries::get_task(&pool, task_id)
                .await
                .expect("load stale running task")
                .expect("task exists");
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 0,
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("simulate task already pending");
            queries::complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("release sandbox for pending task");

            let event_bus = test_event_bus(pool.clone());
            handle_dispatch_retryable_failure(
                &pool,
                &event_bus,
                &stale_task,
                Some(session_id),
                sandbox_id,
                stale_task.owner_epoch,
                "stale dispatch retry",
                None,
            )
            .await;

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load pending task after stale dispatch retry");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 0);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale dispatch retry");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale dispatch retry events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn start_task_send_failure_exhausts_retries_and_marks_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let sandbox_id = Uuid::now_v7();
        let task_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                sandbox_id,
                &format!("start-send-exhausted-{sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert linked sandbox");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            let _ = queries::transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set sandbox last task");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 2, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert running task at retry limit");

            let config = JoySafeterConfig::from_env();
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client = redis::Client::open(
                config
                    .redis_url
                    .clone()
                    .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
            )
            .expect("build redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
            let (closed_tx, closed_rx) = mpsc::channel(1);
            drop(closed_rx);
            let task = queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Start(
                    proto::StartTask::default(),
                )),
            };

            let sent = send_start_task_or_handle_failure(
                &pool,
                &event_bus,
                &closed_tx,
                &task,
                Some(session_id),
                sandbox_id,
                msg,
                None,
            )
            .await;
            assert!(!sent);

            let (task_status, retry_count, task_sandbox_id, task_error): (
                String,
                i32,
                Option<Uuid>,
                Option<String>,
            ) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted task after send failure");
            assert_eq!(task_status, "failed");
            assert_eq!(retry_count, 2);
            assert_eq!(task_sandbox_id, Some(sandbox_id));
            assert_eq!(
                task_error.as_deref(),
                Some("Failed to send StartTask: outbound channel closed")
            );

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after exhausted send failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after exhausted send failure");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some("Failed to send StartTask: outbound channel closed")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'Failed to send StartTask: outbound channel closed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn dispatch_exhausted_failure_does_not_release_sandbox_on_terminal_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "dispatch-terminal-exhausted",
            2,
            2,
        )
        .await;

        let result = async {
            let stale_task = queries::get_task(&pool, task_id)
                .await
                .expect("load stale exhausted task")
                .expect("task exists");
            let cancelled =
                queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                    .await
                    .expect("cancel task before stale exhausted failure");
            assert!(cancelled);

            let event_bus = test_event_bus(pool.clone());
            handle_dispatch_retryable_failure(
                &pool,
                &event_bus,
                &stale_task,
                Some(session_id),
                sandbox_id,
                stale_task.owner_epoch,
                "stale exhausted dispatch failure",
                None,
            )
            .await;

            let (task_status, retry_count): (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after stale exhausted dispatch failure");
            assert_eq!(task_status, "cancelled");
            assert_eq!(retry_count, 2);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale exhausted dispatch failure");
            assert_eq!(sandbox_status, "running");
            assert_eq!(last_task_id, Some(task_id));

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale exhausted dispatch idle events");
            assert_eq!(idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn dispatch_exhausted_failure_does_not_fail_pending_task_on_stale_snapshot() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "dispatch-pending-exhausted",
            2,
            2,
        )
        .await;

        let result = async {
            let stale_task = queries::get_task(&pool, task_id)
                .await
                .expect("load stale exhausted task")
                .expect("task exists");
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 2,
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("simulate exhausted task already pending");
            queries::complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("release sandbox for pending task");

            let event_bus = test_event_bus(pool.clone());
            handle_dispatch_retryable_failure(
                &pool,
                &event_bus,
                &stale_task,
                Some(session_id),
                sandbox_id,
                stale_task.owner_epoch,
                "stale exhausted dispatch failure",
                None,
            )
            .await;

            let (task_status, retry_count, task_error, task_sandbox_id): (
                String,
                i32,
                Option<String>,
                Option<Uuid>,
            ) = sqlx::query_as(
                "SELECT status, retry_count, error, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load pending task after stale exhausted dispatch failure");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 2);
            assert_eq!(task_error, None);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale exhausted dispatch failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count stale exhausted dispatch idle events");
            assert_eq!(idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn failover_retry_marks_session_rescheduling_and_releases_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "failover-retry", 0, 2).await;

        let result = async {
            let event_bus = test_event_bus(pool.clone());
            failover_or_fail_inline(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "runner disconnected",
                None,
            )
            .await;

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after failover retry");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 1);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after failover retry");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after failover retry");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(|value| value.as_str()),
                Some("sandbox_failed")
            );

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count failover rescheduling events");
            assert_eq!(rescheduling_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn failover_exhausted_retries_marks_task_failed_and_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "failover-exhausted", 2, 2)
                .await;

        let result = async {
            let event_bus = test_event_bus(pool.clone());
            failover_or_fail_inline(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "runner disconnected",
                None,
            )
            .await;

            let (task_status, retry_count, task_sandbox_id, task_error): (
                String,
                i32,
                Option<Uuid>,
                Option<String>,
            ) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load task after exhausted failover");
            assert_eq!(task_status, "failed");
            assert_eq!(retry_count, 2);
            assert_eq!(task_sandbox_id, Some(sandbox_id));
            assert_eq!(task_error.as_deref(), Some("runner disconnected"));

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after exhausted failover");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after exhausted failover");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some("runner disconnected")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'runner disconnected'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count failover idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn task_disconnect_before_result_retries_and_marks_session_rescheduling() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "disconnect-retry", 0, 2)
                .await;

        let result = async {
            let event_bus = test_event_bus(pool.clone());
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));

            let task_result = handle_task_disconnect_before_result(
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "Sandbox disconnected unexpectedly",
                None,
            )
            .await;
            assert!(matches!(task_result, TaskResult::Disconnected));

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after disconnect retry");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 1);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after disconnect retry");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after disconnect retry");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("sandbox_failed")
            );

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count disconnect rescheduling events");
            assert_eq!(rescheduling_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn failover_with_agent_output_completes_task_and_releases_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "failover-output", 0, 2).await;

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'session.status_running', $3, 1)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"task_id": task_id.to_string()}))
            .execute(&pool)
            .await
            .expect("insert running status event");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'agent.message', $3, $4)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"content": [{"type": "text", "text": "partial answer"}]}))
            .bind(2_i64)
            .execute(&pool)
            .await
            .expect("insert agent output after running status");

            let event_bus = test_event_bus(pool.clone());
            failover_or_fail_inline(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "runner disconnected after output",
                None,
            )
            .await;

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after output failover");
            assert_eq!(task_status, "completed");
            assert_eq!(retry_count, 0);
            assert_eq!(task_sandbox_id, Some(sandbox_id));

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after output failover");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after output failover");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("end_turn")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count output failover idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn failover_with_agent_output_does_not_complete_pending_retry() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "failover-output-pending",
            0,
            2,
        )
        .await;

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'session.status_running', $3, 1)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"task_id": task_id.to_string()}))
            .execute(&pool)
            .await
            .expect("insert running status event");

            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'agent.message', $3, 2)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(json!({"content": [{"type": "text", "text": "partial answer"}]}))
            .execute(&pool)
            .await
            .expect("insert agent output after running status");

            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 1,
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("simulate retry after output");
            queries::complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("release sandbox after simulated retry");
            let stop_reason = json!({"type": "sandbox_failed"});
            let payload =
                json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
            queries::update_session_status_and_insert_event(
                &pool,
                session_id,
                "rescheduling",
                Some(&stop_reason),
                "session.status_rescheduling",
                &payload,
            )
            .await
            .expect("mark session rescheduling after simulated retry")
            .expect("insert rescheduling event");

            let event_bus = test_event_bus(pool.clone());
            failover_or_fail_inline(
                &pool,
                &event_bus,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                "late failover after retry",
                None,
            )
            .await;

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load pending retry after late output failover");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 1);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after late output failover");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after late output failover");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("sandbox_failed")
            );

            let end_turn_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count false end_turn idle events");
            assert_eq!(end_turn_idle_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn orphaned_task_rescue_marks_session_rescheduling_before_requeue() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "orphan-rescue", 0, 2).await;
        let event_bus = test_event_bus(pool.clone());
        let queue = TaskQueue::new(
            redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client"),
        );

        let result = async {
            rescue_orphaned_tasks(&pool, &event_bus, sandbox_id, &queue).await;

            let task: (String, i32, Option<Uuid>) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load rescued orphan task");
            assert_eq!(task.0, "pending");
            assert_eq!(task.1, 1);
            assert_eq!(task.2, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load rescued orphan session");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(stop_reason, Some(json!({"type": "sandbox_failed"})));

            let rescheduling_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count orphan rescue rescheduling events");
            assert_eq!(rescheduling_events, 1);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn orphaned_task_rescue_exhausted_marks_session_idle_without_requeue() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "orphan-exhausted", 2, 2)
                .await;
        let event_bus = test_event_bus(pool.clone());
        let queue = TaskQueue::new(
            redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client"),
        );

        let result = async {
            rescue_orphaned_tasks(&pool, &event_bus, sandbox_id, &queue).await;

            let task: (String, i32, Option<String>) = sqlx::query_as(
                "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted orphan task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(
                task.2.as_deref(),
                Some("Orphaned running task exceeded reconnect retry limit")
            );

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load exhausted orphan session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(Value::as_str),
                Some("Orphaned running task exceeded reconnect retry limit")
            );

            let sandbox: (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted orphan sandbox");
            assert_eq!(sandbox.0, "idle");
            assert_eq!(sandbox.1, None);

            let pending_retries: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_tasks WHERE id = $1 AND status = 'pending'",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("count pending exhausted orphan task");
            assert_eq!(pending_retries, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn sandbox_cleanup_exhausted_scheduling_task_marks_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let (sandbox_id, task_id) =
            create_running_sandbox_task(&pool, agent_id, session_id, "cleanup-exhausted", 2, 2)
                .await;

        let result = async {
            sqlx::query("UPDATE joysafeter_tasks SET status = 'scheduling' WHERE id = $1")
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("move task back to scheduling for cleanup test");

            let config = JoySafeterConfig::from_env();
            execute_sandbox_cleanup(&pool, sandbox_id, Some(session_id), false, None, None, &config)
                .await;

            let task: (String, i32, Option<String>) =
                sqlx::query_as("SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load cleanup exhausted task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(
                task.2.as_deref(),
                Some("sandbox cleanup exceeded task retry limit")
            );

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load cleanup exhausted session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(Value::as_str),
                Some("sandbox cleanup exceeded task retry limit")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'sandbox cleanup exceeded task retry limit'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count cleanup exhausted idle events");
            assert_eq!(idle_events, 1);

            let rescheduling_events: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1 AND event_type = 'session.status_rescheduling'",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count cleanup exhausted rescheduling events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn sandbox_cleanup_does_not_idle_session_with_active_task_on_another_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let stale_sandbox_id = Uuid::now_v7();

        let result = async {
            queries::create_sandbox(
                &pool,
                stale_sandbox_id,
                &format!("cleanup-stale-sandbox-{stale_sandbox_id}"),
                "recording",
                "test-image:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("insert stale linked sandbox");
            queries::destroy_sandbox(&pool, stale_sandbox_id)
                .await
                .expect("mark stale sandbox destroyed before replacement");

            let (active_sandbox_id, active_task_id) = create_running_sandbox_task(
                &pool,
                agent_id,
                session_id,
                "cleanup-active-other-sandbox",
                0,
                2,
            )
            .await;

            let config = JoySafeterConfig::from_env();
            execute_sandbox_cleanup(
                &pool,
                stale_sandbox_id,
                Some(session_id),
                false,
                None,
                None,
                &config,
            )
            .await;

            let session_status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after stale sandbox cleanup");
            assert_eq!(session_status, "running");

            let disconnected_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->'stop_reason'->>'type' = 'sandbox_disconnected'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count false sandbox disconnected idle events");
            assert_eq!(disconnected_idle_events, 0);

            let active_task: (String, Option<Uuid>) =
                sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                    .bind(active_task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load active task after stale sandbox cleanup");
            assert_eq!(active_task.0, "running");
            assert_eq!(active_task.1, Some(active_sandbox_id));

            (active_sandbox_id, active_task_id)
        }
        .await;

        let (active_sandbox_id, active_task_id) = result;
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
            .bind(active_task_id)
            .execute(&pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id IN ($1, $2)")
            .bind(stale_sandbox_id)
            .bind(active_sandbox_id)
            .execute(&pool)
            .await;
        cleanup(&pool, agent_id, session_id).await;
    }

    #[tokio::test]
    async fn memory_sync_rejects_archived_store_without_mutating_existing_memory() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool).await;
        let store_id = create_mounted_memory_store(&pool, session_id).await;

        let result = async {
            handle_memory_sync_db(
                &pool,
                Some(session_id),
                "main",
                "/notes.txt",
                "first",
                "modified",
                2000,
            )
            .await;

            let (content, version): (String, i32) = sqlx::query_as(
                r#"
                SELECT content, version
                FROM joysafeter_memories
                WHERE store_id = $1 AND path = '/notes.txt'
                "#,
            )
            .bind(store_id)
            .fetch_one(&pool)
            .await
            .expect("active memory sync creates memory");
            assert_eq!(content, "first");
            assert_eq!(version, 1);

            let version_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_memory_versions WHERE store_id = $1",
            )
            .bind(store_id)
            .fetch_one(&pool)
            .await
            .expect("count memory versions after create");
            assert_eq!(version_count, 1);

            sqlx::query("UPDATE joysafeter_memory_stores SET archived_at = NOW() WHERE id = $1")
                .bind(store_id)
                .execute(&pool)
                .await
                .expect("archive memory store");

            handle_memory_sync_db(
                &pool,
                Some(session_id),
                "main",
                "/notes.txt",
                "second",
                "modified",
                2000,
            )
            .await;
            handle_memory_sync_db(
                &pool,
                Some(session_id),
                "main",
                "/notes.txt",
                "",
                "delete",
                2000,
            )
            .await;

            let (content_after, version_after): (String, i32) = sqlx::query_as(
                r#"
                SELECT content, version
                FROM joysafeter_memories
                WHERE store_id = $1 AND path = '/notes.txt'
                "#,
            )
            .bind(store_id)
            .fetch_one(&pool)
            .await
            .expect("archived memory sync leaves existing memory intact");
            assert_eq!(content_after, "first");
            assert_eq!(version_after, 1);

            let version_count_after_archive: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_memory_versions WHERE store_id = $1",
            )
            .bind(store_id)
            .fetch_one(&pool)
            .await
            .expect("count memory versions after archived writes");
            assert_eq!(version_count_after_archive, 1);
        }
        .await;

        cleanup_memory_store(&pool, session_id, store_id).await;
        cleanup(&pool, agent_id, session_id).await;
        result
    }
}

/// Full reconnect handler — runs a complete event loop for the active task.
/// Matches Python `_handle_reconnect_active_task` (536 lines).
async fn handle_reconnect_with_event_loop(
    inbound: &mut Streaming<RunnerMessage>,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    event_bus: &EventBus,
    config: &JoySafeterConfig,
    sandbox_db_id: Uuid,
    active_task_id: Uuid,
    linked_session_id: Option<Uuid>,
    exec_sem: &Arc<Semaphore>,
    redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_registry: &BridgeRegistry,
    runtime_config: &RuntimeConfig,
) {
    // Verify task exists and belongs to this sandbox
    let task = match queries::get_task(pool, active_task_id).await {
        Ok(Some(t)) => t,
        _ => {
            warn!(task_id = %active_task_id, "Reconnect: task not found");
            return;
        }
    };

    if task.sandbox_id != Some(sandbox_db_id) {
        warn!(task_id = %active_task_id, "Reconnect: task belongs to different sandbox");
        return;
    }

    let status = crate::db::models::TaskStatus::from_str(&task.status);
    if status.as_ref().map(|s| s.is_terminal()).unwrap_or(false) {
        info!(task_id = %active_task_id, status = %task.status, "Reconnect: task already terminal");
        return;
    }

    // #17: Acquire execution semaphore (blocking, Python L374)
    // G2 fix: handle closed semaphore gracefully (same as multi_task_loop)
    let _exec_permit = match exec_sem.clone().acquire_owned().await {
        Ok(p) => p,
        Err(_) => {
            warn!(task_id = %active_task_id, "Execution semaphore closed during reconnect");
            return;
        }
    };

    info!(task_id = %active_task_id, "Resuming reconnected active task with full event loop");

    bridge.setup_done.store(true, Ordering::Relaxed);
    *bridge.current_task_owner_epoch.lock().await = task.owner_epoch;
    *bridge.current_task_id.lock().await = Some(active_task_id);
    let session_id = task.session_id.or(linked_session_id);

    // #5: Redis set_task_sandbox (Python L382-384)
    if let Some(coord) = redis_coord {
        let _ = coord
            .map_task_to_sandbox(active_task_id, sandbox_db_id)
            .await;
    }

    if let Some(sid) = session_id {
        if let Err(e) = replay_pending_control_inputs(pool, sid, tx, active_task_id).await {
            warn!(task_id = %active_task_id, session_id = %sid, error = %e, "Failed to replay pending DB control inputs");
        }
    }

    // Also drain in-memory control queue
    {
        let mut ctrl_rx = bridge.control_rx.lock().await;
        while let Ok(content) = ctrl_rx.try_recv() {
            let input_msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Input(proto::SendInput {
                    content,
                })),
            };
            let _ = tx.send(input_msg).await;
        }
    }

    let _ = emit_session_running_status(
        pool,
        event_bus,
        active_task_id,
        session_id,
        sandbox_db_id,
        "reconnect",
    )
    .await;

    // Run the full task event loop (same as run_single_task)
    let heartbeat_timeout = Duration::from_secs(
        runtime_config
            .heartbeat_timeout_sec()
            .max(HEARTBEAT_TIMEOUT_DEFAULT),
    );
    // Reset cancel token for the reconnected task
    bridge.reset_cancel().await;
    let task_cancel = bridge.current_cancel_token().await;
    let result = run_single_task(
        inbound,
        tx,
        bridge,
        pool,
        event_bus,
        config,
        active_task_id,
        task.owner_epoch,
        session_id,
        sandbox_db_id,
        heartbeat_timeout,
        memory_subscribers.clone(),
        bridge_registry,
        &task_cancel,
        None,
    )
    .await;

    // Clear task on bridge
    *bridge.current_task_id.lock().await = None;
    *bridge.current_task_owner_epoch.lock().await = None;
    bridge
        .requires_action_pending
        .store(false, Ordering::Relaxed);
    bridge.reset_confirmation();
    let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

    match result {
        TaskResult::Completed => {
            info!(task_id = %active_task_id, "Reconnected task completed");
        }
        TaskResult::Failed(ref reason) => {
            // #6: failover_or_fail_task on reconnect failure (Python L824-835)
            warn!(task_id = %active_task_id, "Reconnected task failed: {reason}");
            failover_or_fail_inline(
                pool,
                event_bus,
                active_task_id,
                task.owner_epoch,
                session_id,
                sandbox_db_id,
                reason,
                None,
            )
            .await;
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(active_task_id).await;
            }
        }
        TaskResult::Timeout => {
            warn!(task_id = %active_task_id, "Reconnected task timed out");
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(active_task_id).await;
            }
        }
        TaskResult::Cancelled => {
            info!(task_id = %active_task_id, "Reconnected task cancelled");
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(active_task_id).await;
            }
        }
        TaskResult::Disconnected => {
            // #6: failover on disconnect (Python L824-835)
            warn!(task_id = %active_task_id, "Runner disconnected again during reconnected task");
            failover_or_fail_inline(
                pool,
                event_bus,
                active_task_id,
                task.owner_epoch,
                session_id,
                sandbox_db_id,
                "runner disconnected",
                None,
            )
            .await;
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(active_task_id).await;
            }
        }
    }
}

// Keep the old function as a convenience alias (not used in hot path)
async fn handle_reconnect_active_task(
    pool: &PgPool,
    _event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    _tx: &mpsc::Sender<OrchestratorMessage>,
    sandbox_db_id: Uuid,
    active_task_id: Uuid,
    _linked_session_id: Option<Uuid>,
    _config: &JoySafeterConfig,
) {
    // Simplified version without stream access — only sets up bridge state.
    // Full version is handle_reconnect_with_event_loop which has stream access.
    let task = match queries::get_task(pool, active_task_id).await {
        Ok(Some(t)) => t,
        _ => return,
    };
    if task.sandbox_id != Some(sandbox_db_id) {
        return;
    }
    let status = crate::db::models::TaskStatus::from_str(&task.status);
    if status.as_ref().map(|s| s.is_terminal()).unwrap_or(false) {
        return;
    }

    bridge.setup_done.store(true, Ordering::Relaxed);
    *bridge.current_task_owner_epoch.lock().await = task.owner_epoch;
    *bridge.current_task_id.lock().await = Some(active_task_id);
}

async fn rescue_orphaned_tasks(
    pool: &PgPool,
    event_bus: &EventBus,
    sandbox_db_id: Uuid,
    queue: &TaskQueue,
) {
    match queries::find_running_tasks_for_sandbox(pool, sandbox_db_id).await {
        Ok(tasks) => {
            for task in tasks {
                let task_id = task.id;
                handle_dispatch_retryable_failure(
                    pool,
                    event_bus,
                    &task,
                    task.session_id,
                    sandbox_db_id,
                    task.owner_epoch,
                    "Orphaned running task exceeded reconnect retry limit",
                    None,
                )
                .await;

                if matches!(
                    queries::get_task(pool, task_id).await,
                    Ok(Some(ref updated)) if updated.status == "pending"
                ) {
                    match queue.push_to_global(task_id).await {
                        Ok(()) => {
                            info!(task_id = %task_id, "Orphaned task reset and re-queued");
                        }
                        Err(e) => {
                            warn!(task_id = %task_id, error = %e, "Failed to re-queue orphaned task");
                        }
                    }
                }
            }
        }
        Err(e) => {
            error!(sandbox_id = %sandbox_db_id, "Failed to rescue orphaned tasks: {e}");
        }
    }
}

// ---------------------------------------------------------------------------
// SetupSandbox
// ---------------------------------------------------------------------------

async fn session_files_signature(pool: &PgPool, session_id: Uuid) -> anyhow::Result<String> {
    let signature: Option<String> = sqlx::query_scalar(
        r#"
        SELECT COALESCE(
            string_agg(
                sf.id::text || ':' || sf.mount_path || ':' ||
                COALESCE(f.storage_key, '') || ':' ||
                COALESCE(f.size_bytes, 0)::text,
                ',' ORDER BY sf.created_at, sf.id
            ),
            ''
        )
        FROM joysafeter_session_files sf
        JOIN joysafeter_files f ON f.id = sf.file_id
        WHERE sf.session_id = $1 AND f.deleted_at IS NULL
        "#,
    )
    .bind(session_id)
    .fetch_one(pool)
    .await?;

    Ok(signature.unwrap_or_default())
}

async fn inject_session_files_before_start(
    pool: &PgPool,
    provider: &Arc<dyn SandboxProvider>,
    bridge: &Arc<SandboxBridge>,
    sandbox_external_id: &str,
    session_id: Option<Uuid>,
) -> anyhow::Result<()> {
    let Some(session_id) = session_id else {
        return Ok(());
    };

    let signature = session_files_signature(pool, session_id)
        .await
        .map_err(|e| {
            anyhow::anyhow!("failed to load session file signature for session {session_id}: {e}")
        })?;
    if signature.is_empty() {
        *bridge.injected_session_files_signature.lock().await = Some(signature);
        return Ok(());
    }

    {
        let current = bridge.injected_session_files_signature.lock().await;
        if current.as_deref() == Some(signature.as_str()) {
            return Ok(());
        }
    }

    let ctx = crate::sandbox::file_injection::FileInjectionContext {
        session_id,
        external_id: sandbox_external_id.to_string(),
        workspace_path: None,
        runner_capabilities: vec![],
        is_pool_sandbox: true,
    };

    let files = crate::sandbox::file_injection::inject_session_files(pool, &ctx, provider.as_ref())
        .await
        .map_err(|e| {
            anyhow::anyhow!(
                "failed to inject updated session files into sandbox {sandbox_external_id} for session {session_id}: {e}"
            )
        })?;
    *bridge.injected_session_files_signature.lock().await = Some(signature);
    info!(
        session_id = %session_id,
        sandbox_id = %sandbox_external_id,
        file_count = files.len(),
        "Injected updated session files before StartTask"
    );
    Ok(())
}

async fn handle_task_setup_failure_result(
    harness_result: &proto::RunnerHarnessResult,
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    task_error: &mut bool,
) -> TaskMessageOutcome {
    *task_error = true;
    let error = harness_result
        .error
        .as_deref()
        .unwrap_or("SetupSandbox failed");

    let cas_ok = match queries::transition_task_cas(
        pool,
        task_id,
        "running",
        "failed",
        Some(error),
        expected_owner_epoch,
    )
    .await
    {
        Ok(true) => true,
        Ok(false) => {
            warn!(task_id = %task_id, "CAS conflict: task already terminal, ignoring setup failure result");
            false
        }
        Err(db_error) => {
            error!(task_id = %task_id, error = %db_error, "Failed to transition setup failure result");
            false
        }
    };
    if cas_ok {
        let _ = queries::complete_task(
            pool,
            task_id,
            "failed",
            Some(&harness_result.output),
            Some(error),
            None,
        )
        .await;
    }
    let task_result = if cas_ok {
        TaskResult::Failed(error.to_string())
    } else {
        load_terminal_task_result(pool, task_id)
            .await
            .unwrap_or_else(|| TaskResult::Failed(error.to_string()))
    };

    mark_idle_setup_failure(pool, bridge, sandbox_db_id, harness_result).await;
    *bridge.last_result_status.lock().await = Some("failed".to_string());
    *bridge.last_result_error.lock().await = Some(error.to_string());

    let result_payload = json!({
        "type": "complete",
        "status": "failed",
        "output": harness_result.output,
        "error": error,
        "duration_ms": harness_result.duration_ms,
    });
    bridge.broadcast_to_task(task_id, result_payload).await;
    bridge.remove_task_subscribers(task_id).await;

    if cas_ok {
        emit_session_idle_status(
            pool,
            event_bus,
            task_id,
            session_id,
            sandbox_db_id,
            json!({"type": "error", "message": error}),
            "setup failure result",
        )
        .await;
        event_bus.flush().await;
    }

    info!(task_id = %task_id, "SetupSandbox failure result received during task dispatch");
    TaskMessageOutcome {
        task_done: true,
        terminal_idle_handled: true,
        task_result: Some(task_result),
        ..Default::default()
    }
}

async fn send_shutdown(tx: &mpsc::Sender<OrchestratorMessage>, reason: String) {
    let message = OrchestratorMessage {
        payload: Some(orchestrator_message::Payload::Shutdown(Shutdown { reason })),
    };
    if let Err(e) = tx.send(message).await {
        debug!("Failed to send runner shutdown: {e}");
    }
}

fn is_setup_failure_result(result: &proto::RunnerHarnessResult) -> bool {
    result.status == "failed" && result.error.as_deref().is_some_and(is_setup_failure_error)
}

fn is_setup_failure_error(error: &str) -> bool {
    error.starts_with("SetupSandbox failed")
}

fn is_setup_failure_task_result(result: &TaskResult) -> bool {
    matches!(result, TaskResult::Failed(reason) if is_setup_failure_error(reason))
}

async fn mark_idle_setup_failure(
    pool: &PgPool,
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: Uuid,
    result: &proto::RunnerHarnessResult,
) {
    bridge.setup_done.store(false, Ordering::Relaxed);
    let error = result.error.as_deref().unwrap_or("SetupSandbox failed");
    error!(
        sandbox_id = %sandbox_db_id,
        error = error,
        "Runner reported SetupSandbox failure while idle; marking sandbox error"
    );
    if let Err(err) = queries::mark_sandbox_error(pool, sandbox_db_id, Some(error)).await {
        warn!(
            sandbox_id = %sandbox_db_id,
            error = %err,
            "Failed to mark sandbox error after SetupSandbox failure"
        );
    }
}

async fn send_setup(
    pool: &PgPool,
    _bridge: &Arc<SandboxBridge>,
    sandbox_db_id: Uuid,
    tx: &mpsc::Sender<OrchestratorMessage>,
) -> anyhow::Result<bool> {
    let mut session_id = None;
    for attempt in 0..50 {
        if let Some(sandbox) = queries::get_sandbox(pool, sandbox_db_id).await? {
            if let Some(sid) = sandbox.chat_session_id {
                session_id = Some(sid);
                break;
            }
        }
        if attempt < 49 {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    let Some(session_id) = session_id else {
        warn!(sandbox_id = %sandbox_db_id, "Timed out waiting for session link; setup not sent");
        return Ok(false);
    };

    let Some(session) = queries::get_session(pool, session_id).await? else {
        anyhow::bail!("linked session {session_id} not found for sandbox {sandbox_db_id}");
    };

    let setup_task = crate::db::models::JoySafeterTask {
        id: Uuid::now_v7(),
        project_id: session.project_id.clone(),
        agent_id: session.agent_id,
        session_id: Some(session_id),
        sandbox_id: Some(sandbox_db_id),
        status: "setup".to_string(),
        prompt: String::new(),
        system_prompt: None,
        output: String::new(),
        error: None,
        usage: None,
        timeout_sec: None,
        retry_count: 0,
        max_retries: 0,
        started_at: None,
        completed_at: None,
        duration_ms: None,
        created_at: chrono::Utc::now(),
        updated_at: chrono::Utc::now(),
        owner_epoch: None,
    };

    let builder = HarnessInputBuilder::new(pool.clone());
    let input = builder
        .build(&setup_task, &sandbox_db_id.to_string(), sandbox_db_id)
        .await?;
    let mut setup = HarnessInputBuilder::build_setup_sandbox(&input);
    let file_count = setup.files.len();
    let file_ref_count = setup.file_refs.len();
    setup.files.clear();
    setup.file_refs.clear();

    let msg = OrchestratorMessage {
        payload: Some(orchestrator_message::Payload::Setup(setup)),
    };
    tx.send(msg)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to send SetupSandbox: {e}"))?;
    info!(
        sandbox_id = %sandbox_db_id,
        omitted_files = file_count,
        omitted_file_refs = file_ref_count,
        "SetupSandbox sent"
    );

    Ok(true)
}

// ---------------------------------------------------------------------------
// Sandbox cleanup
// ---------------------------------------------------------------------------

async fn execute_sandbox_cleanup(
    pool: &PgPool,
    sandbox_db_id: Uuid,
    session_id: Option<Uuid>,
    failure_ejected: bool,
    queue: Option<&TaskQueue>,
    redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
    config: &JoySafeterConfig,
) {
    // Step 1: CAS sandbox status to stopped or error
    let sandbox = queries::get_sandbox(pool, sandbox_db_id)
        .await
        .ok()
        .flatten();
    let current_status = sandbox
        .as_ref()
        .map(|s| s.status.as_str())
        .unwrap_or("unknown");
    if !matches!(current_status, "destroyed" | "stopped" | "error") {
        let new_status = if failure_ejected { "error" } else { "stopped" };
        let _ =
            queries::transition_sandbox_cas(pool, sandbox_db_id, current_status, new_status).await;
    }

    // Step 2: Remove bridge from registry (already done by caller)

    let failure_reason = "sandbox cleanup exceeded task retry limit";
    let failed_tasks = match queries::fail_exhausted_sandbox_tasks_returning(
        pool,
        sandbox_db_id,
        failure_reason,
    )
    .await
    {
        Ok(tasks) => tasks,
        Err(e) => {
            error!(sandbox_id = %sandbox_db_id, error = %e, "Failed to mark exhausted cleanup tasks failed");
            Vec::new()
        }
    };
    persist_failed_tasks_idle(pool, &failed_tasks, failure_reason).await;

    // Step 3: Reset retryable scheduling tasks for this sandbox back to pending
    let reset_tasks = match queries::reset_sandbox_tasks_to_pending_returning(pool, sandbox_db_id)
        .await
    {
        Ok(tasks) => {
            if !tasks.is_empty() {
                info!(sandbox_id = %sandbox_db_id, count = tasks.len(), "Step 3: Reset tasks to pending");
            }
            tasks
        }
        Err(e) => {
            error!(sandbox_id = %sandbox_db_id, error = %e, "Failed to reset cleanup tasks to pending");
            Vec::new()
        }
    };
    persist_reset_tasks_rescheduling(pool, &reset_tasks).await;

    // Step 4: Drain sandbox wakeup queue. Task recovery is DB-driven.
    if let Some(q) = queue {
        let _ = q.drain(sandbox_db_id).await;
    }

    // Step 5: Schedule delayed retry for each task reset in Step 3 (Python L2185-2201)
    if let Some(q) = queue {
        for task in &reset_tasks {
            let delay = compute_retry_delay(task.previous_retry_count as u32, task.id, config);
            let q_clone = q.clone();
            let task_id = task.id;
            tokio::spawn(async move {
                tokio::time::sleep(delay).await;
                if let Err(e) = q_clone.push_to_global(task_id).await {
                    warn!(task_id = %task_id, error = %e, "Failed to enqueue delayed retry");
                }
            });
        }
    }

    // Step 6: Remove Redis sandbox owner + queue keys (Python L2203-2207)
    if let Some(coord) = redis_coord {
        let _ = coord.remove_sandbox(sandbox_db_id).await;
        let _ = coord.remove_sandbox_queue(sandbox_db_id).await;
    }

    // #19: Step 7 — if no task-specific retry/failure transition happened,
    // treat the sandbox disappearance as an idle/disconnected session event.
    if let Some(sid) = session_id {
        if let Ok(Some(session)) = queries::get_session(pool, sid).await {
            let current = session.status.as_str();
            if (current == "running" || current == "rescheduling")
                && reset_tasks.is_empty()
                && failed_tasks.is_empty()
            {
                // Sandbox lifetime is independent from session lifetime. If a
                // sandbox disappears after a turn, keep the session reusable;
                // the next user.message will resolve a fresh sandbox.
                let stop_reason = json!({"type": "sandbox_disconnected"});
                let payload = json!({"stop_reason": stop_reason.clone()});
                let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                    pool,
                    sid,
                    "idle",
                    Some(&stop_reason),
                    "session.status_idle",
                    &payload,
                )
                .await;

                info!(sandbox_id = %sandbox_db_id, session_id = %sid, status = "idle", "Step 7: Session status updated");
            }
        }
    }

    // Step 8: Memory subscribers are unregistered by the session owner after
    // bridge/grace-period cleanup, matching Python's unregister_session path.

    // Step 9: Teardown networking (if Envoy was used)
    // (Envoy teardown happens via EnvoyManager when sandbox is removed)

    info!(sandbox_id = %sandbox_db_id, "Sandbox cleanup complete (9 steps)");
}

async fn persist_failed_tasks_idle(
    pool: &PgPool,
    tasks: &[queries::FailedSandboxTask],
    reason: &str,
) {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let stop_reason = json!({"type": "error", "message": reason});
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone()
        });
        if let Err(e) = queries::update_session_status_if_no_active_tasks_and_insert_event(
            pool,
            session_id,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &payload,
        )
        .await
        {
            error!(
                task_id = %task.id,
                session_id = %session_id,
                error = %e,
                "Failed to persist exhausted cleanup task session idle status"
            );
        }
    }
}

async fn persist_reset_tasks_rescheduling(pool: &PgPool, tasks: &[queries::ResetSandboxTask]) {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let stop_reason = json!({"type": "sandbox_failed"});
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone()
        });
        if let Err(e) = queries::update_session_status_and_insert_event(
            pool,
            session_id,
            "rescheduling",
            Some(&stop_reason),
            "session.status_rescheduling",
            &payload,
        )
        .await
        {
            error!(
                task_id = %task.id,
                session_id = %session_id,
                error = %e,
                "Failed to persist cleanup task session rescheduling status"
            );
        }
    }
}

/// Probe container status and run grace period cleanup.
/// 120s reconnect window with early checks at 5/10/15s.
async fn probe_and_grace_period_cleanup(
    pool: &PgPool,
    sandbox_db_id: Uuid,
    session_id: Option<Uuid>,
    failure_ejected: bool,
    bridge_registry: &BridgeRegistry,
    queue: Option<&TaskQueue>,
    redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
    config: &JoySafeterConfig,
) {
    // First probe after 3s
    tokio::time::sleep(Duration::from_secs(3)).await;
    if bridge_registry.get_by_db_id(sandbox_db_id).is_some() {
        info!(sandbox_id = %sandbox_db_id, "Reconnection detected (3s)");
        return;
    }

    // Second probe after 2 more seconds
    tokio::time::sleep(Duration::from_secs(2)).await;
    if bridge_registry.get_by_db_id(sandbox_db_id).is_some() {
        info!(sandbox_id = %sandbox_db_id, "Reconnection detected (5s)");
        return;
    }

    // Early reconnection checks at 5s intervals (cumulative: 10, 15)
    for i in 0..2 {
        tokio::time::sleep(Duration::from_secs(5)).await;
        if bridge_registry.get_by_db_id(sandbox_db_id).is_some() {
            info!(sandbox_id = %sandbox_db_id, check = i + 2, "Reconnection detected during grace period");
            return;
        }
    }

    // Remaining grace period: 120 - 15 = 105s
    info!(sandbox_id = %sandbox_db_id, "Entering remaining 105s grace period");
    tokio::time::sleep(Duration::from_secs(105)).await;

    // Final check
    if bridge_registry.get_by_db_id(sandbox_db_id).is_some() {
        info!(sandbox_id = %sandbox_db_id, "Reconnection detected at end of grace period");
        return;
    }

    warn!(sandbox_id = %sandbox_db_id, "Grace period expired (120s), executing cleanup");
    execute_sandbox_cleanup(
        pool,
        sandbox_db_id,
        session_id,
        failure_ejected,
        queue,
        redis_coord,
        config,
    )
    .await;
}

/// Handle memory sync: validate path, write to DB.
async fn handle_memory_sync_db(
    pool: &PgPool,
    session_id: Option<Uuid>,
    store_mount_name: &str,
    relative_path: &str,
    content: &str,
    operation: &str,
    max_memories_per_store: i64,
) {
    // Path traversal protection
    let normalized = relative_path.replace('\\', "/");
    if normalized.contains("..") || normalized.contains('\0') {
        warn!(
            path = relative_path,
            "Path traversal attempt in memory sync, rejecting"
        );
        return;
    }

    let session_id = match session_id {
        Some(sid) => sid,
        None => return,
    };

    // Normalize path to start with /
    let norm_path = if normalized.starts_with('/') {
        normalized
    } else {
        format!("/{normalized}")
    };

    // Resolve store from mount_name → store_id
    let store = match sqlx::query_as::<_, (Uuid, String)>(
        r#"
        SELECT sms.store_id, sms.access
        FROM joysafeter_session_memory_stores sms
        WHERE sms.session_id = $1 AND sms.mount_name = $2
        LIMIT 1
        "#,
    )
    .bind(session_id)
    .bind(store_mount_name)
    .fetch_optional(pool)
    .await
    {
        Ok(Some(s)) => s,
        Ok(None) => {
            debug!(
                mount = store_mount_name,
                "Memory store not found for session"
            );
            return;
        }
        Err(e) => {
            error!("Memory sync store lookup failed: {e}");
            return;
        }
    };

    let (store_id, access) = store;

    // Check read-only
    if access == "read_only" {
        warn!(
            store = store_mount_name,
            "Rejecting write to read-only memory store"
        );
        return;
    }

    let mut tx = match pool.begin().await {
        Ok(tx) => tx,
        Err(e) => {
            error!(error = %e, "Memory sync transaction start failed");
            return;
        }
    };

    let archived_at = match sqlx::query_scalar::<_, Option<chrono::DateTime<chrono::Utc>>>(
        "SELECT archived_at FROM joysafeter_memory_stores WHERE id = $1 FOR UPDATE",
    )
    .bind(store_id)
    .fetch_optional(&mut *tx)
    .await
    {
        Ok(Some(archived_at)) => archived_at,
        Ok(None) => {
            warn!(store_id = %store_id, "Memory store missing during sync");
            return;
        }
        Err(e) => {
            error!(error = %e, "Memory store lock failed");
            return;
        }
    };
    if archived_at.is_some() {
        warn!(
            store_id = %store_id,
            store = store_mount_name,
            "Rejecting write to archived memory store"
        );
        return;
    }

    match operation {
        "delete" => {
            let existing = match sqlx::query_as::<_, (Uuid,)>(
                r#"
                SELECT id FROM joysafeter_memories
                WHERE store_id = $1 AND path = $2
                LIMIT 1
                "#,
            )
            .bind(store_id)
            .bind(&norm_path)
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(row) => row,
                Err(e) => {
                    error!(error = %e, "Memory delete lookup failed");
                    return;
                }
            };

            let Some((memory_id,)) = existing else {
                let _ = tx.commit().await;
                return;
            };

            let version_id = Uuid::now_v7();
            if let Err(e) = sqlx::query(
                r#"
                INSERT INTO joysafeter_memory_versions
                    (id, store_id, memory_id, operation, path, content, content_sha256,
                     content_size_bytes, session_id, api_key_id, created_at)
                VALUES ($1, $2, $3, 'deleted', $4, NULL, NULL, NULL, $5, NULL, NOW())
                "#,
            )
            .bind(version_id)
            .bind(store_id)
            .bind(memory_id)
            .bind(&norm_path)
            .bind(session_id)
            .execute(&mut *tx)
            .await
            {
                error!(error = %e, "Memory delete version insert failed");
                return;
            }

            if let Err(e) =
                sqlx::query("DELETE FROM joysafeter_memories WHERE store_id = $1 AND id = $2")
                    .bind(store_id)
                    .bind(memory_id)
                    .execute(&mut *tx)
                    .await
            {
                error!(error = %e, "Memory delete failed");
                return;
            }

            if let Err(e) = tx.commit().await {
                error!(error = %e, "Memory delete transaction commit failed");
                return;
            }

            debug!(
                store = store_mount_name,
                path = norm_path,
                "Memory file deleted"
            );
        }
        _ => {
            let content_bytes = content.as_bytes();
            let size = content_bytes.len() as i64;
            let sha = hex::encode(Sha256::digest(content_bytes));

            let existing = match sqlx::query_as::<_, (Uuid, String)>(
                r#"
                SELECT id, content_sha256 FROM joysafeter_memories
                WHERE store_id = $1 AND path = $2
                LIMIT 1
                "#,
            )
            .bind(store_id)
            .bind(&norm_path)
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(row) => row,
                Err(e) => {
                    error!(error = %e, "Memory upsert lookup failed");
                    return;
                }
            };

            if let Some((memory_id, existing_sha)) = existing {
                if existing_sha == sha {
                    let _ = tx.commit().await;
                    return;
                }

                let version_id = Uuid::now_v7();
                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memory_versions
                        (id, store_id, memory_id, operation, path, content, content_sha256,
                         content_size_bytes, session_id, api_key_id, created_at)
                    VALUES ($1, $2, $3, 'modified', $4, $5, $6, $7, $8, NULL, NOW())
                    "#,
                )
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(session_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory modified version insert failed");
                    return;
                }

                if let Err(e) = sqlx::query(
                    r#"
                    UPDATE joysafeter_memories
                    SET content = $1,
                        content_sha256 = $2,
                        size_bytes = $3,
                        version = COALESCE(version, 1) + 1,
                        current_version_id = $4,
                        updated_at = NOW()
                    WHERE store_id = $5 AND id = $6
                    "#,
                )
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory update failed");
                    return;
                }
            } else {
                let count = match sqlx::query_as::<_, (i64,)>(
                    "SELECT COUNT(*) FROM joysafeter_memories WHERE store_id = $1",
                )
                .bind(store_id)
                .fetch_one(&mut *tx)
                .await
                {
                    Ok((count,)) => count,
                    Err(e) => {
                        error!(error = %e, "Memory count lookup failed");
                        return;
                    }
                };

                if count >= max_memories_per_store {
                    warn!(
                        store = store_mount_name,
                        limit = max_memories_per_store,
                        "Rejecting memory create because store limit was reached"
                    );
                    return;
                }

                let memory_id = Uuid::now_v7();
                let version_id = Uuid::now_v7();
                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memory_versions
                        (id, store_id, memory_id, operation, path, content, content_sha256,
                         content_size_bytes, session_id, api_key_id, created_at)
                    VALUES ($1, $2, $3, 'created', $4, $5, $6, $7, $8, NULL, NOW())
                    "#,
                )
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(session_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory created version insert failed");
                    return;
                }

                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memories
                        (id, store_id, path, content, content_sha256, size_bytes,
                         version, current_version_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, 1, $7, NOW(), NOW())
                    "#,
                )
                .bind(memory_id)
                .bind(store_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(version_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory create failed");
                    return;
                }
            }

            if let Err(e) = tx.commit().await {
                error!(error = %e, "Memory upsert transaction commit failed");
                return;
            }

            debug!(
                store = store_mount_name,
                path = norm_path,
                "Memory file upserted"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async fn emit_session_running_status(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: Uuid,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    context: &str,
) -> bool {
    let Some(sid) = session_id else {
        return true;
    };
    let payload = json!({"task_id": task_id.to_string()});
    match queries::update_session_status_and_insert_event(
        pool,
        sid,
        "running",
        None,
        "session.status_running",
        &payload,
    )
    .await
    {
        Ok(Some((event_id, seq))) => {
            let envelope = EventEnvelope::new(sid, "session.status_running", payload)
                .with_task(task_id)
                .with_sandbox(sandbox_db_id)
                .status_change(None)
                .with_db_persisted(event_id, seq);
            event_bus.publish(envelope).await;
            true
        }
        Ok(None) => {
            warn!(
                task_id = %task_id,
                session_id = %sid,
                context = context,
                "Session running status update skipped"
            );
            false
        }
        Err(error) => {
            error!(
                task_id = %task_id,
                session_id = %sid,
                context = context,
                error = %error,
                "Failed to publish session running status"
            );
            false
        }
    }
}

async fn emit_session_idle_status(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: Uuid,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    stop_reason: serde_json::Value,
    context: &str,
) -> bool {
    let Some(sid) = session_id else {
        return true;
    };
    let payload = json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
    match queries::update_session_status_if_no_active_tasks_and_insert_event(
        pool,
        sid,
        "idle",
        Some(&stop_reason),
        "session.status_idle",
        &payload,
    )
    .await
    {
        Ok(Some((event_id, seq))) => {
            let envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                .with_task(task_id)
                .with_sandbox(sandbox_db_id)
                .status_change(Some(stop_reason))
                .with_db_persisted(event_id, seq);
            event_bus.publish(envelope).await;
            true
        }
        Ok(None) => {
            warn!(
                task_id = %task_id,
                session_id = %sid,
                context = context,
                "Session idle status update skipped"
            );
            false
        }
        Err(error) => {
            error!(
                task_id = %task_id,
                session_id = %sid,
                context = context,
                error = %error,
                "Failed to publish session idle status"
            );
            false
        }
    }
}

async fn transition_running_task_and_emit_idle(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    target_status: &str,
    error_message: Option<&str>,
    stop_reason: serde_json::Value,
    context: &str,
) -> bool {
    match queries::transition_task_cas(
        pool,
        task_id,
        "running",
        target_status,
        error_message,
        expected_owner_epoch,
    )
    .await
    {
        Ok(true) => {
            emit_session_idle_status(
                pool,
                event_bus,
                task_id,
                session_id,
                sandbox_db_id,
                stop_reason,
                context,
            )
            .await;
            true
        }
        Ok(false) => {
            warn!(
                task_id = %task_id,
                target_status = target_status,
                context = context,
                "Task terminal transition skipped because task was no longer running"
            );
            false
        }
        Err(error) => {
            error!(
                task_id = %task_id,
                target_status = target_status,
                context = context,
                error = %error,
                "Failed to transition running task to terminal status"
            );
            false
        }
    }
}

async fn handle_task_disconnect_before_result(
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    reason: &str,
    queue: Option<&TaskQueue>,
) -> TaskResult {
    event_bus.flush().await;
    failover_or_fail_inline(
        pool,
        event_bus,
        task_id,
        expected_owner_epoch,
        session_id,
        sandbox_db_id,
        reason,
        queue,
    )
    .await;
    bridge.remove_task_subscribers(task_id).await;
    TaskResult::Disconnected
}

fn task_result_from_status(status: &str, error: Option<&str>) -> Option<TaskResult> {
    match status {
        "completed" => Some(TaskResult::Completed),
        "failed" => Some(TaskResult::Failed(
            error.unwrap_or("Task failed").to_string(),
        )),
        "aborted" => Some(TaskResult::Failed(
            error.unwrap_or("Task aborted").to_string(),
        )),
        "timeout" => Some(TaskResult::Timeout),
        "cancelled" => Some(TaskResult::Cancelled),
        _ => None,
    }
}

async fn load_terminal_task_result(pool: &PgPool, task_id: Uuid) -> Option<TaskResult> {
    match queries::get_task(pool, task_id).await {
        Ok(Some(task)) => task_result_from_status(&task.status, task.error.as_deref()),
        Ok(None) => {
            warn!(task_id = %task_id, "Unable to resolve task result because task no longer exists");
            None
        }
        Err(error) => {
            error!(task_id = %task_id, error = %error, "Failed to resolve task result from DB");
            None
        }
    }
}

async fn fail_pre_start_task(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    reason: &str,
) {
    let transitioned = match queries::transition_task_cas(
        pool,
        task_id,
        "running",
        "failed",
        Some(reason),
        expected_owner_epoch,
    )
    .await
    {
        Ok(value) => value,
        Err(e) => {
            error!(task_id = %task_id, error = %e, "Failed to mark pre-start task failed");
            false
        }
    };

    if !transitioned {
        return;
    }

    let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

    if let Some(sid) = session_id {
        let stop_reason = json!({"type": "error", "message": reason});
        let payload = json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
        match queries::update_session_status_if_no_active_tasks_and_insert_event(
            pool,
            sid,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &payload,
        )
        .await
        {
            Ok(Some((event_id, seq))) => {
                let envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                    .with_task(task_id)
                    .with_sandbox(sandbox_db_id)
                    .status_change(Some(stop_reason))
                    .with_db_persisted(event_id, seq);
                event_bus.publish(envelope).await;
                event_bus.flush().await;
            }
            Ok(None) => {}
            Err(e) => {
                error!(
                    task_id = %task_id,
                    session_id = %sid,
                    error = %e,
                    "Failed to publish pre-start session idle status"
                );
            }
        }
    }
}

async fn send_start_task_or_handle_failure(
    pool: &PgPool,
    event_bus: &EventBus,
    tx: &mpsc::Sender<OrchestratorMessage>,
    task: &crate::db::models::JoySafeterTask,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    msg: OrchestratorMessage,
    queue: Option<&TaskQueue>,
) -> bool {
    // Bounded send prevents blocking forever when the outbound stream is no
    // longer draining. A failed send means the runner never received StartTask,
    // so the task must be retried or failed without leaving the session running.
    let send_result = tokio::time::timeout(Duration::from_secs(10), tx.send(msg)).await;
    match send_result {
        Ok(Ok(())) => true,
        Ok(Err(_)) => {
            error!(
                task_id = %task.id,
                "Failed to send StartTask because outbound channel is closed"
            );
            handle_dispatch_retryable_failure(
                pool,
                event_bus,
                task,
                session_id,
                sandbox_db_id,
                task.owner_epoch,
                "Failed to send StartTask: outbound channel closed",
                queue,
            )
            .await;
            false
        }
        Err(_) => {
            error!(
                task_id = %task.id,
                "Failed to send StartTask because outbound channel timed out"
            );
            handle_dispatch_retryable_failure(
                pool,
                event_bus,
                task,
                session_id,
                sandbox_db_id,
                task.owner_epoch,
                "Failed to send StartTask: outbound channel timed out",
                queue,
            )
            .await;
            false
        }
    }
}

async fn handle_dispatch_retryable_failure(
    pool: &PgPool,
    event_bus: &EventBus,
    task: &crate::db::models::JoySafeterTask,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    expected_owner_epoch: Option<i64>,
    reason: &str,
    queue: Option<&TaskQueue>,
) {
    let task_id = task.id;

    if task.retry_count < task.max_retries {
        match queries::increment_running_retry(
            pool,
            task_id,
            task.retry_count,
            expected_owner_epoch,
        )
        .await
        {
            Ok(true) => {
                let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;
                if let Some(sid) = session_id.or(task.session_id) {
                    let stop_reason = json!({"type": "sandbox_failed"});
                    let payload =
                        json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
                    match queries::update_session_status_and_insert_event(
                        pool,
                        sid,
                        "rescheduling",
                        Some(&stop_reason),
                        "session.status_rescheduling",
                        &payload,
                    )
                    .await
                    {
                        Ok(Some((event_id, seq))) => {
                            let envelope =
                                EventEnvelope::new(sid, "session.status_rescheduling", payload)
                                    .with_task(task_id)
                                    .with_sandbox(sandbox_db_id)
                                    .status_change(Some(stop_reason))
                                    .with_db_persisted(event_id, seq);
                            event_bus.publish(envelope).await;
                            event_bus.flush().await;
                        }
                        Ok(None) => {}
                        Err(error) => {
                            error!(
                                task_id = %task_id,
                                session_id = %sid,
                                error = %error,
                                "Failed to publish dispatch retry session rescheduling status"
                            );
                        }
                    }
                }
                if let Some(q) = queue {
                    if let Err(e) = q.push_to_global(task_id).await {
                        warn!(task_id = %task_id, error = %e, "Failed to re-enqueue task after dispatch retry");
                    }
                }
                info!(
                    task_id = %task_id,
                    retry = task.retry_count + 1,
                    max_retries = task.max_retries,
                    "Dispatch failure moved task back to pending"
                );
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Dispatch failure retry skipped because task is no longer running or retry count changed");
            }
            Err(error) => {
                error!(task_id = %task_id, error = %error, "Failed to retry task after dispatch failure");
            }
        }
    } else {
        match queries::transition_task_cas(
            pool,
            task_id,
            "running",
            "failed",
            Some(reason),
            expected_owner_epoch,
        )
        .await
        {
            Ok(true) => {
                let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;
                if let Some(sid) = session_id.or(task.session_id) {
                    let stop_reason = json!({"type": "error", "message": reason});
                    let payload =
                        json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
                    match queries::update_session_status_if_no_active_tasks_and_insert_event(
                        pool,
                        sid,
                        "idle",
                        Some(&stop_reason),
                        "session.status_idle",
                        &payload,
                    )
                    .await
                    {
                        Ok(Some((event_id, seq))) => {
                            let envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                                .with_task(task_id)
                                .with_sandbox(sandbox_db_id)
                                .status_change(Some(stop_reason))
                                .with_db_persisted(event_id, seq);
                            event_bus.publish(envelope).await;
                            event_bus.flush().await;
                        }
                        Ok(None) => {}
                        Err(error) => {
                            error!(
                                task_id = %task_id,
                                session_id = %sid,
                                error = %error,
                                "Failed to publish dispatch failure session idle status"
                            );
                        }
                    }
                }
                warn!(
                    task_id = %task_id,
                    max_retries = task.max_retries,
                    "Dispatch failure exhausted retries: {reason}"
                );
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Dispatch failure skipped because task is no longer running");
            }
            Err(error) => {
                error!(task_id = %task_id, error = %error, "Failed to mark dispatch failure task failed");
            }
        }
    }
}

/// #18: Inline failover_or_fail_task — checks agent output, retries, or marks failed.
/// Matches Python TaskController.failover_or_fail_task (L274-337).
async fn failover_or_fail_inline(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: Uuid,
    expected_owner_epoch: Option<i64>,
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    reason: &str,
    queue: Option<&TaskQueue>,
) {
    let task = match queries::get_task(pool, task_id).await {
        Ok(Some(t)) => t,
        _ => return,
    };

    // Skip if already terminal
    if let Some(status) = crate::db::models::TaskStatus::from_str(&task.status) {
        if status.is_terminal() {
            return;
        }
    }

    // Check agent output — if task produced output, mark completed + session idle
    if let Some(sid) = session_id.or(task.session_id) {
        if queries::task_has_agent_output(pool, task_id, sid)
            .await
            .unwrap_or(false)
        {
            match queries::transition_task_cas(
                pool,
                task_id,
                "running",
                "completed",
                None,
                expected_owner_epoch,
            )
            .await
            {
                Ok(true) => {
                    let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;
                    emit_session_idle_status(
                        pool,
                        event_bus,
                        task_id,
                        Some(sid),
                        sandbox_db_id,
                        serde_json::json!({"type":"end_turn"}),
                        "failover with agent output",
                    )
                    .await;
                    info!(task_id = %task_id, "Failover: task had output, marking completed + session idle");
                }
                Ok(false) => {
                    warn!(task_id = %task_id, "Failover agent-output completion skipped because task was no longer running");
                }
                Err(error) => {
                    error!(task_id = %task_id, error = %error, "Failed to complete task after failover agent output");
                }
            }
            return;
        }
    }

    handle_dispatch_retryable_failure(
        pool,
        event_bus,
        &task,
        session_id,
        sandbox_db_id,
        expected_owner_epoch,
        reason,
        queue,
    )
    .await;
}

fn compute_stop_reason(status: Option<&str>, error: Option<&str>) -> serde_json::Value {
    match status {
        Some("completed") => json!({"type": "end_turn"}),
        Some("timeout") => json!({"type": "timeout"}),
        Some("cancelled") => json!({"type": "cancelled"}),
        Some("failed") | Some("aborted") => {
            json!({"type": "error", "message": error.unwrap_or("Task failed")})
        }
        _ => json!({"type": "end_turn"}),
    }
}

fn compute_retry_delay(retry_count: u32, task_id: Uuid, config: &JoySafeterConfig) -> Duration {
    let exponent = retry_count.min(14);
    let delay_ms = config
        .task_retry_base_ms
        .saturating_mul(2u64.saturating_pow(exponent))
        .min(config.task_retry_max_ms);
    let jitter_ms = if delay_ms > 0 {
        (task_id.as_u128() % (delay_ms / 4 + 1) as u128) as u64
    } else {
        0
    };
    Duration::from_millis(delay_ms.saturating_add(jitter_ms))
}

async fn wait_for_ready(
    inbound: &mut Streaming<RunnerMessage>,
) -> Result<Option<proto::RunnerReady>, Status> {
    let timeout = Duration::from_secs(30);
    match tokio::time::timeout(timeout, inbound.message()).await {
        Ok(Ok(Some(msg))) => match msg.payload {
            Some(runner_message::Payload::Ready(ready)) => Ok(Some(ready)),
            _ => Ok(None),
        },
        Ok(Ok(None)) => Err(Status::aborted("stream closed before RunnerReady")),
        Ok(Err(e)) => Err(e),
        Err(_) => Err(Status::deadline_exceeded("timeout waiting for RunnerReady")),
    }
}

/// Build a StartTask proto from task+agent+session through the same parity builder used by SetupSandbox.
async fn build_start_task_full(
    pool: &PgPool,
    task: &crate::db::models::JoySafeterTask,
    sandbox_db_id: Uuid,
    config: &JoySafeterConfig,
) -> anyhow::Result<proto::StartTask> {
    let timeout_seconds = task
        .timeout_sec
        .unwrap_or(config.task_default_timeout as i32) as u64;
    let builder = HarnessInputBuilder::new(pool.clone());
    let input = builder
        .build(task, &sandbox_db_id.to_string(), sandbox_db_id)
        .await?;
    Ok(HarnessInputBuilder::build_start_task(
        &input,
        task,
        timeout_seconds,
    ))
}

/// Derive permission_mode from agent tool configs.
/// If any tool has permission_policy.type == "always_ask", use "default"; otherwise "bypassPermissions".
fn derive_permission_mode(agent: &Option<crate::db::models::JoySafeterAgent>) -> Option<String> {
    let agent = match agent {
        Some(a) => a,
        None => return None,
    };

    if let Some(ref pm) = agent.permission_mode {
        return Some(pm.clone());
    }

    // Check tools for permission_policy
    if let Some(ref tools_val) = agent.tools {
        if let Some(arr) = tools_val.as_array() {
            for tool in arr {
                if let Some(configs) = tool.get("configs").and_then(|v| v.as_array()) {
                    for tcfg in configs {
                        if let Some(policy) = tcfg.get("permission_policy") {
                            if policy.get("type").and_then(|v| v.as_str()) == Some("always_ask") {
                                return Some("default".to_string());
                            }
                        }
                    }
                }
            }
        }
    }

    Some("bypassPermissions".to_string())
}

// ---------------------------------------------------------------------------
// Server startup
// ---------------------------------------------------------------------------

pub async fn start_grpc_server(
    addr: SocketAddr,
    bridge_registry: BridgeRegistry,
    event_bus: EventBus,
    queue: TaskQueue,
    pool: PgPool,
    config: JoySafeterConfig,
    sandbox_provider: Arc<dyn SandboxProvider>,
    redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    runtime_config: Arc<RuntimeConfig>,
    xds_service: Option<Arc<crate::sandbox::lds_backend::DeltaXdsServer>>,
) -> anyhow::Result<JoinHandle<()>> {
    let service = AgentBridgeService::new(
        bridge_registry,
        event_bus,
        queue,
        pool,
        config,
        sandbox_provider,
        redis_coordinator,
        memory_subscribers,
        runtime_config,
    );

    // Build the service with message size limits
    let svc = AgentBridgeServer::new(service)
        .max_decoding_message_size(GRPC_MAX_RECV_MESSAGE_SIZE)
        .max_encoding_message_size(GRPC_MAX_SEND_MESSAGE_SIZE);

    let handle = tokio::spawn(async move {
        info!(addr = %addr, xds = xds_service.is_some(), "gRPC server listening (services: joysafeter.AgentBridge[, envoy ADS])");

        let mut builder = tonic::transport::Server::builder()
            // Fix 1.2: transport-level keepalive for dead connection detection
            .tcp_keepalive(Some(Duration::from_secs(30)))
            .http2_keepalive_interval(Some(Duration::from_secs(30)))
            .http2_keepalive_timeout(Some(Duration::from_secs(10)));

        // The AgentBridge (runner) service is always present. When the Envoy
        // LDS backend is in gRPC mode, the Delta ADS service is registered on
        // the SAME server — tonic routes by service path, so runners and Envoy
        // coexist on one port with no interference.
        let serve_result = if let Some(xds) = xds_service {
            use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
            let ads = AggregatedDiscoveryServiceServer::from_arc(xds);
            builder.add_service(svc).add_service(ads).serve(addr).await
        } else {
            builder.add_service(svc).serve(addr).await
        };

        if let Err(e) = serve_result {
            error!("gRPC server error: {e}");
        }
    });

    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(handle)
}
