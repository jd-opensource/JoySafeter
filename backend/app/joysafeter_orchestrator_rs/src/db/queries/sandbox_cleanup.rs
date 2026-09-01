use chrono::{DateTime, Utc};
use sqlx::PgPool;
use uuid::Uuid;

use crate::ids::SandboxId;
use crate::sandbox::provider::SandboxResidualCleanup;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct SandboxCleanupWork {
    pub id: Uuid,
    pub sandbox_id: SandboxId,
    pub provider: String,
    pub resource_kind: String,
    pub resource_name: String,
    pub resource_path: String,
    pub node_name: Option<String>,
    pub attempt_count: i32,
    pub last_error: Option<String>,
    pub claim_expires_at: Option<DateTime<Utc>>,
}

impl SandboxCleanupWork {
    pub fn residual_cleanup(&self) -> SandboxResidualCleanup {
        SandboxResidualCleanup {
            resource_kind: self.resource_kind.clone(),
            resource_name: self.resource_name.clone(),
            resource_path: self.resource_path.clone(),
            node_name: self.node_name.clone(),
            last_error: self.last_error.clone().unwrap_or_default(),
        }
    }
}

pub async fn claim_due_sandbox_cleanup_work(
    pool: &PgPool,
    provider: &str,
    claim_owner: &str,
    claim_ttl_seconds: i64,
    limit: i64,
) -> Result<Vec<SandboxCleanupWork>, sqlx::Error> {
    sqlx::query_as::<_, SandboxCleanupWork>(
        r#"
        WITH due AS (
            SELECT id
            FROM joysafeter_sandbox_cleanup_work
            WHERE provider = $1
              AND (
                    (status = 'pending' AND next_attempt_at <= NOW())
                 OR (status = 'running' AND claim_expires_at < NOW())
              )
            ORDER BY next_attempt_at, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT $4
        )
        UPDATE joysafeter_sandbox_cleanup_work work
        SET status = 'running',
            attempt_count = attempt_count + 1,
            claim_owner = $2,
            claim_expires_at = NOW() + ($3 * INTERVAL '1 second'),
            updated_at = NOW()
        FROM due
        WHERE work.id = due.id
        RETURNING work.id, work.sandbox_id, work.provider, work.resource_kind,
                  work.resource_name, work.resource_path, work.node_name,
                  work.attempt_count, work.last_error, work.claim_expires_at
        "#,
    )
    .bind(provider)
    .bind(claim_owner)
    .bind(claim_ttl_seconds)
    .bind(limit)
    .fetch_all(pool)
    .await
}

pub async fn complete_sandbox_cleanup_work(
    pool: &PgPool,
    work_id: Uuid,
    claim_owner: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandbox_cleanup_work
        SET status = 'completed', claim_owner = NULL, claim_expires_at = NULL,
            completed_at = NOW(), updated_at = NOW()
        WHERE id = $1 AND status = 'running' AND claim_owner = $2
        "#,
    )
    .bind(work_id)
    .bind(claim_owner)
    .execute(pool)
    .await?;
    Ok(result.rows_affected() == 1)
}

pub async fn retry_sandbox_cleanup_work(
    pool: &PgPool,
    work_id: Uuid,
    claim_owner: &str,
    backoff_seconds: i64,
    last_error: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandbox_cleanup_work
        SET status = 'pending', claim_owner = NULL, claim_expires_at = NULL,
            next_attempt_at = NOW() + ($3 * INTERVAL '1 second'),
            last_error = $4, updated_at = NOW()
        WHERE id = $1 AND status = 'running' AND claim_owner = $2
        "#,
    )
    .bind(work_id)
    .bind(claim_owner)
    .bind(backoff_seconds)
    .bind(last_error)
    .execute(pool)
    .await?;
    Ok(result.rows_affected() == 1)
}

pub fn sandbox_cleanup_backoff_seconds(attempt_count: i32) -> i64 {
    let exponent = attempt_count.saturating_sub(1).clamp(0, 8) as u32;
    5_i64.saturating_mul(1_i64 << exponent).min(900)
}

#[cfg(test)]
mod tests {
    #[test]
    fn cleanup_backoff_is_bounded() {
        assert_eq!(super::sandbox_cleanup_backoff_seconds(1), 5);
        assert_eq!(super::sandbox_cleanup_backoff_seconds(2), 10);
        assert_eq!(super::sandbox_cleanup_backoff_seconds(20), 900);
    }
}
