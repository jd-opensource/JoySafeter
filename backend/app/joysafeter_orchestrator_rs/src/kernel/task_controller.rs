use std::time::Duration;

use sqlx::PgPool;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
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
}

impl TaskController {
    pub fn new(pool: PgPool, queue: TaskQueue, config: JoySafeterConfig) -> Self {
        Self {
            pool,
            queue,
            config,
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
            let recovered_tasks: Vec<(Uuid,)> = sqlx::query_as(
                r#"
                SELECT id FROM joysafeter_tasks
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND started_at + (COALESCE(timeout_sec, 7200) * INTERVAL '1 second') < NOW()
                "#,
            )
            .fetch_all(&self.pool)
            .await?;

            for (task_id,) in &recovered_tasks {
                let _ = queries::transition_task(
                    &self.pool,
                    *task_id,
                    "failed",
                    Some("Orchestrator restarted - task was running when process exited"),
                )
                .await;
            }

            // DB pending tasks are the durable source of truth; enqueue all on startup.
            let pending_tasks = queries::find_pending_tasks(&self.pool, 500).await?;
            for (task_id,) in &pending_tasks {
                if let Err(e) = self.queue.push_to_global(*task_id).await {
                    error!(task_id = %task_id, "Failed to enqueue pending task during startup recovery: {e}");
                }
            }

            // Scheduling tasks -> pending (unconditional, retry increment), matching Python.
            let scheduling_tasks: Vec<(Uuid,)> =
                sqlx::query_as("SELECT id FROM joysafeter_tasks WHERE status = 'scheduling'")
                    .fetch_all(&self.pool)
                    .await?;
            for (task_id,) in &scheduling_tasks {
                let _ = queries::increment_retry(&self.pool, *task_id).await;
                // T9 fix: push to global queue so they don't wait 60s for scan
                if let Err(e) = self.queue.push_to_global(*task_id).await {
                    error!(task_id = %task_id, "Failed to enqueue reset scheduling task during startup recovery: {e}");
                }
            }

            // Provisioning sandboxes: allow enough time for remote providers
            // and queued setup work before declaring the sandbox stale.
            let provisioning_minutes: i32 = 45;
            let stale_provisioning: Vec<(Uuid,)> = sqlx::query_as(
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
                let _ = queries::transition_sandbox(&self.pool, *sandbox_id, "stopped").await;
            }

            // Reset sessions stuck in 'rescheduling'.
            let stale_rescheduling_sessions: Vec<(Uuid,)> = sqlx::query_as(
                r#"
                SELECT id FROM joysafeter_sessions
                WHERE status = 'rescheduling'
                  AND updated_at < NOW() - INTERVAL '5 minutes'
                "#,
            )
            .fetch_all(&self.pool)
            .await?;
            for (session_id,) in &stale_rescheduling_sessions {
                let _ = queries::update_session_status(
                    &self.pool,
                    *session_id,
                    "terminated",
                    Some(&serde_json::json!({"type":"retries_exhausted"})),
                )
                .await;
                // I-NEW-5 fix: emit session event for startup recovery (matching Python transition_and_emit)
                let _ = queries::insert_session_event(
                    &self.pool,
                    *session_id,
                    "session.status_terminated",
                    &serde_json::json!({"stop_reason": {"type":"retries_exhausted"}}),
                )
                .await;
            }

            // Reset running sessions only when stale and no active task remains.
            let stale_running_sessions: Vec<(Uuid,)> = sqlx::query_as(
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
                let _ = queries::update_session_status(
                    &self.pool,
                    *session_id,
                    "idle",
                    Some(&serde_json::json!({"type":"end_turn"})),
                )
                .await;
                // I-NEW-5 fix: emit session event for startup recovery
                let _ = queries::insert_session_event(
                    &self.pool,
                    *session_id,
                    "session.status_idle",
                    &serde_json::json!({"stop_reason": {"type":"end_turn"}}),
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
            let interval = Duration::from_secs(60);
            info!("TaskController check loop started (interval=60s)");

            loop {
                tokio::time::sleep(interval).await;

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

        let overdue: Vec<(Uuid, Option<Uuid>)> = sqlx::query_as(
            r#"
            SELECT id, chat_session_id FROM joysafeter_tasks
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
        for (task_id, session_id) in &overdue {
            warn!(task_id = %task_id, "Task overdue, marking as timeout");
            let _ = queries::transition_task(
                &self.pool,
                *task_id,
                "timeout",
                Some("task exceeded deadline (detected by TaskController)"),
            )
            .await;

            if let Some(sid) = session_id {
                let _ = queries::update_session_status(
                    &self.pool,
                    *sid,
                    "idle",
                    Some(&serde_json::json!({"type":"timeout"})),
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
        let stuck: Vec<(Uuid, i32, i32)> = sqlx::query_as(
            r#"
            SELECT id, retry_count, max_retries FROM joysafeter_tasks
            WHERE status = 'scheduling'
              AND updated_at < NOW() - INTERVAL '2 minutes'
            LIMIT 20
            "#,
        )
        .fetch_all(&mut *tx)
        .await?;

        tx.commit().await?;

        // Transitions outside the lock transaction
        for (task_id, retry_count, max_retries) in &stuck {
            if *retry_count >= *max_retries {
                warn!(task_id = %task_id, "Task stuck in scheduling past max_retries, marking failed");
                let _ = queries::transition_task(
                    &self.pool,
                    *task_id,
                    "failed",
                    Some("scheduling stuck after max retries"),
                )
                .await;
            } else {
                warn!(task_id = %task_id, "Task stuck in scheduling (>2min), resetting to pending");
                let _ = queries::increment_retry(&self.pool, *task_id).await;
                if let Err(e) = self.queue.push_to_global(*task_id).await {
                    error!(task_id = %task_id, "Failed to enqueue reset stuck scheduling task: {e}");
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

        let tasks: Vec<(Uuid,)> = sqlx::query_as(
            "SELECT id FROM joysafeter_tasks WHERE status = 'pending' ORDER BY created_at LIMIT 500",
        )
        .fetch_all(&mut *tx)
        .await?;

        tx.commit().await?;

        for (task_id,) in &tasks {
            if let Err(e) = self.queue.push_to_global(*task_id).await {
                error!(task_id = %task_id, "Failed to enqueue scanned pending task: {e}");
            }
        }
        if !tasks.is_empty() {
            debug!("Scanned and re-enqueued {} pending tasks", tasks.len());
        }

        Ok(())
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
        task_id: Uuid,
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
                let _ = queries::transition_task(&self.pool, task_id, "completed", None).await;
                // #15: Also transition session to idle (Python L308-318)
                let _ = queries::update_session_status(
                    &self.pool,
                    sid,
                    "idle",
                    Some(&serde_json::json!({"type":"end_turn"})),
                )
                .await;
                info!(task_id = %task_id, "Task had agent output, marking completed + session idle");
                return Ok(());
            }
        }

        let max_retries = task.max_retries as u32;
        let current_retries = task.retry_count as u32;

        if current_retries < max_retries {
            // CAS retry: only increment if status and retry_count match
            let result = sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending', sandbox_id = NULL,
                    retry_count = retry_count + 1, updated_at = NOW()
                WHERE id = $1 AND retry_count = $2
                  AND status NOT IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                "#,
            )
            .bind(task_id)
            .bind(task.retry_count)
            .execute(&self.pool)
            .await?;

            if result.rows_affected() > 0 {
                info!(
                    task_id = %task_id,
                    retry = current_retries + 1,
                    max_retries = max_retries,
                    "Task will be retried"
                );
            } else {
                warn!(task_id = %task_id, "CAS conflict on retry increment");
            }
        } else {
            let _ = queries::transition_task(&self.pool, task_id, "failed", Some(error_msg)).await;
            warn!(
                task_id = %task_id,
                "Task failed after {max_retries} retries: {error_msg}"
            );
        }

        Ok(())
    }
}
