use sqlx::PgPool;
use uuid::Uuid;

use super::models::{JoySafeterAgent, JoySafeterSandbox, JoySafeterSession, JoySafeterTask};

// ---------------------------------------------------------------------------
// Task queries
// ---------------------------------------------------------------------------

/// Claim a single pending task by ID for scheduling (PENDING → SCHEDULING).
pub async fn claim_pending_task_by_id(
    pool: &PgPool,
    task_id: Uuid,
) -> Result<Option<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'scheduling', started_at = NOW(), updated_at = NOW()
        WHERE id = $1 AND status = 'pending'
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
    .bind(limit)
    .fetch_all(pool)
    .await
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

// ---------------------------------------------------------------------------
// Session queries
// ---------------------------------------------------------------------------

/// Get a session by ID.
pub async fn get_session(
    pool: &PgPool,
    session_id: Uuid,
) -> Result<Option<JoySafeterSession>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSession>("SELECT * FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .fetch_optional(pool)
        .await
}

/// Atomically update a session status and append its replayable status event.
///
/// The session row and its `session.status_*` event are one state transition:
/// splitting them lets UI refresh, SSE replay, and recovery observe different
/// truths. This helper owns the session advisory lock and assigns the canonical
/// DB `seq` in the same transaction.
pub async fn update_session_status_and_insert_event(
    pool: &PgPool,
    session_id: Uuid,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<Option<(Uuid, i64)>, sqlx::Error> {
    update_session_status_and_insert_event_inner(
        pool,
        session_id,
        new_status,
        stop_reason,
        event_type,
        payload,
        false,
    )
    .await
}

/// Atomically update a session status only when no active task remains.
///
/// Use this for terminal/recovery observations that are not themselves the
/// authority for a specific active task. It prevents stale cleanup or watchdog
/// paths from making a session reusable while another task in the same session
/// is still pending, scheduling, or running.
pub async fn update_session_status_if_no_active_tasks_and_insert_event(
    pool: &PgPool,
    session_id: Uuid,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<Option<(Uuid, i64)>, sqlx::Error> {
    update_session_status_and_insert_event_inner(
        pool,
        session_id,
        new_status,
        stop_reason,
        event_type,
        payload,
        true,
    )
    .await
}

async fn update_session_status_and_insert_event_inner(
    pool: &PgPool,
    session_id: Uuid,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
    require_no_active_tasks: bool,
) -> Result<Option<(Uuid, i64)>, sqlx::Error> {
    let mut tx = pool.begin().await?;

    let lock_key = i64::from_be_bytes(session_id.as_bytes()[8..16].try_into().unwrap());
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(lock_key)
        .execute(&mut *tx)
        .await?;

    let allowed_from = match new_status {
        "running" => "'idle','running','rescheduling'",
        "idle" => "'running','rescheduling'",
        "terminated" => "'idle','running','rescheduling'",
        "rescheduling" => "'running','idle'",
        _ => "'idle','running','rescheduling','terminated'",
    };

    let active_task_guard = if require_no_active_tasks {
        r#"
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE chat_session_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#
    } else {
        ""
    };

    let sql = format!(
        r#"
        UPDATE joysafeter_sessions
        SET status = $2,
            stop_reason = CASE
                WHEN $3::jsonb IS NOT NULL OR $2 IN ('idle', 'terminated') THEN $3::jsonb
                ELSE stop_reason
            END,
            updated_at = NOW()
        WHERE id = $1 AND status IN ({allowed_from})
          {active_task_guard}
          AND NOT (status = $2 AND COALESCE(stop_reason, '{{}}'::jsonb) = COALESCE($3::jsonb, '{{}}'::jsonb))
        "#,
    );
    let update_result = sqlx::query(&sql)
        .bind(session_id)
        .bind(new_status)
        .bind(stop_reason)
        .execute(&mut *tx)
        .await?;

    if update_result.rows_affected() == 0 {
        tx.commit().await?;
        return Ok(None);
    }

    let seq: i64 = sqlx::query_scalar(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM joysafeter_session_events WHERE session_id = $1",
    )
    .bind(session_id)
    .fetch_one(&mut *tx)
    .await?;

    let event_id = Uuid::now_v7();
    let inserted = sqlx::query_as::<_, (Uuid, i64)>(
        r#"
        INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING id, seq
        "#,
    )
    .bind(event_id)
    .bind(session_id)
    .bind(event_type)
    .bind(payload)
    .bind(seq)
    .fetch_one(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(Some(inserted))
}

/// Update session sandbox reference.
pub async fn update_session_sandbox(
    pool: &PgPool,
    session_id: Uuid,
    sandbox_id: Uuid,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        "UPDATE joysafeter_sessions SET last_sandbox_id = $2, updated_at = NOW() WHERE id = $1",
    )
    .bind(session_id)
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Accumulate token usage for a session (field-by-field addition, not merge).
/// Matches Python SessionService.accumulate_usage which adds each token field.
pub async fn accumulate_session_usage(
    pool: &PgPool,
    session_id: Uuid,
    usage: &serde_json::Value,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        UPDATE joysafeter_sessions
        SET usage = jsonb_build_object(
            'input_tokens', COALESCE((usage->>'input_tokens')::bigint, 0) + COALESCE(($2::jsonb->>'input_tokens')::bigint, 0),
            'output_tokens', COALESCE((usage->>'output_tokens')::bigint, 0) + COALESCE(($2::jsonb->>'output_tokens')::bigint, 0),
            'cache_read_input_tokens', COALESCE((usage->>'cache_read_input_tokens')::bigint, 0) + COALESCE(($2::jsonb->>'cache_read_input_tokens')::bigint, 0),
            'cache_creation_input_tokens', COALESCE((usage->>'cache_creation_input_tokens')::bigint, 0) + COALESCE(($2::jsonb->>'cache_creation_input_tokens')::bigint, 0),
            'by_model', (
                SELECT COALESCE(
                    jsonb_object_agg(
                        model_name,
                        jsonb_build_object(
                            'input_tokens',
                                COALESCE((existing_usage->>'input_tokens')::bigint, 0)
                                + COALESCE((incoming_usage->>'input_tokens')::bigint, 0),
                            'output_tokens',
                                COALESCE((existing_usage->>'output_tokens')::bigint, 0)
                                + COALESCE((incoming_usage->>'output_tokens')::bigint, 0),
                            'cache_read_input_tokens',
                                COALESCE((existing_usage->>'cache_read_input_tokens')::bigint, 0)
                                + COALESCE((incoming_usage->>'cache_read_input_tokens')::bigint, 0),
                            'cache_creation_input_tokens',
                                COALESCE((existing_usage->>'cache_creation_input_tokens')::bigint, 0)
                                + COALESCE((incoming_usage->>'cache_creation_input_tokens')::bigint, 0)
                        )
                    ),
                    '{}'::jsonb
                )
                FROM jsonb_each(COALESCE(usage->'by_model', '{}'::jsonb))
                    AS existing_models(model_name, existing_usage)
                FULL OUTER JOIN jsonb_each(COALESCE($2::jsonb->'by_model', '{}'::jsonb))
                    AS incoming_models(model_name, incoming_usage)
                USING (model_name)
            )
        ),
            updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(session_id)
    .bind(usage)
    .execute(pool)
    .await?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Session event queries
// ---------------------------------------------------------------------------

/// Insert a batch of session events.
pub async fn batch_insert_events(
    pool: &PgPool,
    events: &[(Uuid, Uuid, &str, Option<&serde_json::Value>, Option<i64>)],
) -> Result<u64, sqlx::Error> {
    if events.is_empty() {
        return Ok(0);
    }

    let mut total = 0u64;
    for (id, session_id, event_type, payload, seq) in events {
        let result = sqlx::query(
            r#"
            INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (id) DO NOTHING
            "#,
        )
        .bind(id)
        .bind(session_id)
        .bind(event_type)
        .bind(payload)
        .bind(seq)
        .execute(pool)
        .await?;
        total += result.rows_affected();
    }
    Ok(total)
}

// ---------------------------------------------------------------------------
// Sandbox queries
// ---------------------------------------------------------------------------

/// Get a sandbox by ID.
pub async fn get_sandbox(
    pool: &PgPool,
    sandbox_id: Uuid,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>("SELECT * FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .fetch_optional(pool)
        .await
}

/// Find the current non-destroyed sandbox for a session (for reuse/recovery).
pub async fn find_sandbox_for_session(
    pool: &PgPool,
    session_id: Uuid,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE chat_session_id = $1
          AND status IN ('idle', 'running', 'creating', 'provisioning', 'stopped', 'stopping', 'error')
          AND destroyed_at IS NULL
        ORDER BY last_used_at DESC NULLS LAST
        LIMIT 1
        "#,
    )
    .bind(session_id)
    .fetch_optional(pool)
    .await
}

/// List all live sandboxes for Envoy LDS recovery on orchestrator startup.
///
/// Returns sandboxes that still exist (not destroyed) and are in a state where
/// their runner may still be connected, so their Envoy listeners must be
/// rebuilt after an orchestrator restart (which wipes the in-memory/gRPC xDS
/// state). The listener set (grpc + http pipes) is derived from the sandbox id;
/// the egress allowlist is read from `config.fingerprint.networking`.
pub async fn list_live_sandboxes_for_recovery(
    pool: &PgPool,
) -> Result<Vec<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE status IN ('idle', 'running', 'creating', 'provisioning')
          AND destroyed_at IS NULL
        ORDER BY created_at
        "#,
    )
    .fetch_all(pool)
    .await
}

/// Create a new sandbox record.
pub async fn create_sandbox(
    pool: &PgPool,
    id: Uuid,
    external_id: &str,
    provider: &str,
    image: &str,
    session_id: Option<Uuid>,
    project_id: Option<&str>,
    workspace_path: Option<&str>,
    config: Option<&serde_json::Value>,
) -> Result<JoySafeterSandbox, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        INSERT INTO joysafeter_sandboxes
            (id, external_id, provider, status, image, chat_session_id, project_id, workspace_path, config, last_used_at, created_at, updated_at)
        VALUES ($1, $2, $3, 'creating', $4, $5, $6, $7, $8, NOW(), NOW(), NOW())
        RETURNING *
        "#,
    )
    .bind(id)
    .bind(external_id)
    .bind(provider)
    .bind(image)
    .bind(session_id)
    .bind(project_id)
    .bind(workspace_path)
    .bind(config)
    .fetch_one(pool)
    .await
}

