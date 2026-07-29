use sqlx::PgPool;
use uuid::Uuid;

use crate::db::models::JoySafeterSandbox;

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CommandDestroySandboxClaim {
    pub external_id: Option<String>,
    pub previous_status: String,
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
