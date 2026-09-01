use serde_json::json;
use sqlx::{PgPool, Postgres, Transaction};
use uuid::Uuid;

use crate::db::models::JoySafeterTask;
use crate::ids::{EventId, ProjectId, SandboxId, SessionId, TaskId};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

use super::session::{
    accumulate_session_usage_in_tx, insert_session_event_locked_in_tx,
    lock_session_event_sequence_in_tx, update_session_status_and_insert_event_in_tx,
    update_session_status_and_insert_event_locked_in_tx,
};

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ResetSandboxTask {
    pub id: TaskId,
    pub session_id: Option<SessionId>,
    pub previous_retry_count: i32,
    pub session_event: Option<(EventId, i64)>,
}

#[derive(Debug, Clone)]
pub struct FailedSandboxTask {
    pub id: TaskId,
    pub session_id: Option<SessionId>,
    pub session_event: Option<(EventId, i64)>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskRetryOutcome {
    pub session_id: Option<SessionId>,
    pub sandbox_id: Option<SandboxId>,
    pub sandbox_released: bool,
    pub session_event: Option<(EventId, i64)>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommittedSessionEvent {
    pub event_id: EventId,
    pub seq: i64,
    pub event_type: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskTerminalOutcome {
    pub session_id: Option<SessionId>,
    pub sandbox_id: Option<SandboxId>,
    pub sandbox_released: bool,
    pub session_events: Vec<CommittedSessionEvent>,
}

#[derive(Clone, Copy)]
enum TaskRetryTransition<'a> {
    Running {
        expected_owner_epoch: Option<i64>,
        require_expired_lease: bool,
        require_retry_budget: bool,
        error_message: Option<&'a str>,
    },
    Scheduling {
        backoff_seconds: i64,
        error_type: &'a str,
        error_message: &'a str,
    },
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
#[cfg(test)]
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
    let mut transaction = pool.begin().await?;
    let rows = sqlx::query_as::<_, (TaskId, Option<SessionId>, i32)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending', sandbox_id = NULL, started_at = NULL,
            scheduling_started_at = NULL, retry_count = retry_count + 1, updated_at = NOW()
        WHERE sandbox_id = $1 AND status = 'scheduling' AND retry_count < max_retries
        RETURNING id, chat_session_id, retry_count - 1 AS previous_retry_count
        "#,
    )
    .bind(sandbox_id)
    .fetch_all(&mut *transaction)
    .await?;
    let mut tasks = rows
        .into_iter()
        .map(|(id, session_id, previous_retry_count)| ResetSandboxTask {
            id,
            session_id,
            previous_retry_count,
            session_event: None,
        })
        .collect::<Vec<_>>();
    persist_reset_task_sessions_in_tx(
        &mut transaction,
        &mut tasks,
        &json!({"type": "sandbox_failed"}),
    )
    .await?;
    transaction.commit().await?;
    Ok(tasks)
}

/// Fail scheduling tasks already at retry limit for a sandbox and return
/// changed rows so callers can repair session state.
pub async fn fail_exhausted_sandbox_tasks_returning(
    pool: &PgPool,
    sandbox_id: SandboxId,
    reason: &str,
) -> Result<Vec<FailedSandboxTask>, sqlx::Error> {
    let mut transaction = pool.begin().await?;
    let rows = sqlx::query_as::<_, (TaskId, Option<SessionId>)>(
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
    .fetch_all(&mut *transaction)
    .await?;
    let mut tasks = rows
        .into_iter()
        .map(|(id, session_id)| FailedSandboxTask {
            id,
            session_id,
            session_event: None,
        })
        .collect::<Vec<_>>();
    persist_failed_task_sessions_in_tx(
        &mut transaction,
        &mut tasks,
        &json!({"type": "error", "message": reason}),
    )
    .await?;
    transaction.commit().await?;
    Ok(tasks)
}

pub(crate) async fn persist_reset_task_sessions_in_tx(
    transaction: &mut Transaction<'_, Postgres>,
    tasks: &mut [ResetSandboxTask],
    stop_reason: &serde_json::Value,
) -> Result<(), sqlx::Error> {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone(),
        });
        task.session_event = update_session_status_and_insert_event_in_tx(
            transaction,
            session_id,
            "rescheduling",
            Some(stop_reason),
            "session.status_rescheduling",
            &payload,
            false,
        )
        .await?;
    }
    Ok(())
}

