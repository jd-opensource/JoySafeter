use serde_json::json;
use sqlx::PgPool;

use crate::ids::SandboxId;

use super::task::{persist_failed_task_sessions_in_tx, persist_reset_task_sessions_in_tx};
use super::task::{FailedSandboxTask, ResetSandboxTask};

#[derive(Debug, Clone)]
pub struct RunnerFailureRecovery {
    pub reset_tasks: Vec<ResetSandboxTask>,
    pub failed_tasks: Vec<FailedSandboxTask>,
}

pub async fn quarantine_and_recover_runner_failure(
    pool: &PgPool,
    sandbox_id: SandboxId,
    error_code: &str,
    error_message: &str,
) -> Result<Option<RunnerFailureRecovery>, sqlx::Error> {
    let mut transaction = pool.begin().await?;
    let quarantined = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = CASE
                WHEN status IN ('stopping', 'stopped') THEN status
                ELSE 'error'
            END,
            runner_auth_state = 'revoked',
            runner_token_digest = NULL,
            runner_auth_expires_at = NULL,
            config = COALESCE(config, '{}'::jsonb)
                || jsonb_build_object(
                    'setup_error', $3::text,
                    'runtime_failure', jsonb_build_object(
                        'code', $2::text,
                        'message', $3::text
                    )
                ),
            last_task_id = NULL,
            last_used_at = NOW(),
            updated_at = NOW(),
            idle_since = NULL
        WHERE id = $1
          AND status IN (
              'creating', 'provisioning', 'pooled', 'idle', 'running',
              'stopping', 'stopped'
          )
          AND runner_auth_state IN ('admission', 'active')
          AND destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .bind(error_code)
    .bind(error_message)
    .execute(&mut *transaction)
    .await?;

    if quarantined.rows_affected() != 1 {
        transaction.rollback().await?;
        return Ok(None);
    }

    let failed_rows = sqlx::query_as::<_, (crate::ids::TaskId, Option<crate::ids::SessionId>)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'failed',
            error = $2,
            last_schedule_error_type = $3,
            last_schedule_error = $2,
            completed_at = NOW(),
            duration_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000,
            updated_at = NOW()
        WHERE sandbox_id = $1
          AND status = 'scheduling'
          AND retry_count >= max_retries
        RETURNING id, chat_session_id
        "#,
    )
    .bind(sandbox_id)
    .bind(error_message)
    .bind(error_code)
    .fetch_all(&mut *transaction)
    .await?;
    let mut failed_tasks = failed_rows
        .into_iter()
        .map(|(id, session_id)| FailedSandboxTask {
            id,
            session_id,
            session_event: None,
        })
        .collect::<Vec<_>>();

    let reset_rows = sqlx::query_as::<_, (crate::ids::TaskId, Option<crate::ids::SessionId>, i32)>(
        r#"
        UPDATE joysafeter_tasks
        SET status = 'pending',
            sandbox_id = NULL,
            started_at = NULL,
            scheduling_started_at = NULL,
            retry_count = retry_count + 1,
            last_schedule_error_type = $2,
            last_schedule_error = $3,
            updated_at = NOW()
        WHERE sandbox_id = $1
          AND status = 'scheduling'
          AND retry_count < max_retries
        RETURNING id, chat_session_id, retry_count - 1 AS previous_retry_count
        "#,
    )
    .bind(sandbox_id)
    .bind(error_code)
    .bind(error_message)
    .fetch_all(&mut *transaction)
    .await?;
    let mut reset_tasks = reset_rows
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
        &mut reset_tasks,
        &json!({
            "type": "sandbox_failed",
            "code": error_code,
            "message": error_message,
        }),
    )
    .await?;
    persist_failed_task_sessions_in_tx(
        &mut transaction,
        &mut failed_tasks,
        &json!({
            "type": "error",
            "code": error_code,
            "message": error_message,
        }),
    )
    .await?;

    transaction.commit().await?;
    Ok(Some(RunnerFailureRecovery {
        reset_tasks,
        failed_tasks,
    }))
}
