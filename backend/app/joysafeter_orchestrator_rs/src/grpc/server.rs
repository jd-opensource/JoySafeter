use std::collections::HashMap;
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
const GRPC_MAX_RECV_MESSAGE_SIZE: usize = 8 * 1024 * 1024;
const GRPC_MAX_SEND_MESSAGE_SIZE: usize = 32 * 1024 * 1024;

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
                        send_shutdown(&tx, "authentication required: missing runner token".to_string()).await;
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
                        send_shutdown(&tx, "authentication failed: invalid runner token".to_string()).await;
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
            let bridge = Arc::new(SandboxBridge::new(sandbox_db_id, sandbox_db_id, tx.clone()));
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
                if let Err(e) = send_setup(&pool, &bridge, sandbox_db_id, &tx).await {
                    warn!(sandbox_id = %sandbox_db_id, "Failed to send SetupSandbox: {e}");
                }
                bridge.setup_done.store(true, Ordering::Relaxed);
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
                rescue_orphaned_tasks(&pool, sandbox_db_id, &queue).await;
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
    _queue: &TaskQueue,
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
        let task_id = match queries::claim_next_sandbox_task(pool, sandbox_db_id).await {
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
                        match queries::claim_next_sandbox_task(pool, sandbox_db_id).await {
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
                                if let Some(runner_message::Payload::Heartbeat(_)) = &runner_msg.payload {
                                    heartbeat_deadline = Instant::now() + heartbeat_timeout;
                                    // Heartbeats no longer touch last_used_at:
                                    // the idle sweep drives off idle_since
                                    // (set by RunnerIdle, precise even with
                                    // background sub-agents) plus a bridge-
                                    // disconnect / hard-timeout fallback, so
                                    // we don't need a per-heartbeat write.
                                    // This removes the row bloat on long-
                                    // running sandboxes.
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
                let _ = queries::increment_retry(pool, task_id).await;
                return false;
            }
        };

        // Set task on bridge
        *bridge.current_task_id.lock().await = Some(task_id);
        let _ = queries::transition_sandbox(pool, sandbox_db_id, "running").await;

        // Redis: register task→sandbox mapping (Python L1107)
        if let Some(coord) = redis_coord {
            let _ = coord.map_task_to_sandbox(task_id, sandbox_db_id).await;
        }

        // Get task details
        let task = match queries::get_task(pool, task_id).await {
            Ok(Some(t)) => t,
            _ => {
                *bridge.current_task_id.lock().await = None;
                continue;
            }
        };

        // Defensive check: task must be in RUNNING status (Python L1142)
        if task.status != "running" {
            warn!(
                task_id = %task_id,
                status = %task.status,
                "Task not in running status after claim, skipping dispatch"
            );
            *bridge.current_task_id.lock().await = None;
            let _ = queries::transition_sandbox(pool, sandbox_db_id, "idle").await;
            // Remove Redis task mapping (Python L1152)
            if let Some(coord) = redis_coord {
                let _ = coord.remove_task_sandbox(task_id).await;
            }
            continue;
        }

        let session_id = task.session_id.or(linked_session_id);

        // sandbox_svc.touch(sandbox_id, task_id) — Python L1157
        let _ = queries::touch_sandbox(pool, sandbox_db_id).await;
        let _ = sqlx::query(
            "UPDATE joysafeter_sandboxes SET last_task_id = $2, updated_at = NOW() WHERE id = $1",
        )
        .bind(sandbox_db_id)
        .bind(task_id)
        .execute(pool)
        .await;

        // #8: Check agent exists before dispatch (Python L1133-1140)
        if let Some(agent_id) = task.agent_id {
            if queries::get_agent(pool, agent_id)
                .await
                .ok()
                .flatten()
                .is_none()
            {
                error!(task_id = %task_id, agent_id = %agent_id, "Agent not found, marking task FAILED");
                let _ = queries::transition_task(pool, task_id, "failed", Some("Agent not found"))
                    .await;
                *bridge.current_task_id.lock().await = None;
                let _ = queries::transition_sandbox(pool, sandbox_db_id, "idle").await;
                continue;
            }
        }

        // Send SetupSandbox if not done yet (pool containers)
        if !bridge.setup_done.load(Ordering::Relaxed) {
            if let Err(e) = send_setup(pool, bridge, sandbox_db_id, tx).await {
                warn!("Failed to send SetupSandbox: {e}");
            }
            bridge.setup_done.store(true, Ordering::Relaxed);
        }

        inject_session_files_before_start(
            pool,
            sandbox_provider,
            bridge,
            sandbox_external_id,
            session_id,
        )
        .await;

        // Build and send StartTask (full field resolution from DB)
        let start_task = build_start_task_full(pool, &task, sandbox_db_id, config).await;
        let msg = OrchestratorMessage {
            payload: Some(orchestrator_message::Payload::Start(start_task)),
        };
        // Fix 7.1: bounded send with timeout to prevent blocking when outbound is full
        let send_result = tokio::time::timeout(Duration::from_secs(10), tx.send(msg)).await;
        if send_result.is_err() || send_result.unwrap().is_err() {
            error!(task_id = %task_id, "Failed to send StartTask (channel full or timeout)");
            // Use increment_retry instead of direct transition (respects retry count)
            let _ = queries::increment_retry(pool, task_id).await;
            return false;
        }
        info!(task_id = %task_id, "StartTask sent");

        // Emit session.status_running
        if let Some(sid) = session_id {
            // Agentd pattern: direct DB write first, then broadcast for SSE
            let _ = queries::update_session_status(pool, sid, "running", None).await;
            let envelope = EventEnvelope::new(
                sid,
                "session.status_running",
                json!({"task_id": task_id.to_string()}),
            )
            .with_task(task_id)
            .with_sandbox(sandbox_db_id)
            .status_change(None);
            event_bus.publish(envelope).await;
        }

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
            session_id,
            sandbox_db_id,
            heartbeat_timeout,
            memory_subscribers.clone(),
            bridge_registry,
            &task_cancel,
        )
        .await;

        // Clear task on bridge
        *bridge.current_task_id.lock().await = None;
        bridge
            .requires_action_pending
            .store(false, Ordering::Relaxed);
        bridge.reset_confirmation();
        let _ = queries::transition_sandbox(pool, sandbox_db_id, "idle").await;
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
enum TaskResult {
    Completed,
    Failed(String),
    Timeout,
    Cancelled,
    Disconnected,
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
    session_id: Option<Uuid>,
    sandbox_db_id: Uuid,
    heartbeat_timeout: Duration,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_registry: &BridgeRegistry,
    task_cancel: &tokio_util::sync::CancellationToken,
) -> TaskResult {
    // I-NEW-2 fix: use per-task timeout_sec if set, else global default (matching Python)
    let timeout_secs = match queries::get_task(pool, task_id).await {
        Ok(Some(t)) => t.timeout_sec.unwrap_or(config.task_default_timeout as i32) as u64,
        _ => config.task_default_timeout,
    };

    // #38: Extract custom_names/mcp_names from agent for event routing
    let (custom_names, mcp_names) = if let Ok(Some(task)) = queries::get_task(pool, task_id).await {
        if let Some(aid) = task.agent_id {
            if let Ok(Some(agent)) = queries::get_agent(pool, aid).await {
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
    let mut got_idle = false;
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
                // C-NEW-1 fix: update DB status immediately but continue the loop
                // to receive the runner's Result+Idle confirmation (matching Python).
          let _ = queries::transition_task_cas(pool, task_id, "running", "cancelled", None).await;
                if let Some(sid) = session_id {
                    let envelope = EventEnvelope::new(sid, "session.status_idle", json!({"stop_reason": {"type": "cancelled"}}))
                        .with_task(task_id).with_sandbox(sandbox_db_id)
                        .status_change(Some(serde_json::json!({"type":"cancelled"})));
                    event_bus.publish(envelope).await;
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

                // Emit session.status_running
                if let Some(sid) = session_id {
                    let envelope = EventEnvelope::new(
                        sid,
                        "session.status_running",
                        json!({"task_id": task_id.to_string()}),
                    )
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .status_change(None);
                    event_bus.publish(envelope).await;
                }

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
                let _ = queries::transition_task_cas(pool, task_id, "running", "timeout",
                    Some(&format!("Task timed out after {timeout_secs}s"))).await;
                if let Some(sid) = session_id {
                    let envelope = EventEnvelope::new(sid, "session.status_idle", json!({"stop_reason": {"type": "timeout"}}))
                        .with_task(task_id).with_sandbox(sandbox_db_id)
                        .status_change(Some(serde_json::json!({"type":"timeout"})));
                    event_bus.publish(envelope).await;
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
                warn!(task_id = %task_id, "Heartbeat timeout during task");
                event_bus.flush().await;
                failover_or_fail_inline(pool, task_id, session_id, "Heartbeat timeout — sandbox unresponsive").await;
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
                        let (done, idle) = handle_task_message(
                            &runner_msg, pool, event_bus, bridge,
                            task_id, session_id, sandbox_db_id, tx,
                            &mut requires_action_pending,
                            &mut buffered_events,
                            &mut task_completed, &mut task_error,
                            &custom_names, &mcp_names,
                            memory_subscribers.clone(), bridge_registry,
                            config.grpc_max_memories_per_store,
                        ).await;
                        if done { task_done = true; }
                        if idle { got_idle = true; }
                        if task_done { break; }
                    }
                    Ok(None) => {
                        info!(task_id = %task_id, "Stream closed during task");
                        if !task_done {
                            let _ = queries::transition_task(pool, task_id, "failed",
                                Some("Sandbox disconnected unexpectedly")).await;
                        }
                        return TaskResult::Disconnected;
                    }
                    Err(e) => {
                        error!(task_id = %task_id, "Stream error: {e}");
                        return TaskResult::Disconnected;
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
        failover_or_fail_inline(pool, task_id, session_id, &reason).await;
        bridge.remove_task_subscribers(task_id).await;
        return TaskResult::Disconnected;
    }

    if task_done && !got_idle {
        // Got result but runner didn't send idle — emit session idle event
        bridge.remove_task_subscribers(task_id).await;
        if let Some(sid) = session_id {
            let stop_reason = if task_error {
                json!({"type": "error", "message": "Task failed"})
            } else {
                json!({"type": "end_turn"})
            };
            // Agentd three-step: DB sessions + DB events + broadcast
            let _ = queries::update_session_status(pool, sid, "idle", Some(&stop_reason)).await;
            let payload = json!({"stop_reason": stop_reason});
            let inserted =
                queries::insert_session_event(pool, sid, "session.status_idle", &payload)
                    .await
                    .ok()
                    .flatten();
            let mut envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                .with_task(task_id)
                .with_sandbox(sandbox_db_id)
                .status_change(Some(stop_reason));
            if let Some((event_id, seq)) = inserted {
                envelope.event_id = Some(event_id);
                envelope.seq = Some(seq);
            }
            event_bus.publish(envelope).await;
        }
    }

    if task_completed {
        TaskResult::Completed
    } else if task_error {
        TaskResult::Failed("Task ended in error state".to_string())
    } else {
        TaskResult::Completed
    }
}

/// Handle a single message during task execution.
/// Returns (task_done, got_idle).
async fn handle_task_message(
    msg: &RunnerMessage,
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: Uuid,
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
) -> (bool, bool) {
    let payload = match &msg.payload {
        Some(p) => p,
        None => return (false, false),
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
                        return (false, false);
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
                            .with_seq(harness_event.seq as i64);
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
                        let envelope = EventEnvelope::new(
                            sid,
                            "session.status_idle",
                            json!({"stop_reason": stop_reason}),
                        )
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .status_change(Some(stop_reason.clone()));
                        event_bus.publish(envelope).await;

                        return (false, false);
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
                        .with_seq(harness_event.seq as i64);
                    if is_status_event {
                        envelope = envelope.status_change(stop_reason);
                    }
                    event_bus.publish(envelope).await;
                }
            }
            (false, false)
        }

        runner_message::Payload::Result(harness_result) => {
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

            // CAS task completion — only update output/usage if CAS succeeds (Python L1831-1849)
            let cas_ok = if harness_result.error.is_some() {
                queries::transition_task_cas(
                    pool,
                    task_id,
                    "running",
                    status,
                    harness_result.error.as_deref(),
                )
                .await
                .unwrap_or(false)
            } else {
                queries::transition_task_cas(pool, task_id, "running", status, None)
                    .await
                    .unwrap_or(false)
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
            } else {
                warn!(task_id = %task_id, "CAS conflict: task already terminal, ignoring runner result");
            }

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
                    let has_agent_output = queries::task_has_agent_output(pool, task_id, sid)
                        .await
                        .unwrap_or(false);
                    if !has_agent_output {
                        let envelope = EventEnvelope::new(
                            sid,
                            "agent.message",
                            json!({
                                "content": [{"type": "text", "text": harness_result.output}],
                            }),
                        )
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .flush_immediately();
                        event_bus.publish(envelope).await;
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

            // Agentd pattern: three-step direct write for session idle.
            // 1. Update sessions table (authoritative status)
            // 2. Insert session_events row (with proper seq)
            // 3. Redis publish (for cross-selivery)
            // No dependency on broadcast channels or async subscribers.
            if cas_ok {
                if let Some(sid) = session_id {
                    let stop_reason = if *task_error {
                        json!({"type": "error", "message": "Task failed"})
                    } else {
                        json!({"type": "end_turn"})
                    };
                    // Step 1: Direct DB write — sessions table
                    let _ =
                        queries::update_session_status(pool, sid, "idle", Some(&stop_reason)).await;
                    // Step 2: Direct DB write — session_events table (with seq)
                    let payload =
                        json!({"task_id": task_id.to_string(), "stop_reason": stop_reason});
                    let inserted =
                        queries::insert_session_event(pool, sid, "session.status_idle", &payload)
                            .await
                            .ok()
                            .flatten();
                    // Step 3: event_bus.publish for Redis pub/sub + SSE broadcast
                    let mut envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .status_change(Some(stop_reason));
                    if let Some((event_id, seq)) = inserted {
                        envelope.event_id = Some(event_id);
                        envelope.seq = Some(seq);
                    }
                    event_bus.publish(envelope).await;
                }
            }

            info!(task_id = %task_id, status = status, "Task result received");
            (true, false) // task_done=true, got_idle=false
        }

        runner_message::Payload::Idle(idle_msg) => {
            // Update sandbox DB status
            let _ = queries::transition_sandbox(pool, sandbox_db_id, "idle").await;
            let _ = queries::touch_sandbox(pool, sandbox_db_id).await;

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
                        return (false, true);
                    }
                    let last_error = bridge.last_result_error.lock().await.clone();
                    let stop_reason =
                        compute_stop_reason(last_status.as_deref(), last_error.as_deref());

                    // Agentd three-step: DB sessions + DB events + broadcast
                    let _ =
                        queries::update_session_status(pool, sid, "idle", Some(&stop_reason)).await;
                    let payload =
                        json!({"task_id": task_id.to_string(), "stop_reason": stop_reason});
                    let inserted =
                        queries::insert_session_event(pool, sid, "session.status_idle", &payload)
                            .await
                            .ok()
                            .flatten();
                    let mut envelope = EventEnvelope::new(sid, "session.status_idle", payload)
                        .with_task(task_id)
                        .with_sandbox(sandbox_db_id)
                        .status_change(Some(stop_reason.clone()));
                    if let Some((event_id, seq)) = inserted {
                        envelope.event_id = Some(event_id);
                        envelope.seq = Some(seq);
                    }
                    event_bus.publish(envelope).await;

                    // E4 fix: also update session status directly via DB
                    let _ =
                        queries::update_session_status(pool, sid, "idle", Some(&stop_reason)).await;
                }
            }

            (false, true) // task_done=false, got_idle=true
        }

        runner_message::Payload::Heartbeat(_) => {
            debug!(task_id = %task_id, "Heartbeat");
            (false, false)
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
            (false, false)
        }

        runner_message::Payload::Ready(_) => {
            warn!(task_id = %task_id, "Unexpected RunnerReady during task");
            (false, false)
        }
    }
}