pub(crate) async fn persist_failed_task_sessions_in_tx(
    transaction: &mut Transaction<'_, Postgres>,
    tasks: &mut [FailedSandboxTask],
    stop_reason: &serde_json::Value,
) -> Result<(), sqlx::Error> {
    for task in tasks {
        let Some(session_id) = task.session_id else {
            continue;
        };
        let payload = json!({
            "task_id": task.id.to_string(),
            "stop_reason": stop_reason.clone(),
        });
        task.session_event = update_session_status_and_insert_event_in_tx(
            transaction,
            session_id,
            "idle",
            Some(stop_reason),
            "session.status_idle",
            &payload,
            true,
        )
        .await?;
    }
    Ok(())
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

pub async fn retry_running_task_and_reschedule_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
    expected_sandbox_id: Option<SandboxId>,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskRetryOutcome>, sqlx::Error> {
    retry_task_and_reschedule_session(
        pool,
        task_id,
        expected_retry_count,
        expected_sandbox_id,
        TaskRetryTransition::Running {
            expected_owner_epoch,
            require_expired_lease: false,
            require_retry_budget: false,
            error_message: None,
        },
        stop_reason,
    )
    .await
}

pub async fn retry_lease_expired_task_and_reschedule_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
    expected_sandbox_id: Option<SandboxId>,
    reason: &str,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskRetryOutcome>, sqlx::Error> {
    retry_task_and_reschedule_session(
        pool,
        task_id,
        expected_retry_count,
        expected_sandbox_id,
        TaskRetryTransition::Running {
            expected_owner_epoch,
            require_expired_lease: true,
            require_retry_budget: true,
            error_message: Some(reason),
        },
        stop_reason,
    )
    .await
}

pub async fn retry_scheduling_task_and_reschedule_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_sandbox_id: Option<SandboxId>,
    backoff_seconds: i64,
    error_type: &str,
    error_message: &str,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskRetryOutcome>, sqlx::Error> {
    retry_task_and_reschedule_session(
        pool,
        task_id,
        expected_retry_count,
        expected_sandbox_id,
        TaskRetryTransition::Scheduling {
            backoff_seconds,
            error_type,
            error_message,
        },
        stop_reason,
    )
    .await
}

/// Atomically finish the exact RUNNING task generation, release only its own
/// sandbox binding, and persist the canonical session idle event.
pub async fn transition_running_task_terminal_and_idle_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_owner_epoch: Option<i64>,
    expected_sandbox_id: Option<SandboxId>,
    terminal_status: &str,
    output: Option<&str>,
    error_message: Option<&str>,
    usage: Option<&serde_json::Value>,
    fallback_agent_message: Option<&serde_json::Value>,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskTerminalOutcome>, sqlx::Error> {
    let mut transaction = pool.begin().await?;

    if let Some(sandbox_id) = expected_sandbox_id {
        sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
            .bind(sandbox_id)
            .fetch_optional(&mut *transaction)
            .await?;
    }

    let task = sqlx::query_as::<_, (Option<SessionId>, Option<SandboxId>)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = $4,
            output = COALESCE($5, output),
            error = COALESCE($6, error),
            usage = COALESCE($7, usage),
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND owner_epoch IS NOT DISTINCT FROM $2
          AND sandbox_id IS NOT DISTINCT FROM $3
          AND $4 = ANY(ARRAY['completed', 'failed', 'aborted', 'timeout', 'cancelled'])
        RETURNING chat_session_id, sandbox_id
        "#,
    )
    .bind(task_id)
    .bind(expected_owner_epoch)
    .bind(expected_sandbox_id)
    .bind(terminal_status)
    .bind(output)
    .bind(error_message)
    .bind(usage)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((session_id, sandbox_id)) = task else {
        transaction.rollback().await?;
        return Ok(None);
    };

    let outcome = finish_terminal_transition_in_tx(
        &mut transaction,
        task_id,
        session_id,
        sandbox_id,
        usage,
        fallback_agent_message,
        stop_reason,
    )
    .await?;
    transaction.commit().await?;
    Ok(Some(outcome))
}

