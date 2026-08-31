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
    ) -> anyhow::Result<Option<StoredRunnerAuth>> {
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
            UPDATE joysafeter_sandboxes
            SET last_used_at = NOW(),
                disconnected_at = NULL,
                updated_at = NOW()
            WHERE id = $1
              AND status IN ('creating', 'provisioning', 'pooled', 'idle', 'running')
              AND runner_token_digest IS NOT DISTINCT FROM $2
              AND (
                    ($3 = 'admission' AND runner_auth_state = 'admission'
                     AND runner_auth_expires_at IS NOT DISTINCT FROM $4
                     AND runner_auth_expires_at > NOW())
                 OR ($3 = 'admission' AND runner_auth_state = 'active'
                     AND runner_auth_expires_at IS NULL)
                 OR ($3 = 'active' AND runner_auth_state = 'active'
                     AND runner_auth_expires_at IS NULL)
              )
              AND destroyed_at IS NULL
            RETURNING status, runner_auth_state, runner_token_digest,
                      runner_auth_expires_at, chat_session_id
            "#,
        )
        .bind(sandbox_id)
        .bind(&expected.token_digest)
        .bind(&expected.state)
        .bind(expected.expires_at)
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
}

#[cfg(test)]
mod tests {
    use std::env;

    use chrono::{Duration, Utc};
    use sqlx::postgres::PgPoolOptions;
    use uuid::Uuid;

    use super::*;
    use crate::kernel::runtime_auth::runner_token_digest;

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    #[tokio::test]
    async fn connection_commit_accepts_same_credential_after_pool_activation() {
        let Some(database_url) = database_url() else {
            eprintln!("skipping Runner auth store integration test: database URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
            .max_connections(2)
            .connect(&database_url)
            .await
            .expect("connect to migrated PostgreSQL test database");
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let token_digest = runner_token_digest("activation-race-token");

        sqlx::query(
            r#"
            INSERT INTO joysafeter_sandboxes (
                id, external_id, provider, status, image, config,
                runner_auth_state, runner_token_digest, runner_auth_expires_at
            )
            VALUES ($1, '', 'test', 'creating', 'test:latest', '{}'::jsonb,
                    'admission', $2, $3)
            "#,
        )
        .bind(sandbox_id)
        .bind(&token_digest)
        .bind(Utc::now() + Duration::minutes(1))
        .execute(&pool)
        .await
        .expect("insert staged sandbox");

        let result = async {
            let store = PostgresRunnerAuthStore::new(pool.clone());
            let verified = store
                .load(sandbox_id)
                .await
                .expect("load staged admission")
                .expect("staged sandbox exists");

            sqlx::query(
                r#"
                UPDATE joysafeter_sandboxes
                SET external_id = $2,
                    status = 'pooled',
                    runner_auth_state = 'active',
                    runner_auth_expires_at = NULL
                WHERE id = $1
                "#,
            )
            .bind(sandbox_id)
            .bind(format!("pool-{sandbox_id}"))
            .execute(&pool)
            .await
            .expect("activate staged pool sandbox");

            let committed = store
                .mark_connected_if_current(sandbox_id, &verified)
                .await
                .expect("commit Runner connection")
                .expect("same credential remains authoritative after activation");

            assert_eq!(committed.state, "active");
            assert_eq!(committed.sandbox_status, "pooled");
            assert_eq!(
                committed.token_digest.as_deref(),
                Some(token_digest.as_str())
            );
            assert_eq!(committed.expires_at, None);
        }
        .await;

        sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("cleanup sandbox fixture");
        result
    }
}
