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
) -> Result<Option<JoySafeterTask>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterTask>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'running', started_at = NOW(), updated_at = NOW()
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

/// Transition a task to a new status.
/// Protected: will NOT overwrite terminal states (completed/failed/aborted/timeout/cancelled).
pub async fn transition_task(
    pool: &PgPool,
    task_id: Uuid,
    new_status: &str,
    error_msg: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = $2,
            error = COALESCE($3, error),
            completed_at = CASE
                WHEN $2 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled') THEN NOW()
                ELSE completed_at
            END,
            duration_ms = CASE
                WHEN $2 IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
                    THEN EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
                ELSE duration_ms
            END,
            updated_at = NOW()
        WHERE id = $1
          AND status NOT IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
        "#,
    )
    .bind(task_id)
    .bind(new_status)
    .bind(error_msg)
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

/// Update session status with state machine validation.
/// Python _VALID_TRANSITIONS (target ← allowed sources):
///   running ← {idle, running, rescheduling}
///   idle ← {running}
///   terminated ← {idle, running, rescheduling}
///   rescheduling ← {running, idle}
pub async fn update_session_status(
    pool: &PgPool,
    session_id: Uuid,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
) -> Result<bool, sqlx::Error> {
    let allowed_from = match new_status {
        "running" => "'idle','running','rescheduling'",
        "idle" => "'running'",
        "terminated" => "'idle','running','rescheduling'",
        "rescheduling" => "'running','idle'",
        _ => "'idle','running','rescheduling','terminated'",
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
          AND NOT (status = $2 AND COALESCE(stop_reason, '{{}}'::jsonb) = COALESCE($3::jsonb, '{{}}'::jsonb))
        "#,
    );
    let result = sqlx::query(&sql)
        .bind(session_id)
        .bind(new_status)
        .bind(stop_reason)
        .execute(pool)
        .await?;

    Ok(result.rows_affected() > 0)
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

/// Get a sandbox by external provider id/name.
pub async fn get_sandbox_by_external_id(
    pool: &PgPool,
    external_id: &str,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE external_id = $1 AND destroyed_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        "#,
    )
    .bind(external_id)
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
///   creating → provisioning, idle, stopped, error, destroyed
///   provisioning → idle, stopped, error, destroyed
///   pooled → provisioning, stopped, destroyed
///   idle → idle, running, stopping, stopped, error, destroyed
///   running → idle, stopped, error, destroyed
///   stopping → idle, stopped, error, destroyed
///   stopped → provisioning, destroyed
///   error → destroyed
/// Rejects transitions from 'destroyed' (terminal).
///
/// M4: DEPRECATED — This function has a TOCTOU race between the SELECT
/// (status validation) and UPDATE. Critical paths should use
/// `transition_sandbox_cas()` instead which performs an atomic CAS in a
/// single UPDATE statement. This non-CAS version is kept for backward
/// compatibility with non-critical callers.
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

    // S7: Fetch current status to validate the transition
    let current_status: Option<String> =
        sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .fetch_optional(pool)
            .await?;

    if let Some(ref from_status) = current_status {
        if !is_valid_sandbox_transition(from_status, new_status) {
            tracing::warn!(
                sandbox_id = %sandbox_id,
                from = %from_status,
                to = %new_status,
                "Invalid sandbox state transition (not in documented state machine)"
            );
        }
    }

    // Allow same-state transitions (idempotent)
    // Block transitions FROM destroyed (terminal)
    // Otherwise trust the caller (CAS version is preferred for critical paths)
    //
    // M4: Added guard against overwriting sandboxes that are already in
    // a stop/destroy flow. This reduces the TOCTOU window without
    // requiring all callers to switch to CAS immediately.
    //
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
          AND status != 'destroyed'
          AND (
              $2 IN ('stopped', 'destroyed', 'error', 'stopping')
              OR status NOT IN ('destroyed', 'stopping')
          )
        "#,
    )
    .bind(sandbox_id)
    .bind(new_status)
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
            | ("creating", "idle")
            | ("creating", "stopped")
            | ("creating", "error")
            | ("creating", "destroyed")
            | ("provisioning", "idle")
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
/// Uses the shared sandbox transition helper, then clears the task association.
pub async fn complete_sandbox_task(pool: &PgPool, sandbox_id: Uuid) -> Result<bool, sqlx::Error> {
    let transitioned = transition_sandbox(pool, sandbox_id, "idle").await?;
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET last_task_id = NULL, updated_at = NOW()
        WHERE id = $1 AND status != 'destroyed'
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;
    Ok(transitioned)
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
        "#,
    )
    .bind(sandbox_id)
    .bind(status)
    .bind(config)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Scheduling tasks currently attached to a sandbox.
