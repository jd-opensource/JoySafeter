use std::env;

use joysafeter_orchestrator::ids::{
    AgentId, CredentialId, EnvironmentId, OrganizationId, ProjectId, TaskId,
};
use joysafeter_orchestrator::kernel::credentials::material::ManagedCredentialMaterialAdapter;
use joysafeter_orchestrator::kernel::credentials::reference::decode_snapshot;
use joysafeter_orchestrator::kernel::credentials::snapshot::{
    create_scheduler_session, SchedulerSnapshotCommand,
};
use joysafeter_orchestrator::kernel::credentials::CredentialStore;
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

const TEST_KEY: [u8; 32] = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    26, 27, 28, 29, 30, 31,
];
const ENCRYPTED_HELLO_WORLD: &str = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";

fn database_url() -> String {
    env::var("JOYSAFETER_CREDENTIAL_RUNTIME_TEST_DATABASE_URL")
        .or_else(|_| env::var("JOYSAFETER_TEST_DATABASE_URL"))
        .or_else(|_| env::var("DATABASE_URL"))
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
        .expect("a credential runtime test database URL must point to migrated PostgreSQL")
}

async fn test_pool() -> PgPool {
    PgPoolOptions::new()
        .max_connections(4)
        .connect(&database_url())
        .await
        .expect("connect to migrated PostgreSQL test database")
}

async fn seed_project(pool: &PgPool, unique: &str) -> (OrganizationId, ProjectId) {
    let organization_id = OrganizationId::new();
    let project_id = ProjectId::new();
    sqlx::query(
        "INSERT INTO joysafeter_organizations (id, name, slug, storage_used_bytes, departed_member_usage) VALUES ($1, $2, $3, 0, 0)",
    )
    .bind(&organization_id)
    .bind(format!("Task 11 Org {unique}"))
    .bind(format!("task-11-org-{unique}"))
    .execute(pool)
    .await
    .expect("insert organization fixture");
    sqlx::query(
        "INSERT INTO joysafeter_organization_projects (id, org_id, name, slug, is_default) VALUES ($1, $2, $3, $4, false)",
    )
    .bind(&project_id)
    .bind(&organization_id)
    .bind(format!("Task 11 Project {unique}"))
    .bind(format!("task-11-project-{unique}"))
    .execute(pool)
    .await
    .expect("insert project fixture");
    (organization_id, project_id)
}

async fn seed_credential(
    pool: &PgPool,
    credential_id: CredentialId,
    project_id: &ProjectId,
    archived: bool,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_credentials (
            id, project_id, kind, name, provider, protocol, data, is_default,
            archived_at
        )
        VALUES (
            $1, $2, 'model', $3, 'anthropic', 'anthropic_messages', $4, false,
            CASE WHEN $5 THEN NOW() ELSE NULL END
        )
        "#,
    )
    .bind(credential_id)
    .bind(project_id)
    .bind(format!("task-11-credential-{credential_id}"))
    .bind(json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}))
    .bind(archived)
    .execute(pool)
    .await
    .expect("insert credential fixture");
}

async fn seed_agent_and_task(
    pool: &PgPool,
    agent_id: AgentId,
    task_id: TaskId,
    credential_id: CredentialId,
    project_id: &ProjectId,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (
            id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
            skills, tools, agents, commands, metadata, version,
            model_credential_id
        )
        VALUES (
            $1, $2, $3, 'claude', $4, 'task 11 system', '{}'::jsonb, '[]'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '{}'::jsonb, 1, $5
        )
        "#,
    )
    .bind(agent_id)
    .bind(project_id)
    .bind(format!("task-11-agent-{agent_id}"))
    .bind(json!({"id": "claude-sonnet-4"}))
    .bind(credential_id)
    .execute(pool)
    .await
    .expect("insert agent fixture");
    sqlx::query(
        r#"
        INSERT INTO joysafeter_tasks (
            id, project_id, agent_id, status, prompt, output, timeout_sec,
            retry_count, max_retries
        )
        VALUES ($1, $2, $3, 'scheduling', 'task 11', '', 7200, 0, 3)
        "#,
    )
    .bind(task_id)
    .bind(project_id)
    .bind(agent_id)
    .execute(pool)
    .await
    .expect("insert task fixture");
}

