use sqlx::PgPool;
use uuid::Uuid;

use crate::ids::{SandboxId, SkillId, SkillSecurityScanId, SkillUsageId, SkillVersionId};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct LoadedSkillUsage {
    pub(crate) skill_id: SkillId,
    pub(crate) skill_version: String,
    pub(crate) skill_version_id: SkillVersionId,
    pub(crate) skill_name: String,
    pub(crate) skill_source_type: Option<String>,
    pub(crate) target: String,
    pub(crate) security_scan_id: Option<SkillSecurityScanId>,
    pub(crate) target_hash: Option<String>,
    pub(crate) artifact_hash: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RecordLoadedSkillUsage {
    Inserted,
    AlreadyRecorded,
    SandboxMissing,
}

pub(crate) async fn record_loaded_skill_usage(
    pool: &PgPool,
    sandbox_id: SandboxId,
    usage: &LoadedSkillUsage,
) -> anyhow::Result<RecordLoadedSkillUsage> {
    let (sandbox_exists, inserted) = sqlx::query_as::<_, (bool, bool)>(
        r#"
        WITH sandbox_context AS (
            SELECT sandbox.id AS sandbox_id,
                   sandbox.chat_session_id AS session_id,
                   session.agent_id,
                   session.project_id
            FROM joysafeter_sandboxes sandbox
            LEFT JOIN joysafeter_sessions session ON session.id = sandbox.chat_session_id
            WHERE sandbox.id = $11
        ), inserted AS (
            INSERT INTO joysafeter_skill_usage_log
              (id, skill_id, skill_name, skill_source_type, skill_version, skill_version_id,
               target, security_scan_id, target_hash, artifact_hash, sandbox_id,
               session_id, agent_id, project_id, user_id, created_at, updated_at)
            SELECT $1, $2, $3, $4, $5,
                   CASE WHEN EXISTS (SELECT 1 FROM joysafeter_skill_versions WHERE id = $6)
                        THEN $6 ELSE NULL END,
                   $7, $8, $9, $10, context.sandbox_id,
                   context.session_id, context.agent_id, context.project_id, NULL,
                   NOW(), NOW()
            FROM sandbox_context context
            ON CONFLICT (sandbox_id, skill_id, skill_version, target, artifact_hash)
              WHERE sandbox_id IS NOT NULL
            DO NOTHING
            RETURNING 1
        )
        SELECT EXISTS (SELECT 1 FROM sandbox_context),
               EXISTS (SELECT 1 FROM inserted)
        "#,
    )
    .bind(SkillUsageId::from_uuid(Uuid::now_v7()))
    .bind(usage.skill_id)
    .bind(&usage.skill_name)
    .bind(usage.skill_source_type.as_deref())
    .bind(&usage.skill_version)
    .bind(usage.skill_version_id)
    .bind(&usage.target)
    .bind(usage.security_scan_id)
    .bind(usage.target_hash.as_deref())
    .bind(&usage.artifact_hash)
    .bind(sandbox_id)
    .fetch_one(pool)
    .await?;

    Ok(match (sandbox_exists, inserted) {
        (false, _) => RecordLoadedSkillUsage::SandboxMissing,
        (true, true) => RecordLoadedSkillUsage::Inserted,
        (true, false) => RecordLoadedSkillUsage::AlreadyRecorded,
    })
}
