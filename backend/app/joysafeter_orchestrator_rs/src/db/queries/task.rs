use sqlx::PgPool;
use uuid::Uuid;

use crate::db::models::JoySafeterTask;

const TASK_ADMISSION_ADVISORY_LOCK_KEY: i64 = 7_421_938_472_193_847;

fn task_admission_capacity(active_count: i64, max_concurrent_tasks: usize) -> i64 {
    let admission_limit = i64::try_from(max_concurrent_tasks).unwrap_or(i64::MAX);
    admission_limit.saturating_sub(active_count).max(0)
}

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct ResetSandboxTask {
    pub id: Uuid,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<Uuid>,
    pub previous_retry_count: i32,
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct FailedSandboxTask {
    pub id: Uuid,
    #[sqlx(rename = "chat_session_id")]
    pub session_id: Option<Uuid>,
}

#[derive(Debug)]
pub enum PendingTaskClaim {
    Claimed(JoySafeterTask),
    AtCapacity,
    NotPending,
}

// ---------------------------------------------------------------------------
// Task queries
// ---------------------------------------------------------------------------

/// Claim a single pending task by ID for scheduling (PENDING → SCHEDULING).
pub async fn claim_pending_task_by_id(
    pool: &PgPool,
    task_id: Uuid,
    max_concurrent_tasks: usize,
) -> Result<PendingTaskClaim, sqlx::Error> {
    let mut tx = pool.begin().await?;
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(TASK_ADMISSION_ADVISORY_LOCK_KEY)
        .execute(&mut *tx)
        .await?;

    let is_pending: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM joysafeter_tasks WHERE id = $1 AND status = 'pending')",
    )
    .bind(task_id)
    .fetch_one(&mut *tx)
    .await?;
    if !is_pending {
        tx.commit().await?;
        return Ok(PendingTaskClaim::NotPending);
    }

    let active_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM joysafeter_tasks WHERE status IN ('scheduling', 'running')",
    )
    .fetch_one(&mut *tx)
    .await?;
    if task_admission_capacity(active_count, max_concurrent_tasks) == 0 {
        tx.commit().await?;
        return Ok(PendingTaskClaim::AtCapacity);
    }

    let task = sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'scheduling', started_at = NOW(), updated_at = NOW()
        WHERE id = $1 AND status = 'pending'
        RETURNING *
        "#,
    )
    .bind(task_id)
    .fetch_optional(&mut *tx)
    .await?;
    tx.commit().await?;

    Ok(match task {
        Some(task) => PendingTaskClaim::Claimed(task),
        None => PendingTaskClaim::NotPending,
    })
}

/// Claim a batch of pending tasks for scheduling (PENDING → SCHEDULING).
/// Uses `FOR UPDATE SKIP LOCKED` to avoid contention across instances.
pub async fn claim_pending_tasks(
    pool: &PgPool,
    limit: i64,
    max_concurrent_tasks: usize,
) -> Result<Vec<JoySafeterTask>, sqlx::Error> {
    let mut tx = pool.begin().await?;
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(TASK_ADMISSION_ADVISORY_LOCK_KEY)
        .execute(&mut *tx)
        .await?;

    let active_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM joysafeter_tasks WHERE status IN ('scheduling', 'running')",
    )
    .fetch_one(&mut *tx)
    .await?;
    let available_capacity = task_admission_capacity(active_count, max_concurrent_tasks);
    let claim_limit = limit.max(0).min(available_capacity);
    if claim_limit == 0 {
        tx.commit().await?;
        return Ok(Vec::new());
    }

    let tasks = sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'scheduling', started_at = NOW(), updated_at = NOW()
        WHERE id IN (
            SELECT id FROM joysafeter_tasks
            WHERE status = 'pending'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        RETURNING *
        "#,
    )
    .bind(claim_limit)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(tasks)
}

#[cfg(test)]
mod admission_tests {
    use super::task_admission_capacity;

    #[test]
    fn task_admission_capacity_never_exceeds_global_limit() {
        assert_eq!(task_admission_capacity(0, 200), 200);
        assert_eq!(task_admission_capacity(199, 200), 1);
        assert_eq!(task_admission_capacity(200, 200), 0);
        assert_eq!(task_admission_capacity(250, 200), 0);
        assert_eq!(task_admission_capacity(0, 0), 0);
    }
}

/// Claim the next task for a specific sandbox (SCHEDULING/PENDING → RUNNING).
pub async fn claim_next_sandbox_task(
    pool: &PgPool,
    sandbox_id: Uuid,
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

/// Attach a sandbox to a task that is in 'scheduling' status.
pub async fn attach_sandbox_to_task(
    pool: &PgPool,
    task_id: Uuid,
    sandbox_id: Uuid,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET sandbox_id = $2, updated_at = NOW()
        WHERE id = $1 AND status = 'scheduling'
        "#,
    )
    .bind(task_id)
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Return a claimed task to PENDING only if it is still in SCHEDULING.
pub async fn reset_scheduling_task_to_pending(
    pool: &PgPool,
    task_id: Uuid,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
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
    task_id: Uuid,
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
pub async fn get_task(pool: &PgPool, task_id: Uuid) -> Result<Option<JoySafeterTask>, sqlx::Error> {
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
    task_id: Uuid,
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
    task_id: Uuid,
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
    sandbox_id: Uuid,
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
    sandbox_id: Uuid,
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
    sandbox_id: Uuid,
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
    task_id: Uuid,
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
    task_id: Uuid,
    sandbox_id: Uuid,
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
    active_task_leases: &[(Uuid, i64)],
) -> Result<u64, sqlx::Error> {
    if active_task_leases.is_empty() {
        return Ok(0);
    }

    let active_task_ids: Vec<Uuid> = active_task_leases
        .iter()
        .map(|(task_id, _)| *task_id)
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
    task_id: Uuid,
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
    task_id: Uuid,
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
pub async fn increment_scheduling_retry(
    pool: &PgPool,
    task_id: Uuid,
    expected_retry_count: i32,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
            retry_count = retry_count + 1,
            updated_at = NOW()
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

/// Check if a task has produced agent.message events (for failover decisions).
pub async fn task_has_agent_output(
    pool: &PgPool,
    task_id: Uuid,
    session_id: Uuid,
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
pub async fn find_pending_tasks(pool: &PgPool, limit: i64) -> Result<Vec<(Uuid,)>, sqlx::Error> {
    sqlx::query_as::<_, (Uuid,)>(
        "SELECT id FROM joysafeter_tasks WHERE status = 'pending' ORDER BY created_at LIMIT $1",
    )
    .bind(limit)
    .fetch_all(pool)
    .await
}