async fn seed_environment(pool: &PgPool, environment_id: EnvironmentId, project_id: &ProjectId) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_environments
            (id, project_id, name, description, config, image_version)
        VALUES ($1, $2, $3, '', '{}'::jsonb, 1)
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .bind(format!("task-11-environment-{environment_id}"))
    .execute(pool)
    .await
    .expect("insert environment fixture");
}

async fn assert_no_scheduler_session(pool: &PgPool, agent_id: AgentId, task_id: TaskId) {
    let session_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM joysafeter_sessions WHERE agent_id = $1")
            .bind(agent_id)
            .fetch_one(pool)
            .await
            .expect("count scheduler sessions");
    let attached: Option<joysafeter_orchestrator::ids::SessionId> =
        sqlx::query_scalar("SELECT chat_session_id FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .fetch_one(pool)
            .await
            .expect("load task session attachment");
    assert_eq!(session_count, 0);
    assert_eq!(attached, None);
}

async fn cleanup(
    pool: &PgPool,
    organization_id: &OrganizationId,
    project_id: &ProjectId,
    agent_id: AgentId,
    task_id: TaskId,
    credential_id: CredentialId,
) {
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE agent_id = $1")
        .bind(agent_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
        .bind(credential_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(project_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(organization_id)
        .execute(pool)
        .await;
}

#[test]
fn scheduler_delegates_snapshot_creation_to_the_credential_kernel() {
    let source = include_str!("../src/kernel/scheduler.rs");
    let production = source
        .split("#[cfg(test)]")
        .next()
        .expect("production scheduler");
    assert!(!production.contains("build_agent_execution_snapshot"));
    assert!(!production.contains("queries::create_session"));
    assert!(production.contains("credentials::snapshot"));
    assert!(production.contains("CredentialStore"));
}

#[test]
fn canonical_reference_decoder_accepts_canonical_v2_paths() {
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let environment_id = CredentialId::from_uuid(Uuid::now_v7());
    let http_id = CredentialId::from_uuid(Uuid::now_v7());
    let decoded = decode_snapshot(&json!({
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "engine_kind": "claude",
        "model": {"id": "claude-sonnet-4"},
        "model_credential_id": credential_id.to_string(),
        "environment_credential_ids": [environment_id.to_string()],
        "environment": {
            "config": {
                "egress_services": [{
                    "base_url": "https://api.example.com",
                    "credential_ref": http_id.to_string(),
                    "inject": {"type": "bearer", "credential_field": "TOKEN"}
                }]
            }
        }
    }))
    .expect("canonical decoder accepts v2 paths");

    let mut expected = vec![credential_id, environment_id, http_id];
    expected.sort_by_key(ToString::to_string);
    assert_eq!(decoded.credential_ids(), expected);
}

#[test]
fn canonical_reference_decoder_rejects_unknown_schema() {
    assert!(
        decode_snapshot(&json!({"schema": "joysafeter.agent_execution_snapshot.v99"})).is_err()
    );
}

#[tokio::test]
async fn scheduler_snapshot_validation_and_session_attach_share_one_transaction() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    seed_environment(&pool, environment_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_agents SET environment_id = $2 WHERE id = $1")
        .bind(agent_id)
        .bind(environment_id)
        .execute(&pool)
        .await
        .expect("bind Agent to Environment ID");
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    let session = create_scheduler_session(
        &pool,
        &store,
        SchedulerSnapshotCommand {
            task_id,
            agent_id,
            project_id,
        },
    )
    .await
    .expect("linearized scheduler session")
    .expect("scheduling task remained attachable");

    assert_eq!(
        session
            .agent_snapshot
            .as_ref()
            .and_then(|value| value["model_credential_id"].as_str()),
        Some(credential_id.to_string().as_str())
    );
    assert_eq!(session.environment_id, Some(environment_id));
    assert_eq!(
        session
            .agent_snapshot
            .as_ref()
            .and_then(|value| value["environment_id"].as_str()),
        Some(environment_id.to_string().as_str())
    );
    assert_eq!(
        session
            .agent_snapshot
            .as_ref()
            .and_then(|value| value["environment"]["environment_id"].as_str()),
        Some(environment_id.to_string().as_str())
    );
    let attached: Option<joysafeter_orchestrator::ids::SessionId> =
        sqlx::query_scalar("SELECT chat_session_id FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load attached session");
    let audit_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM joysafeter_security_audit_logs WHERE event_type = 'session.snapshot.created' AND details->>'target_id' = $1",
    )
    .bind(session.id.to_string())
    .fetch_one(&pool)
    .await
    .expect("count scheduler Snapshot audit");
    assert_eq!(attached, Some(session.id));
    assert_eq!(audit_count, 1);

    let _ = sqlx::query(
        "DELETE FROM joysafeter_security_audit_logs WHERE event_type = 'session.snapshot.created' AND details->>'target_id' = $1",
    )
    .bind(session.id.to_string())
    .execute(&pool)
    .await;

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
    let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
        .bind(environment_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn archived_credential_rolls_back_scheduler_session_and_task_attach() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, true).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    let error = create_scheduler_session(
        &pool,
        &store,
        SchedulerSnapshotCommand {
            task_id,
            agent_id,
            project_id,
        },
    )
    .await
    .expect_err("archived credential must reject activation");

    assert_eq!(
        error
            .downcast_ref::<joysafeter_orchestrator::kernel::credentials::error::CredentialRuntimeError>(),
        Some(&joysafeter_orchestrator::kernel::credentials::error::CredentialRuntimeError::Archived)
    );
    let session_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM joysafeter_sessions WHERE agent_id = $1")
            .bind(agent_id)
            .fetch_one(&pool)
            .await
            .expect("count rolled back sessions");
    let attached: Option<joysafeter_orchestrator::ids::SessionId> =
        sqlx::query_scalar("SELECT chat_session_id FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load unattached task");
    assert_eq!(session_count, 0);
    assert_eq!(attached, None);

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}

#[tokio::test]
async fn scheduler_snapshot_rejects_wrong_project_and_creates_no_session() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let other_unique = Uuid::now_v7().simple().to_string();
    let (other_organization_id, other_project_id) = seed_project(&pool, &other_unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    create_scheduler_session(
        &pool,
        &store,
        SchedulerSnapshotCommand {
            task_id,
            agent_id,
            project_id: other_project_id,
        },
    )
    .await
    .expect_err("wrong-project scheduler activation must fail closed");
    let session_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM joysafeter_sessions WHERE agent_id = $1")
            .bind(agent_id)
            .fetch_one(&pool)
            .await
            .expect("count wrong-project sessions");
    assert_eq!(session_count, 0);

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(&other_project_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(&other_organization_id)
        .execute(&pool)
        .await;
}

#[tokio::test]
async fn environment_foreign_key_rejects_missing_environment_before_snapshot_creation() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let missing_environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let error = sqlx::query("UPDATE joysafeter_agents SET environment_id = $2 WHERE id = $1")
        .bind(agent_id)
        .bind(missing_environment_id)
        .execute(&pool)
        .await
        .expect_err("native environment foreign key must reject missing environment IDs");
    assert_eq!(
        error
            .as_database_error()
            .and_then(|database_error| database_error.code().map(|code| code.into_owned()))
            .as_deref(),
        Some("23503")
    );
    let session_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM joysafeter_sessions WHERE agent_id = $1")
            .bind(agent_id)
            .fetch_one(&pool)
            .await
            .expect("count missing-environment sessions");
    assert_eq!(session_count, 0);

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}

#[tokio::test]
async fn scheduler_snapshot_waits_for_task_project_binding_lock() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );
    let mut blocker = pool.begin().await.expect("begin task lock blocker");
    sqlx::query("SELECT id FROM joysafeter_tasks WHERE id = $1 FOR UPDATE")
        .bind(task_id)
        .execute(&mut *blocker)
        .await
        .expect("lock task row");

    let pool_for_create = pool.clone();
    let store_for_create = store.clone();
    let project_for_create = project_id;
    let create = tokio::spawn(async move {
        create_scheduler_session(
            &pool_for_create,
            &store_for_create,
            SchedulerSnapshotCommand {
                task_id,
                agent_id,
                project_id: project_for_create,
            },
        )
        .await
    });
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    assert!(
        !create.is_finished(),
        "scheduler must wait for the locked task binding"
    );
    blocker.commit().await.expect("release task lock");
    let session = create
        .await
        .expect("scheduler join")
        .expect("scheduler create")
        .expect("task remains attachable");
    assert_eq!(session.agent_id, Some(agent_id));

    let _ = sqlx::query(
        "DELETE FROM joysafeter_security_audit_logs WHERE event_type = 'session.snapshot.created' AND details->>'target_id' = $1",
    )
    .bind(session.id.to_string())
    .execute(&pool)
    .await;
    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}

#[tokio::test]
async fn scheduler_snapshot_waits_for_credential_archive_and_fails_without_session() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    let mut writer = pool.begin().await.expect("begin credential archive writer");
    sqlx::query("UPDATE joysafeter_credentials SET archived_at = NOW() WHERE id = $1")
        .bind(credential_id)
        .execute(&mut *writer)
        .await
        .expect("archive credential under writer lock");

    let pool_for_create = pool.clone();
    let store_for_create = store.clone();
    let project_for_create = project_id;
    let create = tokio::spawn(async move {
        create_scheduler_session(
            &pool_for_create,
            &store_for_create,
            SchedulerSnapshotCommand {
                task_id,
                agent_id,
                project_id: project_for_create,
            },
        )
        .await
    });
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    assert!(
        !create.is_finished(),
        "scheduler must wait for the credential archive writer"
    );

    writer.commit().await.expect("commit credential archive");
    assert!(
        create.await.expect("scheduler join").is_err(),
        "archived Credential must fail Snapshot activation"
    );
    assert_no_scheduler_session(&pool, agent_id, task_id).await;

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}

