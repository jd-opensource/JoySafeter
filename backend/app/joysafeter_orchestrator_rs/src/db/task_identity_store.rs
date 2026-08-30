use async_trait::async_trait;
use sqlx::PgPool;
use uuid::Uuid;

use crate::ids::{ProjectId, TaskId, UserId};
use crate::kernel::task_identity::error::TaskIdentityContextError;
use crate::kernel::task_identity::material::TaskIdentityMaterialError;
use crate::kernel::task_identity::store::{
    ClaimedIdentityMaterial, IdentityMaterialClaim, StoredIdentityMaterial, TaskActorIdentity,
    TaskIdentityStore,
};

const RESOLUTION_LEASE_SECONDS: i64 = 60;

#[derive(Debug, Clone)]
pub(crate) struct PostgresTaskIdentityStore {
    pool: PgPool,
}

impl PostgresTaskIdentityStore {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

type LockedIdentityRow = (
    Option<ProjectId>,
    UserId,
    Option<String>,
    String,
    Option<String>,
    String,
    bool,
    bool,
);

#[async_trait]
impl TaskIdentityStore for PostgresTaskIdentityStore {
    async fn claim_material(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
    ) -> Result<IdentityMaterialClaim, TaskIdentityContextError> {
        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;
        let row: Option<LockedIdentityRow> = sqlx::query_as(
            r#"
            SELECT project_id, user_id, user_name, credential_kind,
                   encrypted_credential, state,
                   expires_at <= NOW() AS material_expired,
                   resolution_expires_at IS NULL OR resolution_expires_at <= NOW() AS claim_expired
            FROM joysafeter_task_identity_contexts
            WHERE task_id = $1
            FOR UPDATE
            "#,
        )
        .bind(task_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;

        let Some((
            persisted_project,
            user_id,
            user_name,
            credential_kind,
            encrypted_credential,
            state,
            material_expired,
            claim_expired,
        )) = row
        else {
            transaction
                .commit()
                .await
                .map_err(|_| TaskIdentityContextError::Database)?;
            return Ok(IdentityMaterialClaim::Unavailable);
        };
        if persisted_project != Some(project_id) {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }

        let claimable = match state.as_str() {
            "captured" => !material_expired,
            "resolving" if claim_expired => !material_expired,
            "resolving" => {
                transaction
                    .commit()
                    .await
                    .map_err(|_| TaskIdentityContextError::Database)?;
                return Ok(IdentityMaterialClaim::Busy);
            }
            "issued" | "expired" | "discarded" => {
                transaction
                    .commit()
                    .await
                    .map_err(|_| TaskIdentityContextError::Database)?;
                return Ok(IdentityMaterialClaim::Unavailable);
            }
            _ => return Err(TaskIdentityContextError::ContextInvalid),
        };

        if !claimable {
            sqlx::query(
                r#"
                UPDATE joysafeter_task_identity_contexts
                SET state = 'expired',
                    encrypted_credential = NULL,
                    resolution_id = NULL,
                    resolution_expires_at = NULL,
                    erased_at = COALESCE(erased_at, NOW()),
                    updated_at = NOW()
                WHERE task_id = $1
                "#,
            )
            .bind(task_id)
            .execute(&mut *transaction)
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;
            transaction
                .commit()
                .await
                .map_err(|_| TaskIdentityContextError::Database)?;
            return Ok(IdentityMaterialClaim::Unavailable);
        }

        let encrypted_credential =
            encrypted_credential.ok_or(TaskIdentityMaterialError::FieldMissing)?;
        let resolution_id = Uuid::now_v7();
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_task_identity_contexts
            SET state = 'resolving',
                resolution_id = $3,
                resolution_expires_at = NOW() + ($4::double precision * INTERVAL '1 second'),
                updated_at = NOW()
            WHERE task_id = $1
              AND project_id = $2
              AND state IN ('captured', 'resolving')
              AND encrypted_credential IS NOT NULL
            "#,
        )
        .bind(task_id)
        .bind(project_id)
        .bind(resolution_id)
        .bind(RESOLUTION_LEASE_SECONDS)
        .execute(&mut *transaction)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        if result.rows_affected() != 1 {
            return Err(TaskIdentityContextError::ClaimConflict);
        }
        transaction
            .commit()
            .await
            .map_err(|_| TaskIdentityContextError::Database)?;

        Ok(IdentityMaterialClaim::Claimed(ClaimedIdentityMaterial {
            resolution_id,
            material: StoredIdentityMaterial {
                user_id,
                user_name,
                credential_kind,
                encrypted_credential,
            },
        }))
    }

    async fn complete_claim(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
        resolution_id: Uuid,
    ) -> Result<(), TaskIdentityContextError> {
        let result = sqlx::query(
            r#"
            UPDATE joysafeter_task_identity_contexts
            SET state = 'issued',
                consumed_at = NOW(),
                erased_at = NOW(),
                encrypted_credential = NULL,
                resolution_id = NULL,
                resolution_expires_at = NULL,
                updated_at = NOW()
            WHERE task_id = $1
              AND project_id = $2
              AND state = 'resolving'
              AND resolution_id = $3
            "#,
        )
        .bind(task_id)
        .bind(project_id)
        .bind(resolution_id)
        .execute(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        if result.rows_affected() != 1 {
            return Err(TaskIdentityContextError::ClaimConflict);
        }
        Ok(())
    }

    async fn release_claim(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
        resolution_id: Uuid,
    ) -> Result<(), TaskIdentityContextError> {
        sqlx::query(
            r#"
            UPDATE joysafeter_task_identity_contexts
            SET state = CASE WHEN expires_at <= NOW() THEN 'expired' ELSE 'captured' END,
                encrypted_credential = CASE
                    WHEN expires_at <= NOW() THEN NULL ELSE encrypted_credential
                END,
                erased_at = CASE
                    WHEN expires_at <= NOW() THEN COALESCE(erased_at, NOW()) ELSE NULL
                END,
                resolution_id = NULL,
                resolution_expires_at = NULL,
                updated_at = NOW()
            WHERE task_id = $1
              AND project_id = $2
              AND state = 'resolving'
              AND resolution_id = $3
            "#,
        )
        .bind(task_id)
        .bind(project_id)
        .bind(resolution_id)
        .execute(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        Ok(())
    }

    async fn load_task_actor(
        &self,
        task_id: TaskId,
        project_id: ProjectId,
    ) -> Result<TaskActorIdentity, TaskIdentityContextError> {
        let row: Option<(Option<ProjectId>, Option<UserId>, Option<String>)> = sqlx::query_as(
            r#"
            SELECT task.project_id, task.user_id, actor.email
            FROM joysafeter_tasks AS task
            LEFT JOIN joysafeter_users AS actor ON actor.id = task.user_id
            WHERE task.id = $1
            "#,
        )
        .bind(task_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| TaskIdentityContextError::Database)?;
        let Some((task_project_id, user_id, user_name)) = row else {
            return Err(TaskIdentityContextError::Database);
        };
        if task_project_id != Some(project_id) {
            return Err(TaskIdentityContextError::ProjectMismatch);
        }
        Ok(TaskActorIdentity {
            user_id: user_id.ok_or(TaskIdentityContextError::ActorMissing)?,
            user_name,
        })
    }
}
