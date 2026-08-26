use sqlx::PgPool;
use uuid::Uuid;

use crate::db::models::JoySafeterTask;
use crate::ids::{ProjectId, SandboxId, SessionId, TaskId};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct ResetSandboxTask {
    pub id: TaskId,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<SessionId>,
    pub previous_retry_count: i32,
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct FailedSandboxTask {
    pub id: TaskId,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<SessionId>,
}

// ---------------------------------------------------------------------------
// Task queries
// ---------------------------------------------------------------------------

/// Claim a single pending task by ID for scheduling (PENDING → SCHEDULING).
pub async fn claim_pending_task_by_id(
    pool: &PgPool,
    task_id: TaskId,
) -> Result<Option<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'scheduling',
            started_at = NOW(),
            scheduling_started_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
          AND status = 'pending'
          AND (next_schedule_at IS NULL OR next_schedule_at <= NOW())
        RETURNING *
        "#,
    )
    .bind(task_id)
    .fetch_optional(pool)
    .await
}

/// Claim a batch of pending tasks for scheduling (PENDING → SCHEDULING).
/// Uses `FOR UPDATE SKIP LOCKED` to avoid contention across instances.
pub async fn claim_pending_tasks(
    pool: &PgPool,
    limit: i64,
) -> Result<Vec<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'scheduling',
            started_at = NOW(),
            scheduling_started_at = NOW(),
            updated_at = NOW()
        WHERE id IN (
            SELECT id FROM joysafeter_tasks
            WHERE status = 'pending'
              AND (next_schedule_at IS NULL OR next_schedule_at <= NOW())
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        RETURNING *
        "#,
    )
    .bind(limit)
    .fetch_all(pool)
    .await
}

/// Claim the next task for a specific sandbox (SCHEDULING/PENDING → RUNNING).
pub async fn claim_next_sandbox_task(
    pool: &PgPool,
    sandbox_id: SandboxId,
    owner_instance_id: &str,
    lease_ttl_sec: i64,
) -> Result<Option<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'running',
            started_at = NOW(),
            owner_instance_id = $2,
            owner_epoch = nextval('joysafeter_task_owner_epoch_seq'),
            lease_expires_at = NOW() + ($3 * INTERVAL '1 second'),
            updated_at = NOW()
        WHERE id = (
            SELECT id FROM joysafeter_tasks
            WHERE sandbox_id = $1 AND status = 'scheduling'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING *
        "#,
    )
    .bind(sandbox_id)
    .bind(owner_instance_id)
    .bind(lease_ttl_sec)
    .fetch_optional(pool)
    .await
}

pub async fn attach_sandbox_to_task_guarded(
    pool: &PgPool,
    task_id: TaskId,
    sandbox_id: SandboxId,
    session_id: SessionId,
    project_id: Option<ProjectId>,
    captured_generation: i64,
) -> Result<(), RuntimeFreshnessError> {
    let mut transaction = pool.begin().await?;
    let session = sqlx::query_as::<
        _,
        (
            Option<ProjectId>,
            String,
            Option<chrono::DateTime<chrono::Utc>>,
            i64,
        ),
    >(
        r#"
        SELECT project_id, status, archived_at, runtime_config_generation
        FROM joysafeter_sessions
        WHERE id = $1
        FOR UPDATE
        "#,
    )
    .bind(session_id)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((session_project_id, session_status, archived_at, actual_generation)) = session else {
        return Err(RuntimeFreshnessError::SessionBindingInvalid {
            session_id,
            reason: "missing session",
        });
    };
    if archived_at.is_some() || session_status == "terminated" {
        return Err(RuntimeFreshnessError::SessionBindingInvalid {
            session_id,
            reason: "inactive session",
        });
    }
    if session_project_id != project_id {
        return Err(RuntimeFreshnessError::SessionBindingInvalid {
            session_id,
            reason: "project mismatch",
        });
    }
    if actual_generation != captured_generation {
        return Err(RuntimeFreshnessError::GenerationChanged {
            expected: captured_generation,
            actual: actual_generation,
        });
    }

    let sandbox = sqlx::query_as::<_, (Option<SessionId>, Option<ProjectId>, String, i64)>(
        r#"
        SELECT chat_session_id, project_id, runtime_config_status,
               runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1 AND destroyed_at IS NULL
        FOR UPDATE
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((sandbox_session_id, sandbox_project_id, runtime_status, applied_generation)) =
        sandbox
    else {
        return Err(RuntimeFreshnessError::Conflict(format!(
            "sandbox {sandbox_id} is not available"
        )));
    };
    if sandbox_session_id != Some(session_id) || sandbox_project_id != project_id {
        return Err(RuntimeFreshnessError::Conflict(format!(
            "sandbox {sandbox_id} ownership changed"
        )));
    }
    if runtime_status != "ready" || applied_generation != actual_generation {
        return Err(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id });
    }

    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET sandbox_id = $2, updated_at = NOW()
        WHERE id = $1
          AND status = 'scheduling'
          AND chat_session_id = $3
          AND project_id IS NOT DISTINCT FROM $4
        "#,
    )
    .bind(task_id)
    .bind(sandbox_id)
    .bind(session_id)
    .bind(project_id)
    .execute(&mut *transaction)
    .await?;
    if result.rows_affected() == 0 {
        return Err(RuntimeFreshnessError::Conflict(format!(
            "task {task_id} changed before sandbox attachment"
        )));
    }
    transaction.commit().await?;
    Ok(())
}