// ---------------------------------------------------------------------------
// Reconnect handling
// ---------------------------------------------------------------------------

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
    *bridge.current_task_id.lock().await = Some(active_task_id);
    let session_id = task.session_id.or(linked_session_id);

    // #5: Redis set_task_sandbox (Python L382-384)
    if let Some(coord) = redis_coord {
        let _ = coord
            .map_task_to_sandbox(active_task_id, sandbox_db_id)
            .await;
    }

    // #1: Replay pending control inputs from DB (Python L409-428)
    // Query unprocessed events from DB (tool_confirmation, custom_tool_result, interrupt)
    if let Some(sid) = session_id {
        let pending: Vec<(Uuid, Option<serde_json::Value>)> = sqlx::query_as(
            r#"
            SELECT id, payload FROM joysafeter_session_events
            WHERE session_id = $1
              AND event_type IN ('user.tool_confirmation', 'user.custom_tool_result', 'user.interrupt')
              AND processed_at IS NULL
            ORDER BY created_at ASC
            "#,
        )
        .bind(sid)
        .fetch_all(pool)
        .await
        .unwrap_or_default();

        for (event_id, payload) in &pending {
            let content = payload
                .as_ref()
                .and_then(|p| p.get("content"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let input_msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Input(proto::SendInput {
                    content,
                })),
            };
            let _ = tx.send(input_msg).await;
            // Mark as processed
            let _ = sqlx::query(
                "UPDATE joysafeter_session_events SET processed_at = NOW() WHERE id = $1",
            )
            .bind(event_id)
            .execute(pool)
            .await;
            info!(task_id = %active_task_id, event_id = %event_id, "Replayed unprocessed DB event on reconnect");
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

    // Emit session.status_running
    if let Some(sid) = session_id {
        let envelope = EventEnvelope::new(
            sid,
            "session.status_running",
            json!({"task_id": active_task_id.to_string()}),
        )
        .with_task(active_task_id)
        .with_sandbox(sandbox_db_id)
        .status_change(None);
        event_bus.publish(envelope).await;
    }

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
        session_id,
        sandbox_db_id,
        heartbeat_timeout,
        memory_subscribers.clone(),
        bridge_registry,
        &task_cancel,
    )
    .await;

    // Clear task on bridge
    *bridge.current_task_id.lock().await = None;
    bridge
        .requires_action_pending
        .store(false, Ordering::Relaxed);
    bridge.reset_confirmation();
    let _ = queries::transition_sandbox(pool, sandbox_db_id, "idle").await;

    match result {
        TaskResult::Completed => {
            info!(task_id = %active_task_id, "Reconnected task completed");
        }
        TaskResult::Failed(ref reason) => {
            // #6: failover_or_fail_task on reconnect failure (Python L824-835)
            warn!(task_id = %active_task_id, "Reconnected task failed: {reason}");
            failover_or_fail_inline(pool, active_task_id, session_id, reason).await;
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
            failover_or_fail_inline(pool, active_task_id, session_id, "runner disconnected").await;
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
    *bridge.current_task_id.lock().await = Some(active_task_id);
}

async fn rescue_orphaned_tasks(pool: &PgPool, sandbox_db_id: Uuid, queue: &TaskQueue) {
    match queries::find_running_tasks_for_sandbox(pool, sandbox_db_id).await {
        Ok(tasks) => {
            for task in tasks {
                if let Ok(true) = queries::increment_retry(pool, task.id).await {
                    // Fix 6.2: actually push to global queue (was just logging before)
                    queue.push_to_global(task.id).await;
                    info!(task_id = %task.id, "Orphaned task reset and re-queued");
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
) {
    let Some(session_id) = session_id else {
        return;
    };

    let signature = match session_files_signature(pool, session_id).await {
        Ok(value) => value,
        Err(e) => {
            warn!(session_id = %session_id, "Failed to load session file signature: {e}");
            return;
        }
    };
    if signature.is_empty() {
        *bridge.injected_session_files_signature.lock().await = Some(signature);
        return;
    }

    {
        let current = bridge.injected_session_files_signature.lock().await;
        if current.as_deref() == Some(signature.as_str()) {
            return;
        }
    }

    let ctx = crate::sandbox::file_injection::FileInjectionContext {
        session_id,
        external_id: sandbox_external_id.to_string(),
        workspace_path: None,
        runner_capabilities: vec![],
        is_pool_sandbox: true,
    };

    match crate::sandbox::file_injection::inject_session_files(pool, &ctx, provider.as_ref()).await
    {
        Ok(files) => {
            *bridge.injected_session_files_signature.lock().await = Some(signature);
            info!(
                session_id = %session_id,
                sandbox_id = %sandbox_external_id,
                file_count = files.len(),
                "Injected updated session files before StartTask"
            );
        }
        Err(e) => {
            warn!(
                session_id = %session_id,
                sandbox_id = %sandbox_external_id,
                "Failed to inject updated session files before StartTask: {e}"
            );
        }
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

async fn send_setup(
    pool: &PgPool,
    _bridge: &Arc<SandboxBridge>,
    sandbox_db_id: Uuid,
    tx: &mpsc::Sender<OrchestratorMessage>,
) -> anyhow::Result<()> {
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
        warn!(sandbox_id = %sandbox_db_id, "Timed out waiting for session link, skipping setup");
        return Ok(());
    };

    let Some(session) = queries::get_session(pool, session_id).await? else {
        return Ok(());
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
        output: None,
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

    Ok(())
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

    let retry_candidates: Vec<(Uuid, i32)> = sqlx::query_as(
        r#"
        SELECT id, retry_count FROM joysafeter_tasks
        WHERE sandbox_id = $1 AND status = 'scheduling'
        ORDER BY created_at ASC
        LIMIT 50
        "#,
    )
    .bind(sandbox_db_id)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Step 3: Reset scheduling tasks for this sandbox back to pending
    match queries::reset_sandbox_tasks_to_pending(pool, sandbox_db_id).await {
        Ok(count) if count > 0 => {
            info!(sandbox_id = %sandbox_db_id, count, "Step 3: Reset tasks to pending");
        }
        _ => {}
    }

    // Step 4: Drain sandbox wakeup queue. Task recovery is DB-driven.
    if let Some(q) = queue {
        let _ = q.drain(sandbox_db_id).await;
    }

    // Step 5: Schedule delayed retry for each task reset in Step 3 (Python L2185-2201)
    if let Some(q) = queue {
        for (tid, retry_count) in retry_candidates {
            let delay = compute_retry_delay(retry_count as u32, tid, config);
            let q_clone = q.clone();
            tokio::spawn(async move {
                tokio::time::sleep(delay).await;
                q_clone.push_to_global(tid).await;
            });
        }
    }

    // Step 6: Remove Redis sandbox owner + queue keys (Python L2203-2207)
    if let Some(coord) = redis_coord {
        let _ = coord.remove_sandbox(sandbox_db_id).await;
        let _ = coord.remove_sandbox_queue(sandbox_db_id).await;
    }

    // #19: Step 7 — use has_retries (pending tasks exist) to decide rescheduling vs idle
    if let Some(sid) = session_id {
        if let Ok(Some(session)) = queries::get_session(pool, sid).await {
            let current = session.status.as_str();
            if current == "running" || current == "rescheduling" {
                // Check if there are pending tasks (= retries exist)
                let has_retries: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM joysafeter_tasks WHERE chat_session_id = $1 AND status = 'pending')"
                )
                .bind(sid)
                .fetch_one(pool)
                .await
                .unwrap_or(false);

                let (new_sess_status, stop_reason) = if has_retries {
                    ("rescheduling", json!({"type": "sandbox_failed"}))
                } else if current != "idle" {
                    // Sandbox lifetime is independent from session lifetime. If a
                    // sandbox disappears after a turn, keep the session reusable;
                    // the next user.message will resolve a fresh sandbox.
                    ("idle", json!({"type": "sandbox_disconnected"}))
                } else {
                    // Session already idle, skip
                    ("idle", json!({"type": "end_turn"}))
                };

                if new_sess_status != "idle" || current != "idle" {
                    let _ = queries::update_session_status(
                        pool,
                        sid,
                        new_sess_status,
                        Some(&stop_reason),
                    )
                    .await;

                    let event_type = format!("session.status_{new_sess_status}");
                    let _ = sqlx::query(
                        r#"
                        INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, created_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        "#,
                    )
                    .bind(Uuid::now_v7())
                    .bind(sid)
                    .bind(&event_type)
                    .bind(&stop_reason)
                    .execute(pool)
                    .await;

                    info!(sandbox_id = %sandbox_db_id, session_id = %sid, status = new_sess_status, "Step 7: Session status updated");
                }
            }
        }
    }

    // Step 8: Memory subscribers are unregistered by the session owner after
    // bridge/grace-period cleanup, matching Python's unregister_session path.

    // Step 9: Teardown networking (if Envoy was used)
    // (Envoy teardown happens via EnvoyManager when sandbox is removed)

    info!(sandbox_id = %sandbox_db_id, "Sandbox cleanup complete (9 steps)");
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

    if let Err(e) = sqlx::query("SELECT id FROM joysafeter_memory_stores WHERE id = $1 FOR UPDATE")
        .bind(store_id)
        .execute(&mut *tx)
        .await
    {
        error!(error = %e, "Memory store lock failed");
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

/// #18: Inline failover_or_fail_task — checks agent output, retries, or marks failed.
/// Matches Python TaskController.failover_or_fail_task (L274-337).
async fn failover_or_fail_inline(
    pool: &PgPool,
    task_id: Uuid,
    session_id: Option<Uuid>,
    reason: &str,
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
            let _ = queries::transition_task(pool, task_id, "completed", None).await;
            let _ = queries::update_session_status(
                pool,
                sid,
                "idle",
                Some(&serde_json::json!({"type":"end_turn"})),
            )
            .await;
            info!(task_id = %task_id, "Failover: task had output, marking completed + session idle");
            return;
        }
    }

    // Retry or fail
    let max_retries = task.max_retries as u32;
    let current = task.retry_count as u32;
    if current < max_retries {
        let _ = queries::increment_retry(pool, task_id).await;
        info!(task_id = %task_id, retry = current + 1, "Failover: task will be retried");
    } else {
        let _ = queries::transition_task(pool, task_id, "failed", Some(reason)).await;
        warn!(task_id = %task_id, "Failover: task failed after {max_retries} retries: {reason}");
    }
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
) -> proto::StartTask {
    let timeout_seconds = task
        .timeout_sec
        .unwrap_or(config.task_default_timeout as i32) as u64;
    let builder = HarnessInputBuilder::new(pool.clone());
    match builder
        .build(task, &sandbox_db_id.to_string(), sandbox_db_id)
        .await
    {
        Ok(input) => HarnessInputBuilder::build_start_task(&input, task, timeout_seconds),
        Err(e) => {
            error!(task_id = %task.id, "Failed to build harness input, falling back to minimal StartTask: {e}");
            let work_dir = if task.session_id.is_some() {
                "/workspace".to_string()
            } else {
                sandbox_db_id.to_string()
            };
            proto::StartTask {
                task_id: task.id.to_string(),
                provider: "claude".to_string(),
                prompt: task.prompt.clone(),
                system_prompt: task.system_prompt.clone(),
                session_id: None,
                model: None,
                max_turns: Some(100),
                timeout_seconds,
                env: HashMap::new(),
                secrets: HashMap::new(),
                mcp_servers: vec![],
                repos: vec![],
                work_dir: Some(work_dir),
                skills: vec![],
                allowed_tools: vec![],
                disallowed_tools: vec![],
                ask_tools: vec![],
                permission_mode: None,
                setup_commands: vec![],
                custom_tools: vec![],
            }
        }
    }
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