/// Transition sandbox status with state machine validation.
/// Only allows transitions defined in Python's SANDBOX_TRANSITIONS:
///   creating → provisioning, pooled, idle, stopped, error, destroyed
///   provisioning → idle, stopping, stopped, error, destroyed
///   pooled → provisioning, stopped, destroyed
///   idle → idle, running, stopping, stopped, error, destroyed
///   running → idle, stopped, error, destroyed
///   stopping → idle, stopped, error, destroyed
///   stopped → provisioning, destroyed
///   error → destroyed
/// Rejects transitions from 'destroyed' (terminal).
///
/// M4: DEPRECATED — Critical paths should call `transition_sandbox_cas()` with
/// an explicit expected state. This compatibility wrapper still performs a
/// status-machine check and fences the UPDATE on the status it just observed,
/// so stale callers cannot overwrite a concurrent terminal/error transition.
pub async fn transition_sandbox(
    pool: &PgPool,
    sandbox_id: Uuid,
    new_status: &str,
) -> Result<bool, sqlx::Error> {
    // M4: trace non-CAS usage so we can find and migrate remaining callers
    tracing::debug!(
        sandbox_id = %sandbox_id,
        to = %new_status,
        "transition_sandbox (non-CAS) called — prefer transition_sandbox_cas for critical paths"
    );

    let current_status: Option<String> =
        sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .fetch_optional(pool)
            .await?;

    let Some(from_status) = current_status else {
        return Ok(false);
    };
    if !is_valid_sandbox_transition(&from_status, new_status) {
        tracing::warn!(
            sandbox_id = %sandbox_id,
            from = %from_status,
            to = %new_status,
            "Rejected invalid sandbox state transition"
        );
        return Ok(false);
    }

    // idle_since is the idle-sweep's authoritative anchor: stamp NOW() when we
    // *enter* idle (current status != 'idle'), clear it when we leave idle,
    // leave it untouched otherwise. Same logic mirrored in transition_sandbox_cas
    // and the Python state machine — keep the three in lockstep.
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = $2,
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = CASE
                WHEN $2 = 'idle' AND status <> 'idle' THEN NOW()
                WHEN $2 <> 'idle' AND status = 'idle' THEN NULL
                ELSE idle_since
            END
        WHERE id = $1
          AND status = $3
        "#,
    )
    .bind(sandbox_id)
    .bind(new_status)
    .bind(from_status)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

