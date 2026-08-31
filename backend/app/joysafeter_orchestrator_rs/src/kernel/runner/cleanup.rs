use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use sqlx::PgPool;
use tracing::{error, info, warn};

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{SandboxId, SessionId};
use crate::kernel::ha::BridgeStore;
use crate::kernel::queue::TaskQueue;

use super::task_lifecycle::compute_retry_delay;

#[derive(Clone, Default)]
pub(crate) struct RunnerCleanupService;

impl RunnerCleanupService {
    pub(crate) fn new() -> Self {
        Self
    }

    pub(crate) async fn cleanup_sandbox(
        &self,
        pool: &PgPool,
        sandbox_db_id: SandboxId,
        session_id: Option<SessionId>,
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
                queries::transition_sandbox_cas(pool, sandbox_db_id, current_status, new_status)
                    .await;
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
        Self::persist_failed_tasks_idle(pool, &failed_tasks, failure_reason).await;

        // Step 3: Reset retryable scheduling tasks for this sandbox back to pending
        let reset_tasks = match queries::reset_sandbox_tasks_to_pending_returning(
            pool,
            sandbox_db_id,
        )
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
        Self::persist_reset_tasks_rescheduling(pool, &reset_tasks).await;

        // Step 4: Drain sandbox wakeup queue. Task recovery is DB-driven.
        if let Some(q) = queue {
            let _ = q.drain(sandbox_db_id).await;
        }

        // Step 5: Schedule delayed retry for each task reset in Step 3.
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

        // Step 6: Remove the Redis queue key. Runner ownership is released by
        // the connection-generation-fenced BridgeStore teardown path.
        if let Some(coord) = redis_coord {
            let _ = coord.remove_sandbox_queue(sandbox_db_id).await;
        }

        // Step 7: If no task-specific retry/failure transition happened,
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
        // bridge/grace-period cleanup.

        // Step 9: Teardown networking (if Envoy was used)
        // Network-policy teardown is owned by the shared sandbox lifecycle service.

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
    pub(crate) async fn probe_and_cleanup(
        &self,
        pool: &PgPool,
        sandbox_db_id: SandboxId,
        session_id: Option<SessionId>,
        failure_ejected: bool,
        bridge_store: Arc<dyn BridgeStore>,
        queue: Option<&TaskQueue>,
        redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
        config: &JoySafeterConfig,
    ) {
        // First probe after 3s
        tokio::time::sleep(Duration::from_secs(3)).await;
        if bridge_store
            .get_owner_instance(sandbox_db_id)
            .await
            .is_some()
        {
            info!(sandbox_id = %sandbox_db_id, "Reconnection detected (3s)");
            return;
        }

        // Second probe after 2 more seconds
        tokio::time::sleep(Duration::from_secs(2)).await;
        if bridge_store
            .get_owner_instance(sandbox_db_id)
            .await
            .is_some()
        {
            info!(sandbox_id = %sandbox_db_id, "Reconnection detected (5s)");
            return;
        }

        // Early reconnection checks at 5s intervals (cumulative: 10, 15)
        for i in 0..2 {
            tokio::time::sleep(Duration::from_secs(5)).await;
            if bridge_store
                .get_owner_instance(sandbox_db_id)
                .await
                .is_some()
            {
                info!(sandbox_id = %sandbox_db_id, check = i + 2, "Reconnection detected during grace period");
                return;
            }
        }

        // Remaining grace period: 120 - 15 = 105s
        info!(sandbox_id = %sandbox_db_id, "Entering remaining 105s grace period");
        tokio::time::sleep(Duration::from_secs(105)).await;

        // Final check
        if bridge_store
            .get_owner_instance(sandbox_db_id)
            .await
            .is_some()
        {
            info!(sandbox_id = %sandbox_db_id, "Reconnection detected at end of grace period");
            return;
        }

        warn!(sandbox_id = %sandbox_db_id, "Grace period expired (120s), executing cleanup");
        self.cleanup_sandbox(
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
}