pub async fn transition_expired_running_task_terminal_and_idle_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
    expected_sandbox_id: Option<SandboxId>,
    reason: &str,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskTerminalOutcome>, sqlx::Error> {
    let mut transaction = pool.begin().await?;

    if let Some(sandbox_id) = expected_sandbox_id {
        sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
            .bind(sandbox_id)
            .fetch_optional(&mut *transaction)
            .await?;
    }

    let task = sqlx::query_as::<_, (Option<SessionId>, Option<SandboxId>)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            error = $5,
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND retry_count = $2
          AND retry_count >= max_retries
          AND owner_epoch IS NOT DISTINCT FROM $3
          AND sandbox_id IS NOT DISTINCT FROM $4
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < NOW()
        RETURNING chat_session_id, sandbox_id
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .bind(expected_owner_epoch)
    .bind(expected_sandbox_id)
    .bind(reason)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((session_id, sandbox_id)) = task else {
        transaction.rollback().await?;
        return Ok(None);
    };

    let outcome = finish_terminal_transition_in_tx(
        &mut transaction,
        task_id,
        session_id,
        sandbox_id,
        None,
        None,
        stop_reason,
    )
    .await?;
    transaction.commit().await?;
    Ok(Some(outcome))
}

/// Atomically fail the exact RUNNING task generation after its provider runtime
/// disappeared, clear the task binding, release the sandbox, and persist the
/// canonical session idle event.
pub async fn transition_missing_runtime_task_terminal_and_idle_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_owner_epoch: Option<i64>,
    expected_sandbox_id: SandboxId,
    reason: &str,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskTerminalOutcome>, sqlx::Error> {
    let mut transaction = pool.begin().await?;

    sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
        .bind(expected_sandbox_id)
        .fetch_optional(&mut *transaction)
        .await?;

    let session_id = sqlx::query_scalar::<_, Option<SessionId>>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            sandbox_id = NULL,
            error = $5,
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'running'
          AND retry_count = $2
          AND retry_count >= max_retries
          AND owner_epoch IS NOT DISTINCT FROM $3
          AND sandbox_id = $4
        RETURNING chat_session_id
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .bind(expected_owner_epoch)
    .bind(expected_sandbox_id)
    .bind(reason)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some(session_id) = session_id else {
        transaction.rollback().await?;
        return Ok(None);
    };

    let outcome = finish_terminal_transition_in_tx(
        &mut transaction,
        task_id,
        session_id,
        Some(expected_sandbox_id),
        None,
        None,
        stop_reason,
    )
    .await?;
    transaction.commit().await?;
    Ok(Some(outcome))
}

/// Atomically finish the exact SCHEDULING attempt, release only its sandbox
/// binding, and persist the canonical session idle event.
pub async fn transition_scheduling_task_terminal_and_idle_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_sandbox_id: Option<SandboxId>,
    terminal_status: &str,
    error_message: &str,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskTerminalOutcome>, sqlx::Error> {
    let mut transaction = pool.begin().await?;

    if let Some(sandbox_id) = expected_sandbox_id {
        sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
            .bind(sandbox_id)
            .fetch_optional(&mut *transaction)
            .await?;
    }

    let task = sqlx::query_as::<_, (Option<SessionId>, Option<SandboxId>)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = $4,
            error = COALESCE($5, error),
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            owner_instance_id = NULL,
            owner_epoch = NULL,
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND status = 'scheduling'
          AND retry_count = $2
          AND sandbox_id IS NOT DISTINCT FROM $3
          AND $4 = ANY(ARRAY['completed', 'failed', 'aborted', 'timeout', 'cancelled'])
        RETURNING chat_session_id, sandbox_id
        "#,
    )
    .bind(task_id)
    .bind(expected_retry_count)
    .bind(expected_sandbox_id)
    .bind(terminal_status)
    .bind(error_message)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((session_id, sandbox_id)) = task else {
        transaction.rollback().await?;
        return Ok(None);
    };

    let outcome = finish_terminal_transition_in_tx(
        &mut transaction,
        task_id,
        session_id,
        sandbox_id,
        None,
        None,
        stop_reason,
    )
    .await?;
    transaction.commit().await?;
    Ok(Some(outcome))
}

