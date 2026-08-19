use anyhow::Context;
use serde_json::{json, Value};
use sqlx::{FromRow, PgConnection, PgPool};
use uuid::Uuid;

use crate::db::models::{JoySafeterAgent, JoySafeterSession};
use crate::ids::{AgentId, EnvironmentId, SessionId, TaskId};

use super::error::CredentialRuntimeError;
use super::model::resolve_model_credential;
use super::record::ProjectId;
use super::reference::{
    decode_snapshot, encode_snapshot, DecodedSnapshot, EncodeVersion, SnapshotCredentialReference,
};
use super::service::{resolve_service_credential, ServiceUsage};
use super::CredentialStore;

const MAX_SOURCE_ATTEMPTS: usize = 3;

#[derive(Debug, Clone)]
pub struct SchedulerSnapshotCommand {
    pub task_id: TaskId,
    pub agent_id: AgentId,
    pub project_id: ProjectId,
}

#[derive(Debug, Clone, FromRow)]
struct EnvironmentSnapshot {
    id: EnvironmentId,
    name: String,
    config: Value,
    image_tag: Option<String>,
    image_version: i32,
}

#[derive(Clone)]
struct SnapshotSource {
    agent: JoySafeterAgent,
    snapshot: Value,
    environment_id: Option<EnvironmentId>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SnapshotLockFingerprint {
    agent_id: AgentId,
    environment_id: Option<EnvironmentId>,
    credential_ids: Vec<crate::ids::CredentialId>,
}

#[derive(Debug, FromRow)]
struct TaskSnapshotBinding {
    project_id: Option<String>,
    agent_id: Option<AgentId>,
    status: String,
    chat_session_id: Option<SessionId>,
}

pub async fn create_scheduler_session(
    pool: &PgPool,
    store: &CredentialStore,
    command: SchedulerSnapshotCommand,
) -> anyhow::Result<Option<JoySafeterSession>> {
    for _attempt in 0..MAX_SOURCE_ATTEMPTS {
        let prelock_source =
            load_source_from_pool(pool, command.agent_id, &command.project_id).await?;
        let prelock_decoded = decode_snapshot(&prelock_source.snapshot)?;
        let prelock_fingerprint = lock_fingerprint(&prelock_source, &prelock_decoded);
        let mut transaction = pool.begin().await?;

        let Some(task_binding) = lock_task_binding(&mut transaction, command.task_id).await? else {
            transaction.rollback().await?;
            return Ok(None);
        };
        if task_binding.project_id.as_deref() != Some(command.project_id.as_str())
            || task_binding.agent_id != Some(command.agent_id)
        {
            transaction.rollback().await?;
            return Err(CredentialRuntimeError::ProjectMismatch.into());
        }
        if task_binding.status != "scheduling" || task_binding.chat_session_id.is_some() {
            transaction.rollback().await?;
            return Ok(None);
        }

        let locked_source =
            load_source_from_connection(&mut transaction, command.agent_id, &command.project_id)
                .await?;
        let locked_decoded = decode_snapshot(&locked_source.snapshot)?;
        if lock_fingerprint(&locked_source, &locked_decoded) != prelock_fingerprint {
            transaction.rollback().await?;
            continue;
        }
        if let Err(error) = lock_and_validate_references(
            &mut transaction,
            store,
            &command.project_id,
            &locked_source,
            &locked_decoded.references,
        )
        .await
        {
            transaction.rollback().await?;
            return Err(error.into());
        }

        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let session = sqlx::query_as::<_, JoySafeterSession>(
            r#"
            INSERT INTO joysafeter_sessions
                (id, agent_id, project_id, status, agent_version, agent_snapshot,
                 environment_ref, created_at, updated_at)
            VALUES ($1, $2, $3, 'idle', $4, $5, $6, NOW(), NOW())
            RETURNING *
            "#,
        )
        .bind(session_id)
        .bind(locked_source.agent.id)
        .bind(command.project_id.as_str())
        .bind(locked_source.agent.version)
        .bind(&locked_source.snapshot)
        .bind(locked_source.agent.environment_ref.as_deref())
        .fetch_one(&mut *transaction)
        .await?;

        sqlx::query(
            r#"
            INSERT INTO joysafeter_security_audit_logs
                (id, event_type, event_status, ip_address, details, created_at, updated_at)
            VALUES ($1, 'session.snapshot.created', 'success', 'scheduler', $2, NOW(), NOW())
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(json!({
            "project_id": locked_source.agent.project_id,
            "target_type": "session",
            "target_id": session.id.to_string(),
            "agent_id": locked_source.agent.id.to_string(),
            "agent_version": locked_source.agent.version,
            "caller": "scheduler",
        }))
        .execute(&mut *transaction)
        .await?;

        let attached = sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET chat_session_id = $2,
                updated_at = NOW()
            WHERE id = $1
              AND project_id = $3
              AND agent_id = $4
              AND status = 'scheduling'
              AND chat_session_id IS NULL
            "#,
        )
        .bind(command.task_id)
        .bind(session.id)
        .bind(command.project_id.as_str())
        .bind(command.agent_id)
        .execute(&mut *transaction)
        .await?;
        if attached.rows_affected() == 0 {
            transaction.rollback().await?;
            return Ok(None);
        }

        transaction.commit().await?;
        return Ok(Some(session));
    }

    anyhow::bail!("scheduler Snapshot source changed repeatedly during activation")
}

async fn lock_and_validate_references(
    connection: &mut PgConnection,
    store: &CredentialStore,
    project_id: &ProjectId,
    source: &SnapshotSource,
    references: &[SnapshotCredentialReference],
) -> Result<(), CredentialRuntimeError> {
    if references.is_empty() {
        return Ok(());
    }
    let mut credential_ids = references
        .iter()
        .map(SnapshotCredentialReference::credential_id)
        .collect::<Vec<_>>();
    credential_ids.sort_by_key(ToString::to_string);
    credential_ids.dedup();

    let mut records = Vec::with_capacity(credential_ids.len());
    for credential_id in credential_ids {
        let record = store
            .lock_active(connection, project_id, credential_id)
            .await?;
        records.push((credential_id, record));
    }

    let engine_kind = source.agent.engine_kind.as_deref().unwrap_or("claude");
    for reference in references {
        let credential_id = reference.credential_id();
        let record = records
            .iter()
            .find_map(|(candidate_id, record)| (*candidate_id == credential_id).then_some(record))
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        match reference {
            SnapshotCredentialReference::Model(_) => {
                resolve_model_credential(record, engine_kind)?;
            }
            SnapshotCredentialReference::Environment(_) => {
                resolve_service_credential(record, ServiceUsage::EnvironmentInjection)?;
            }
            SnapshotCredentialReference::HttpEgress { field, .. } => {
                resolve_service_credential(
                    record,
                    ServiceUsage::HttpEgressField {
                        field: field.as_str(),
                    },
                )?;
            }
        }
    }
    Ok(())
}

fn lock_fingerprint(source: &SnapshotSource, decoded: &DecodedSnapshot) -> SnapshotLockFingerprint {
    SnapshotLockFingerprint {
        agent_id: source.agent.id,
        environment_id: source.environment_id,
        credential_ids: decoded.credential_ids(),
    }
}

async fn lock_task_binding(
    connection: &mut PgConnection,
    task_id: TaskId,
) -> anyhow::Result<Option<TaskSnapshotBinding>> {
    Ok(sqlx::query_as::<_, TaskSnapshotBinding>(
        r#"
        SELECT project_id, agent_id, status, chat_session_id
        FROM joysafeter_tasks
        WHERE id = $1
        FOR UPDATE
        "#,
    )
    .bind(task_id)
    .fetch_optional(&mut *connection)
    .await?)
}

async fn load_source_from_pool(
    pool: &PgPool,
    agent_id: AgentId,
    project_id: &ProjectId,
) -> anyhow::Result<SnapshotSource> {
    let agent = sqlx::query_as::<_, JoySafeterAgent>(
        r#"
        SELECT id, project_id, name, engine_kind, model->>'id' AS model, system_prompt,
               description, env, mcp_servers, skills, agents, commands, tools,
               permission_mode, metadata, multiagent, version, environment_ref,
               model_credential_id
        FROM joysafeter_agents
        WHERE id = $1 AND project_id = $2 AND deleted_at IS NULL AND archived_at IS NULL
        "#,
    )
    .bind(agent_id)
    .bind(project_id.as_str())
    .fetch_optional(pool)
    .await?
    .context("scheduler Snapshot agent not found")?;
    let environment =
        load_environment_from_pool(pool, agent.environment_ref.as_deref(), project_id).await?;
    Ok(build_source(agent, environment)?)
}

async fn load_source_from_connection(
    connection: &mut PgConnection,
    agent_id: AgentId,
    project_id: &ProjectId,
) -> anyhow::Result<SnapshotSource> {
    let agent = sqlx::query_as::<_, JoySafeterAgent>(
        r#"
        SELECT id, project_id, name, engine_kind, model->>'id' AS model, system_prompt,
               description, env, mcp_servers, skills, agents, commands, tools,
               permission_mode, metadata, multiagent, version, environment_ref,
               model_credential_id
        FROM joysafeter_agents
        WHERE id = $1 AND project_id = $2 AND deleted_at IS NULL AND archived_at IS NULL
        FOR UPDATE
        "#,
    )
    .bind(agent_id)
    .bind(project_id.as_str())
    .fetch_optional(&mut *connection)
    .await?
    .context("scheduler Snapshot agent not found")?;
    let environment =
        load_environment_from_connection(connection, agent.environment_ref.as_deref(), project_id)
            .await?;
    Ok(build_source(agent, environment)?)
}

async fn load_environment_from_pool(
    pool: &PgPool,
    environment_ref: Option<&str>,
    project_id: &ProjectId,
) -> anyhow::Result<Option<EnvironmentSnapshot>> {
    let Some(environment_ref) = environment_ref.filter(|value| !value.trim().is_empty()) else {
        return Ok(None);
    };
    if let Ok(environment_id) = EnvironmentId::from_public(environment_ref) {
        let environment = sqlx::query_as::<_, EnvironmentSnapshot>(
            r#"
            SELECT id, name, config, image_tag, image_version
            FROM joysafeter_environments
            WHERE id = $1 AND deleted_at IS NULL AND archived_at IS NULL
              AND project_id = $2
            "#,
        )
        .bind(environment_id)
        .bind(project_id.as_str())
        .fetch_optional(pool)
        .await?;
        return environment
            .map(Some)
            .ok_or_else(|| anyhow::anyhow!("scheduler Snapshot environment not found"));
    }
    let environment = sqlx::query_as::<_, EnvironmentSnapshot>(
        r#"
        SELECT id, name, config, image_tag, image_version
        FROM joysafeter_environments
        WHERE name = $1 AND deleted_at IS NULL AND archived_at IS NULL
          AND project_id = $2
        "#,
    )
    .bind(environment_ref)
    .bind(project_id.as_str())
    .fetch_optional(pool)
    .await?;
    environment
        .map(Some)
        .ok_or_else(|| anyhow::anyhow!("scheduler Snapshot environment not found"))
}

async fn load_environment_from_connection(
    connection: &mut PgConnection,
    environment_ref: Option<&str>,
    project_id: &ProjectId,
) -> anyhow::Result<Option<EnvironmentSnapshot>> {
    let Some(environment_ref) = environment_ref.filter(|value| !value.trim().is_empty()) else {
        return Ok(None);
    };
    if let Ok(environment_id) = EnvironmentId::from_public(environment_ref) {
        let environment = sqlx::query_as::<_, EnvironmentSnapshot>(
            r#"
            SELECT id, name, config, image_tag, image_version
            FROM joysafeter_environments
            WHERE id = $1 AND deleted_at IS NULL AND archived_at IS NULL
              AND project_id = $2
            FOR UPDATE
            "#,
        )
        .bind(environment_id)
        .bind(project_id.as_str())
        .fetch_optional(&mut *connection)
        .await?;
        return environment
            .map(Some)
            .ok_or_else(|| anyhow::anyhow!("scheduler Snapshot environment not found"));
    }
    let environment = sqlx::query_as::<_, EnvironmentSnapshot>(
        r#"
        SELECT id, name, config, image_tag, image_version
        FROM joysafeter_environments
        WHERE name = $1 AND deleted_at IS NULL AND archived_at IS NULL
          AND project_id = $2
        FOR UPDATE
        "#,
    )
    .bind(environment_ref)
    .bind(project_id.as_str())
    .fetch_optional(&mut *connection)
    .await?;
    environment
        .map(Some)
        .ok_or_else(|| anyhow::anyhow!("scheduler Snapshot environment not found"))
}

fn build_source(
    agent: JoySafeterAgent,
    environment: Option<EnvironmentSnapshot>,
) -> Result<SnapshotSource, CredentialRuntimeError> {
    let mut snapshot = json!({
        "id": agent.id.to_string(),
        "version": agent.version,
        "name": agent.name,
        "engine_kind": agent.engine_kind,
        "description": agent.description,
        "model": agent.model,
        "system": agent.system_prompt,
        "metadata": agent.metadata,
        "env": agent.env,
        "tools": agent.tools,
        "skills": agent.skills,
        "agents": agent.agents,
        "commands": agent.commands,
        "mcp_servers": agent.mcp_servers,
        "permission_mode": agent.permission_mode,
        "multiagent": agent.multiagent,
        "environment_ref": agent.environment_ref,
        "model_credential_id": agent.model_credential_id.map(|id| id.to_string()),
    });
    if let Some(ref environment) = environment {
        snapshot["environment"] = json!({
            "ref": agent.environment_ref,
            "id": environment.id.to_string(),
            "name": environment.name,
            "config": environment.config,
            "image_tag": environment.image_tag,
            "image_version": environment.image_version,
        });
    }
    let snapshot = encode_snapshot(&snapshot, Some(EncodeVersion::V1))?;
    let environment_id = environment.as_ref().map(|environment| environment.id);
    Ok(SnapshotSource {
        agent,
        snapshot,
        environment_id,
    })
}