pub async fn mark_sandbox_error(
    pool: &PgPool,
    sandbox_id: Uuid,
    error_msg: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'error',
            config = CASE
                WHEN $2::text IS NULL THEN config
                ELSE COALESCE(config, '{}'::jsonb) || jsonb_build_object('setup_error', $2::text)
            END,
            last_task_id = NULL,
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status != 'destroyed'
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE sandbox_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(error_msg)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// S7: Check if a sandbox state transition is valid per the documented state machine.
/// Returns true for valid transitions, false otherwise.
fn is_valid_sandbox_transition(from: &str, to: &str) -> bool {
    // Same-state transitions are always valid (idempotent)
    if from == to {
        return true;
    }
    matches!(
        (from, to),
        ("creating", "provisioning")
            | ("creating", "pooled")
            | ("creating", "idle")
            | ("creating", "stopped")
            | ("creating", "error")
            | ("creating", "destroyed")
            | ("provisioning", "idle")
            | ("provisioning", "stopping")
            | ("provisioning", "stopped")
            | ("provisioning", "error")
            | ("provisioning", "destroyed")
            | ("pooled", "provisioning")
            | ("pooled", "stopped")
            | ("pooled", "destroyed")
            | ("idle", "running")
            | ("idle", "stopping")
            | ("idle", "stopped")
            | ("idle", "error")
            | ("idle", "destroyed")
            | ("running", "idle")
            | ("running", "stopped")
            | ("running", "error")
            | ("running", "destroyed")
            | ("stopping", "idle")
            | ("stopping", "stopped")
            | ("stopping", "error")
            | ("stopping", "destroyed")
            | ("stopped", "provisioning")
            | ("stopped", "destroyed")
            | ("error", "destroyed")
    )
}

/// Mark a sandbox task as complete and return the sandbox to idle.
///
/// This helper is on critical execution/recovery paths. It must release the
/// task association without resurrecting unhealthy sandboxes: `error`,
/// `stopped`, `stopping`, and `destroyed` are not allowed to become `idle`.
pub async fn complete_sandbox_task(pool: &PgPool, sandbox_id: Uuid) -> Result<bool, sqlx::Error> {
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
        WHERE id = $1 AND status != 'destroyed'
        RETURNING status = 'idle'
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(pool)
    .await?;

    Ok(transitioned.unwrap_or(false))
}

/// Mark a healthy sandbox as running for a specific task.
///
/// Dispatch must not resurrect sandboxes that a cleanup/setup-failure path has
/// already moved to `error`, `stopped`, `stopping`, or `destroyed`. This helper
/// binds `last_task_id` and the running status in one conditional write so
/// downstream cleanup can reliably release the exact task association.
pub async fn start_sandbox_task(
    pool: &PgPool,
    sandbox_id: Uuid,
    task_id: Uuid,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'running',
            last_task_id = $2,
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND destroyed_at IS NULL
          AND status IN ('idle', 'provisioning', 'running')
          AND (last_task_id IS NULL OR last_task_id = $2)
        "#,
    )
    .bind(sandbox_id)
    .bind(task_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark a sandbox as stopped without overwriting terminal/unhealthy states.
///
/// Stop/reaper paths often perform provider calls before the DB write. During
/// that gap another path can mark the sandbox `error` or `destroyed`; this
/// helper preserves those authoritative states instead of converting them to a
/// healthy stopped row.
pub async fn mark_sandbox_stopped_if_active(
    pool: &PgPool,
    sandbox_id: Uuid,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND destroyed_at IS NULL
          AND status IN ('creating', 'provisioning', 'pooled', 'idle', 'running', 'stopping', 'stopped')
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark a sandbox as stopped only while it is still the row claimed by cleanup.
pub async fn mark_sandbox_stopped_if_status_and_external_id(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_status: &str,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = $2
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $3
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_status)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Finalize a newly-created warm-pool sandbox as pooled.
///
/// This is intentionally narrower than the generic sandbox state machine:
/// warm-pool provisioning creates the provider runtime before inserting the DB
/// row, then immediately finalizes the row as `pooled`. A fast runner can
/// connect between insert and finalize, causing the ready path to move the row
/// to `idle`; accepting `idle` here preserves that production race without
/// exposing a general `idle -> pooled` transition. Error/stop/destroy states
/// are preserved so a late pool finalizer cannot resurrect cleaned-up rows.
pub async fn mark_pool_sandbox_ready(pool: &PgPool, sandbox_id: Uuid) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'pooled',
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND destroyed_at IS NULL
          AND chat_session_id IS NULL
          AND status IN ('creating', 'idle', 'pooled')
          AND config #>> '{provisioning,stage}' = 'pool_warm'
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Keep sandbox status and config in sync during provisioning progress polling.
pub async fn update_sandbox_status_and_config(
    pool: &PgPool,
    sandbox_id: Uuid,
    status: &str,
    config: &serde_json::Value,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = $2, config = COALESCE(config, '{}'::jsonb) || $3::jsonb, updated_at = NOW()
        WHERE id = $1
          AND status = $2
          AND destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .bind(status)
    .bind(config)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

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

/// Mark sandbox as destroyed.
pub async fn destroy_sandbox(pool: &PgPool, sandbox_id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'destroyed', destroyed_at = NOW(), updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(())
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CommandDestroySandboxClaim {
    pub external_id: Option<String>,
    pub previous_status: String,
}

/// Claim a sandbox row for an explicit cross-instance destroy command.
///
/// Unlike passive cleanup, explicit user/admin destroy may be part of a forced
/// lifecycle operation after upstream cancellation. It therefore fences on row
/// identity and `external_id`, but does not reject solely because historical
/// active task rows still reference the sandbox.
pub async fn claim_sandbox_for_command_destroy(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_external_id: Option<&str>,
) -> Result<Option<CommandDestroySandboxClaim>, sqlx::Error> {
    sqlx::query_as::<_, CommandDestroySandboxClaim>(
        r#"
        WITH candidate AS (
            SELECT id, external_id, status AS previous_status
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND status != 'destroyed'
              AND destroyed_at IS NULL
              AND ($2::TEXT IS NULL OR external_id = $2)
            FOR UPDATE
        )
        UPDATE joysafeter_sandboxes s
        SET status = 'stopping',
            updated_at = NOW(),
            idle_since = NULL
        FROM candidate
        WHERE s.id = candidate.id
        RETURNING candidate.external_id, candidate.previous_status
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_external_id)
    .fetch_optional(pool)
    .await
}

/// Mark a passively observed sandbox as destroyed only if the row still matches
/// the status/external id observed by the cleanup path.
///
/// Passive sweeps and command-driven provider deletion must not convert a
/// sandbox that concurrently restarted, reconnected, or moved to a different
/// lifecycle state into `destroyed` based on a stale pre-provider-call
/// observation.
pub async fn destroy_sandbox_if_status_and_external_id(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_status: &str,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'destroyed',
            destroyed_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = $2
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $3
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_status)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark a passively recovered sandbox as destroyed after task repair.
///
/// Missing-runtime/bridge-health cleanup can legitimately move a `running`
/// sandbox to `idle` while retrying/failing its tasks. This helper accepts that
/// cleanup-owned `idle` release, but still rejects rows whose external id changed
/// or that have any active task bound to the sandbox.
pub async fn destroy_sandbox_after_passive_recovery(
    pool: &PgPool,
    sandbox_id: Uuid,
    observed_status: &str,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'destroyed',
            destroyed_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $3
          AND (status = $2 OR status = 'idle')
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE sandbox_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(observed_status)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Claim a sandbox row for passive external destruction.
///
/// This is intentionally separate from final `destroyed`: cleanup paths must
/// prove they still own the stale observation before calling provider.destroy,
/// but they should not hide a row as destroyed until the provider operation has
/// actually succeeded. Moving the row to `stopping` prevents reuse/dispatch
/// while the external runtime is being destroyed.
pub async fn claim_sandbox_for_passive_destroy(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_status: &str,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopping',
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = $2
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $3
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE sandbox_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_status)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Claim an unattached warm-pool sandbox before provider destroy.
///
/// Pool provisioning starts as an unattached `creating` row, while pool claim
/// first moves `pooled -> provisioning` without a session. If ready finalization
/// or later session/config attach fails, resolver may only destroy the external
/// runtime while the row is still that unattached warm-pool row. A concurrent
/// error, session attachment, or task binding owns the row and must stop cleanup
/// from deleting the provider runtime.
pub async fn claim_unattached_pool_sandbox_for_passive_destroy(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_external_id: Option<&str>,
) -> Result<Option<String>, sqlx::Error> {
    let previous_status = sqlx::query_scalar::<_, String>(
        r#"
        WITH candidate AS (
            SELECT id, status
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND status IN ('creating', 'provisioning')
              AND destroyed_at IS NULL
              AND external_id IS NOT DISTINCT FROM $2
              AND chat_session_id IS NULL
              AND config #>> '{provisioning,stage}' = 'pool_warm'
              AND NOT EXISTS (
                  SELECT 1 FROM joysafeter_tasks
                  WHERE sandbox_id = $1
                    AND status IN ('pending', 'scheduling', 'running')
              )
            FOR UPDATE
        )
        UPDATE joysafeter_sandboxes
        SET status = 'stopping',
            updated_at = NOW(),
            idle_since = NULL
        FROM candidate
        WHERE joysafeter_sandboxes.id = candidate.id
        RETURNING candidate.status
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_external_id)
    .fetch_optional(pool)
    .await?;

    Ok(previous_status)
}

/// Claim a passively recovered sandbox row for external destruction.
///
/// Missing-runtime and bridge-health cleanup first repair task/session state.
/// That can legitimately release a previously `running` sandbox back to `idle`.
/// Before calling provider.destroy, cleanup still has to isolate the row so no
/// scheduler can reuse the same external runtime while it is being destroyed.
/// Returns the status that should be restored if provider destruction fails.
pub async fn claim_sandbox_for_passive_destroy_after_recovery(
    pool: &PgPool,
    sandbox_id: Uuid,
    observed_status: &str,
    expected_external_id: Option<&str>,
) -> Result<Option<String>, sqlx::Error> {
    let previous_status = sqlx::query_scalar::<_, String>(
        r#"
        WITH candidate AS (
            SELECT id, status
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND destroyed_at IS NULL
              AND external_id IS NOT DISTINCT FROM $3
              AND (status = $2 OR status = 'idle')
              AND NOT EXISTS (
                  SELECT 1 FROM joysafeter_tasks
                  WHERE sandbox_id = $1
                    AND status IN ('pending', 'scheduling', 'running')
              )
            FOR UPDATE
        )
        UPDATE joysafeter_sandboxes s
        SET status = 'stopping',
            updated_at = NOW(),
            idle_since = NULL
        FROM candidate
        WHERE s.id = candidate.id
        RETURNING candidate.status
        "#,
    )
    .bind(sandbox_id)
    .bind(observed_status)
    .bind(expected_external_id)
    .fetch_optional(pool)
    .await?;

    Ok(previous_status)
}

/// Claim a passively recovered sandbox row before external stop.
///
/// Non-graceful reap first repairs tasks. A previously `running` sandbox can be
/// released to `idle` by that repair, but provider.stop must not run while the
/// row is reusable. This claim isolates the row as `stopping` only for active
/// lifecycle states owned by the stale reap observation.
pub async fn claim_sandbox_for_passive_stop_after_recovery(
    pool: &PgPool,
    sandbox_id: Uuid,
    observed_status: &str,
    expected_external_id: Option<&str>,
) -> Result<Option<String>, sqlx::Error> {
    let previous_status = sqlx::query_scalar::<_, String>(
        r#"
        WITH candidate AS (
            SELECT id, status
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND destroyed_at IS NULL
              AND external_id IS NOT DISTINCT FROM $3
              AND $2 IN ('creating', 'provisioning', 'running')
              AND (
                  status = $2
                  OR ($2 = 'running' AND status = 'idle')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM joysafeter_tasks
                  WHERE sandbox_id = $1
                    AND status IN ('pending', 'scheduling', 'running')
              )
            FOR UPDATE
        )
        UPDATE joysafeter_sandboxes s
        SET status = 'stopping',
            updated_at = NOW(),
            idle_since = NULL
        FROM candidate
        WHERE s.id = candidate.id
        RETURNING candidate.status
        "#,
    )
    .bind(sandbox_id)
    .bind(observed_status)
    .bind(expected_external_id)
    .fetch_optional(pool)
    .await?;

    Ok(previous_status)
}

/// Re-claim a stuck `stopping` sandbox before force-stopping its runtime.
pub async fn claim_stopping_sandbox_for_force_stop(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = 'stopping'
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $2
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE sandbox_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Restore a passive-destroy claim when provider destruction failed.
pub async fn restore_sandbox_after_passive_destroy_failure(
    pool: &PgPool,
    sandbox_id: Uuid,
    previous_status: &str,
    expected_external_id: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = $2,
            updated_at = NOW(),
            idle_since = CASE
                WHEN $2 = 'idle' THEN COALESCE(idle_since, NOW())
                ELSE idle_since
            END
        WHERE id = $1
          AND status = 'stopping'
          AND destroyed_at IS NULL
          AND external_id IS NOT DISTINCT FROM $3
        "#,
    )
    .bind(sandbox_id)
    .bind(previous_status)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

// ---------------------------------------------------------------------------
// Agent queries
// ---------------------------------------------------------------------------

/// Get an agent by ID.
pub async fn get_agent(
    pool: &PgPool,
    agent_id: Uuid,
) -> Result<Option<JoySafeterAgent>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterAgent>(
        r#"
        SELECT id, project_id, name, engine_kind, model->>'id' AS model, system_prompt,
               description, env, mcp_configs, skills, agents, commands, tools,
               permission_mode, metadata, multiagent, version, environment_ref, secret_ref
        FROM joysafeter_agents
        WHERE id = $1 AND deleted_at IS NULL
        "#,
    )
    .bind(agent_id)
    .fetch_optional(pool)
    .await
}

// ---------------------------------------------------------------------------
// Additional queries for full parity (Phase 2+)
// ---------------------------------------------------------------------------

/// CAS (compare-and-swap) sandbox status transition.
/// Only updates if current status matches `expected_status`.
pub async fn transition_sandbox_cas(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_status: &str,
    new_status: &str,
) -> Result<bool, sqlx::Error> {
    // Same idle_since bookkeeping as update_sandbox_status. Because this is
    // a CAS we know the current status equals expected_status when the row
    // matches, so we use it directly instead of CASE on the row's status.
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = $3,
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = CASE
                WHEN $3 = 'idle' AND $2 <> 'idle' THEN NOW()
                WHEN $3 <> 'idle' AND $2 = 'idle' THEN NULL
                ELSE idle_since
            END
        WHERE id = $1 AND status = $2
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_status)
    .bind(new_status)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Claim a stopped sandbox row before restarting its external runtime.
pub async fn claim_stopped_sandbox_for_restart(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_external_id: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'provisioning',
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = 'stopped'
          AND destroyed_at IS NULL
          AND external_id = $2
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Restore a restart claim when provider start fails before task dispatch.
pub async fn restore_stopped_sandbox_after_restart_start_failure(
    pool: &PgPool,
    sandbox_id: Uuid,
    expected_external_id: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status = 'provisioning'
          AND destroyed_at IS NULL
          AND external_id = $2
          AND NOT EXISTS (
              SELECT 1 FROM joysafeter_tasks
              WHERE sandbox_id = $1
                AND status IN ('pending', 'scheduling', 'running')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(expected_external_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
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

/// Create a new session record.
pub async fn create_session(
    pool: &PgPool,
    id: Uuid,
    agent_id: Option<Uuid>,
    project_id: Option<&str>,
    agent_snapshot: Option<&serde_json::Value>,
    environment_ref: Option<&str>,
) -> Result<JoySafeterSession, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSession>(
        r#"
        INSERT INTO joysafeter_sessions
            (id, agent_id, project_id, status, agent_snapshot, environment_ref, created_at, updated_at)
        VALUES ($1, $2, $3, 'idle', $4, $5, NOW(), NOW())
        RETURNING *
        "#,
    )
    .bind(id)
    .bind(agent_id)
    .bind(project_id)
    .bind(agent_snapshot)
    .bind(environment_ref)
    .fetch_one(pool)
    .await
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

/// Touch sandbox last_used_at timestamp.
pub async fn touch_sandbox(pool: &PgPool, sandbox_id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query(
        "UPDATE joysafeter_sandboxes SET last_used_at = NOW(), updated_at = NOW() WHERE id = $1",
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Stamp the bridge-disconnect marker. Fallback sweeper reaps sandboxes
/// whose bridge has been gone past a grace window, so a crashed runner
/// can't leave a sandbox indefinitely "idle" without ever sending
/// RunnerIdle. Idempotent: a second call while the marker is still set
/// is a no-op (we want the earliest disconnect timestamp).
pub async fn mark_bridge_disconnected(pool: &PgPool, sandbox_id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET disconnected_at = NOW(), updated_at = NOW()
        WHERE id = $1 AND disconnected_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Clear the bridge-disconnect marker on a successful runner attach.
pub async fn mark_bridge_connected(pool: &PgPool, sandbox_id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET disconnected_at = NULL, updated_at = NOW()
        WHERE id = $1 AND disconnected_at IS NOT NULL
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(())
}

/// Update session with sandbox info (harness_session_id, work_dir).
pub async fn update_session_sandbox_info(
    pool: &PgPool,
    session_id: Uuid,
    sandbox_id: Uuid,
    harness_session_id: Option<&str>,
    work_dir: Option<&str>,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        UPDATE joysafeter_sessions
        SET last_sandbox_id = $2,
            last_harness_session_id = COALESCE($3, last_harness_session_id),
            last_work_dir = COALESCE($4, last_work_dir),
            updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(session_id)
    .bind(sandbox_id)
    .bind(harness_session_id)
    .bind(work_dir)
    .execute(pool)
    .await?;
    Ok(())
}

/// Try to acquire a PostgreSQL advisory lock (non-blocking).
///
/// IMPORTANT: `pg_try_advisory_lock` is a session-level lock — it must be
/// released on the SAME connection. With a connection pool, separate
/// `execute(pool)` calls may hit different connections, so the lock is
/// acquired on one connection but never released (the unlock runs on
/// another connection and produces "you don't own a lock" warnings).
///
/// For watchdog use-cases where the critical section is short, prefer
/// wrapping all work in a single transaction with `pg_try_advisory_xact_lock`
/// (which auto-releases on COMMIT/ROLLBACK). This function is kept for
/// backward compatibility but callers should migrate.
pub async fn try_advisory_lock(pool: &PgPool, lock_name: &str) -> Result<bool, sqlx::Error> {
    let row: (bool,) = sqlx::query_as("SELECT pg_try_advisory_lock(hashtext($1))")
        .bind(lock_name)
        .fetch_one(pool)
        .await?;

    Ok(row.0)
}

/// Release a PostgreSQL advisory lock.
///
/// NOTE: This is a no-op if the lock was acquired on a different pooled
/// connection. See `try_advisory_lock` doc. Callers should migrate to
/// transaction-scoped advisory locks (`pg_try_advisory_xact_lock`).
pub async fn release_advisory_lock(pool: &PgPool, lock_name: &str) -> Result<(), sqlx::Error> {
    // Intentionally a no-op now. Session-level advisory locks acquired via
    // the pool cannot be reliably released because unlock may run on a
    // different connection. The locks are harmless — they auto-release
    // when the connection is returned to the pool and eventually closed.
    // Callers should use transaction-scoped locks instead.
    let _ = lock_name;
    let _ = pool;
    Ok(())
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

/// Find a stopped sandbox for a session (for restart).
pub async fn find_stopped_sandbox_for_session(
    pool: &PgPool,
    session_id: Uuid,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE chat_session_id = $1
          AND status = 'stopped'
          AND destroyed_at IS NULL
        ORDER BY last_used_at DESC NULLS LAST
        LIMIT 1
        "#,
    )
    .bind(session_id)
    .fetch_optional(pool)
    .await
}

/// Claim a sandbox from the warm pool (FOR UPDATE SKIP LOCKED).
pub async fn claim_pool_sandbox(
    pool: &PgPool,
    image: &str,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'provisioning', updated_at = NOW()
        WHERE id = (
            SELECT id FROM joysafeter_sandboxes
            WHERE status = 'pooled' AND image = $1 AND destroyed_at IS NULL
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING *
        "#,
    )
    .bind(image)
    .fetch_optional(pool)
    .await
}

/// Query session memory stores for a session.
pub async fn list_session_memory_stores(
    pool: &PgPool,
    session_id: Uuid,
) -> Result<Vec<SessionMemoryStore>, sqlx::Error> {
    sqlx::query_as::<_, SessionMemoryStore>(
        r#"
        SELECT sms.store_id, ms.name as store_name, sms.mount_name, sms.access, sms.instructions
        FROM joysafeter_session_memory_stores sms
        JOIN joysafeter_memory_stores ms ON ms.id = sms.store_id
        WHERE sms.session_id = $1
        "#,
    )
    .bind(session_id)
    .fetch_all(pool)
    .await
}

/// A session's memory store mount info.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct SessionMemoryStore {
    pub store_id: Uuid,
    pub store_name: String,
    pub mount_name: String,
    pub access: String,
    pub instructions: Option<String>,
}

/// Load memory files for a store.
pub async fn load_memory_files(
    pool: &PgPool,
    store_id: Uuid,
    limit: i64,
) -> Result<Vec<MemoryFileRow>, sqlx::Error> {
    sqlx::query_as::<_, MemoryFileRow>(
        r#"
        SELECT path, content FROM joysafeter_memories
        WHERE store_id = $1
        ORDER BY path
        LIMIT $2
        "#,
    )
    .bind(store_id)
    .bind(limit)
    .fetch_all(pool)
    .await
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct MemoryFileRow {
    pub path: String,
    pub content: Option<String>,
}

#[cfg(test)]
mod tests {
    use std::env;
    use std::sync::Arc;

    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;

    use super::*;
    use crate::config::JoySafeterConfig;
    use crate::events::bus::EventBus;
    use crate::events::envelope::EventEnvelope;
    use crate::events::persist::EventPersister;
    use crate::events::session_state::SessionStateSubscriber;
    use crate::events::stream_publisher::EventStreamPublisher;
    use crate::runtime_config::RuntimeConfig;

    fn database_url() -> Option<String> {
        env::var("DATABASE_URL")
            .ok()
            .or_else(|| env::var("JOYSAFETER_TEST_DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres scenario test: DATABASE_URL is not set");
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

    async fn create_agent_and_session(pool: &PgPool, status: &str) -> (Uuid, Uuid) {
        let agent_id = Uuid::now_v7();
        let session_id = Uuid::now_v7();
        let agent_name = format!("rust-status-scenario-{agent_id}");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_agents (id, name, engine_kind, permission_mode, version)
            VALUES ($1, $2, 'claude', 'bypassPermissions', 1)
            "#,
        )
        .bind(agent_id)
        .bind(agent_name)
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

    async fn create_task(pool: &PgPool, agent_id: Uuid, session_id: Uuid, status: &str) -> Uuid {
        let task_id = Uuid::now_v7();
        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, 'test prompt', '', 7200, 0, 2)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(status)
        .execute(pool)
        .await
        .expect("insert test task");
        task_id
    }

    #[tokio::test]
    async fn transition_task_cas_sets_terminal_completion_metadata() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            sqlx::query(
                "UPDATE joysafeter_tasks SET started_at = NOW() - INTERVAL '3 seconds' WHERE id = $1",
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("backdate running task start");

            let transitioned = transition_task_cas(
                &pool,
                task_id,
                "running",
                "timeout",
                Some("server-side deadline"),
                None,
            )
            .await
            .expect("timeout CAS transition");
            assert!(transitioned);

            let row: (
                String,
                Option<String>,
                Option<chrono::DateTime<chrono::Utc>>,
                Option<i64>,
            ) = sqlx::query_as(
                "SELECT status, error, completed_at, duration_ms FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load terminal task metadata");

            assert_eq!(row.0, "timeout");
            assert_eq!(row.1.as_deref(), Some("server-side deadline"));
            assert!(row.2.is_some());
            assert!(row.3.unwrap_or_default() >= 2_000);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn scheduling_retry_helpers_do_not_move_running_tasks_back_to_pending() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let scheduling_task_id = create_task(&pool, agent_id, session_id, "scheduling").await;
        let running_task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let reset = reset_scheduling_task_to_pending(&pool, scheduling_task_id)
                .await
                .expect("reset scheduling task");
            assert!(reset);

            let scheduling_row: (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(scheduling_task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load reset scheduling task");
            assert_eq!(scheduling_row.0, "pending");
            assert_eq!(scheduling_row.1, 0);

            let reset_running = reset_scheduling_task_to_pending(&pool, running_task_id)
                .await
                .expect("reset running task should be no-op");
            assert!(!reset_running);

            let retry_running = increment_scheduling_retry(&pool, running_task_id, 0)
                .await
                .expect("retry running task should be no-op");
            assert!(!retry_running);

            let running_row: (String, i32) =
                sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                    .bind(running_task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load running task after scheduling-only helpers");
            assert_eq!(running_row.0, "running");
            assert_eq!(running_row.1, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn running_retry_is_owner_epoch_fenced_and_clears_lease() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET owner_instance_id = 'owner-a',
                    owner_epoch = 41,
                    lease_expires_at = NOW() + INTERVAL '60 seconds',
                    started_at = NOW()
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("stamp owner lease");

            let stale_retry = increment_running_retry(&pool, task_id, 0, Some(40))
                .await
                .expect("stale owner retry should be a clean CAS miss");
            assert!(!stale_retry);

            let owned_retry = increment_running_retry(&pool, task_id, 0, Some(41))
                .await
                .expect("current owner retry should succeed");
            assert!(owned_retry);

            let row: (
                String,
                i32,
                Option<String>,
                Option<i64>,
                Option<chrono::DateTime<chrono::Utc>>,
                Option<chrono::DateTime<chrono::Utc>>,
            ) = sqlx::query_as(
                r#"
                SELECT status, retry_count, owner_instance_id, owner_epoch, lease_expires_at, started_at
                FROM joysafeter_tasks
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load retried task");

            assert_eq!(row.0, "pending");
            assert_eq!(row.1, 1);
            assert!(row.2.is_none());
            assert!(row.3.is_none());
            assert!(row.4.is_none());
            assert!(row.5.is_none());
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn observed_owner_epoch_transition_does_not_mutate_reclaimed_task() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let null_owner_task = create_task(&pool, agent_id, session_id, "running").await;
        let epoch_owner_task = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET owner_instance_id = 'owner-b',
                    owner_epoch = 51,
                    started_at = NOW(),
                    lease_expires_at = NOW() + INTERVAL '60 seconds'
                WHERE id = $1
                "#,
            )
            .bind(null_owner_task)
            .execute(&pool)
            .await
            .expect("simulate reclaim after legacy null-owner observation");

            let stale_null_transition = transition_task_cas_observed_owner_epoch(
                &pool,
                null_owner_task,
                "running",
                "timeout",
                Some("stale null-owner watchdog"),
                None,
            )
            .await
            .expect("stale null owner transition should be a clean CAS miss");
            assert!(!stale_null_transition);

            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET owner_instance_id = 'owner-a',
                    owner_epoch = 41,
                    started_at = NOW() - INTERVAL '10 seconds',
                    lease_expires_at = NOW() + INTERVAL '60 seconds'
                WHERE id = $1
                "#,
            )
            .bind(epoch_owner_task)
            .execute(&pool)
            .await
            .expect("stamp original owner");
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET owner_instance_id = 'owner-b',
                    owner_epoch = 42,
                    started_at = NOW(),
                    lease_expires_at = NOW() + INTERVAL '60 seconds'
                WHERE id = $1
                "#,
            )
            .bind(epoch_owner_task)
            .execute(&pool)
            .await
            .expect("simulate reclaim with new owner");

            let stale_epoch_transition = transition_task_cas_observed_owner_epoch(
                &pool,
                epoch_owner_task,
                "running",
                "timeout",
                Some("stale owner watchdog"),
                Some(41),
            )
            .await
            .expect("stale owner transition should be a clean CAS miss");
            assert!(!stale_epoch_transition);

            let current_epoch_transition = transition_task_cas_observed_owner_epoch(
                &pool,
                epoch_owner_task,
                "running",
                "completed",
                None,
                Some(42),
            )
            .await
            .expect("current owner transition should succeed");
            assert!(current_epoch_transition);

            let null_owner_row: (String, Option<i64>, Option<String>) = sqlx::query_as(
                "SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(null_owner_task)
            .fetch_one(&pool)
            .await
            .expect("load null-owner reclaimed task");
            assert_eq!(null_owner_row.0, "running");
            assert_eq!(null_owner_row.1, Some(51));
            assert!(null_owner_row.2.is_none());

            let epoch_owner_row: (String, Option<i64>, Option<String>) = sqlx::query_as(
                "SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(epoch_owner_task)
            .fetch_one(&pool)
            .await
            .expect("load epoch-owner reclaimed task");
            assert_eq!(epoch_owner_row.0, "completed");
            assert!(epoch_owner_row.1.is_none());
            assert!(epoch_owner_row.2.is_none());
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn lease_renewal_matches_task_id_and_owner_epoch_pair() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_a = create_task(&pool, agent_id, session_id, "running").await;
        let task_b = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            for (task_id, owner_epoch) in [(task_a, 10_i64), (task_b, 20_i64)] {
                sqlx::query(
                    r#"
                    UPDATE joysafeter_tasks
                    SET owner_instance_id = 'owner-a',
                        owner_epoch = $2,
                        lease_expires_at = NOW() - INTERVAL '10 seconds'
                    WHERE id = $1
                    "#,
                )
                .bind(task_id)
                .bind(owner_epoch)
                .execute(&pool)
                .await
                .expect("stamp expired owner lease");
            }

            let renewed =
                renew_running_task_leases(&pool, "owner-a", 60, &[(task_a, 10), (task_b, 19)])
                    .await
                    .expect("renew matching leases");
            assert_eq!(renewed, 1);

            let rows: Vec<(Uuid, bool)> = sqlx::query_as(
                r#"
                SELECT id, lease_expires_at > NOW() AS renewed
                FROM joysafeter_tasks
                WHERE id = ANY($1)
                ORDER BY id
                "#,
            )
            .bind(&[task_a, task_b][..])
            .fetch_all(&pool)
            .await
            .expect("load renewal state");

            assert!(rows.iter().any(|(id, renewed)| *id == task_a && *renewed));
            assert!(rows.iter().any(|(id, renewed)| *id == task_b && !*renewed));
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn complete_sandbox_task_returns_running_sandbox_to_idle() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("complete-running-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create running completion sandbox");
            transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            transition_sandbox(&pool, sandbox_id, "running")
                .await
                .expect("sandbox running");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set sandbox last task");

            let completed = complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("complete running sandbox");
            assert!(completed);

            let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
                sqlx::query_as(
                    "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load completed sandbox");
            assert_eq!(sandbox.0, "idle");
            assert_eq!(sandbox.1, None);
            assert!(sandbox.2.is_some());
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
    async fn complete_sandbox_task_does_not_resurrect_error_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("complete-error-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create error completion sandbox");
            mark_sandbox_error(&pool, sandbox_id, Some("setup failed"))
                .await
                .expect("mark sandbox error");
            sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
                .bind(sandbox_id)
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("set errored sandbox last task");

            let completed = complete_sandbox_task(&pool, sandbox_id)
                .await
                .expect("complete errored sandbox");
            assert!(!completed);

            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
                "SELECT status, last_task_id, config FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load errored sandbox after completion");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1, None);
            assert_eq!(
                sandbox
                    .2
                    .get("setup_error")
                    .and_then(serde_json::Value::as_str),
                Some("setup failed")
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
    async fn transition_sandbox_rejects_invalid_error_to_idle_resurrection() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("invalid-resurrection-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create sandbox for invalid transition");
            mark_sandbox_error(&pool, sandbox_id, Some("setup failed"))
                .await
                .expect("mark sandbox error");

            let transitioned = transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("attempt invalid transition");
            assert!(!transitioned);

            let sandbox: (String, serde_json::Value) =
                sqlx::query_as("SELECT status, config FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load sandbox after rejected transition");
            assert_eq!(sandbox.0, "error");
            assert_eq!(
                sandbox
                    .1
                    .get("setup_error")
                    .and_then(serde_json::Value::as_str),
                Some("setup failed")
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
    async fn mark_sandbox_error_does_not_clear_active_task_binding() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("active-error-guard-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create active sandbox");
            transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");
            sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
                .bind(task_id)
                .bind(sandbox_id)
                .execute(&pool)
                .await
                .expect("bind active task to sandbox");
            assert!(
                start_sandbox_task(&pool, sandbox_id, task_id)
                    .await
                    .expect("start sandbox task")
            );

            let marked = mark_sandbox_error(&pool, sandbox_id, Some("late setup failure"))
                .await
                .expect("attempt late sandbox error");
            assert!(!marked);

            let sandbox: (String, Option<Uuid>, Option<String>) = sqlx::query_as(
                "SELECT status, last_task_id, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load protected active sandbox");
            assert_eq!(sandbox.0, "running");
            assert_eq!(sandbox.1, Some(task_id));
            assert_eq!(sandbox.2, None);

            let task: (String, Option<Uuid>) =
                sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load protected active task");
            assert_eq!(task.0, "running");
            assert_eq!(task.1, Some(sandbox_id));
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
    async fn atomic_session_status_helper_writes_status_event_and_canonical_seq() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let task_id = Uuid::now_v7();

        let result = async {
            let running_payload = json!({"task_id": task_id.to_string()});
            let running = update_session_status_and_insert_event(
                &pool,
                session_id,
                "running",
                None,
                "session.status_running",
                &running_payload,
            )
            .await
            .expect("running transition succeeds")
            .expect("running transition inserts event");

            assert_eq!(running.1, 1);

            let session_row: (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after running transition");
            assert_eq!(session_row.0, "running");
            assert_eq!(session_row.1, None);

            let running_event: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
                "SELECT id, event_type, payload, seq FROM joysafeter_session_events WHERE session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load running event");
            assert_eq!(running_event.0, running.0);
            assert_eq!(running_event.1, "session.status_running");
            assert_eq!(running_event.2, running_payload);
            assert_eq!(running_event.3, 1);

            let duplicate = update_session_status_and_insert_event(
                &pool,
                session_id,
                "running",
                None,
                "session.status_running",
                &running_payload,
            )
            .await
            .expect("duplicate running transition is accepted as no-op");
            assert_eq!(duplicate, None);

            let count_after_duplicate: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count events after duplicate");
            assert_eq!(count_after_duplicate, 1);

            let stop_reason = json!({"type": "end_turn"});
            let idle_payload = json!({
                "task_id": task_id.to_string(),
                "stop_reason": stop_reason.clone()
            });
            let idle = update_session_status_and_insert_event(
                &pool,
                session_id,
                "idle",
                Some(&stop_reason),
                "session.status_idle",
                &idle_payload,
            )
            .await
            .expect("idle transition succeeds")
            .expect("idle transition inserts event");
            assert_eq!(idle.1, 2);

            let final_session: (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after idle transition");
            assert_eq!(final_session.0, "idle");
            assert_eq!(final_session.1, Some(stop_reason));

            let events: Vec<(String, i64)> = sqlx::query_as(
                r#"
                SELECT event_type, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq ASC
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load ordered status events");
            assert_eq!(
                events,
                vec![
                    ("session.status_running".to_string(), 1),
                    ("session.status_idle".to_string(), 2),
                ]
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn atomic_session_status_helper_rolls_back_status_when_seq_assignment_fails() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;

        let result = async {
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'agent.message', '{}'::jsonb, $3)
                "#,
            )
            .bind(Uuid::now_v7())
            .bind(session_id)
            .bind(i64::MAX)
            .execute(&pool)
            .await
            .expect("insert max seq sentinel");

            let payload = json!({"task_id": Uuid::now_v7().to_string()});
            let err = update_session_status_and_insert_event(
                &pool,
                session_id,
                "running",
                None,
                "session.status_running",
                &payload,
            )
            .await
            .expect_err("seq overflow must fail the transition");

            assert!(
                err.to_string().contains("out of range") || err.to_string().contains("overflow"),
                "unexpected error: {err}"
            );

            let status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after failed transition");
            assert_eq!(status, "idle");

            let status_event_count: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1 AND event_type = 'session.status_running'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count failed status events");
            assert_eq!(status_event_count, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn db_persisted_status_envelope_does_not_reenter_event_bus_db_persister() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let task_id = Uuid::now_v7();

        let result = async {
            let payload = json!({"task_id": task_id.to_string()});
            let (event_id, seq) = update_session_status_and_insert_event(
                &pool,
                session_id,
                "running",
                None,
                "session.status_running",
                &payload,
            )
            .await
            .expect("running transition succeeds")
            .expect("running transition inserts event");

            let mut config = JoySafeterConfig::from_env();
            config.event_stream_enabled = false;
            config.event_batch_max_size = 1;
            config.event_batch_max_delay_ms = 1;
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client =
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

            let envelope = EventEnvelope::new(session_id, "session.status_running", payload)
                .with_task(task_id)
                .status_change(None)
                .with_db_persisted(event_id, seq);
            event_bus.publish(envelope).await;
            event_bus.flush().await;

            let rows: Vec<(Uuid, String, i64)> = sqlx::query_as(
                r#"
                SELECT id, event_type, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq ASC
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load events after publishing db-persisted envelope");

            assert_eq!(
                rows,
                vec![(event_id, "session.status_running".to_string(), 1)]
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_bus_persists_runner_event_with_canonical_db_seq_not_runner_seq() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let mut config = JoySafeterConfig::from_env();
            config.event_stream_enabled = false;
            config.event_batch_max_size = 1;
            config.event_batch_max_delay_ms = 1;
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client =
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

            let payload = json!({"content": "hello from runner"});
            let envelope = EventEnvelope::new(session_id, "agent.message", payload.clone())
                .with_task(task_id)
                .with_runner_seq(777)
                .flush_immediately();
            let event_id = envelope.event_id.expect("new envelope has event id");
            event_bus.publish(envelope).await;
            event_bus.flush().await;

            let row: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
                r#"
                SELECT id, event_type, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load persisted runner event");

            assert_eq!(row.0, event_id);
            assert_eq!(row.1, "agent.message");
            assert_eq!(row.2, payload);
            assert_eq!(row.3, 1, "DB canonical seq must not reuse runner seq");
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_bus_stream_primary_falls_back_to_db_before_flush_immediate_returns() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let mut config = JoySafeterConfig::from_env();
            config.event_stream_enabled = true;
            config.event_stream_fallback_to_db = true;
            config.event_batch_max_size = 10;
            config.event_batch_max_delay_ms = 60_000;
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client =
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

            let payload = json!({"content": "stream fallback"});
            let envelope = EventEnvelope::new(session_id, "agent.message", payload.clone())
                .with_task(task_id)
                .flush_immediately();
            let event_id = envelope.event_id.expect("new envelope has event id");
            event_bus.publish(envelope).await;

            let row: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
                r#"
                SELECT id, event_type, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("fallback DB row should be visible when publish returns");

            assert_eq!(row.0, event_id);
            assert_eq!(row.1, "agent.message");
            assert_eq!(row.2, payload);
            assert_eq!(row.3, 1);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_bus_stream_primary_without_fallback_does_not_direct_write_to_db() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let mut config = JoySafeterConfig::from_env();
            config.event_stream_enabled = true;
            config.event_stream_fallback_to_db = false;
            config.event_batch_max_size = 1;
            config.event_batch_max_delay_ms = 1;
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client =
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

            let envelope = EventEnvelope::new(session_id, "agent.message", json!({"content": "no fallback"}))
                .with_task(task_id)
                .flush_immediately();
            event_bus.publish(envelope).await;
            event_bus.flush().await;

            let count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count events after stream publish failure without fallback");

            assert_eq!(
                count, 0,
                "stream-enabled EventBus must not use the direct DB persister as a second primary path"
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_persister_redelivered_event_id_does_not_consume_next_db_seq() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;

        let result = async {
            let persister = EventPersister::new(
                pool.clone(),
                10,
                60_000,
                None,
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
                "rust-event-persister-test".to_string(),
            );

            let redelivered_id = Uuid::now_v7();
            let next_id = Uuid::now_v7();
            persister
                .push(
                    redelivered_id,
                    session_id,
                    "agent.message",
                    &json!({"content": "first delivery"}),
                    None,
                )
                .await;
            persister.flush().await;

            persister
                .push(
                    redelivered_id,
                    session_id,
                    "agent.message",
                    &json!({"content": "redelivery"}),
                    None,
                )
                .await;
            persister
                .push(
                    next_id,
                    session_id,
                    "agent.message",
                    &json!({"content": "next event"}),
                    None,
                )
                .await;
            persister.flush().await;

            let rows: Vec<(Uuid, serde_json::Value, i64)> = sqlx::query_as(
                r#"
                SELECT id, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq ASC
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load persisted events after duplicate event id");

            assert_eq!(
                rows,
                vec![
                    (redelivered_id, json!({"content": "first delivery"}), 1),
                    (next_id, json!({"content": "next event"}), 2),
                ],
                "a duplicate event id must not consume the next canonical DB seq"
            );
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_persister_skips_session_status_events_even_when_called_directly() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;

        let result = async {
            let persister = EventPersister::new(
                pool.clone(),
                10,
                60_000,
                None,
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
                "rust-event-persister-status-test".to_string(),
            );

            persister
                .push(
                    Uuid::now_v7(),
                    session_id,
                    "session.status_idle",
                    &json!({"task_id": Uuid::now_v7().to_string(), "stop_reason": {"type": "end_turn"}}),
                    None,
                )
                .await;
            let message_id = Uuid::now_v7();
            persister
                .push(
                    message_id,
                    session_id,
                    "agent.message",
                    &json!({"content": "still persists"}),
                    None,
                )
                .await;
            persister.flush().await;

            let rows: Vec<(Uuid, String, serde_json::Value, i64)> = sqlx::query_as(
                r#"
                SELECT id, event_type, payload, seq
                FROM joysafeter_session_events
                WHERE session_id = $1
                ORDER BY seq ASC
                "#,
            )
            .bind(session_id)
            .fetch_all(&pool)
            .await
            .expect("load persisted events after direct persister status skip");

            assert_eq!(
                rows,
                vec![(
                    message_id,
                    "agent.message".to_string(),
                    json!({"content": "still persists"}),
                    1,
                )],
                "generic persister must not persist session.status_* or consume seq"
            );

            let status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session status after direct persister status skip");
            assert_eq!(status, "running", "generic persister must not mutate session status");
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn raw_status_envelope_through_subscriber_uses_canonical_db_seq_not_runner_seq() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let (tx, rx) = tokio::sync::broadcast::channel(8);
            let subscriber = SessionStateSubscriber::new(
                pool.clone(),
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
                "rust-status-test".to_string(),
            );
            let handle = subscriber.spawn(rx);

            let payload = json!({"task_id": task_id.to_string()});
            let envelope =
                EventEnvelope::new(session_id, "session.status_running", payload.clone())
                    .with_task(task_id)
                    .with_runner_seq(777)
                    .status_change(None);
            tx.send(Arc::new(envelope))
                .expect("send raw status envelope to subscriber");

            let mut observed: Option<(String, String, serde_json::Value, i64)> = None;
            for _ in 0..50 {
                observed = sqlx::query_as(
                    r#"
                    SELECT s.status, e.event_type, e.payload, e.seq
                    FROM joysafeter_sessions s
                    JOIN joysafeter_session_events e ON e.session_id = s.id
                    WHERE s.id = $1
                    ORDER BY e.seq ASC
                    LIMIT 1
                    "#,
                )
                .bind(session_id)
                .fetch_optional(&pool)
                .await
                .expect("poll raw status subscriber result");
                if observed.is_some() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }

            handle.abort();

            let observed = observed.expect("subscriber should persist raw status envelope");
            assert_eq!(observed.0, "running");
            assert_eq!(observed.1, "session.status_running");
            assert_eq!(observed.2, payload);
            assert_eq!(observed.3, 1, "DB canonical seq must not reuse runner seq");
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn raw_idle_status_with_active_task_is_skipped_except_requires_action() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let (tx, rx) = tokio::sync::broadcast::channel(8);
            let subscriber = SessionStateSubscriber::new(
                pool.clone(),
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
                "rust-status-active-task-test".to_string(),
            );
            let handle = subscriber.spawn(rx);

            let stale_reason = json!({"type": "end_turn"});
            let stale_payload = json!({
                "task_id": task_id.to_string(),
                "stop_reason": stale_reason.clone()
            });
            let stale_idle =
                EventEnvelope::new(session_id, "session.status_idle", stale_payload.clone())
                    .with_task(task_id)
                    .status_change(Some(stale_reason));
            tx.send(Arc::new(stale_idle))
                .expect("send stale idle status envelope");

            let requires_action_reason = json!({
                "type": "requires_action",
                "event_ids": ["evt_test_requires_action"]
            });
            let requires_action_payload = json!({
                "task_id": task_id.to_string(),
                "stop_reason": requires_action_reason.clone()
            });
            let requires_action_idle = EventEnvelope::new(
                session_id,
                "session.status_idle",
                requires_action_payload.clone(),
            )
            .with_task(task_id)
            .status_change(Some(requires_action_reason.clone()));
            tx.send(Arc::new(requires_action_idle))
                .expect("send requires_action idle status envelope");

            let mut observed: Option<(String, serde_json::Value)> = None;
            for _ in 0..50 {
                observed = sqlx::query_as(
                    r#"
                    SELECT s.status, e.payload
                    FROM joysafeter_sessions s
                    JOIN joysafeter_session_events e ON e.session_id = s.id
                    WHERE s.id = $1
                      AND e.event_type = 'session.status_idle'
                      AND e.payload->'stop_reason'->>'type' = 'requires_action'
                    ORDER BY e.seq ASC
                    LIMIT 1
                    "#,
                )
                .bind(session_id)
                .fetch_optional(&pool)
                .await
                .expect("poll requires_action idle status subscriber result");
                if observed.is_some() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }

            handle.abort();

            let observed = observed.expect("requires_action idle should be persisted");
            assert_eq!(observed.0, "idle");
            assert_eq!(observed.1, requires_action_payload);

            let stale_idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count stale end_turn idle events");
            assert_eq!(stale_idle_events, 0);
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn event_bus_routes_raw_status_to_state_subscriber_not_generic_persister() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let mut config = JoySafeterConfig::from_env();
            config.event_stream_enabled = false;
            config.event_batch_max_size = 1;
            config.event_batch_max_delay_ms = 1;
            let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
            let redis_client =
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
            let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
            let subscriber = SessionStateSubscriber::new(
                pool.clone(),
                redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
                "rust-status-test".to_string(),
            );
            let handle = subscriber.spawn(event_bus.subscribe());

            let payload = json!({"task_id": task_id.to_string()});
            let envelope =
                EventEnvelope::new(session_id, "session.status_running", payload.clone())
                    .with_task(task_id)
                    .with_runner_seq(777)
                    .status_change(None);
            event_bus.publish(envelope).await;
            event_bus.flush().await;

            let mut observed: Option<(String, String, serde_json::Value, i64)> = None;
            for _ in 0..50 {
                observed = sqlx::query_as(
                    r#"
                    SELECT s.status, e.event_type, e.payload, e.seq
                    FROM joysafeter_sessions s
                    JOIN joysafeter_session_events e ON e.session_id = s.id
                    WHERE s.id = $1
                    ORDER BY e.seq ASC
                    LIMIT 1
                    "#,
                )
                .bind(session_id)
                .fetch_optional(&pool)
                .await
                .expect("poll event bus status subscriber result");
                if observed.is_some() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }

            handle.abort();

            let observed = observed.expect("event bus should route raw status to subscriber");
            assert_eq!(observed.0, "running");
            assert_eq!(observed.1, "session.status_running");
            assert_eq!(observed.2, payload);
            assert_eq!(observed.3, 1, "DB canonical seq must not reuse runner seq");
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn stream_publisher_skips_status_events_instead_of_falling_back_to_db() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;

        let result = async {
            let fallback_persister = Arc::new(EventPersister::new(
                pool.clone(),
                1,
                1,
                None,
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
                "rust-status-test".to_string(),
            ));
            let stream_publisher = EventStreamPublisher::new(
                redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
                "joysafeter:test:events",
                100,
                Some(fallback_persister),
                true,
            );
            let (tx, rx) = tokio::sync::broadcast::channel(8);
            let handle = stream_publisher.spawn(rx);

            let payload = json!({"task_id": task_id.to_string()});
            let envelope =
                EventEnvelope::new(session_id, "session.status_running", payload.clone())
                    .with_task(task_id)
                    .with_runner_seq(777)
                    .status_change(None);
            tx.send(Arc::new(envelope))
                .expect("send status envelope to stream publisher");
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            handle.abort();

            let event_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count status events after stream publisher skip");
            assert_eq!(event_count, 0);

            let status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after stream publisher skip");
            assert_eq!(status, "idle");
        }
        .await;

        cleanup(&pool, agent_id, session_id).await;
        result
    }

    #[tokio::test]
    async fn provisioning_progress_update_does_not_resurrect_error_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("progress-error-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({"provisioning": {"stage": "booting"}})),
            )
            .await
            .expect("create provisioning progress sandbox");
            mark_sandbox_error(&pool, sandbox_id, Some("provider setup failed"))
                .await
                .expect("mark sandbox error");

            let updated = update_sandbox_status_and_config(
                &pool,
                sandbox_id,
                "provisioning",
                &json!({"provisioning": {"stage": "late_poll", "progress": 90}}),
            )
            .await
            .expect("attempt progress update after concurrent error");
            assert!(!updated);

            let sandbox: (
                String,
                serde_json::Value,
                Option<chrono::DateTime<chrono::Utc>>,
            ) = sqlx::query_as(
                "SELECT status, config, idle_since FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after late progress update");
            assert_eq!(sandbox.0, "error");
            assert_eq!(
                sandbox
                    .1
                    .get("setup_error")
                    .and_then(|value| value.as_str()),
                Some("provider setup failed")
            );
            assert_eq!(
                sandbox
                    .1
                    .get("provisioning")
                    .and_then(|value| value.get("stage"))
                    .and_then(|value| value.as_str()),
                Some("booting")
            );
            assert!(sandbox.2.is_none());
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
    async fn start_sandbox_task_binds_healthy_sandbox_to_task() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("start-healthy-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create dispatch sandbox");
            transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle");

            let started = start_sandbox_task(&pool, sandbox_id, task_id)
                .await
                .expect("start sandbox task");
            assert!(started);

            let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
                sqlx::query_as(
                    "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load started sandbox");
            assert_eq!(sandbox.0, "running");
            assert_eq!(sandbox.1, Some(task_id));
            assert!(sandbox.2.is_none());
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
    async fn start_sandbox_task_does_not_resurrect_error_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("start-error-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create error dispatch sandbox");
            mark_sandbox_error(&pool, sandbox_id, Some("setup failed before dispatch"))
                .await
                .expect("mark sandbox error");

            let started = start_sandbox_task(&pool, sandbox_id, task_id)
                .await
                .expect("attempt start on error sandbox");
            assert!(!started);

            let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
                "SELECT status, last_task_id, config FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load error sandbox");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1, None);
            assert_eq!(
                sandbox
                    .2
                    .get("setup_error")
                    .and_then(|value| value.as_str()),
                Some("setup failed before dispatch")
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
    async fn mark_sandbox_stopped_if_active_stops_running_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let task_id = create_task(&pool, agent_id, session_id, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("stop-running-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create running stop sandbox");
            transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("sandbox idle before start");
            assert!(
                start_sandbox_task(&pool, sandbox_id, task_id)
                    .await
                    .expect("start sandbox task")
            );

            let stopped = mark_sandbox_stopped_if_active(&pool, sandbox_id)
                .await
                .expect("mark active sandbox stopped");
            assert!(stopped);

            let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
                sqlx::query_as(
                    "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load stopped sandbox");
            assert_eq!(sandbox.0, "stopped");
            assert_eq!(sandbox.1, Some(task_id));
            assert!(sandbox.2.is_none());
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
    async fn mark_sandbox_stopped_if_active_does_not_overwrite_error_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("stop-error-preserve-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                Some(session_id),
                None,
                None,
                Some(&json!({})),
            )
            .await
            .expect("create error stop sandbox");
            mark_sandbox_error(&pool, sandbox_id, Some("must stay error"))
                .await
                .expect("mark sandbox error");

            let stopped = mark_sandbox_stopped_if_active(&pool, sandbox_id)
                .await
                .expect("attempt mark error sandbox stopped");
            assert!(!stopped);

            let sandbox: (String, Option<String>) = sqlx::query_as(
                "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load preserved error sandbox");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1.as_deref(), Some("must stay error"));
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
    async fn mark_pool_sandbox_ready_finalizes_creating_pool_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("pool-ready-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({"provisioning": {"stage": "pool_warm"}})),
            )
            .await
            .expect("create warm pool sandbox");

            let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize warm pool sandbox");
            assert!(ready);

            let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
                sqlx::query_as(
                    "SELECT status, chat_session_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load finalized pool sandbox");
            assert_eq!(sandbox.0, "pooled");
            assert_eq!(sandbox.1, None);
            assert!(sandbox.2.is_none());
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn mark_pool_sandbox_ready_accepts_runner_ready_idle_race() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("pool-ready-idle-race-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({"provisioning": {"stage": "pool_warm"}})),
            )
            .await
            .expect("create warm pool sandbox");
            transition_sandbox(&pool, sandbox_id, "idle")
                .await
                .expect("simulate fast runner ready before pool finalization");

            let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("finalize warm pool after runner-ready race");
            assert!(ready);

            let status: String =
                sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
                    .bind(sandbox_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load finalized pool sandbox");
            assert_eq!(status, "pooled");
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        result
    }

    #[tokio::test]
    async fn mark_pool_sandbox_ready_does_not_resurrect_error_sandbox() {
        let Some(pool) = test_pool().await else {
            return;
        };
        let sandbox_id = Uuid::now_v7();

        let result = async {
            create_sandbox(
                &pool,
                sandbox_id,
                &format!("pool-ready-error-{sandbox_id}"),
                "test",
                "joysafeter/test:latest",
                None,
                None,
                None,
                Some(&json!({"provisioning": {"stage": "pool_warm"}})),
            )
            .await
            .expect("create warm pool sandbox");
            mark_sandbox_error(&pool, sandbox_id, Some("pool setup failed"))
                .await
                .expect("mark warm pool sandbox error");

            let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
                .await
                .expect("attempt late pool finalization after error");
            assert!(!ready);

            let sandbox: (String, Option<String>) = sqlx::query_as(
                "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load preserved pool error sandbox");
            assert_eq!(sandbox.0, "error");
            assert_eq!(sandbox.1.as_deref(), Some("pool setup failed"));
        }
        .await;

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;
        result
    }
}
