use crate::db::models::JoySafeterSandbox;
use crate::ids::{SandboxId, SessionId, TaskId};
use serde_json::Value;
use sqlx::PgPool;

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct CommandDestroySandboxClaim {
    pub external_id: Option<String>,
    pub previous_status: String,
}

#[derive(Debug, Clone)]
pub struct UpsertNetworkPolicy<'a> {
    pub sandbox_id: SandboxId,
    pub session_id: Option<SessionId>,
    pub task_id: Option<TaskId>,
    pub policy_hash: &'a str,
    pub desired_policy_json: &'a Value,
    pub rendered_summary_json: &'a Value,
}

// ---------------------------------------------------------------------------
// Sandbox queries
// ---------------------------------------------------------------------------

/// Get a sandbox by ID.
pub async fn get_sandbox(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<Option<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>("SELECT * FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .fetch_optional(pool)
        .await
}

/// Find the current non-destroyed sandbox for a session (for reuse/recovery).
pub async fn find_sandbox_for_session(
    pool: &PgPool,
    session_id: SessionId,
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

/// List live limited-networking sandboxes for a project. Used by API-triggered
/// credential/environment refreshes to push updated Envoy policies immediately.
pub async fn list_live_limited_sandboxes_for_project(
    pool: &PgPool,
    project_id: Option<&str>,
) -> Result<Vec<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE status IN ('idle', 'running', 'creating', 'provisioning')
          AND destroyed_at IS NULL
          AND ($1::text IS NULL OR project_id = $1)
          AND config #>> '{fingerprint,networking,type}' = 'limited'
        ORDER BY created_at
        "#,
    )
    .bind(project_id)
    .fetch_all(pool)
    .await
}

/// List live limited-networking sandboxes whose Envoy egress policy is NOT in
/// the `ready` state — a push failed, NACK'd, or was left degraded (e.g. a
/// transient xDS/Docker hiccup during provisioning). The networking-reconcile
/// loop re-pushes these so a sandbox self-heals instead of running with no
/// egress until the next task. Ordered oldest-updated-first so the
/// longest-degraded sandbox is retried first.
pub async fn list_degraded_limited_sandboxes(
    pool: &PgPool,
    limit: i64,
) -> Result<Vec<JoySafeterSandbox>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSandbox>(
        r#"
        SELECT * FROM joysafeter_sandboxes
        WHERE status IN ('idle', 'running', 'provisioning')
          AND destroyed_at IS NULL
          AND external_id IS NOT NULL
          AND config #>> '{fingerprint,networking,type}' = 'limited'
          AND networking_status IN ('pending', 'nacked', 'failed')
        ORDER BY updated_at
        LIMIT $1
        "#,
    )
    .bind(limit)
    .fetch_all(pool)
    .await
}

