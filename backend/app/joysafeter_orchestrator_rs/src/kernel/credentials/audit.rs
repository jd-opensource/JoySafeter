use std::collections::BTreeSet;

use sqlx::PgPool;
use uuid::Uuid;

use crate::ids::{CredentialId, SessionId, TaskId};

use super::record::{CredentialKind, ProjectId};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CredentialAccessUsage {
    ModelInference,
    EnvironmentInjection,
    HttpEgress,
    McpEgress,
}

impl CredentialAccessUsage {
    const fn as_str(self) -> &'static str {
        match self {
            Self::ModelInference => "model_inference",
            Self::EnvironmentInjection => "environment_injection",
            Self::HttpEgress => "http_egress",
            Self::McpEgress => "mcp_egress",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CredentialAccessFailure {
    Denied,
    Failed,
}

impl CredentialAccessFailure {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Denied => "denied",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone)]
pub struct CredentialAccessAuditEntry {
    pub project_id: ProjectId,
    pub credential_id: CredentialId,
    pub credential_kind: CredentialKind,
    pub usage: CredentialAccessUsage,
    pub consumer_type: String,
    pub consumer_id: Option<String>,
    pub principal_type: String,
    pub principal_id: String,
    pub session_id: Option<SessionId>,
    pub task_id: Option<TaskId>,
    pub generation: Option<i64>,
    pub field_names: BTreeSet<String>,
}

#[derive(Clone)]
pub struct CredentialAccessAuditWriter {
    pool: PgPool,
}

impl CredentialAccessAuditWriter {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn append_success(
        &self,
        entry: &CredentialAccessAuditEntry,
    ) -> Result<bool, sqlx::Error> {
        let field_names = entry.field_names.iter().cloned().collect::<Vec<_>>();
        let result = sqlx::query(
            r#"
            INSERT INTO joysafeter_credential_access_audits (
                id, project_id, credential_id, credential_kind, usage,
                consumer_type, consumer_id, principal_type, principal_id,
                session_id, task_id, generation, field_names, result, error_code
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'success', NULL)
            ON CONFLICT (
                session_id, generation, credential_id, usage, consumer_type, consumer_id
            ) WHERE result = 'success' AND session_id IS NOT NULL AND generation IS NOT NULL
            DO NOTHING
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(entry.project_id.as_str())
        .bind(entry.credential_id)
        .bind(entry.credential_kind.as_str())
        .bind(entry.usage.as_str())
        .bind(&entry.consumer_type)
        .bind(&entry.consumer_id)
        .bind(&entry.principal_type)
        .bind(&entry.principal_id)
        .bind(entry.session_id)
        .bind(entry.task_id)
        .bind(entry.generation)
        .bind(sqlx::types::Json(field_names))
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected() == 1)
    }

    pub async fn append_failure(
        &self,
        entry: &CredentialAccessAuditEntry,
        result: CredentialAccessFailure,
        error_code: &str,
    ) -> Result<bool, sqlx::Error> {
        let field_names = entry.field_names.iter().cloned().collect::<Vec<_>>();
        let result = sqlx::query(
            r#"
            INSERT INTO joysafeter_credential_access_audits (
                id, project_id, credential_id, credential_kind, usage,
                consumer_type, consumer_id, principal_type, principal_id,
                session_id, task_id, generation, field_names, result, error_code
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(entry.project_id.as_str())
        .bind(entry.credential_id)
        .bind(entry.credential_kind.as_str())
        .bind(entry.usage.as_str())
        .bind(&entry.consumer_type)
        .bind(&entry.consumer_id)
        .bind(&entry.principal_type)
        .bind(&entry.principal_id)
        .bind(entry.session_id)
        .bind(entry.task_id)
        .bind(entry.generation)
        .bind(sqlx::types::Json(field_names))
        .bind(result.as_str())
        .bind(error_code)
        .execute(&self.pool)
        .await?;
        Ok(result.rows_affected() == 1)
    }
}