async fn finish_terminal_transition_in_tx(
    transaction: &mut Transaction<'_, Postgres>,
    task_id: TaskId,
    session_id: Option<SessionId>,
    sandbox_id: Option<SandboxId>,
    usage: Option<&serde_json::Value>,
    fallback_agent_message: Option<&serde_json::Value>,
    stop_reason: &serde_json::Value,
) -> Result<TaskTerminalOutcome, sqlx::Error> {
    let sandbox_released = match sandbox_id {
        Some(sandbox_id) => release_sandbox_task_in_tx(transaction, sandbox_id, task_id).await?,
        None => false,
    };
    let mut session_events = Vec::new();

    if let Some(session_id) = session_id {
        lock_session_event_sequence_in_tx(transaction, session_id).await?;

        if let Some(usage) = usage {
            accumulate_session_usage_in_tx(transaction, session_id, usage).await?;
        }

        if let Some(payload) = fallback_agent_message {
            let has_agent_output: bool = sqlx::query_scalar(
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
            .fetch_one(&mut **transaction)
            .await?;
            if !has_agent_output {
                let (event_id, seq) = insert_session_event_locked_in_tx(
                    transaction,
                    session_id,
                    "agent.message",
                    payload,
                )
                .await?;
                session_events.push(CommittedSessionEvent {
                    event_id,
                    seq,
                    event_type: "agent.message".to_string(),
                    payload: payload.clone(),
                });
            }
        }

        let idle_payload = json!({
            "task_id": task_id.to_string(),
            "stop_reason": stop_reason.clone(),
        });
        if let Some((event_id, seq)) = update_session_status_and_insert_event_locked_in_tx(
            transaction,
            session_id,
            "idle",
            Some(stop_reason),
            "session.status_idle",
            &idle_payload,
            true,
        )
        .await?
        {
            session_events.push(CommittedSessionEvent {
                event_id,
                seq,
                event_type: "session.status_idle".to_string(),
                payload: idle_payload,
            });
        }
    }

    Ok(TaskTerminalOutcome {
        session_id,
        sandbox_id,
        sandbox_released,
        session_events,
    })
}

async fn retry_task_and_reschedule_session(
    pool: &PgPool,
    task_id: TaskId,
    expected_retry_count: i32,
    expected_sandbox_id: Option<SandboxId>,
    transition: TaskRetryTransition<'_>,
    stop_reason: &serde_json::Value,
) -> Result<Option<TaskRetryOutcome>, sqlx::Error> {
    let mut transaction = pool.begin().await?;

    if let Some(sandbox_id) = expected_sandbox_id {
        sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
            .bind(sandbox_id)
            .fetch_optional(&mut *transaction)
            .await?;
    }

    let expected_status = match transition {
        TaskRetryTransition::Running { .. } => "running",
        TaskRetryTransition::Scheduling { .. } => "scheduling",
    };
    let expected_owner_epoch = match transition {
        TaskRetryTransition::Running {
            expected_owner_epoch,
            ..
        } => expected_owner_epoch,
        TaskRetryTransition::Scheduling { .. } => None,
    };
    let (require_expired_lease, require_retry_budget) = match transition {
        TaskRetryTransition::Running {
            require_expired_lease,
            require_retry_budget,
            ..
        } => (require_expired_lease, require_retry_budget),
        TaskRetryTransition::Scheduling { .. } => (false, false),
    };
    let task = sqlx::query_as::<_, (Option<SessionId>, Option<SandboxId>)>(
        r#"
        SELECT chat_session_id, sandbox_id
        FROM joysafeter_tasks
        WHERE id = $1
          AND status = $2
          AND retry_count = $3
          AND sandbox_id IS NOT DISTINCT FROM $4
          AND ($2 <> 'running' OR owner_epoch IS NOT DISTINCT FROM $5)
          AND (NOT $6 OR lease_expires_at < NOW())
          AND (NOT $7 OR retry_count < max_retries)
        FOR UPDATE
        "#,
    )
    .bind(task_id)
    .bind(expected_status)
    .bind(expected_retry_count)
    .bind(expected_sandbox_id)
    .bind(expected_owner_epoch)
    .bind(require_expired_lease)
    .bind(require_retry_budget)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some((session_id, sandbox_id)) = task else {
        transaction.rollback().await?;
        return Ok(None);
    };

    match transition {
        TaskRetryTransition::Running { error_message, .. } => {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    started_at = NULL,
                    scheduling_started_at = NULL,
                    retry_count = retry_count + 1,
                    owner_instance_id = NULL,
                    owner_epoch = NULL,
                    lease_expires_at = NULL,
                    error = COALESCE($2, error),
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .bind(error_message)
            .execute(&mut *transaction)
            .await?;
        }
        TaskRetryTransition::Scheduling {
            backoff_seconds,
            error_type,
            error_message,
        } => {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    started_at = NULL,
                    scheduling_started_at = NULL,
                    schedule_attempts = schedule_attempts + 1,
                    retry_count = retry_count + 1,
                    next_schedule_at = NOW() + ($2 * INTERVAL '1 second'),
                    last_schedule_error_type = $3,
                    last_schedule_error = $4,
                    owner_instance_id = NULL,
                    owner_epoch = NULL,
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .bind(backoff_seconds)
            .bind(error_type)
            .bind(error_message)
            .execute(&mut *transaction)
            .await?;
        }
    }

    let sandbox_released = match sandbox_id {
        Some(sandbox_id) => {
            release_sandbox_task_in_tx(&mut transaction, sandbox_id, task_id).await?
        }
        None => false,
    };

    let session_event = match session_id {
        Some(session_id) => {
            let payload = json!({
                "task_id": task_id.to_string(),
                "stop_reason": stop_reason.clone(),
            });
            update_session_status_and_insert_event_in_tx(
                &mut transaction,
                session_id,
                "rescheduling",
                Some(stop_reason),
                "session.status_rescheduling",
                &payload,
                false,
            )
            .await?
        }
        None => None,
    };

    transaction.commit().await?;
    Ok(Some(TaskRetryOutcome {
        session_id,
        sandbox_id,
        sandbox_released,
        session_event,
    }))
}

async fn release_sandbox_task_in_tx(
    transaction: &mut Transaction<'_, Postgres>,
    sandbox_id: SandboxId,
    task_id: TaskId,
) -> Result<bool, sqlx::Error> {
    let transitioned: Option<bool> = sqlx::query_scalar(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = CASE
                WHEN status IN ('creating', 'provisioning', 'pooled', 'running', 'idle')
                    THEN 'idle'
                ELSE status
            END,
            last_task_id = NULL,
            last_used_at = CASE
                WHEN status IN ('creating', 'provisioning', 'pooled', 'running', 'idle')
                    THEN NOW()
                ELSE last_used_at
            END,
            updated_at = NOW(),
            idle_since = CASE
                WHEN status IN ('creating', 'provisioning', 'pooled', 'running') THEN NOW()
                ELSE idle_since
            END
        WHERE id = $1
          AND last_task_id = $2
          AND status != 'destroyed'
        RETURNING status = 'idle'
        "#,
    )
    .bind(sandbox_id)
    .bind(task_id)
    .fetch_optional(&mut **transaction)
    .await?;
    Ok(transitioned.unwrap_or(false))
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

/// Retry a task only if it is still in SCHEDULING with the expected retry count.
///
/// Scheduler failure callbacks are based on stale async observations; this CAS
/// prevents a late resolver failure from moving a task that already reached
/// RUNNING back to PENDING.
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