/// Create a new sandbox record.
pub async fn create_sandbox(
    pool: &PgPool,
    id: SandboxId,
    external_id: &str,
    provider: &str,
    image: &str,
    session_id: Option<SessionId>,
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

pub async fn mark_sandbox_error(
    pool: &PgPool,
    sandbox_id: SandboxId,
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

#[cfg(test)]
mod transition_validation_tests {
    use super::is_valid_sandbox_transition;

    #[test]
    fn accepts_idempotent_and_documented_transitions() {
        assert!(is_valid_sandbox_transition("idle", "idle"));
        assert!(is_valid_sandbox_transition("creating", "provisioning"));
        assert!(is_valid_sandbox_transition("provisioning", "idle"));
        assert!(is_valid_sandbox_transition("idle", "running"));
        assert!(is_valid_sandbox_transition("running", "idle"));
        assert!(is_valid_sandbox_transition("stopped", "destroyed"));
        assert!(is_valid_sandbox_transition("error", "destroyed"));
    }

    #[test]
    fn rejects_resurrection_and_unknown_transitions() {
        assert!(!is_valid_sandbox_transition("error", "idle"));
        assert!(!is_valid_sandbox_transition("destroyed", "idle"));
        assert!(!is_valid_sandbox_transition("pooled", "idle"));
        assert!(!is_valid_sandbox_transition("unknown", "running"));
    }
}

/// Mark a sandbox task as complete and return the sandbox to idle.
///
/// This helper is on critical execution/recovery paths. It must release the
/// task association without resurrecting unhealthy sandboxes: `error`,
/// `stopped`, `stopping`, and `destroyed` are not allowed to become `idle`.
pub async fn complete_sandbox_task(
    pool: &PgPool,
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
    task_id: TaskId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
pub async fn mark_pool_sandbox_ready(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<bool, sqlx::Error> {
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
    sandbox_id: SandboxId,
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

/// Mark the sandbox networking control-plane status.
pub async fn update_sandbox_networking_status(
    pool: &PgPool,
    sandbox_id: SandboxId,
    status: &str,
    policy_hash: Option<&str>,
    policy_version: Option<i64>,
    last_error: Option<&str>,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = $2,
            networking_policy_hash = COALESCE($3, networking_policy_hash),
            networking_policy_version = COALESCE($4, networking_policy_version),
            networking_last_error = $5,
            networking_ready_at = CASE WHEN $2 = 'ready' THEN NOW() ELSE networking_ready_at END,
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .bind(status)
    .bind(policy_hash)
    .bind(policy_version)
    .bind(last_error)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Prepare a sandbox network-policy push on the hot path.
///
/// The sandbox row is the authoritative latest-state record. We only write when
/// the effective policy hash changed or the previous status was not ready;
/// repeated healthy refreshes avoid database writes entirely.
pub async fn prepare_sandbox_network_policy_push(
    pool: &PgPool,
    sandbox_id: SandboxId,
    policy_hash: &str,
) -> Result<Option<i64>, sqlx::Error> {
    let row = sqlx::query_as::<_, (i64,)>(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'pending',
            networking_policy_hash = $2,
            networking_policy_version = CASE
                WHEN networking_policy_hash IS DISTINCT FROM $2
                    THEN GREATEST(networking_policy_version, 0) + 1
                ELSE networking_policy_version
            END,
            networking_last_error = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
          AND (
              networking_policy_hash IS DISTINCT FROM $2
              OR networking_status <> 'ready'
              OR networking_last_error IS NOT NULL
          )
        RETURNING networking_policy_version
        "#,
    )
    .bind(sandbox_id)
    .bind(policy_hash)
    .fetch_optional(pool)
    .await?;

    Ok(row.map(|(policy_version,)| policy_version))
}

/// Mark an accepted network-policy push without touching audit history.
pub async fn mark_sandbox_network_policy_acked(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'ready',
            networking_last_error = NULL,
            networking_ready_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
          AND (networking_status <> 'ready' OR networking_last_error IS NOT NULL)
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Persist a failed policy application as sparse audit history.
///
/// Successful ACKs remain on `joysafeter_sandboxes`; failures are durable so the
/// platform diagnostics page can explain why a sandbox cannot be scheduled.
pub async fn record_network_policy_failure(
    pool: &PgPool,
    sandbox_id: SandboxId,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        WITH sandbox AS (
            SELECT id,
                   chat_session_id,
                   NULLIF(networking_policy_hash, '') AS policy_hash,
                   GREATEST(networking_policy_version, 1) AS policy_version,
                   COALESCE(config->'fingerprint', '{}'::jsonb) AS fingerprint
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND destroyed_at IS NULL
        ), status_update AS (
            UPDATE joysafeter_sandboxes s
            SET networking_status = 'nacked',
                networking_last_error = $2,
                updated_at = NOW()
            FROM sandbox
            WHERE s.id = sandbox.id
            RETURNING s.id
        )
        INSERT INTO joysafeter_sandbox_network_policies (
            id, sandbox_id, session_id, task_id, policy_hash, policy_version,
            desired_policy_json, rendered_summary_json, status,
            last_error, last_nack_reason, created_at, updated_at
        )
        SELECT gen_random_uuid(),
               sandbox.id,
               sandbox.chat_session_id,
               NULL,
               COALESCE(sandbox.policy_hash, 'unknown'),
               sandbox.policy_version,
               jsonb_build_object('fingerprint', sandbox.fingerprint, 'recorded_on', 'failure'),
               '{}'::jsonb,
               'nacked',
               $2,
               $2,
               NOW(),
               NOW()
        FROM sandbox
        ON CONFLICT (sandbox_id, policy_version) DO UPDATE
        SET status = 'nacked',
            last_error = EXCLUDED.last_error,
            last_nack_reason = EXCLUDED.last_nack_reason,
            updated_at = NOW()
        "#,
    )
    .bind(sandbox_id)
    .bind(reason)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Persist a failed policy application with the redacted desired/rendered policy.
pub async fn record_network_policy_failure_detail(
    pool: &PgPool,
    policy: UpsertNetworkPolicy<'_>,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        WITH sandbox AS (
            SELECT id,
                   chat_session_id,
                   GREATEST(networking_policy_version, 1) AS policy_version
            FROM joysafeter_sandboxes
            WHERE id = $1
              AND destroyed_at IS NULL
        ), status_update AS (
            UPDATE joysafeter_sandboxes s
            SET networking_status = 'nacked',
                networking_policy_hash = $2,
                networking_last_error = $6,
                updated_at = NOW()
            FROM sandbox
            WHERE s.id = sandbox.id
            RETURNING s.id
        )
        INSERT INTO joysafeter_sandbox_network_policies (
            id, sandbox_id, session_id, task_id, policy_hash, policy_version,
            desired_policy_json, rendered_summary_json, status,
            last_error, last_nack_reason, created_at, updated_at
        )
        SELECT gen_random_uuid(),
               sandbox.id,
               COALESCE($3, sandbox.chat_session_id),
               $4,
               $2,
               sandbox.policy_version,
               $5,
               $7,
               'nacked',
               $6,
               $6,
               NOW(),
               NOW()
        FROM sandbox
        ON CONFLICT (sandbox_id, policy_version) DO UPDATE
        SET session_id = COALESCE(EXCLUDED.session_id, joysafeter_sandbox_network_policies.session_id),
            task_id = COALESCE(EXCLUDED.task_id, joysafeter_sandbox_network_policies.task_id),
            policy_hash = EXCLUDED.policy_hash,
            desired_policy_json = EXCLUDED.desired_policy_json,
            rendered_summary_json = EXCLUDED.rendered_summary_json,
            status = 'nacked',
            last_error = EXCLUDED.last_error,
            last_nack_reason = EXCLUDED.last_nack_reason,
            updated_at = NOW()
        "#,
    )
    .bind(policy.sandbox_id)
    .bind(policy.policy_hash)
    .bind(policy.session_id)
    .bind(policy.task_id)
    .bind(policy.desired_policy_json)
    .bind(reason)
    .bind(policy.rendered_summary_json)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Insert a new desired network-policy revision for a sandbox.
pub async fn create_network_policy_revision(
    pool: &PgPool,
    policy: UpsertNetworkPolicy<'_>,
) -> Result<i64, sqlx::Error> {
    let row: (i64,) = sqlx::query_as(
        r#"
        WITH next_version AS (
            SELECT COALESCE(MAX(policy_version), 0) + 1 AS version
            FROM joysafeter_sandbox_network_policies
            WHERE sandbox_id = $1
        ), inserted AS (
            INSERT INTO joysafeter_sandbox_network_policies (
                id, sandbox_id, session_id, task_id, policy_hash, policy_version,
                desired_policy_json, rendered_summary_json, status, created_at, updated_at
            )
            SELECT gen_random_uuid(), $1, $2, $3, $4, version, $5, $6, 'pending', NOW(), NOW()
            FROM next_version
            RETURNING policy_version
        )
        SELECT policy_version FROM inserted
        "#,
    )
    .bind(policy.sandbox_id)
    .bind(policy.session_id)
    .bind(policy.task_id)
    .bind(policy.policy_hash)
    .bind(policy.desired_policy_json)
    .bind(policy.rendered_summary_json)
    .fetch_one(pool)
    .await?;

    Ok(row.0)
}

/// Mark a sandbox policy revision as pushed to Envoy.
pub async fn mark_network_policy_pushed(
    pool: &PgPool,
    sandbox_id: SandboxId,
    policy_version: i64,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandbox_network_policies
        SET status = 'pushed', pushed_at = NOW(), updated_at = NOW(), last_error = NULL
        WHERE sandbox_id = $1 AND policy_version = $2
        "#,
    )
    .bind(sandbox_id)
    .bind(policy_version)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark the latest policy for a sandbox as ACKed by Envoy.
pub async fn mark_latest_network_policy_acked(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        WITH latest AS (
            SELECT id, policy_hash, policy_version
            FROM joysafeter_sandbox_network_policies
            WHERE sandbox_id = $1
            ORDER BY policy_version DESC
            LIMIT 1
        ), policy_update AS (
            UPDATE joysafeter_sandbox_network_policies p
            SET status = 'acked', acked_at = NOW(), updated_at = NOW(), last_error = NULL, last_nack_reason = NULL
            FROM latest
            WHERE p.id = latest.id
            RETURNING latest.policy_hash, latest.policy_version
        )
        UPDATE joysafeter_sandboxes s
        SET networking_status = 'ready',
            networking_policy_hash = policy_update.policy_hash,
            networking_policy_version = policy_update.policy_version,
            networking_last_error = NULL,
            networking_ready_at = NOW(),
            updated_at = NOW()
        FROM policy_update
        WHERE s.id = $1
          AND s.destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark the latest policy for a sandbox as NACKed/failed.
pub async fn mark_latest_network_policy_nacked(
    pool: &PgPool,
    sandbox_id: SandboxId,
    reason: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        WITH latest AS (
            SELECT id
            FROM joysafeter_sandbox_network_policies
            WHERE sandbox_id = $1
            ORDER BY policy_version DESC
            LIMIT 1
        ), policy_update AS (
            UPDATE joysafeter_sandbox_network_policies p
            SET status = 'nacked', last_error = $2, last_nack_reason = $2, updated_at = NOW()
            FROM latest
            WHERE p.id = latest.id
            RETURNING p.sandbox_id
        )
        UPDATE joysafeter_sandboxes s
        SET networking_status = 'nacked',
            networking_last_error = $2,
            updated_at = NOW()
        FROM policy_update
        WHERE s.id = policy_update.sandbox_id
          AND s.destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .bind(reason)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Merge non-secret sandbox config metadata while preserving lifecycle fields.
pub async fn merge_sandbox_config(
    pool: &PgPool,
    sandbox_id: SandboxId,
    config: &serde_json::Value,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET config = COALESCE(config, '{}'::jsonb) || $2::jsonb,
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .bind(config)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() > 0)
}

/// Mark sandbox as destroyed.
pub async fn destroy_sandbox(pool: &PgPool, sandbox_id: SandboxId) -> Result<(), sqlx::Error> {
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
    sandbox_id: SandboxId,
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
/// the cleanup claim/external id.
///
/// Passive sweeps and command-driven provider deletion must not convert a
/// A graceful stop path can race after a passive cleanup claim and move the row
/// from `stopping` to `stopped` after the provider runtime has already been
/// destroyed. Accept that narrow cleanup-owned transition too; otherwise the
/// stopped row keeps occupying `idx_csb_active_session_unique` and blocks
/// rescheduling the session forever.
pub async fn destroy_sandbox_if_status_and_external_id(
    pool: &PgPool,
    sandbox_id: SandboxId,
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
          AND (status = $2 OR ($2 = 'stopping' AND status = 'stopped'))
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

/// Mark a passively recovered sandbox as destroyed after task repair.
///
/// Missing-runtime/bridge-health cleanup can legitimately move a `running`
/// sandbox to `idle` while retrying/failing its tasks. This helper accepts that
/// cleanup-owned `idle` release, but still rejects rows whose external id changed
/// or that have any active task bound to the sandbox.
pub async fn destroy_sandbox_after_passive_recovery(
    pool: &PgPool,
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
    expected_status: &str,
    new_status: &str,
) -> Result<bool, sqlx::Error> {
    if !is_valid_sandbox_transition(expected_status, new_status) {
        tracing::warn!(
            sandbox_id = %sandbox_id,
            from = %expected_status,
            to = %new_status,
            "Rejected invalid sandbox CAS transition"
        );
        return Ok(false);
    }

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
    sandbox_id: SandboxId,
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
    sandbox_id: SandboxId,
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
pub async fn touch_sandbox(pool: &PgPool, sandbox_id: SandboxId) -> Result<(), sqlx::Error> {
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
pub async fn mark_bridge_disconnected(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<(), sqlx::Error> {
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
pub async fn mark_bridge_connected(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<(), sqlx::Error> {
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
    session_id: SessionId,
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