/// Return a claimed task to PENDING only if it is still in SCHEDULING.
pub async fn reset_scheduling_task_to_pending(
    pool: &PgPool,
    task_id: TaskId,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
            scheduling_started_at = NULL,
            updated_at = NOW()
        WHERE id = $1 AND status = 'scheduling'
        "#,
    )
    .bind(task_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Complete a task with output and usage data.
/// Called AFTER transition_task_cas has already moved status to a terminal state.
/// Uses `WHERE status = $2` to ensure we only write data for the status we set
/// (prevents a late runner result from overwriting a watchdog timeout/cancel,
/// since the watchdog would have set a different terminal status).
pub async fn complete_task(
    pool: &PgPool,
    task_id: TaskId,
    status: &str,
    output: Option<&str>,
    error_msg: Option<&str>,
    usage: Option<&serde_json::Value>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET output = COALESCE($3, output),
            error = COALESCE($4, error),
            usage = COALESCE($5, usage),
            completed_at = COALESCE(completed_at, NOW()),
            duration_ms = COALESCE(duration_ms,
                EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000),
            updated_at = NOW()
        WHERE id = $1 AND status = $2
        "#,
    )
    .bind(task_id)
    .bind(status)
    .bind(output)
    .bind(error_msg)
    .bind(usage)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Get a task by ID.
pub async fn get_task(
    pool: &PgPool,
    task_id: TaskId,
) -> Result<Option<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>("SELECT * FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .fetch_optional(pool)
        .await
}

/// Count tasks currently in non-terminal states.
pub async fn count_active_tasks(pool: &PgPool) -> Result<i64, sqlx::Error> {
    let row: (i64,) = sqlx::query_as(
        "SELECT COUNT(*) FROM joysafeter_tasks WHERE status IN ('pending', 'scheduling', 'running')",
    )
    .fetch_one(pool)
    .await?;
    Ok(row.0)
}

/// CAS task status transition.
pub async fn transition_task_cas(
    pool: &PgPool,
    task_id: TaskId,
    expected_status: &str,
    new_status: &str,
    error_msg: Option<&str>,
    expected_owner_epoch: Option<i64>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = $3,
            error = COALESCE($4, error),
            completed_at = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NOW()
                ELSE completed_at
            END,
            duration_ms = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                    THEN EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
                ELSE duration_ms
            END,
            owner_instance_id = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE owner_instance_id
            END,
            owner_epoch = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE owner_epoch
            END,
            lease_expires_at = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE lease_expires_at
            END,
            updated_at = NOW()
        WHERE id = $1 AND status = $2
          AND ($5::bigint IS NULL OR owner_epoch = $5)
        "#,
    )
    .bind(task_id)
    .bind(expected_status)
    .bind(new_status)
    .bind(error_msg)
    .bind(expected_owner_epoch)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// CAS task status transition fenced to the owner epoch observed by a stale-prone caller.
///
/// `transition_task_cas` treats `None` as "no owner fence" for pre-RUNNING callers.
/// Watchdogs and failover paths that first load a RUNNING row and later mutate it
/// need stricter semantics: even an observed `NULL` owner must not match a task
/// that has since been reclaimed with a new owner epoch.
pub async fn transition_task_cas_observed_owner_epoch(
    pool: &PgPool,
    task_id: TaskId,
    expected_status: &str,
    new_status: &str,
    error_msg: Option<&str>,
    observed_owner_epoch: Option<i64>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = $3,
            error = COALESCE($4, error),
            completed_at = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NOW()
                ELSE completed_at
            END,
            duration_ms = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                    THEN EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
                ELSE duration_ms
            END,
            owner_instance_id = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE owner_instance_id
            END,
            owner_epoch = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE owner_epoch
            END,
            lease_expires_at = CASE
                WHEN $3 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NULL
                ELSE lease_expires_at
            END,
            updated_at = NOW()
        WHERE id = $1 AND status = $2
          AND owner_epoch IS NOT DISTINCT FROM $5
        "#,
    )
    .bind(task_id)
    .bind(expected_status)
    .bind(new_status)
    .bind(error_msg)
    .bind(observed_owner_epoch)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Reset all scheduling tasks for a sandbox back to pending and return changed
/// rows so callers can repair session state for exactly those task mutations.
pub async fn reset_sandbox_tasks_to_pending_returning(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<Vec<ResetSandboxTask>, sqlx::Error> {
    sqlx::query_as::<_, ResetSandboxTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending', sandbox_id = NULL, started_at = NULL,
            retry_count = retry_count + 1, updated_at = NOW()
        WHERE sandbox_id = $1 AND status = 'scheduling' AND retry_count < max_retries
        RETURNING id, chat_session_id, retry_count - 1 AS previous_retry_count
        "#,
    )
    .bind(sandbox_id)
    .fetch_all(pool)
    .await
}

/// Fail scheduling tasks already at retry limit for a sandbox and return
/// changed rows so callers can repair session state.
pub async fn fail_exhausted_sandbox_tasks_returning(
    pool: &PgPool,
    sandbox_id: SandboxId,
    reason: &str,
) -> Result<Vec<FailedSandboxTask>, sqlx::Error> {
    sqlx::query_as::<_, FailedSandboxTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            error = COALESCE($2, error),
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            updated_at = NOW()
        WHERE sandbox_id = $1 AND status = 'scheduling' AND retry_count >= max_retries
        RETURNING id, chat_session_id
        "#,
    )
    .bind(sandbox_id)
    .bind(reason)
    .fetch_all(pool)
    .await
}

