use sqlx::PgPool;

use crate::db::models::JoySafeterSession;
use crate::ids::{AgentId, EnvironmentId, EventId, MemoryStoreId, ProjectId, SandboxId, SessionId};

// ---------------------------------------------------------------------------
// Structs
// ---------------------------------------------------------------------------

/// A session's memory store mount info.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct SessionMemoryStore {
    pub store_id: MemoryStoreId,
    pub store_name: String,
    pub mount_name: String,
    pub access: String,
    pub instructions: Option<String>,
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct MemoryFileRow {
    pub path: String,
    pub content: Option<String>,
}

// ---------------------------------------------------------------------------
// Session queries
// ---------------------------------------------------------------------------

/// Get a session by ID.
pub async fn get_session(
    pool: &PgPool,
    session_id: SessionId,
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
    session_id: SessionId,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<Option<(EventId, i64)>, sqlx::Error> {
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
    session_id: SessionId,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<Option<(EventId, i64)>, sqlx::Error> {
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

/// Build the atomic session status UPDATE. The trailing predicate makes the
/// write idempotent: it is a no-op unless the status actually changes, or the
/// stop_reason is being (re)written for a terminal/idle transition. `allowed_from`
/// and `active_task_guard` are trusted, caller-computed SQL fragments.
pub(crate) fn build_session_status_update_sql(
    allowed_from: &str,
    active_task_guard: &str,
) -> String {
    format!(
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
          AND (
              status <> $2
              OR (
                  ($3::jsonb IS NOT NULL OR $2 IN ('idle', 'terminated'))
                  AND COALESCE(stop_reason, '{{}}'::jsonb) <> COALESCE($3::jsonb, '{{}}'::jsonb)
              )
          )
        "#,
    )
}

async fn update_session_status_and_insert_event_inner(
    pool: &PgPool,
    session_id: SessionId,
    new_status: &str,
    stop_reason: Option<&serde_json::Value>,
    event_type: &str,
    payload: &serde_json::Value,
    require_no_active_tasks: bool,
) -> Result<Option<(EventId, i64)>, sqlx::Error> {
    let mut tx = pool.begin().await?;

    let lock_key = i64::from_be_bytes(session_id.as_uuid().as_bytes()[8..16].try_into().unwrap());
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

    let sql = build_session_status_update_sql(allowed_from, active_task_guard);
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

    let event_id = EventId::from_uuid(uuid::Uuid::now_v7());
    let inserted = sqlx::query_as::<_, (EventId, i64)>(
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
    session_id: SessionId,
    sandbox_id: SandboxId,
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
    session_id: SessionId,
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

/// Create a new session record.
pub async fn create_session(
    pool: &PgPool,
    id: SessionId,
    agent_id: Option<AgentId>,
    project_id: Option<ProjectId>,
    agent_snapshot: Option<&serde_json::Value>,
    environment_id: Option<EnvironmentId>,
) -> Result<JoySafeterSession, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterSession>(
        r#"
        INSERT INTO joysafeter_sessions
            (id, agent_id, project_id, status, agent_snapshot, environment_id, created_at, updated_at)
        VALUES ($1, $2, $3, 'idle', $4, $5, NOW(), NOW())
        RETURNING *
        "#,
    )
    .bind(id)
    .bind(agent_id)
    .bind(project_id)
    .bind(agent_snapshot)
    .bind(environment_id)
    .fetch_one(pool)
    .await
}

/// Update session with sandbox info (harness_session_id, work_dir).
pub async fn update_session_sandbox_info(
    pool: &PgPool,
    session_id: SessionId,
    sandbox_id: SandboxId,
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

/// Query session memory stores for a session.
pub async fn list_session_memory_stores(
    pool: &PgPool,
    session_id: SessionId,
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

/// Load memory files for a store.
pub async fn load_memory_files(
    pool: &PgPool,
    store_id: MemoryStoreId,
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
