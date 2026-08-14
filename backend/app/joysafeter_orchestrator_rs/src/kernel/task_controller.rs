use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{AgentId, SandboxId, SessionId, TaskId};
use crate::kernel::ha::BridgeStore;
use crate::kernel::queue::TaskQueue;

/// Task lifecycle watchdog with full Python parity.
///
/// Handles:
/// - Startup recovery with pg_advisory_lock
/// - Periodic overdue task detection with session transition
/// - Stuck scheduling detection (2-minute threshold)
/// - scan_pending_tasks re-enqueue on startup
/// - Agent output check before failover
/// - Failover/retry with exponential backoff + jitter
pub struct TaskController {
    pool: PgPool,
    queue: TaskQueue,
    config: JoySafeterConfig,
    bridge_store: Arc<dyn BridgeStore>,
}

impl TaskController {
    pub fn new(
        pool: PgPool,
        queue: TaskQueue,
        config: JoySafeterConfig,
        bridge_store: Arc<dyn BridgeStore>,
    ) -> Self {
        Self {
            pool,
            queue,
            config,
            bridge_store,
        }
    }

    /// Run startup recovery with transaction-scoped advisory lock.
    pub async fn recover_on_startup(&self) -> anyhow::Result<()> {
        info!("TaskController: running startup recovery...");

        // Use transaction-scoped advisory lock (auto-releases on commit/rollback)
        let mut tx = self.pool.begin().await?;
        let locked: (bool,) =
            sqlx::query_as("SELECT pg_try_advisory_xact_lock(hashtext('task_recovery'))")
                .fetch_one(&mut *tx)
                .await?;
        if !locked.0 {
            tx.commit().await?;
            info!("TaskController: another instance is running recovery, skipping");
            return Ok(());
        }

        // Lock acquired — commit to release the advisory lock.
        // Recovery queries below are idempotent, so running without the lock
        // held is safe. The lock only prevents two instances from starting
        // recovery simultaneously.
        tx.commit().await?;

        let recovery_result: anyhow::Result<()> = async {
            // Python parity: only running tasks that exceeded their own timeout are failed.
            let recovered_tasks: Vec<(TaskId, Option<SessionId>, Option<SandboxId>, Option<i64>)> = sqlx::query_as(
                r#"
                SELECT id, chat_session_id, sandbox_id, owner_epoch FROM joysafeter_tasks
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND started_at + (COALESCE(timeout_sec, 7200) * INTERVAL '1 second') < NOW()
                "#,
            )
            .fetch_all(&self.pool)
            .await?;

            for (task_id, session_id, sandbox_id, owner_epoch) in &recovered_tasks {
                self.fail_task_and_mark_session_idle(
                    *task_id,
                    *session_id,
                    *sandbox_id,
                    *owner_epoch,
                    "Orchestrator restarted - task was running when process exited",
                )
                .await;
            }

            // DB pending tasks are the durable source of truth; enqueue all on startup.
            let pending_tasks = queries::find_pending_tasks(&self.pool, 500).await?;
            for (task_id,) in &pending_tasks {
                if let Err(e) = self.queue.push_to_global(*task_id).await {
                    warn!(task_id = %task_id, error = %e, "Failed to re-enqueue pending task");
                }
            }

            // Scheduling tasks -> pending (unconditional, retry increment), matching Python.
            let scheduling_tasks: Vec<(TaskId, Option<SessionId>, Option<SandboxId>, i32, i32)> =
                sqlx::query_as(
                    r#"
                    SELECT id, chat_session_id, sandbox_id, retry_count, max_retries
                    FROM joysafeter_tasks
                    WHERE status = 'scheduling'
                    "#,
                )
                    .fetch_all(&self.pool)
                    .await?;
            for (task_id, session_id, sandbox_id, retry_count, max_retries) in &scheduling_tasks {
                if retry_count >= max_retries {
                    self.fail_scheduling_task_and_mark_session_idle(
                        *task_id,
                        *session_id,
                        *sandbox_id,
                        "scheduling stuck after max retries",
                    )
                    .await;
                } else if self
                    .retry_scheduling_task_and_mark_session_rescheduling(
                        *task_id,
                        *session_id,
                        *sandbox_id,
                        *retry_count,
                    )
                    .await
                {
                    // T9 fix: push to global queue so they don't wait 60s for scan
                    if let Err(e) = self.queue.push_to_global(*task_id).await {
                        warn!(task_id = %task_id, error = %e, "Failed to re-enqueue scheduling task");
                    }
                }
            }

            // Provisioning sandboxes: 45min with Redis configured, 20min without.
            let provisioning_minutes: i32 = if self.config.redis_url.is_some() {
                45
            } else {
                20
            };
            let stale_provisioning: Vec<(SandboxId,)> = sqlx::query_as(
                r#"
                SELECT id FROM joysafeter_sandboxes
                WHERE status = 'provisioning'
                  AND created_at < NOW() - ($1 * INTERVAL '1 minute')
                "#,
            )
            .bind(provisioning_minutes)
            .fetch_all(&self.pool)
            .await?;
            for (sandbox_id,) in &stale_provisioning {
                let _ = queries::transition_sandbox_cas(
                    &self.pool,
                    *sandbox_id,
                    "provisioning",
                    "stopped",
                )
                .await;
            }

            // Reset sessions stuck in 'rescheduling'.
            let stale_rescheduling_sessions: Vec<(SessionId,)> = sqlx::query_as(
                r#"
                SELECT id FROM joysafeter_sessions
                WHERE status = 'rescheduling'
                  AND updated_at < NOW() - INTERVAL '5 minutes'
                  AND NOT EXISTS (
                      SELECT 1 FROM joysafeter_tasks
                      WHERE joysafeter_tasks.chat_session_id = joysafeter_sessions.id
                        AND joysafeter_tasks.status IN ('pending', 'scheduling', 'running')
                  )
                "#,
            )
            .fetch_all(&self.pool)
            .await?;
            for (session_id,) in &stale_rescheduling_sessions {
                let stop_reason = serde_json::json!({"type":"retries_exhausted"});
                let payload = serde_json::json!({"stop_reason": stop_reason.clone()});
                let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                    &self.pool,
                    *session_id,
                    "terminated",
                    Some(&stop_reason),
                    "session.status_terminated",
                    &payload,
                )
                .await;
            }

            // Reset running sessions only when stale and no active task remains.
            let stale_running_sessions: Vec<(SessionId,)> = sqlx::query_as(
                r#"
                SELECT id FROM joysafeter_sessions
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL '5 minutes'
                  AND NOT EXISTS (
                      SELECT 1 FROM joysafeter_tasks
                      WHERE joysafeter_tasks.chat_session_id = joysafeter_sessions.id
                        AND joysafeter_tasks.status IN ('pending', 'scheduling', 'running')
                  )
                "#,
            )
            .fetch_all(&self.pool)
            .await?;
            for (session_id,) in &stale_running_sessions {
                let stop_reason = serde_json::json!({"type":"end_turn"});
                let payload = serde_json::json!({"stop_reason": stop_reason.clone()});
                let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                    &self.pool,
                    *session_id,
                    "idle",
                    Some(&stop_reason),
                    "session.status_idle",
                    &payload,
                )
                .await;
            }

