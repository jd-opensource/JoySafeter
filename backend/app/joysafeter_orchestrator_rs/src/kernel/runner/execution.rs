use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use sqlx::PgPool;
use tokio::sync::{mpsc, Semaphore};
use tokio::time::Instant;
use tonic::Streaming;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::events::bus::EventBus;
use crate::events::envelope::EventEnvelope;
use crate::events::mapping;
use crate::grpc::proto;
use crate::grpc::proto::{
    orchestrator_message, runner_message, OrchestratorMessage, RunnerMessage,
};
use crate::ids::{EventId, SandboxId, SessionId, TaskId};
use crate::kernel::ha::BridgeStore;
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::SandboxBridge;
use crate::kernel::sandbox_resolver::SandboxIdentityPolicy;
use crate::runtime_config::RuntimeConfig;

use super::memory_sync::handle_memory_sync_db;
use super::setup::{
    build_start_task_full, is_setup_failure_error, is_setup_failure_result,
    is_setup_failure_task_result, mark_idle_setup_failure, send_setup,
};
use super::task_lifecycle::{
    compute_stop_reason, emit_session_idle_status, emit_session_running_status,
    fail_pre_start_task, failover_or_fail_inline, handle_dispatch_retryable_failure,
    handle_task_disconnect_before_result, load_terminal_task_result,
    send_start_task_or_handle_failure, task_result_from_status,
    transition_running_task_and_emit_idle, TaskResult,
};

const HEARTBEAT_TIMEOUT_DEFAULT: u64 = 120;
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

/// Owns process-local concurrency state for Runner task execution.
pub(crate) struct RunnerExecutionService {
    semaphore: Arc<Semaphore>,
}

impl RunnerExecutionService {
    pub(crate) fn new(max_executions: usize) -> Self {
        Self {
            semaphore: Arc::new(Semaphore::new(max_executions)),
        }
    }

    pub(crate) fn semaphore(&self) -> Arc<Semaphore> {
        self.semaphore.clone()
    }
}

// ---------------------------------------------------------------------------
// Multi-task loop
// ---------------------------------------------------------------------------