/// Find running tasks for a sandbox (for orphan rescue on reconnect).
pub async fn find_running_tasks_for_sandbox(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<Vec<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        "SELECT * FROM joysafeter_tasks WHERE sandbox_id = $1 AND status = 'running'",
    )
    .bind(sandbox_id)
    .fetch_all(pool)
    .await
}

/// Retry a task only if it is still RUNNING with the expected retry count.
///
/// Runtime failover callbacks are based on stale runner/stream observations.
/// This CAS prevents a late disconnect or send failure from double-retrying a
/// task that another path already returned to PENDING.
pub async fn increment_running_retry(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
            retry_count = retry_count + 1,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND retry_count = $2
          AND ($3::bigint IS NULL OR owner_epoch = $3)
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .bind(expected_owner_epoch)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Fail a RUNNING task bound to a specific sandbox and release its sandbox
/// association in the same CAS write.
pub async fn fail_running_task_for_sandbox(
    pool: &PgPool,
    task_id: TaskId,
    sandbox_id: SandboxId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            sandbox_id = NULL,
            error = COALESCE($5, error),
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND sandbox_id = $2
          AND status = 'running'
          AND retry_count = $3
          AND ($4::bigint IS NULL OR owner_epoch = $4)
        "#,
    )
    .bind(task_id)
    .bind(sandbox_id)
    .bind(expected_retry_count)
    .bind(expected_owner_epoch)
    .bind(reason)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Renew leases only for tasks this process is actively executing.
pub async fn renew_running_task_leases(
    pool: &PgPool,
    owner_instance_id: &str,
    lease_ttl_sec: i64,
    active_task_leases: &[(TaskId, i64)],
) -> Result<u64, sqlx::Error> {
    if active_task_leases.is_empty() {
        return Ok(0);
    }

    let active_task_ids: Vec<Uuid> = active_task_leases
        .iter()
        .map(|(task_id, _)| task_id.as_uuid())
        .collect();
    let active_owner_epochs: Vec<i64> = active_task_leases
        .iter()
        .map(|(_, owner_epoch)| *owner_epoch)
        .collect();

    let result = sqlx::query(
        r#"
        WITH active_tasks AS (
            SELECT * FROM UNNEST($3::uuid[], $4::bigint[]) AS active(task_id, owner_epoch)
        )
        UPDATE joysafeter_tasks AS task
        SET lease_expires_at = NOW() + ($2 * INTERVAL '1 second'),
            updated_at = NOW()
        FROM active_tasks
        WHERE task.owner_instance_id = $1
          AND task.status = 'running'
          AND task.id = active_tasks.task_id
          AND task.owner_epoch = active_tasks.owner_epoch
        "#,
    )
    .bind(owner_instance_id)
    .bind(lease_ttl_sec)
    .bind(&active_task_ids)
    .bind(&active_owner_epochs)
    .execute(pool)
    .await?;

    Ok(result.rows_affected())
}

/// Running tasks whose ownership lease expired.
pub async fn find_lease_expired_running_tasks(
    pool: &PgPool,
    limit: i64,
) -> Result<Vec<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        SELECT *
        FROM joysafeter_tasks
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < NOW()
        ORDER BY lease_expires_at ASC
        LIMIT $1
        "#,
    )
    .bind(limit)
    .fetch_all(pool)
    .await
}

