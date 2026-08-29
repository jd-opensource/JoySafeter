use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use sqlx::PgPool;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::events::bus::EventBus;
use crate::events::envelope::EventEnvelope;
use crate::grpc::proto::OrchestratorMessage;
use crate::ids::{SandboxId, SessionId, TaskId};
use crate::kernel::queue::TaskQueue;
use crate::kernel::sandbox_bridge::SandboxBridge;

/// Result of a single task execution.
#[derive(Clone, Debug)]
pub(crate) enum TaskResult {
    Completed,
    Failed(String),
    Timeout,
    Cancelled,
    Disconnected,
}

pub(crate) async fn emit_session_running_status(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: TaskId,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) async fn emit_session_idle_status(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: TaskId,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) async fn transition_running_task_and_emit_idle(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) async fn handle_task_disconnect_before_result(
    pool: &PgPool,
    event_bus: &EventBus,
    bridge: &Arc<SandboxBridge>,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) fn task_result_from_status(status: &str, error: Option<&str>) -> Option<TaskResult> {
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

pub(crate) async fn load_terminal_task_result(
    pool: &PgPool,
    task_id: TaskId,
) -> Option<TaskResult> {
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

pub(crate) async fn fail_pre_start_task(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) async fn send_start_task_or_handle_failure(
    pool: &PgPool,
    event_bus: &EventBus,
    tx: &mpsc::Sender<OrchestratorMessage>,
    task: &crate::db::models::JoySafeterTask,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) async fn handle_dispatch_retryable_failure(
    pool: &PgPool,
    event_bus: &EventBus,
    task: &crate::db::models::JoySafeterTask,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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
/// Applies the authoritative retry-or-fail transition for a lost task runtime.
pub(crate) async fn failover_or_fail_inline(
    pool: &PgPool,
    event_bus: &EventBus,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    session_id: Option<SessionId>,
    sandbox_db_id: SandboxId,
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

pub(crate) fn compute_stop_reason(status: Option<&str>, error: Option<&str>) -> serde_json::Value {
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

pub(crate) fn compute_retry_delay(
    retry_count: u32,
    task_id: TaskId,
    config: &JoySafeterConfig,
) -> Duration {
    let exponent = retry_count.min(14);
    let delay_ms = config
        .task_retry_base_ms
        .saturating_mul(2u64.saturating_pow(exponent))
        .min(config.task_retry_max_ms);
    let jitter_ms = if delay_ms > 0 {
        (task_id.as_uuid().as_u128() % (delay_ms / 4 + 1) as u128) as u64
    } else {
        0
    };
    Duration::from_millis(delay_ms.saturating_add(jitter_ms))
}