pub(crate) async fn multi_task_loop(
    inbound: &mut Streaming<RunnerMessage>,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    event_bus: &EventBus,
    queue: &TaskQueue,
    config: &JoySafeterConfig,
    identity_policy: &Arc<dyn SandboxIdentityPolicy>,
    sandbox_db_id: SandboxId,
    sandbox_external_id: &str,
    linked_session_id: Option<SessionId>,
    exec_sem: &Arc<Semaphore>,
    redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_store: Arc<dyn BridgeStore>,
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
                                        if let Err(error) = bridge
                                            .record_runner_heartbeat(
                                                &heartbeat.runtime_state,
                                                heartbeat.active_task_id.as_deref(),
                                                heartbeat.harness_session_id.clone(),
                                            )
                                            .await
                                        {
                                            warn!(sandbox_id = %sandbox_db_id, error = %error, "Ignoring invalid runner heartbeat task id");
                                        }
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

        // Acquire execution capacity and handle shutdown without panicking.
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

        // The durable task row must still be running after the claim.
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

        // Register the task-to-sandbox coordination mapping.
        if let Some(coord) = redis_coord {
            let _ = coord.map_task_to_sandbox(task_id, sandbox_db_id).await;
        }

        let session_id = task.session_id.or(linked_session_id);

        // Revalidate that the referenced agent still exists before dispatch.
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
            match send_setup(pool, bridge, sandbox_db_id, tx, config.envoy_enabled).await {
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
            bridge_store.clone(),
            identity_policy.as_ref(),
            &task_cancel,
            Some(queue),
        )
        .await;

        if !matches!(result, TaskResult::Disconnected) {
            if let Err(error) = identity_policy.clear_policy(sandbox_db_id, task_id).await {
                error!(
                    sandbox_id = %sandbox_db_id,
                    task_id = %task_id,
                    error = %error,
                    "Agent Identity policy cleanup failed closed"
                );
            }
        }

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

        // Remove the task-to-sandbox mapping and publish completion.
        if let Some(coord) = redis_coord {
            // Publish the completion event to Redis.
            let complete_payload =
                serde_json::to_string(&json!({"type": "complete", "task_id": task_id.to_string()}))
                    .unwrap_or_default();
            let _ = coord.publish_task_event(task_id, &complete_payload).await;
            let _ = coord.remove_task_sandbox(task_id).await;
            // Refresh the sandbox ownership TTL.
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

#[derive(Default)]
pub(crate) struct TaskMessageOutcome {
    pub(crate) task_done: bool,
    pub(crate) runner_idle_seen: bool,
    pub(crate) terminal_idle_handled: bool,
    pub(crate) task_result: Option<TaskResult>,
}
pub(crate) async fn handle_task_setup_failure_result(
    harness_result: &proto::RunnerHarnessResult,
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

// ---------------------------------------------------------------------------
// Single task event loop — with HITL support
// ---------------------------------------------------------------------------

pub(crate) async fn run_single_task(
    inbound: &mut Streaming<RunnerMessage>,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    event_bus: &EventBus,
    config: &JoySafeterConfig,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
    heartbeat_timeout: Duration,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_store: Arc<dyn BridgeStore>,
    identity_policy: &dyn SandboxIdentityPolicy,
    task_cancel: &tokio_util::sync::CancellationToken,
    queue: Option<&TaskQueue>,
) -> TaskResult {
    // Prefer the persisted per-task timeout, falling back to the configured default.
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
        match crate::kernel::run_spec::agent_for_execution(live_agent, session.as_ref()) {
            Ok(Some(agent)) => crate::kernel::harness_input_builder::extract_tool_name_sets(&agent),
            Ok(None) => (
                std::collections::HashSet::new(),
                std::collections::HashSet::new(),
            ),
            Err(error) => {
                return TaskResult::Failed(format!(
                    "invalid persisted agent snapshot for task {task_id}: {error}"
                ));
            }
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
    let mut identity_refresh_deadline = identity_policy
        .refresh_delay(sandbox_db_id, task_id)
        .await
        .ok()
        .flatten()
        .map(|delay| Instant::now() + delay);

    loop {
        // Build select branches based on HITL state
        tokio::select! {
            _ = tokio::time::sleep_until(
                identity_refresh_deadline.unwrap_or_else(|| Instant::now() + Duration::from_secs(86_400))
            ), if identity_refresh_deadline.is_some() => {
                match identity_policy
                    .refresh_policy(task_id, sandbox_db_id)
                    .await
                {
                    Ok(Some(seconds)) => {
                        identity_refresh_deadline =
                            Some(Instant::now() + Duration::from_secs(seconds.max(1)));
                    }
                    Ok(None) => identity_refresh_deadline = None,
                    Err(error) => {
                        error!(
                            sandbox_id = %sandbox_db_id,
                            task_id = %task_id,
                            error = %error,
                            "Agent Identity refresh failed; cancelling task fail-closed"
                        );
                        let reason = "Agent Identity credential refresh failed";
                        let _ = tx
                            .send(OrchestratorMessage {
                                payload: Some(orchestrator_message::Payload::Cancel(
                                    proto::CancelTask { reason: reason.to_string() },
                                )),
                            })
                            .await;
                        let transitioned = transition_running_task_and_emit_idle(
                            pool,
                            event_bus,
                            task_id,
                            expected_owner_epoch,
                            session_id,
                            sandbox_db_id,
                            "failed",
                            Some(reason),
                            json!({"type": "error", "message": reason, "code": "AGENT_IDENTITY_REFRESH_FAILED"}),
                            "agent identity refresh",
                        )
                        .await;
                        if transitioned {
                            return TaskResult::Failed(reason.to_string());
                        }
                        if let Some(result) = load_terminal_task_result(pool, task_id).await {
                            return result;
                        }
                        return TaskResult::Failed(reason.to_string());
                    }
                }
                continue;
            }

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

            // On heartbeat timeout, flush pending events before durable failover.
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
                            memory_subscribers.clone(), bridge_store.clone(),
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

    // Finalize the durable task, sandbox, usage, and subscriber state.
    if !task_done {
        // A stream break before Result follows the durable failover policy.
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
pub(crate) async fn handle_task_message(
    msg: &RunnerMessage,
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
    _tx: &mpsc::Sender<OrchestratorMessage>,
    requires_action_pending: &mut bool,
    buffered_events: &mut Vec<(String, serde_json::Value)>,
    task_completed: &mut bool,
    task_error: &mut bool,
    custom_names: &std::collections::HashSet<String>,
    mcp_names: &std::collections::HashSet<String>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    bridge_store: Arc<dyn BridgeStore>,
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

                    // Preserve the latest runner error on the bridge.
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
                        let event_id = EventId::from_uuid(Uuid::now_v7());
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
                            "event_ids": [event_id.to_public()]
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

            // Persist output and usage only when the terminal CAS succeeds.
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

            // Return the sandbox to idle and clear its active task binding.
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

            // Broadcast completion to per-task subscribers.
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
                .record_runner_heartbeat("idle", None, idle_msg.harness_session_id.clone())
                .await
                .expect("idle heartbeat has no task id");

            // Update sandbox DB status
            let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

            // Update session sandbox info
            if let Some(sid) = session_id {
                let harness_session_id = idle_msg.harness_session_id.as_deref();
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
            if let Err(error) = bridge
                .record_runner_heartbeat(
                    &heartbeat.runtime_state,
                    heartbeat.active_task_id.as_deref(),
                    heartbeat.harness_session_id.clone(),
                )
                .await
            {
                warn!(task_id = %task_id, error = %error, "Ignoring invalid runner heartbeat task id");
            }
            debug!(task_id = %task_id, "Heartbeat");
            TaskMessageOutcome::default()
        }

        runner_message::Payload::MemorySync(sync_msg) => {
            // Memory sync with path traversal protection + DB write
            let pool_clone = pool.clone();
            let memory_subscribers = memory_subscribers.clone();
            let bridge_store = bridge_store.clone();
            let session_id_clone = session_id;
            let mount_name = sync_msg.store_mount_name.clone();
            let rel_path = sync_msg.relative_path.clone();
            let content = sync_msg.content.clone();
            let operation = sync_msg.operation.clone();

            // Persist memory synchronization without blocking the runner stream.
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
                        &*bridge_store,
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
    event_id: EventId,
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

pub(crate) async fn replay_pending_control_inputs(
    pool: &PgPool,
    session_id: SessionId,
    tx: &mpsc::Sender<OrchestratorMessage>,
    active_task_id: TaskId,
) -> Result<usize, sqlx::Error> {
    let pending: Vec<(EventId, String, Option<serde_json::Value>)> = sqlx::query_as(
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
