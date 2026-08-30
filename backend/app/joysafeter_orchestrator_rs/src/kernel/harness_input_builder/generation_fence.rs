use sqlx::{FromRow, PgPool};

use crate::ids::{ProjectId, SandboxId, SessionId};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

pub(super) async fn load(
    pool: &PgPool,
    session_id: SessionId,
    sandbox_id: SandboxId,
) -> anyhow::Result<HarnessGenerationFence> {
    sqlx::query_as::<_, HarnessGenerationFence>(
        r#"
        SELECT
            session.id AS session_id,
            session.project_id AS session_project_id,
            session.status AS session_status,
            session.archived_at AS session_archived_at,
            session.runtime_config_generation AS generation,
            sandbox.chat_session_id AS sandbox_session_id,
            sandbox.project_id AS sandbox_project_id,
            sandbox.runtime_config_status,
            sandbox.runtime_config_applied_generation AS applied_generation
        FROM joysafeter_sessions AS session
        JOIN joysafeter_sandboxes AS sandbox ON sandbox.id = $2
        WHERE session.id = $1
        "#,
    )
    .bind(session_id)
    .bind(sandbox_id)
    .fetch_optional(pool)
    .await?
    .ok_or_else(|| RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id }.into())
}

#[derive(Debug, FromRow)]
pub(super) struct HarnessGenerationFence {
    pub(super) session_id: SessionId,
    session_project_id: Option<ProjectId>,
    session_status: String,
    session_archived_at: Option<chrono::DateTime<chrono::Utc>>,
    sandbox_session_id: Option<SessionId>,
    sandbox_project_id: Option<ProjectId>,
    runtime_config_status: String,
    pub(super) generation: i64,
    applied_generation: i64,
}

impl HarnessGenerationFence {
    pub(super) fn validate(&self, sandbox_id: SandboxId) -> Result<(), RuntimeFreshnessError> {
        if self.session_archived_at.is_some() || self.session_status == "terminated" {
            return Err(RuntimeFreshnessError::SessionBindingInvalid {
                session_id: self.session_id,
                reason: "inactive session",
            });
        }
        if self.sandbox_session_id != Some(self.session_id)
            || self.sandbox_project_id != self.session_project_id
        {
            return Err(RuntimeFreshnessError::Conflict(format!(
                "sandbox {sandbox_id} ownership changed"
            )));
        }
        if self.applied_generation != self.generation {
            return Err(RuntimeFreshnessError::GenerationChanged {
                expected: self.generation,
                actual: self.applied_generation,
            });
        }
        if self.runtime_config_status != "ready" {
            return Err(RuntimeFreshnessError::RuntimeRestartRequired { sandbox_id });
        }
        Ok(())
    }
}