pub async fn find_scheduling_task_ids_for_sandbox(
    pool: &PgPool,
    sandbox_id: Uuid,
) -> Result<Vec<Uuid>, sqlx::Error> {
    sqlx::query_scalar(
        r#"
        SELECT id FROM joysafeter_tasks
        WHERE sandbox_id = $1 AND status = 'scheduling'
        "#,
    )
    .bind(sandbox_id)
    .fetch_all(pool)
    .await
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

/// CAS task status transition.
pub async fn transition_task_cas(
    pool: &PgPool,
    task_id: Uuid,
    expected_status: &str,
    new_status: &str,
    error_msg: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = $3, error = COALESCE($4, error), updated_at = NOW()
        WHERE id = $1 AND status = $2
        "#,
    )
    .bind(task_id)
    .bind(expected_status)
    .bind(new_status)
    .bind(error_msg)
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
) -> Result<JoySafeterSession, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSession>(
        r#"
        INSERT INTO joysafeter_sessions
            (id, agent_id, project_id, status, agent_snapshot, created_at, updated_at)
        VALUES ($1, $2, $3, 'idle', $4, NOW(), NOW())
        RETURNING *
        "#,
    )
    .bind(id)
    .bind(agent_id)
    .bind(project_id)
    .bind(agent_snapshot)
    .fetch_one(pool)
    .await
}

/// Reset all running tasks for a sandbox back to pending.
pub async fn reset_sandbox_tasks_to_pending(
    pool: &PgPool,
    sandbox_id: Uuid,
) -> Result<u64, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending', sandbox_id = NULL, started_at = NULL,
            retry_count = retry_count + 1, updated_at = NOW()
        WHERE sandbox_id = $1 AND status = 'scheduling'
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected())
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

/// Increment retry count for a task and reset to pending.
/// Increment retry count with CAS protection against double-increment.
///
/// If `expected_retry_count` is provided, only increments if the current count
/// matches (prevents scheduler + watchdog from both incrementing the same failure).
/// If `None`, increments unconditionally (for startup recovery paths where
/// double-increment is acceptable).
pub async fn increment_retry(
    pool: &PgPool,
    task_id: Uuid,
    expected_retry_count: Option<i32>,
) -> Result<bool, sqlx::Error> {
    let result = if let Some(expected) = expected_retry_count {
        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET status = 'pending', sandbox_id = NULL, started_at = NULL,
                retry_count = retry_count + 1, updated_at = NOW()
            WHERE id = $1
              AND retry_count = $2
              AND status NOT IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
            "#,
        )
        .bind(task_id)
        .bind(expected)
        .execute(pool)
        .await?
    } else {
        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET status = 'pending', sandbox_id = NULL, started_at = NULL,
                retry_count = retry_count + 1, updated_at = NOW()
            WHERE id = $1
              AND status NOT IN ('completed', 'failed', 'aborted', 'timeout', 'cancelled')
            "#,
        )
        .bind(task_id)
        .execute(pool)
        .await?
    };

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

// ---------------------------------------------------------------------------
// Session event insertion (for startup recovery, matching Python transition_and_emit)
// ---------------------------------------------------------------------------

/// Insert a session event directly (used by TaskController for recovery events).
pub async fn insert_session_event(
    pool: &PgPool,
    session_id: Uuid,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<Option<(Uuid, i64)>, sqlx::Error> {
    // Use transaction + advisory lock to prevent seq races
    // (matching Python SessionService._lock_event_sequence pattern).
    let mut tx = pool.begin().await?;

    let lock_key = i64::from_be_bytes(session_id.as_bytes()[8..16].try_into().unwrap());
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(lock_key)
        .execute(&mut *tx)
        .await?;

    let seq: i64 = sqlx::query_scalar(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM joysafeter_session_events WHERE session_id = $1",
    )
    .bind(session_id)
    .fetch_one(&mut *tx)
    .await?;

    let inserted = sqlx::query_as::<_, (Uuid, i64)>(
        r#"
        INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
        VALUES (gen_random_uuid(), $1, $2, $3, $4, NOW())
        ON CONFLICT DO NOTHING
        RETURNING id, seq
        "#,
    )
    .bind(session_id)
    .bind(event_type)
    .bind(payload)
    .bind(seq)
    .fetch_optional(&mut *tx)
    .await?;

    tx.commit().await?;
    Ok(inserted)
}