pub async fn retry_lease_expired_task(
    pool: &PgPool,
    task_id: TaskId,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
            retry_count = retry_count + 1,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            error = $2,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND lease_expires_at < NOW()
          AND retry_count < max_retries
        "#,
    )
    .bind(task_id)
    .bind(reason)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

pub async fn fail_lease_expired_task(
    pool: &PgPool,
    task_id: TaskId,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            error = $2,
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND lease_expires_at < NOW()
          AND retry_count >= max_retries
        "#,
    )
    .bind(task_id)
    .bind(reason)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Retry a task only if it is still in SCHEDULING with the expected retry count.
///
/// Scheduler failure callbacks are based on stale async observations; this CAS
/// prevents a late resolver failure from moving a task that already reached
/// RUNNING back to PENDING.
pub async fn increment_scheduling_retry_keep_scheduling(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    backoff_seconds: i64,
    error_type: &str,
    error_message: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET sandbox_id = NULL,
            started_at = NULL,
            schedule_attempts = schedule_attempts + 1,
            retry_count = retry_count + 1,
            next_schedule_at = NOW() + ($3 * INTERVAL '1 second'),
            last_schedule_error_type = $4,
            last_schedule_error = $5,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'scheduling'
          AND retry_count = $2
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .bind(backoff_seconds)
    .bind(error_type)
    .bind(error_message)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Move a retried scheduling task back to PENDING while preserving next_schedule_at.
pub async fn release_scheduling_retry_to_pending(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending', scheduling_started_at = NULL, updated_at = NOW()
        WHERE id = $1
          AND status = 'scheduling'
          AND retry_count = $2
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Immediate retry helper for non-scheduler controllers that already perform
/// their own backoff/lifecycle coordination.
pub async fn increment_scheduling_retry(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
) -> Result<bool, sqlx::Error> {
    let updated = increment_scheduling_retry_keep_scheduling(
        pool,
        task_id,
        expected_retry_count,
        0,
        "runtime_retry",
        "runtime retry",
    )
    .await?;
    if !updated {
        return Ok(false);
    }
    release_scheduling_retry_to_pending(pool, task_id, expected_retry_count + 1).await
}

/// Check if a task has produced agent.message events (for failover decisions).
pub async fn task_has_agent_output(
    pool: &PgPool,
    task_id: TaskId,
    session_id: SessionId,
) -> Result<bool, sqlx::Error> {
    let row: (bool,) = sqlx::query_as(
        r#"
        SELECT EXISTS(
          SELECT 1 FROM joysafeter_session_events
          WHERE session_id = $1
            AND event_type = 'agent.message'
            AND seq > (
              SELECT COALESCE(MAX(seq), 0) FROM joysafeter_session_events
              WHERE session_id = $1
                AND event_type = 'session.status_running'
                AND payload->>'task_id' = $2
            )
        )
        "#,
    )
    .bind(session_id)
    .bind(task_id.to_string())
    .fetch_one(pool)
    .await?;

    Ok(row.0)
}

/// Find all pending tasks (for startup re-enqueue).
pub async fn find_pending_tasks(pool: &PgPool, limit: i64) -> Result<Vec<(TaskId,)>, sqlx::Error> {
    sqlx::query_as::<_, (TaskId,)>(
        r#"
        SELECT id FROM joysafeter_tasks
        WHERE status = 'pending'
          AND (next_schedule_at IS NULL OR next_schedule_at <= NOW())
        ORDER BY created_at
        LIMIT $1
        "#,
    )
    .bind(limit)
    .fetch_all(pool)
    .await
}