#[tokio::test]
async fn scheduler_snapshot_waits_for_agent_archive_and_fails_without_session() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    let mut writer = pool.begin().await.expect("begin Agent archive writer");
    sqlx::query("UPDATE joysafeter_agents SET archived_at = NOW() WHERE id = $1")
        .bind(agent_id)
        .execute(&mut *writer)
        .await
        .expect("archive Agent under writer lock");

    let pool_for_create = pool.clone();
    let store_for_create = store.clone();
    let project_for_create = project_id;
    let create = tokio::spawn(async move {
        create_scheduler_session(
            &pool_for_create,
            &store_for_create,
            SchedulerSnapshotCommand {
                task_id,
                agent_id,
                project_id: project_for_create,
            },
        )
        .await
    });
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    assert!(
        !create.is_finished(),
        "scheduler must wait for the Agent archive writer"
    );

    writer.commit().await.expect("commit Agent archive");
    assert!(
        create.await.expect("scheduler join").is_err(),
        "archived Agent must fail Snapshot activation"
    );
    assert_no_scheduler_session(&pool, agent_id, task_id).await;

    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}

#[tokio::test]
async fn scheduler_snapshot_waits_for_environment_archive_and_fails_without_session() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let (organization_id, project_id) = seed_project(&pool, &unique).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    seed_credential(&pool, credential_id, &project_id, false).await;
    seed_agent_and_task(&pool, agent_id, task_id, credential_id, &project_id).await;
    seed_environment(&pool, environment_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_agents SET environment_id = $2 WHERE id = $1")
        .bind(agent_id)
        .bind(environment_id)
        .execute(&pool)
        .await
        .expect("bind Agent to Environment");
    let store = CredentialStore::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );

    let mut writer = pool
        .begin()
        .await
        .expect("begin Environment archive writer");
    sqlx::query("UPDATE joysafeter_environments SET archived_at = NOW() WHERE id = $1")
        .bind(environment_id)
        .execute(&mut *writer)
        .await
        .expect("archive Environment under writer lock");

    let pool_for_create = pool.clone();
    let store_for_create = store.clone();
    let project_for_create = project_id;
    let create = tokio::spawn(async move {
        create_scheduler_session(
            &pool_for_create,
            &store_for_create,
            SchedulerSnapshotCommand {
                task_id,
                agent_id,
                project_id: project_for_create,
            },
        )
        .await
    });
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    assert!(
        !create.is_finished(),
        "scheduler must wait for the Environment archive writer"
    );

    writer.commit().await.expect("commit Environment archive");
    assert!(
        create.await.expect("scheduler join").is_err(),
        "archived Environment must fail Snapshot activation"
    );
    assert_no_scheduler_session(&pool, agent_id, task_id).await;

    let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
        .bind(environment_id)
        .execute(&pool)
        .await;
    cleanup(
        &pool,
        &organization_id,
        &project_id,
        agent_id,
        task_id,
        credential_id,
    )
    .await;
}
