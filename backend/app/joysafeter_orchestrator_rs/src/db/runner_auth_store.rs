use async_trait::async_trait;
use sqlx::PgPool;

use crate::ids::SandboxId;
use crate::kernel::runtime_auth::{RunnerAuthStore, StoredRunnerAuth};

#[derive(Clone)]
pub(crate) struct PostgresRunnerAuthStore {
    pool: PgPool,
}

impl PostgresRunnerAuthStore {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl RunnerAuthStore for PostgresRunnerAuthStore {
    async fn load(&self, sandbox_id: SandboxId) -> anyhow::Result<Option<StoredRunnerAuth>> {
        let row = sqlx::query_as::<
            _,
            (
                String,
                String,
                Option<String>,
                Option<chrono::DateTime<chrono::Utc>>,
                Option<crate::ids::SessionId>,
            ),
        >(
            r#"
            SELECT status, runner_auth_state, runner_token_digest,
                   runner_auth_expires_at, chat_session_id
            FROM joysafeter_sandboxes
            WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(row.map(
            |(sandbox_status, state, token_digest, expires_at, linked_session_id)| {
                StoredRunnerAuth {
                    state,
                    token_digest,
                    expires_at,
                    sandbox_status,
                    linked_session_id,
                }
            },
        ))
    }

    async fn mark_connected_if_current(
        &self,
        sandbox_id: SandboxId,
        expected: &StoredRunnerAuth,
    ) -> anyhow::Result<bool> {
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET last_used_at = NOW(),
                disconnected_at = NULL,
                updated_at = NOW()
            WHERE id = $1
              AND status = $2
              AND runner_auth_state = $3
              AND runner_token_digest IS NOT DISTINCT FROM $4
              AND runner_auth_expires_at IS NOT DISTINCT FROM $5
              AND chat_session_id IS NOT DISTINCT FROM $6
              AND destroyed_at IS NULL
            "#,
        )
        .bind(sandbox_id)
        .bind(&expected.sandbox_status)
        .bind(&expected.state)
        .bind(&expected.token_digest)
        .bind(expected.expires_at)
        .bind(expected.linked_session_id)
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected() == 1)
    }
}