            info!(
                tasks_failed = recovered_tasks.len(),
                pending_requeued = pending_tasks.len(),
                scheduling_reset = scheduling_tasks.len(),
                provisioning_recovered = stale_provisioning.len(),
                rescheduling_sessions_terminated = stale_rescheduling_sessions.len(),
                running_sessions_reset = stale_running_sessions.len(),
                redis_available = self.config.redis_url.is_some(),
                "TaskController: startup recovery complete"
            );
            Ok(())
        }
        .await;

        recovery_result
    }

    /// Spawn the periodic check loop.
    pub fn spawn(self) -> JoinHandle<()> {
        tokio::spawn(async move {
            let interval = Duration::from_secs(self.config.task_lease_renew_interval_sec.max(1));
            info!(
                interval_seconds = self.config.task_lease_renew_interval_sec.max(1),
                "TaskController check loop started"
            );

            loop {
                tokio::time::sleep(interval).await;

                if let Err(e) = self.renew_running_task_leases().await {
                    error!("Running task lease renewal failed: {e}");
                }

                if let Err(e) = self.check_lease_expired_tasks().await {
                    error!("Lease-expired task check failed: {e}");
                }

                if let Err(e) = self.check_overdue_tasks().await {
                    error!("Overdue task check failed: {e}");
                }

                if let Err(e) = self.check_stuck_scheduling().await {
                    error!("Stuck scheduling check failed: {e}");
                }

                // #14: Periodic scan_pending_tasks (Python L247-271)
                if let Err(e) = self.scan_pending_tasks().await {
                    error!("Scan pending tasks failed: {e}");
                }
            }
        })
    }

    async fn active_task_ids(&self) -> Vec<TaskId> {
        let mut active_task_ids = Vec::new();
        for bridge in self.bridge_store.all_bridges() {
            if let Some(task_id) = *bridge.current_task_id.lock().await {
                active_task_ids.push(task_id);
            }
        }
        active_task_ids
    }

    async fn active_task_leases(&self) -> Vec<(TaskId, i64)> {
        let mut active_task_leases = Vec::new();
        for bridge in self.bridge_store.all_bridges() {
            let task_id = *bridge.current_task_id.lock().await;
            let owner_epoch = *bridge.current_task_owner_epoch.lock().await;
            if let (Some(task_id), Some(owner_epoch)) = (task_id, owner_epoch) {
                active_task_leases.push((task_id, owner_epoch));
            }
        }
        active_task_leases
    }

    async fn renew_running_task_leases(&self) -> anyhow::Result<()> {
        let active_task_leases = self.active_task_leases().await;
        let renewed = queries::renew_running_task_leases(
            &self.pool,
            &self.config.instance_id,
            self.config.task_lease_ttl_sec,
            &active_task_leases,
        )
        .await?;
        debug!(
            renewed,
            active = active_task_leases.len(),
            "Renewed running task leases"
        );
        Ok(())
    }

    async fn check_lease_expired_tasks(&self) -> anyhow::Result<()> {
        let expired = queries::find_lease_expired_running_tasks(&self.pool, 20).await?;
        for task in expired {
            let task_id = &task.id;
            let reason = "task ownership lease expired";
            if task.retry_count < task.max_retries {
                if queries::retry_lease_expired_task(&self.pool, *task_id, reason).await? {
                    if let Some(sandbox_id) = task.sandbox_id {
                        let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                    }
                    if let Some(session_id) = task.session_id {
                        let stop_reason =
                            serde_json::json!({"type": "failover", "message": reason});
                        let payload = serde_json::json!({
                            "task_id": task_id.to_string(),
                            "stop_reason": stop_reason.clone(),
                        });
                        let _ = queries::update_session_status_and_insert_event(
                            &self.pool,
                            session_id,
                            "rescheduling",
                            Some(&stop_reason),
                            "session.status_rescheduling",
                            &payload,
                        )
                        .await;
                    }
                    self.queue.push_to_global(*task_id).await?;
                    warn!(task_id = %task_id, "Requeued lease-expired running task");
                }
            } else if queries::fail_lease_expired_task(&self.pool, *task_id, reason).await? {
                if let Some(sandbox_id) = task.sandbox_id {
                    let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                }
                if let Some(session_id) = task.session_id {
                    let stop_reason = serde_json::json!({"type": "error", "message": reason});
                    let payload = serde_json::json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone(),
                    });
                    let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                        &self.pool,
                        session_id,
                        "idle",
                        Some(&stop_reason),
                        "session.status_idle",
                        &payload,
                    )
                    .await;
                }
                warn!(task_id = %task_id, "Failed lease-expired running task");
            }
        }
        Ok(())
    }

    /// Detect tasks that have exceeded their timeout while running.
    /// Uses transaction-scoped advisory lock (auto-releases on commit/rollback).
    async fn check_overdue_tasks(&self) -> anyhow::Result<()> {
        let mut tx = self.pool.begin().await?;

        // Transaction-scoped advisory lock — auto-releases on commit
        let locked: (bool,) =
            sqlx::query_as("SELECT pg_try_advisory_xact_lock(hashtext('task_watchdog'))")
                .fetch_one(&mut *tx)
                .await?;
        if !locked.0 {
            tx.commit().await?;
            return Ok(());
        }

        let overdue: Vec<(TaskId, Option<SessionId>, Option<SandboxId>, Option<i64>)> =
            sqlx::query_as(
                r#"
            SELECT id, chat_session_id, sandbox_id, owner_epoch FROM joysafeter_tasks
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND started_at + (COALESCE(timeout_sec, 7200) * INTERVAL '1 second') < NOW()
            LIMIT 20
            "#,
            )
            .fetch_all(&mut *tx)
            .await?;

        tx.commit().await?;

        // Perform transitions outside the lock transaction (they have their own guards)
        for (task_id, session_id, sandbox_id, owner_epoch) in &overdue {
            warn!(task_id = %task_id, "Task overdue, marking as timeout");
            let transitioned = match queries::transition_task_cas_observed_owner_epoch(
                &self.pool,
                *task_id,
                "running",
                "timeout",
                Some("task exceeded deadline (detected by TaskController)"),
                *owner_epoch,
            )
            .await
            {
                Ok(value) => value,
                Err(e) => {
                    error!(task_id = %task_id, error = %e, "Failed to mark overdue task timeout");
                    false
                }
            };

            if !transitioned {
                warn!(task_id = %task_id, "Overdue task timeout skipped because task was no longer running");
                continue;
            }

            if let Some(sandbox_id) = sandbox_id {
                let _ = queries::complete_sandbox_task(&self.pool, *sandbox_id).await;
            }

            if let Some(sid) = session_id {
                let stop_reason = serde_json::json!({"type":"timeout"});
                let payload = serde_json::json!({
                    "task_id": task_id.to_string(),
                    "stop_reason": stop_reason.clone()
                });
                let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                    &self.pool,
                    *sid,
                    "idle",
                    Some(&stop_reason),
                    "session.status_idle",
                    &payload,
                )
                .await;
            }
        }

        if !overdue.is_empty() {
            info!(count = overdue.len(), "Timed out overdue tasks");
        }

        Ok(())
    }

    /// Detect tasks stuck in 'scheduling' for too long (> 2 minutes).
    async fn check_stuck_scheduling(&self) -> anyhow::Result<()> {
        let mut tx = self.pool.begin().await?;

        let locked: (bool,) = sqlx::query_as(
            "SELECT pg_try_advisory_xact_lock(hashtext('task_scheduling_watchdog'))",
        )
        .fetch_one(&mut *tx)
        .await?;
        if !locked.0 {
            tx.commit().await?;
            return Ok(());
        }

        // T6 fix: also select retry_count and max_retries to avoid
        // infinite re-enqueue past max_retries
        let stuck: Vec<(TaskId, Option<SessionId>, Option<SandboxId>, i32, i32)> = sqlx::query_as(
            r#"
            SELECT id, chat_session_id, sandbox_id, retry_count, max_retries
            FROM joysafeter_tasks
            WHERE status = 'scheduling'
              AND COALESCE(started_at, updated_at) < NOW() - INTERVAL '2 minutes'
            ORDER BY COALESCE(started_at, updated_at) ASC, id ASC
            LIMIT 20
            "#,
        )
        .fetch_all(&mut *tx)
        .await?;

        tx.commit().await?;

        // Transitions outside the lock transaction
        for (task_id, session_id, sandbox_id, retry_count, max_retries) in &stuck {
            if *retry_count >= *max_retries {
                warn!(task_id = %task_id, "Task stuck in scheduling past max_retries, marking failed");
                self.fail_scheduling_task_and_mark_session_idle(
                    *task_id,
                    *session_id,
                    *sandbox_id,
                    "scheduling stuck after max retries",
                )
                .await;
            } else {
                warn!(task_id = %task_id, "Task stuck in scheduling (>2min), resetting to pending");
                if self
                    .retry_scheduling_task_and_mark_session_rescheduling(
                        *task_id,
                        *session_id,
                        *sandbox_id,
                        *retry_count,
                    )
                    .await
                {
                    if let Err(e) = self.queue.push_to_global(*task_id).await {
                        warn!(task_id = %task_id, error = %e, "Failed to re-enqueue stuck scheduling task");
                    }
                }
            }
        }

        if !stuck.is_empty() {
            info!(count = stuck.len(), "Reset stuck scheduling tasks");
        }

        Ok(())
    }

    /// #14: Periodic scan of all pending tasks, push to global queue as wakeup signal.
    async fn scan_pending_tasks(&self) -> anyhow::Result<()> {
        let mut tx = self.pool.begin().await?;

        let locked: (bool,) =
            sqlx::query_as("SELECT pg_try_advisory_xact_lock(hashtext('task_pending_scanner'))")
                .fetch_one(&mut *tx)
                .await?;
        if !locked.0 {
            tx.commit().await?;
            return Ok(());
        }

        let tasks: Vec<(TaskId,)> = sqlx::query_as(
            r#"
            SELECT id FROM joysafeter_tasks
            WHERE status = 'pending'
              AND (next_schedule_at IS NULL OR next_schedule_at <= NOW())
            ORDER BY created_at
            LIMIT 500
            "#,
        )
        .fetch_all(&mut *tx)
        .await?;

        tx.commit().await?;

        for (task_id,) in &tasks {
            if let Err(e) = self.queue.push_to_global(*task_id).await {
                warn!(task_id = %task_id, error = %e, "Failed to re-enqueue scanned pending task");
            }
        }
        if !tasks.is_empty() {
            debug!("Scanned and re-enqueued {} pending tasks", tasks.len());
        }

        Ok(())
    }

    async fn retry_task_and_mark_session_rescheduling(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        sandbox_id: Option<SandboxId>,
        expected_retry_count: Option<i32>,
        expected_owner_epoch: Option<i64>,
    ) -> bool {
        let Some(expected_retry_count) = expected_retry_count else {
            error!(task_id = %task_id, "Running retry requires expected retry count");
            return false;
        };

        match queries::increment_running_retry(
            &self.pool,
            task_id,
            expected_retry_count,
            expected_owner_epoch,
        )
        .await
        {
            Ok(true) => {
                if let Some(sandbox_id) = sandbox_id {
                    let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                }
                if let Some(session_id) = session_id {
                    let stop_reason = serde_json::json!({"type":"sandbox_failed"});
                    let payload = serde_json::json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone()
                    });
                    let _ = queries::update_session_status_and_insert_event(
                        &self.pool,
                        session_id,
                        "rescheduling",
                        Some(&stop_reason),
                        "session.status_rescheduling",
                        &payload,
                    )
                    .await;
                }
                if let Err(e) = self.queue.push_to_global(task_id).await {
                    warn!(task_id = %task_id, error = %e, "Failed to re-enqueue running task after retry");
                }
                true
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Retry skipped because task is no longer running or retry count changed");
                false
            }
            Err(e) => {
                error!(task_id = %task_id, error = %e, "Failed to retry task");
                false
            }
        }
    }

    async fn retry_scheduling_task_and_mark_session_rescheduling(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        sandbox_id: Option<SandboxId>,
        expected_retry_count: i32,
    ) -> bool {
        match queries::increment_scheduling_retry(&self.pool, task_id, expected_retry_count).await {
            Ok(true) => {
                if let Some(sandbox_id) = sandbox_id {
                    let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                }
                if let Some(session_id) = session_id {
                    let stop_reason = serde_json::json!({"type":"sandbox_failed"});
                    let payload = serde_json::json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone()
                    });
                    let _ = queries::update_session_status_and_insert_event(
                        &self.pool,
                        session_id,
                        "rescheduling",
                        Some(&stop_reason),
                        "session.status_rescheduling",
                        &payload,
                    )
                    .await;
                }
                true
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Scheduling retry skipped because task is no longer scheduling");
                false
            }
            Err(e) => {
                error!(task_id = %task_id, error = %e, "Failed to retry scheduling task");
                false
            }
        }
    }

    async fn fail_task_and_mark_session_idle(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        sandbox_id: Option<SandboxId>,
        observed_owner_epoch: Option<i64>,
        reason: &str,
    ) {
        match queries::transition_task_cas_observed_owner_epoch(
            &self.pool,
            task_id,
            "running",
            "failed",
            Some(reason),
            observed_owner_epoch,
        )
        .await
        {
            Ok(true) => {
                if let Some(sandbox_id) = sandbox_id {
                    let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                }
                if let Some(session_id) = session_id {
                    let stop_reason = serde_json::json!({"type":"error", "message": reason});
                    let payload = serde_json::json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone()
                    });
                    let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                        &self.pool,
                        session_id,
                        "idle",
                        Some(&stop_reason),
                        "session.status_idle",
                        &payload,
                    )
                    .await;
                }
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Task failure skipped because task is no longer running");
            }
            Err(e) => {
                error!(task_id = %task_id, error = %e, "Failed to mark task failed");
            }
        }
    }

    async fn fail_scheduling_task_and_mark_session_idle(
        &self,
        task_id: TaskId,
        session_id: Option<SessionId>,
        sandbox_id: Option<SandboxId>,
        reason: &str,
    ) -> bool {
        match queries::transition_task_cas(
            &self.pool,
            task_id,
            "scheduling",
            "failed",
            Some(reason),
            None,
        )
        .await
        {
            Ok(true) => {
                if let Some(sandbox_id) = sandbox_id {
                    let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                }
                if let Some(session_id) = session_id {
                    let stop_reason = serde_json::json!({"type":"error", "message": reason});
                    let payload = serde_json::json!({
                        "task_id": task_id.to_string(),
                        "stop_reason": stop_reason.clone()
                    });
                    let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                        &self.pool,
                        session_id,
                        "idle",
                        Some(&stop_reason),
                        "session.status_idle",
                        &payload,
                    )
                    .await;
                }
                true
            }
            Ok(false) => {
                warn!(task_id = %task_id, "Scheduling failure skipped because task is no longer scheduling");
                false
            }
            Err(e) => {
                error!(task_id = %task_id, error = %e, "Failed to fail scheduling task");
                false
            }
        }
    }

    pub fn compute_retry_delay(&self, retry_count: u32) -> Duration {
        let base_ms = self.config.task_retry_base_ms;
        let max_ms = self.config.task_retry_max_ms;
        // T12 fix: prevent overflow for large retry_count (cap exponent to 63)
        let exp = retry_count.min(63);
        let delay_ms = base_ms.saturating_mul(1u64 << exp).min(max_ms);
        Duration::from_millis(delay_ms)
    }

    /// Retry or fail a task based on retry count.
    /// Checks agent output first — if task produced output, mark completed instead.
    pub async fn failover_or_fail_task(
        &self,
        task_id: TaskId,
        error_msg: &str,
    ) -> anyhow::Result<()> {
        let task = queries::get_task(&self.pool, task_id).await?;
        let task = match task {
            Some(t) => t,
            None => return Ok(()),
        };

        // Guard: skip if already terminal
        if let Some(status) = crate::db::models::TaskStatus::from_str(&task.status) {
            if status.is_terminal() {
                return Ok(());
            }
        }

        // Check if task produced agent output — if so, mark completed + session idle (#15)
        if let Some(sid) = task.session_id {
            if queries::task_has_agent_output(&self.pool, task_id, sid)
                .await
                .unwrap_or(false)
            {
                match queries::transition_task_cas_observed_owner_epoch(
                    &self.pool,
                    task_id,
                    "running",
                    "completed",
                    None,
                    task.owner_epoch,
                )
                .await
                {
                    Ok(true) => {
                        if let Some(sandbox_id) = task.sandbox_id {
                            let _ = queries::complete_sandbox_task(&self.pool, sandbox_id).await;
                        }
                        // #15: Also transition session to idle (Python L308-318)
                        let stop_reason = serde_json::json!({"type":"end_turn"});
                        let payload = serde_json::json!({
                            "task_id": task_id.to_string(),
                            "stop_reason": stop_reason.clone()
                        });
                        let _ = queries::update_session_status_if_no_active_tasks_and_insert_event(
                            &self.pool,
                            sid,
                            "idle",
                            Some(&stop_reason),
                            "session.status_idle",
                            &payload,
                        )
                        .await;
                        info!(task_id = %task_id, "Task had agent output, marking completed + session idle");
                    }
                    Ok(false) => {
                        warn!(task_id = %task_id, "Agent-output completion skipped because task was no longer running");
                    }
                    Err(e) => {
                        error!(task_id = %task_id, error = %e, "Failed to complete task after agent output");
                    }
                }
                return Ok(());
            }
        }

        let max_retries = task.max_retries as u32;
        let current_retries = task.retry_count as u32;

        if current_retries < max_retries {
            // CAS retry: only increment if status and retry_count match
            if self
                .retry_task_and_mark_session_rescheduling(
                    task_id,
                    task.session_id,
                    task.sandbox_id,
                    Some(task.retry_count),
                    task.owner_epoch,
                )
                .await
            {
                info!(
                    task_id = %task_id,
                    retry = current_retries + 1,
                    max_retries = max_retries,
                    "Task will be retried"
                );
            }
        } else {
            self.fail_task_and_mark_session_idle(
                task_id,
                task.session_id,
                task.sandbox_id,
                task.owner_epoch,
                error_msg,
            )
            .await;
            warn!(
                task_id = %task_id,
                "Task failed after {max_retries} retries: {error_msg}"
            );
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::env;
    use std::sync::Arc;

    use serde_json::Value;
    use sqlx::postgres::PgPoolOptions;

    use super::*;
    use crate::kernel::sandbox_bridge::BridgeRegistry;

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres TaskController test: DATABASE_URL is not set");
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

    fn test_controller(pool: PgPool) -> TaskController {
        let config = JoySafeterConfig::from_env();
        let redis_client = redis::Client::open(
            config
                .redis_url
                .clone()
                .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
        )
        .expect("build redis client");
        TaskController::new(
            pool,
            TaskQueue::new(redis_client),
            config,
            Arc::new(BridgeRegistry::new()),
        )
    }

    async fn create_agent_session(pool: &PgPool, status: &str) -> (AgentId, SessionId) {
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, permission_mode, version)
            VALUES ($1, $2, 'claude', 'bypassPermissions', 1)
            "#,
        )
        .bind(agent_id)
        .bind(format!("task-controller-agent-{agent_id}"))
        .execute(pool)
        .await
        .expect("insert test agent");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_sessions (id, agent_id, status)
            VALUES ($1, $2, $3)
            "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(status)
        .execute(pool)
        .await
        .expect("insert test session");

        (agent_id, session_id)
    }

    async fn cleanup(
        pool: &PgPool,
        agent_id: AgentId,
        session_id: SessionId,
        sandbox_id: SandboxId,
    ) {
        let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
        let _ =
            sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
                .bind(session_id)
                .bind(agent_id)
                .execute(pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
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

    async fn cleanup_test_artifacts(pool: &PgPool) {
        let _ = sqlx::query(
            r#"
            DELETE FROM joysafeter_session_events
            WHERE session_id IN (
                SELECT s.id
                FROM joysafeter_sessions s
                JOIN joysafeter_agents a ON a.id = s.agent_id
                WHERE a.name LIKE 'task-controller-agent-%'
            )
            "#,
        )
        .execute(pool)
        .await;
        let _ = sqlx::query(
            r#"
            DELETE FROM joysafeter_tasks
            WHERE agent_id IN (
                SELECT id FROM joysafeter_agents WHERE name LIKE 'task-controller-agent-%'
            )
            "#,
        )
        .execute(pool)
        .await;
        let _ = sqlx::query(
            r#"
            DELETE FROM joysafeter_sandboxes
            WHERE external_id LIKE 'startup-recovery-%'
               OR external_id LIKE 'overdue-timeout-%'
               OR external_id LIKE 'helper-race-%'
               OR external_id LIKE 'stuck-retry-%'
               OR external_id LIKE 'stuck-exhausted-%'
               OR external_id LIKE 'stuck-race-%'
               OR external_id LIKE 'task-controller-output-%'
            "#,
        )
        .execute(pool)
        .await;
        let _ = sqlx::query(
            r#"
            DELETE FROM joysafeter_sessions
            WHERE agent_id IN (
                SELECT id FROM joysafeter_agents WHERE name LIKE 'task-controller-agent-%'
            )
            "#,
        )
        .execute(pool)
        .await;
        let _ =
            sqlx::query("DELETE FROM joysafeter_agents WHERE name LIKE 'task-controller-agent-%'")
                .execute(pool)
                .await;
    }

    async fn create_sandbox_task(
        pool: &PgPool,
        agent_id: AgentId,
        session_id: SessionId,
        label: &str,
        status: &str,
        retry_count: i32,
        max_retries: i32,
        stale: bool,
    ) -> (SandboxId, TaskId) {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        queries::create_sandbox(
            pool,
            sandbox_id,
            &format!("{label}-{sandbox_id}"),
            "recording",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&serde_json::json!({})),
        )
        .await
        .expect("insert linked sandbox");
        let _ = queries::transition_sandbox_cas(pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle");
        let _ = queries::transition_sandbox_cas(pool, sandbox_id, "idle", "running")
            .await
            .expect("sandbox running");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(pool)
            .await
            .expect("set sandbox last task");

        let started_at_sql = if status == "scheduling" && stale {
            "NOW() - INTERVAL '100 years'"
        } else if status == "running" {
            "NOW() - INTERVAL '10 seconds'"
        } else {
            "NULL"
        };
        let sql = format!(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries, started_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, 'test prompt', '', 1, $6, $7, {started_at_sql}, NOW())
            "#
        );
        sqlx::query(&sql)
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .bind(status)
            .bind(retry_count)
            .bind(max_retries)
            .execute(pool)
            .await
            .expect("insert task");

        if stale {
            sqlx::query(
                "UPDATE joysafeter_tasks SET updated_at = NOW() - INTERVAL '100 years' WHERE id = $1",
            )
            .bind(task_id)
            .execute(pool)
            .await
            .expect("make task stale");
        }

        (sandbox_id, task_id)
    }

    #[tokio::test]
    async fn task_controller_startup_recovery_fails_overdue_running_task_and_idles_session() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "startup-recovery",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            controller
                .recover_on_startup()
                .await
                .expect("startup recovery succeeds");

            let (task_status, task_error): (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load recovered task");
            assert_eq!(task_status, "failed");
            assert_eq!(
                task_error.as_deref(),
                Some("Orchestrator restarted - task was running when process exited")
            );

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load recovered sandbox");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load recovered session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some("Orchestrator restarted - task was running when process exited")
            );

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
            .expect("count idle events");
            assert_eq!(idle_events, 1);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_overdue_timeout_releases_sandbox_and_idles_session() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "overdue-timeout",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            controller
                .check_overdue_tasks()
                .await
                .expect("overdue task check succeeds");

            let (task_status, task_error, completed_at): (
                String,
                Option<String>,
                Option<chrono::DateTime<chrono::Utc>>,
            ) = sqlx::query_as(
                "SELECT status, error, completed_at FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load timed out task");
            assert_eq!(task_status, "timeout");
            assert_eq!(
                task_error.as_deref(),
                Some("task exceeded deadline (detected by TaskController)")
            );
            assert!(completed_at.is_some());

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load released sandbox after timeout");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load idle session after timeout");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("timeout")
            );

            let idle_events: i64 = sqlx::query_scalar(
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
            assert_eq!(idle_events, 1);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_retry_helper_marks_session_rescheduling() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "stuck-retry",
            "scheduling",
            0,
            2,
            true,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            assert!(
                controller
                    .retry_scheduling_task_and_mark_session_rescheduling(
                        task_id,
                        Some(session_id),
                        Some(sandbox_id),
                        0,
                    )
                    .await
            );

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load retried scheduling task");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 1);
            assert_eq!(task_sandbox_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load rescheduling session");
            assert_eq!(session_status, "rescheduling");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(|value| value.as_str()),
                Some("sandbox_failed")
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_retry_helper_does_not_release_sandbox_on_terminal_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "helper-race-retry",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
            let completed = queries::transition_task_cas(
                &pool,
                task_id,
                "running",
                "completed",
                Some("result already won"),
                None,
            )
            .await
            .expect("terminal task transition");
            assert!(completed);

            let controller = test_controller(pool.clone());
            assert!(
                !controller
                    .retry_task_and_mark_session_rescheduling(
                        task_id,
                        Some(session_id),
                        Some(sandbox_id),
                        Some(0),
                        None,
                    )
                    .await
            );

            let (task_status, retry_count): (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load terminal task after stale retry");
            assert_eq!(task_status, "completed");
            assert_eq!(retry_count, 0);

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale retry conflict");
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
            .expect("count stale retry conflict events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_fail_helper_does_not_release_sandbox_on_terminal_conflict() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "helper-race-fail",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
            let cancelled = queries::transition_task_cas(
                &pool,
                task_id,
                "running",
                "cancelled",
                Some("user cancellation already won"),
                None,
            )
            .await
            .expect("terminal task transition");
            assert!(cancelled);

            let controller = test_controller(pool.clone());
            controller
                .fail_task_and_mark_session_idle(
                    task_id,
                    Some(session_id),
                    Some(sandbox_id),
                    None,
                    "late failover error",
                )
                .await;

            let (task_status, task_error): (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load terminal task after stale fail");
            assert_eq!(task_status, "cancelled");
            assert_eq!(task_error.as_deref(), Some("user cancellation already won"));

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale fail conflict");
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
            .expect("count stale fail conflict events");
            assert_eq!(idle_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_runtime_helpers_do_not_mutate_pending_task() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "rescheduling").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "helper-race-pending",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
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

            let controller = test_controller(pool.clone());
            assert!(
                !controller
                    .retry_task_and_mark_session_rescheduling(
                        task_id,
                        Some(session_id),
                        Some(sandbox_id),
                        Some(0),
                        None,
                    )
                    .await
            );
            controller
                .fail_task_and_mark_session_idle(
                    task_id,
                    Some(session_id),
                    Some(sandbox_id),
                    None,
                    "late runtime failure",
                )
                .await;

            let (task_status, retry_count, task_error, task_sandbox_id): (
                String,
                i32,
                Option<String>,
                Option<SandboxId>,
            ) = sqlx::query_as(
                "SELECT status, retry_count, error, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load pending task after stale runtime helpers");
            assert_eq!(task_status, "pending");
            assert_eq!(retry_count, 0);
            assert_eq!(task_error, None);
            assert_eq!(task_sandbox_id, None);

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale runtime helpers");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let false_status_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type IN ('session.status_rescheduling', 'session.status_idle')
                  AND payload->>'task_id' = $2
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count false runtime helper status events");
            assert_eq!(false_status_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_stale_scheduling_retry_does_not_mutate_running_task() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "stuck-race-retry",
            "running",
            0,
            2,
            false,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            assert!(
                !controller
                    .retry_scheduling_task_and_mark_session_rescheduling(
                        task_id,
                        Some(session_id),
                        Some(sandbox_id),
                        0,
                    )
                    .await
            );

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
                sqlx::query_as(
                    "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load running task after stale scheduling retry");
            assert_eq!(task_status, "running");
            assert_eq!(retry_count, 0);
            assert_eq!(task_sandbox_id, Some(sandbox_id));

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale scheduling retry");
            assert_eq!(sandbox_status, "running");
            assert_eq!(last_task_id, Some(task_id));

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after stale scheduling retry");
            assert_eq!(session_status, "running");
            assert_eq!(stop_reason, None);

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
            .expect("count stale retry rescheduling events");
            assert_eq!(rescheduling_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_stale_scheduling_failure_does_not_mutate_running_task() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "stuck-race-fail",
            "running",
            2,
            2,
            false,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            assert!(
                !controller
                    .fail_scheduling_task_and_mark_session_idle(
                        task_id,
                        Some(session_id),
                        Some(sandbox_id),
                        "scheduling stuck after max retries",
                    )
                    .await
            );

            let (task_status, retry_count, task_error): (String, i32, Option<String>) =
                sqlx::query_as(
                    "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load running task after stale scheduling failure");
            assert_eq!(task_status, "running");
            assert_eq!(retry_count, 2);
            assert_eq!(task_error, None);

            let (sandbox_status, last_task_id): (String, Option<TaskId>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after stale scheduling failure");
            assert_eq!(sandbox_status, "running");
            assert_eq!(last_task_id, Some(task_id));

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after stale scheduling failure");
            assert_eq!(session_status, "running");
            assert_eq!(stop_reason, None);

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
            .expect("count stale failure idle events");
            assert_eq!(idle_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_stuck_scheduling_exhausted_moves_rescheduling_session_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "rescheduling").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "stuck-exhausted",
            "scheduling",
            2,
            2,
            true,
        )
        .await;

        let result = async {
            let controller = test_controller(pool.clone());
            controller
                .check_stuck_scheduling()
                .await
                .expect("stuck scheduling check succeeds");

            let (task_status, retry_count, task_error): (String, i32, Option<String>) =
                sqlx::query_as(
                    "SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1",
                )
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load exhausted scheduling task");
            assert_eq!(task_status, "failed");
            assert_eq!(retry_count, 2);
            assert_eq!(
                task_error.as_deref(),
                Some("scheduling stuck after max retries")
            );

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted sandbox");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load exhausted session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some("scheduling stuck after max retries")
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_failover_with_agent_output_completes_and_releases_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "task-controller-output",
            "running",
            0,
            2,
            false,
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
            .bind(serde_json::json!({"task_id": task_id.to_string()}))
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
            .bind(serde_json::json!({"content": [{"type": "text", "text": "partial answer"}]}))
            .bind(2_i64)
            .execute(&pool)
            .await
            .expect("insert agent output after running status");

            let controller = test_controller(pool.clone());
            controller
                .failover_or_fail_task(task_id, "runner disconnected after output")
                .await
                .expect("failover after output succeeds");

            let (task_status, retry_count): (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load completed task");
            assert_eq!(task_status, "completed");
            assert_eq!(retry_count, 0);

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load released sandbox");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load idle session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str),
                Some("end_turn")
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }

    #[tokio::test]
    async fn task_controller_agent_output_failover_does_not_complete_pending_retry() {
        let Some(pool) = test_pool().await else {
            return;
        };
        cleanup_test_artifacts(&pool).await;
        let (agent_id, session_id) = create_agent_session(&pool, "running").await;
        let (sandbox_id, task_id) = create_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "task-controller-output-pending",
            "running",
            0,
            2,
            false,
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
            .bind(serde_json::json!({"task_id": task_id.to_string()}))
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
            .bind(serde_json::json!({"content": [{"type": "text", "text": "partial answer"}]}))
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
            let stop_reason = serde_json::json!({"type": "sandbox_failed"});
            let payload = serde_json::json!({
                "task_id": task_id.to_string(),
                "stop_reason": stop_reason.clone()
            });
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

            let controller = test_controller(pool.clone());
            controller
                .failover_or_fail_task(task_id, "late failover after retry")
                .await
                .expect("late failover should not complete pending retry");

            let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
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

        cleanup(&pool, agent_id, session_id, sandbox_id).await;
        result
    }
}
