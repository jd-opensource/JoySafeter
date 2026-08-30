use std::env;
use std::str::FromStr;
use std::time::Duration;

use chrono::{DateTime, Utc};
use joysafeter_orchestrator::db::queries;
use joysafeter_orchestrator::ids::{
    AgentId, CredentialAccessAuditId, CredentialGroupId, CredentialId, EnvironmentId,
    OrganizationId, ProjectId, SandboxId, SessionId, TaskId,
};
use joysafeter_orchestrator::kernel;
use joysafeter_orchestrator::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use joysafeter_orchestrator::kernel::credentials::audit::{
    CredentialAccessAuditEntry, CredentialAccessAuditWriter, CredentialAccessFailure,
    CredentialAccessUsage,
};
use joysafeter_orchestrator::kernel::credentials::error::{
    require_bound_credential_id, CredentialRuntimeError,
};
use joysafeter_orchestrator::kernel::credentials::material::ManagedCredentialMaterialAdapter;
use joysafeter_orchestrator::kernel::credentials::mcp::resolve_mcp_members;
use joysafeter_orchestrator::kernel::credentials::model::resolve_model_credential;
use joysafeter_orchestrator::kernel::credentials::service::{
    resolve_service_credential, ResolvedServiceCredential, ServiceUsage,
};
use joysafeter_orchestrator::kernel::credentials::store::CredentialStore;
use joysafeter_orchestrator::kernel::runtime_freshness::RuntimeFreshnessError;
use serde_json::{json, Value};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
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

async fn named_single_connection_pool(application_name: &str) -> PgPool {
    let options = PgConnectOptions::from_str(&database_url())
        .expect("parse PostgreSQL test database URL")
        .application_name(application_name);
    PgPoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
        .expect("connect named PostgreSQL test pool")
}

async fn wait_for_database_lock(pool: &PgPool, application_name: &str) {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let waiting: bool = sqlx::query_scalar(
                r#"
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_stat_activity
                    WHERE application_name = $1
                      AND wait_event_type = 'Lock'
                )
                "#,
            )
            .bind(application_name)
            .fetch_one(pool)
            .await
            .expect("inspect PostgreSQL lock wait");
            if waiting {
                return;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("database writer did not reach the expected lock wait");
}

fn test_store(pool: PgPool) -> CredentialStore {
    CredentialStore::with_material_adapter(
        pool,
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    )
}

async fn insert_project(pool: &PgPool, unique: &str, project_id: &ProjectId) -> OrganizationId {
    let organization_id = OrganizationId::new();
    sqlx::query(
        r#"
        INSERT INTO joysafeter_organizations
            (id, name, slug, storage_used_bytes, departed_member_usage)
        VALUES ($1, $2, $3, 0, 0)
        "#,
    )
    .bind(&organization_id)
    .bind(format!("Task 10 Org {unique}"))
    .bind(format!("task-10-org-{unique}"))
    .execute(pool)
    .await
    .expect("insert organization fixture");

    sqlx::query(
        r#"
        INSERT INTO joysafeter_organization_projects
            (id, org_id, name, slug, is_default)
        VALUES ($1, $2, $3, $4, false)
        "#,
    )
    .bind(project_id)
    .bind(&organization_id)
    .bind(format!("Task 10 Project {unique}"))
    .bind(format!("task-10-project-{unique}"))
    .execute(pool)
    .await
    .expect("insert project fixture");
    organization_id
}

async fn insert_agent(pool: &PgPool, agent_id: AgentId, project_id: &ProjectId) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (
            id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
            skills, tools, agents, commands, metadata, version
        )
        VALUES (
            $1, $2, $3, 'claude', '{}'::jsonb, '', '{}'::jsonb, '[]'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '{}'::jsonb, 1
        )
        "#,
    )
    .bind(agent_id)
    .bind(project_id)
    .bind(format!("task-10-agent-{agent_id}"))
    .execute(pool)
    .await
    .expect("insert agent fixture");
}

async fn insert_session(
    pool: &PgPool,
    session_id: SessionId,
    agent_id: AgentId,
    project_id: &ProjectId,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
        VALUES ($1, $2, $3, 'idle')
        "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(project_id)
    .execute(pool)
    .await
    .expect("insert session fixture");
}

async fn insert_environment(
    pool: &PgPool,
    environment_id: EnvironmentId,
    project_id: &ProjectId,
    name: &str,
    archived: bool,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_environments
            (id, project_id, name, description, config, image_tag, image_version, archived_at)
        VALUES ($1, $2, $3, '', '{}'::jsonb, NULL, 1,
                CASE WHEN $4 THEN NOW() ELSE NULL END)
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .bind(name)
    .bind(archived)
    .execute(pool)
    .await
    .expect("insert environment fixture");
}

struct CredentialFixture<'a> {
    id: CredentialId,
    project_id: &'a ProjectId,
    kind: &'a str,
    provider: Option<&'a str>,
    protocol: Option<&'a str>,
    data: Value,
    group_id: Option<CredentialGroupId>,
    server_url: Option<&'a str>,
    scheme: Option<&'a str>,
    archived: bool,
    deleted: bool,
}

async fn insert_credential(pool: &PgPool, fixture: CredentialFixture<'_>) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_credentials (
            id, project_id, kind, name, provider, protocol, data, group_id,
            mcp_server_url, normalized_mcp_server_url, credential_type,
            archived_at, deleted_at, material_erased_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            CASE WHEN $13 THEN '{}'::jsonb ELSE $7 END, $8,
            $9, $10, $11,
            CASE WHEN $12 THEN NOW() ELSE NULL END,
            CASE WHEN $13 THEN NOW() ELSE NULL END,
            CASE WHEN $13 THEN NOW() ELSE NULL END
        )
        "#,
    )
    .bind(fixture.id)
    .bind(fixture.project_id)
    .bind(fixture.kind)
    .bind(format!("task-10-credential-{}", fixture.id))
    .bind(fixture.provider)
    .bind(fixture.protocol)
    .bind(fixture.data)
    .bind(fixture.group_id)
    .bind(fixture.server_url)
    .bind(fixture.server_url.map(kernel::mcp_url::normalize))
    .bind(fixture.scheme)
    .bind(fixture.archived)
    .bind(fixture.deleted)
    .execute(pool)
    .await
    .expect("insert credential fixture");
}

async fn insert_group(
    pool: &PgPool,
    group_id: CredentialGroupId,
    project_id: &ProjectId,
    archived: bool,
    deleted: bool,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_credential_groups
            (id, project_id, name, description, archived_at, deleted_at)
        VALUES (
            $1, $2, $3, '',
            CASE WHEN $4 THEN NOW() ELSE NULL END,
            CASE WHEN $5 THEN NOW() ELSE NULL END
        )
        "#,
    )
    .bind(group_id)
    .bind(project_id)
    .bind(format!("task-10-group-{group_id}"))
    .bind(archived)
    .bind(deleted)
    .execute(pool)
    .await
    .expect("insert credential group fixture");
}

async fn bind_group(pool: &PgPool, session_id: SessionId, group_id: CredentialGroupId) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id)
        VALUES ($1, $2)
        "#,
    )
    .bind(session_id)
    .bind(group_id)
    .execute(pool)
    .await
    .expect("bind session credential group fixture");
}

async fn cleanup(
    pool: &PgPool,
    agent_ids: &[AgentId],
    session_ids: &[SessionId],
    credential_ids: &[CredentialId],
    group_ids: &[CredentialGroupId],
    projects: &[(&ProjectId, &OrganizationId)],
) {
    for session_id in session_ids {
        let _ =
            sqlx::query("DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1")
                .bind(session_id)
                .execute(pool)
                .await;
        let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
    }
    for agent_id in agent_ids {
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(pool)
            .await;
    }
    for credential_id in credential_ids {
        let _ = sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
            .bind(credential_id)
            .execute(pool)
            .await;
    }
    for group_id in group_ids {
        let _ = sqlx::query("DELETE FROM joysafeter_credential_groups WHERE id = $1")
            .bind(group_id)
            .execute(pool)
            .await;
    }
    for (project_id, organization_id) in projects {
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(project_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
            .bind(organization_id)
            .execute(pool)
            .await;
    }
}

async fn runtime_config_state(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> (String, Option<String>, Option<DateTime<Utc>>) {
    sqlx::query_as(
        r#"
        SELECT runtime_config_status, runtime_config_last_reason, runtime_config_required_at
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(pool)
    .await
    .expect("load sandbox runtime configuration state")
}

async fn runtime_config_state_with_generation(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> (String, Option<String>, Option<DateTime<Utc>>, i64) {
    sqlx::query_as(
        r#"
        SELECT runtime_config_status, runtime_config_last_reason,
               runtime_config_required_at, runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(pool)
    .await
    .expect("load sandbox runtime configuration generation state")
}

async fn delete_sandbox(pool: &PgPool, sandbox_id: SandboxId) {
    sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(pool)
        .await
        .expect("delete sandbox fixture");
}

#[tokio::test]
async fn new_sandbox_creation_starts_runtime_configuration_ready() {
    let pool = test_pool().await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-new-{sandbox_id}");
    let config = json!({});

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3-new:latest",
        None,
        None,
        None,
        Some(&config),
    )
    .await
    .expect("create sandbox fixture");

    assert_eq!(
        runtime_config_state(&pool, sandbox_id).await,
        ("ready".to_string(), None, None)
    );
    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn session_bound_sandbox_insert_requires_captured_generation() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 7 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");

    let rejected_id = SandboxId::from_uuid(Uuid::now_v7());
    let rejected = queries::create_session_bound_sandbox_guarded(
        &pool,
        rejected_id,
        &format!("task-3c-rejected-{rejected_id}"),
        "test",
        "joysafeter/task-3c:latest",
        session_id,
        Some(project_id),
        None,
        Some(&json!({})),
        6,
    )
    .await;
    assert!(matches!(
        rejected,
        Err(RuntimeFreshnessError::GenerationChanged {
            expected: 6,
            actual: 7
        })
    ));
    assert!(queries::get_sandbox(&pool, rejected_id)
        .await
        .expect("query rejected sandbox")
        .is_none());

    let accepted_id = SandboxId::from_uuid(Uuid::now_v7());
    let accepted = queries::create_session_bound_sandbox_guarded(
        &pool,
        accepted_id,
        &format!("task-3c-accepted-{accepted_id}"),
        "test",
        "joysafeter/task-3c:latest",
        session_id,
        Some(project_id),
        None,
        Some(&json!({})),
        7,
    )
    .await
    .expect("matching generation inserts sandbox");
    assert_eq!(accepted.runtime_config_applied_generation, 7);

    delete_sandbox(&pool, accepted_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn task_attach_rejects_generation_change_after_resolution() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let task_id = joysafeter_orchestrator::ids::TaskId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 8 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("advance desired generation after resolution");
    queries::create_session_bound_sandbox_guarded(
        &pool,
        sandbox_id,
        &format!("task-3c-attach-{sandbox_id}"),
        "test",
        "joysafeter/task-3c:latest",
        session_id,
        Some(project_id),
        None,
        Some(&json!({})),
        8,
    )
    .await
    .expect("insert current sandbox");
    sqlx::query(
        r#"
        INSERT INTO joysafeter_tasks (
            id, agent_id, chat_session_id, status, prompt, output, timeout_sec,
            retry_count, max_retries, project_id
        )
        VALUES ($1, $2, $3, 'scheduling', 'task-3c attach', '', 7200, 0, 3, $4)
        "#,
    )
    .bind(task_id)
    .bind(agent_id)
    .bind(session_id)
    .bind(&project_id)
    .execute(&pool)
    .await
    .expect("insert scheduling task");

    let result = queries::attach_sandbox_to_task_guarded(
        &pool,
        task_id,
        sandbox_id,
        session_id,
        Some(project_id),
        7,
    )
    .await;
    assert!(matches!(
        result,
        Err(RuntimeFreshnessError::GenerationChanged {
            expected: 7,
            actual: 8
        })
    ));
    let attached: Option<SandboxId> =
        sqlx::query_scalar("SELECT sandbox_id FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load task attachment");
    assert!(attached.is_none());

    sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("delete task fixture");
    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn pool_reservation_is_freshness_neutral() {
    let pool = test_pool().await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-pool-{sandbox_id}");
    let image = format!("joysafeter/task-3-pool-{sandbox_id}:latest");
    let config = json!({});
    let required_at = "2026-08-21T11:22:33.123456Z"
        .parse::<DateTime<Utc>>()
        .expect("valid fixed timestamp");

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        &image,
        None,
        None,
        None,
        Some(&config),
    )
    .await
    .expect("create pooled sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'pooled',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'credential_rotated',
            runtime_config_required_at = $2,
            runtime_config_applied_generation = 41
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .bind(required_at)
    .execute(&pool)
    .await
    .expect("mark pooled sandbox restart required");

    let claimed = queries::claim_pool_sandbox(&pool, &image)
        .await
        .expect("claim pooled sandbox")
        .expect("pooled sandbox is claimable");

    assert_eq!(claimed.id, sandbox_id);
    assert_eq!(claimed.status, "provisioning");
    assert_eq!(claimed.runtime_config_status, "restart_required");
    assert_eq!(
        claimed.runtime_config_last_reason.as_deref(),
        Some("credential_rotated")
    );
    assert_eq!(claimed.runtime_config_required_at, Some(required_at));
    assert_eq!(claimed.runtime_config_applied_generation, 41);
    assert_eq!(
        runtime_config_state_with_generation(&pool, sandbox_id).await,
        (
            "restart_required".to_string(),
            Some("credential_rotated".to_string()),
            Some(required_at),
            41,
        )
    );
    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn guarded_stopped_restart_rejects_generation_mismatch_without_writing() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-stopped-{sandbox_id}");
    let config = json!({});
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 9 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3-stopped:latest",
        Some(session_id),
        Some(project_id),
        None,
        Some(&config),
    )
    .await
    .expect("create stopped sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'environment_changed',
            runtime_config_required_at = NOW(),
            runtime_config_applied_generation = 8
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("mark stopped sandbox restart required");

    let before = runtime_config_state_with_generation(&pool, sandbox_id).await;
    let result = queries::claim_stopped_sandbox_for_restart_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(project_id),
        8,
    )
    .await;
    assert!(matches!(
        result,
        Err(RuntimeFreshnessError::GenerationChanged {
            expected: 8,
            actual: 9
        })
    ));
    assert_eq!(
        runtime_config_state_with_generation(&pool, sandbox_id).await,
        before
    );
    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn guarded_stopped_restart_rejects_inactive_or_cross_project_session_without_writing() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let other_project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let other_organization_id =
        insert_project(&pool, &format!("{unique}-other"), &other_project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3c-stopped-validation-{sandbox_id}");
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 10 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");
    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3c-stopped-validation:latest",
        Some(session_id),
        Some(project_id),
        None,
        Some(&json!({})),
    )
    .await
    .expect("create stopped sandbox fixture");
    sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("mark sandbox stopped");
    let before = runtime_config_state_with_generation(&pool, sandbox_id).await;

    let wrong_project = queries::claim_stopped_sandbox_for_restart_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(other_project_id),
        10,
    )
    .await;
    assert!(matches!(
        wrong_project,
        Err(RuntimeFreshnessError::SessionBindingInvalid {
            reason: "project mismatch",
            ..
        })
    ));

    sqlx::query("UPDATE joysafeter_sessions SET status = 'terminated' WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("terminate session");
    let inactive = queries::claim_stopped_sandbox_for_restart_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(project_id),
        10,
    )
    .await;
    assert!(matches!(
        inactive,
        Err(RuntimeFreshnessError::SessionBindingInvalid {
            reason: "inactive session",
            ..
        })
    ));
    assert_eq!(
        runtime_config_state_with_generation(&pool, sandbox_id).await,
        before
    );

    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[
            (&project_id, &organization_id),
            (&other_project_id, &other_organization_id),
        ],
    )
    .await;
}

#[tokio::test]
async fn stopped_restart_compensation_restores_exact_runtime_configuration() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-stopped-restore-{sandbox_id}");
    let config = json!({});
    let required_at = "2026-08-21T12:34:56.123456Z"
        .parse::<DateTime<Utc>>()
        .expect("valid fixed timestamp");
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 12 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3-stopped-restore:latest",
        Some(session_id),
        Some(project_id),
        None,
        Some(&config),
    )
    .await
    .expect("create stopped sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'credential_rotated_before_restart',
            runtime_config_required_at = $2,
            runtime_config_applied_generation = 11
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .bind(required_at)
    .execute(&pool)
    .await
    .expect("mark stopped sandbox restart required");

    let claim = queries::claim_stopped_sandbox_for_restart_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(project_id),
        12,
    )
    .await
    .expect("claim stopped sandbox for restart");
    assert_eq!(claim.previous_runtime_config_applied_generation, 11);
    assert_eq!(claim.claimed_runtime_config_applied_generation, 12);
    assert!(
        queries::restore_stopped_sandbox_after_restart_start_failure_guarded(
            &pool,
            sandbox_id,
            &external_id,
            &claim,
        )
        .await
        .expect("restore stopped sandbox after restart failure")
    );

    let restored: (String, String, Option<String>, Option<DateTime<Utc>>, i64) = sqlx::query_as(
        r#"
        SELECT status, runtime_config_status, runtime_config_last_reason,
               runtime_config_required_at, runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load restored sandbox state");
    assert_eq!(
        restored,
        (
            "stopped".to_string(),
            "restart_required".to_string(),
            Some("credential_rotated_before_restart".to_string()),
            Some(required_at),
            11,
        )
    );
    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn stopped_restart_compensation_does_not_clobber_newer_applied_generation() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-stopped-no-clobber-{sandbox_id}");
    let config = json!({});
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 20 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3-stopped-no-clobber:latest",
        Some(session_id),
        Some(project_id),
        None,
        Some(&config),
    )
    .await
    .expect("create stopped sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'older_marker',
            runtime_config_required_at = '2026-08-21T12:00:00Z'::timestamptz,
            runtime_config_applied_generation = 19
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("mark stopped sandbox restart required");

    let claim = queries::claim_stopped_sandbox_for_restart_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(project_id),
        20,
    )
    .await
    .expect("claim stopped sandbox for restart");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET runtime_config_applied_generation = 21
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("write newer applied generation");

    assert!(
        !queries::restore_stopped_sandbox_after_restart_start_failure_guarded(
            &pool,
            sandbox_id,
            &external_id,
            &claim,
        )
        .await
        .expect("restore stopped sandbox after restart failure")
    );

    let restored: (String, String, Option<String>, Option<DateTime<Utc>>, i64) = sqlx::query_as(
        r#"
        SELECT status, runtime_config_status, runtime_config_last_reason,
               runtime_config_required_at, runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load no-clobber sandbox state");
    assert_eq!(
        restored,
        (
            "provisioning".to_string(),
            "ready".to_string(),
            None,
            None,
            21,
        )
    );
    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn guarded_pool_activation_attaches_complete_freshness_state_and_cleanup_claims_exact_token()
{
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3c-pool-activation-{sandbox_id}");
    let image = format!("joysafeter/task-3c-pool-activation-{sandbox_id}:latest");
    let original_config = json!({
        "provisioning": {"stage": "pool_warm"},
        "fingerprint": {"image": "old"}
    });
    let fingerprint = json!({"image": image, "engine_kind": "claude", "networking": null});
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 31 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");
    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        &image,
        None,
        None,
        None,
        Some(&original_config),
    )
    .await
    .expect("create pooled sandbox fixture");
    sqlx::query("UPDATE joysafeter_sandboxes SET status = 'pooled' WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("mark sandbox pooled");
    queries::claim_pool_sandbox(&pool, &image)
        .await
        .expect("reserve pooled sandbox")
        .expect("pooled sandbox is reservable");

    let attachment = queries::activate_reserved_pool_sandbox_guarded(
        &pool,
        sandbox_id,
        &external_id,
        session_id,
        Some(project_id),
        &fingerprint,
        31,
    )
    .await
    .expect("activate reserved pool sandbox");
    let attached: (
        String,
        Option<SessionId>,
        Option<ProjectId>,
        Value,
        String,
        Option<String>,
        Option<DateTime<Utc>>,
        i64,
    ) = sqlx::query_as(
        r#"
        SELECT status, chat_session_id, project_id, config->'fingerprint',
               runtime_config_status, runtime_config_last_reason,
               runtime_config_required_at, runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load attached pool sandbox");
    assert_eq!(
        attached,
        (
            "provisioning".to_string(),
            Some(session_id),
            Some(project_id),
            fingerprint,
            "ready".to_string(),
            None,
            None,
            31,
        )
    );

    sqlx::query(
        "UPDATE joysafeter_sandboxes SET runtime_config_applied_generation = 32 WHERE id = $1",
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("advance applied generation after pool attachment");
    assert!(!queries::claim_attached_pool_sandbox_for_cleanup_guarded(
        &pool,
        &attachment,
        "stale pool attachment token",
    )
    .await
    .expect("stale attachment token is a zero-write cleanup claim"));
    let preserved: (String, Option<SessionId>, String, i64) = sqlx::query_as(
        r#"
        SELECT status, chat_session_id, runtime_config_status,
               runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load pool sandbox after stale cleanup token");
    assert_eq!(
        preserved,
        (
            "provisioning".to_string(),
            Some(session_id),
            "ready".to_string(),
            32,
        )
    );
    sqlx::query(
        "UPDATE joysafeter_sandboxes SET runtime_config_applied_generation = 31 WHERE id = $1",
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("restore claimed applied generation for exact cleanup token");

    assert!(queries::claim_attached_pool_sandbox_for_cleanup_guarded(
        &pool,
        &attachment,
        "pool activation failed",
    )
    .await
    .expect("claim attached pool sandbox for cleanup"));
    let cleanup_state: (String, Option<SessionId>, String, Option<String>, i64) = sqlx::query_as(
        r#"
        SELECT status, chat_session_id, runtime_config_status,
               runtime_config_last_reason, runtime_config_applied_generation
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load attached pool cleanup state");
    assert_eq!(
        cleanup_state,
        (
            "stopping".to_string(),
            Some(session_id),
            "restart_required".to_string(),
            Some("pool activation failed".to_string()),
            31,
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn guarded_pool_activation_waits_for_session_before_locking_sandbox() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3c-pool-mutation-first-{sandbox_id}");
    let image = format!("joysafeter/task-3c-pool-mutation-first-{sandbox_id}:latest");
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 51 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");
    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        &image,
        None,
        None,
        None,
        Some(&json!({"provisioning": {"stage": "pool_warm"}})),
    )
    .await
    .expect("create pooled sandbox fixture");
    sqlx::query("UPDATE joysafeter_sandboxes SET status = 'pooled' WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("mark sandbox pooled");
    queries::claim_pool_sandbox(&pool, &image)
        .await
        .expect("reserve pooled sandbox")
        .expect("pooled sandbox is reservable");

    let mut mutation = pool.begin().await.expect("begin session mutation");
    sqlx::query("SELECT id FROM joysafeter_sessions WHERE id = $1 FOR UPDATE")
        .bind(session_id)
        .execute(&mut *mutation)
        .await
        .expect("lock session before activation");
    let application_name = format!("task3c-pool-mutation-first-{unique}");
    let writer_pool = named_single_connection_pool(&application_name).await;
    let project_for_writer = project_id.clone();
    let external_for_writer = external_id.clone();
    let writer = tokio::spawn(async move {
        queries::activate_reserved_pool_sandbox_guarded(
            &writer_pool,
            sandbox_id,
            &external_for_writer,
            session_id,
            Some(project_for_writer),
            &json!({"image": "guarded"}),
            51,
        )
        .await
    });
    wait_for_database_lock(&pool, &application_name).await;

    let sandbox_lock_available: bool = sqlx::query_scalar(
        r#"
        SELECT EXISTS (
            SELECT 1 FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE NOWAIT
        )
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("sandbox must remain unlocked while activation waits for session");
    assert!(sandbox_lock_available);
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 52 WHERE id = $1")
        .bind(session_id)
        .execute(&mut *mutation)
        .await
        .expect("advance generation while holding session lock");
    mutation.commit().await.expect("commit session mutation");

    let result = tokio::time::timeout(Duration::from_secs(5), writer)
        .await
        .expect("activation completes after session unlock")
        .expect("join activation task");
    assert!(matches!(
        result,
        Err(RuntimeFreshnessError::GenerationChanged {
            expected: 51,
            actual: 52
        })
    ));
    let ownership: (Option<SessionId>, Option<String>) = sqlx::query_as(
        "SELECT chat_session_id, project_id FROM joysafeter_sandboxes WHERE id = $1",
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load rejected pool activation ownership");
    assert_eq!(ownership, (None, None));

    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn guarded_stopped_restart_holds_session_lock_while_waiting_for_sandbox() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3c-stopped-writer-first-{sandbox_id}");
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    sqlx::query("UPDATE joysafeter_sessions SET runtime_config_generation = 61 WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await
        .expect("set desired generation");
    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3c-stopped-writer-first:latest",
        Some(session_id),
        Some(project_id),
        None,
        Some(&json!({})),
    )
    .await
    .expect("create stopped sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'stopped',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'credential_rotated',
            runtime_config_required_at = NOW(),
            runtime_config_applied_generation = 60
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("mark stopped sandbox stale");

    let mut sandbox_blocker = pool.begin().await.expect("begin sandbox blocker");
    sqlx::query("SELECT id FROM joysafeter_sandboxes WHERE id = $1 FOR UPDATE")
        .bind(sandbox_id)
        .execute(&mut *sandbox_blocker)
        .await
        .expect("lock sandbox before guarded writer");
    let application_name = format!("task3c-stopped-writer-first-{unique}");
    let writer_pool = named_single_connection_pool(&application_name).await;
    let project_for_writer = project_id.clone();
    let external_for_writer = external_id.clone();
    let writer = tokio::spawn(async move {
        queries::claim_stopped_sandbox_for_restart_guarded(
            &writer_pool,
            sandbox_id,
            &external_for_writer,
            session_id,
            Some(project_for_writer),
            61,
        )
        .await
    });
    wait_for_database_lock(&pool, &application_name).await;

    let session_probe =
        sqlx::query("SELECT id FROM joysafeter_sessions WHERE id = $1 FOR UPDATE NOWAIT")
            .bind(session_id)
            .execute(&pool)
            .await;
    assert_eq!(
        session_probe
            .expect_err("guarded writer must hold the session lock before waiting on sandbox")
            .as_database_error()
            .and_then(|error| error.code())
            .as_deref(),
        Some("55P03")
    );
    sandbox_blocker
        .commit()
        .await
        .expect("release sandbox lock");
    let claim = tokio::time::timeout(Duration::from_secs(5), writer)
        .await
        .expect("stopped claim completes after sandbox unlock")
        .expect("join stopped claim task")
        .expect("guarded stopped claim succeeds");
    assert_eq!(claim.claimed_runtime_config_applied_generation, 61);

    delete_sandbox(&pool, sandbox_id).await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn ordinary_running_idle_transitions_preserve_restart_required_runtime_configuration() {
    let pool = test_pool().await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let external_id = format!("task-3-transitions-{sandbox_id}");
    let config = json!({});

    queries::create_sandbox(
        &pool,
        sandbox_id,
        &external_id,
        "test",
        "joysafeter/task-3-transitions:latest",
        None,
        None,
        None,
        Some(&config),
    )
    .await
    .expect("create transition sandbox fixture");
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'idle',
            runtime_config_status = 'restart_required',
            runtime_config_last_reason = 'credential_rotated',
            runtime_config_required_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("mark idle sandbox restart required");
    let expected = runtime_config_state(&pool, sandbox_id).await;

    assert!(
        queries::transition_sandbox_cas(&pool, sandbox_id, "idle", "running")
            .await
            .expect("transition sandbox to running")
    );
    assert!(
        queries::transition_sandbox_cas(&pool, sandbox_id, "running", "idle")
            .await
            .expect("transition sandbox to idle")
    );

    assert_eq!(runtime_config_state(&pool, sandbox_id).await, expected);
    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn store_and_usage_resolvers_cover_model_and_service_happy_paths() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_raw = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_raw).await;
    let project_id = project_raw;
    let model_id = CredentialId::from_uuid(Uuid::now_v7());
    let service_id = CredentialId::from_uuid(Uuid::now_v7());

    insert_credential(
        &pool,
        CredentialFixture {
            id: model_id,
            project_id: &project_raw,
            kind: "model",
            provider: Some("anthropic"),
            protocol: Some("anthropic_messages"),
            data: json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            group_id: None,
            server_url: None,
            scheme: None,
            archived: false,
            deleted: false,
        },
    )
    .await;
    insert_credential(
        &pool,
        CredentialFixture {
            id: service_id,
            project_id: &project_raw,
            kind: "service",
            provider: None,
            protocol: None,
            data: json!({"API_TOKEN": ENCRYPTED_HELLO_WORLD}),
            group_id: None,
            server_url: None,
            scheme: None,
            archived: false,
            deleted: false,
        },
    )
    .await;

    let store = test_store(pool.clone());
    let model = store
        .get_active(&project_id, model_id)
        .await
        .expect("active model credential");
    let resolved_model =
        resolve_model_credential(&model, "claude").expect("catalog-compatible model credential");
    assert_eq!(resolved_model.protocol_id, "anthropic_messages");
    assert_eq!(resolved_model.material["ANTHROPIC_API_KEY"], "hello-world");

    let service = store
        .get_active(&project_id, service_id)
        .await
        .expect("active service credential");
    let injected = resolve_service_credential(&service, ServiceUsage::EnvironmentInjection)
        .expect("explicit environment injection");
    assert_eq!(
        injected,
        ResolvedServiceCredential::Environment(json!({"API_TOKEN": "hello-world"}))
    );
    let egress = resolve_service_credential(
        &service,
        ServiceUsage::HttpEgressField { field: "API_TOKEN" },
    )
    .expect("HTTP egress field selection");
    assert_eq!(
        egress,
        ResolvedServiceCredential::HttpEgressField("hello-world".to_string())
    );

    for formatted in [
        format!("{model:?}"),
        format!("{resolved_model:?}"),
        format!("{service:?}"),
        format!("{injected:?}"),
        format!("{egress:?}"),
    ] {
        assert!(!formatted.contains("hello-world"), "{formatted}");
        assert!(formatted.contains("redacted"), "{formatted}");
    }

    cleanup(
        &pool,
        &[],
        &[],
        &[model_id, service_id],
        &[],
        &[(&project_raw, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn persisted_broken_bindings_fail_closed_while_only_absence_is_not_bound() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_a_raw = ProjectId::new();
    let project_b_raw = ProjectId::new();
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a_raw).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b_raw).await;
    let project_a = project_a_raw;
    let archived_id = CredentialId::from_uuid(Uuid::now_v7());
    let deleted_id = CredentialId::from_uuid(Uuid::now_v7());
    let cross_project_id = CredentialId::from_uuid(Uuid::now_v7());
    let missing_field_id = CredentialId::from_uuid(Uuid::now_v7());
    let malformed_material_id = CredentialId::from_uuid(Uuid::now_v7());
    let malformed_envelope_id = CredentialId::from_uuid(Uuid::now_v7());

    for (id, project_id, data, archived, deleted) in [
        (
            archived_id,
            &project_a_raw,
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            true,
            false,
        ),
        (
            deleted_id,
            &project_a_raw,
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            false,
            true,
        ),
        (
            cross_project_id,
            &project_b_raw,
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            false,
            false,
        ),
        (missing_field_id, &project_a_raw, json!({}), false, false),
        (
            malformed_material_id,
            &project_a_raw,
            json!([ENCRYPTED_HELLO_WORLD]),
            false,
            false,
        ),
        (
            malformed_envelope_id,
            &project_a_raw,
            json!({"ANTHROPIC_API_KEY": "enc:v1:not-base64"}),
            false,
            false,
        ),
    ] {
        insert_credential(
            &pool,
            CredentialFixture {
                id,
                project_id,
                kind: "model",
                provider: Some("anthropic"),
                protocol: Some("anthropic_messages"),
                data,
                group_id: None,
                server_url: None,
                scheme: None,
                archived,
                deleted,
            },
        )
        .await;
    }

    assert_eq!(
        require_bound_credential_id(None),
        Err(CredentialRuntimeError::NotBound)
    );

    let store = test_store(pool.clone());
    assert_eq!(
        store.get_active(&project_a, archived_id).await.unwrap_err(),
        CredentialRuntimeError::Archived
    );
    assert_eq!(
        store.get_active(&project_a, deleted_id).await.unwrap_err(),
        CredentialRuntimeError::NotFound
    );
    assert_eq!(
        store
            .get_active(&project_a, cross_project_id)
            .await
            .unwrap_err(),
        CredentialRuntimeError::ProjectMismatch
    );
    assert_eq!(
        store
            .get_active(&project_a, CredentialId::from_uuid(Uuid::now_v7()))
            .await
            .unwrap_err(),
        CredentialRuntimeError::NotFound
    );

    let missing_field = store
        .get_active(&project_a, missing_field_id)
        .await
        .expect("record shape is valid before usage validation");
    assert_eq!(
        resolve_model_credential(&missing_field, "claude").unwrap_err(),
        CredentialRuntimeError::FieldMissing
    );
    assert_eq!(
        store
            .get_active(&project_a, malformed_material_id)
            .await
            .unwrap_err(),
        CredentialRuntimeError::CorruptRecord
    );
    assert_eq!(
        store
            .get_active(&project_a, malformed_envelope_id)
            .await
            .unwrap_err(),
        CredentialRuntimeError::EnvelopeInvalid
    );

    cleanup(
        &pool,
        &[],
        &[],
        &[
            archived_id,
            deleted_id,
            cross_project_id,
            missing_field_id,
            malformed_material_id,
            malformed_envelope_id,
        ],
        &[],
        &[(&project_a_raw, &org_a), (&project_b_raw, &org_b)],
    )
    .await;
}

#[tokio::test]
async fn session_mcp_members_prove_project_and_state_and_fail_as_one_usage() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_a_raw = ProjectId::new();
    let project_b_raw = ProjectId::new();
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a_raw).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b_raw).await;
    let project_a = project_a_raw;
    let agent_a = AgentId::from_uuid(Uuid::now_v7());
    let agent_b = AgentId::from_uuid(Uuid::now_v7());
    let session_a = SessionId::from_uuid(Uuid::now_v7());
    let session_b = SessionId::from_uuid(Uuid::now_v7());
    insert_agent(&pool, agent_a, &project_a_raw).await;
    insert_agent(&pool, agent_b, &project_b_raw).await;
    insert_session(&pool, session_a, agent_a, &project_a_raw).await;
    insert_session(&pool, session_b, agent_b, &project_b_raw).await;

    let group_a = CredentialGroupId::from_uuid(Uuid::now_v7());
    let group_b = CredentialGroupId::from_uuid(Uuid::now_v7());
    insert_group(&pool, group_a, &project_a_raw, false, false).await;
    insert_group(&pool, group_b, &project_b_raw, false, false).await;
    bind_group(&pool, session_a, group_a).await;
    bind_group(&pool, session_b, group_b).await;

    let bearer_id = CredentialId::from_uuid(Uuid::now_v7());
    let corrupt_id = CredentialId::from_uuid(Uuid::now_v7());
    let unknown_scheme_id = CredentialId::from_uuid(Uuid::now_v7());
    for (id, group_id, project_id, url, scheme, token) in [
        (
            bearer_id,
            group_a,
            &project_a_raw,
            "https://mcp-a.example/api",
            "static_bearer",
            ENCRYPTED_HELLO_WORLD,
        ),
        (
            corrupt_id,
            group_a,
            &project_a_raw,
            "https://mcp-b.example/api",
            "static_bearer",
            "enc:v1:not-base64",
        ),
        (
            unknown_scheme_id,
            group_b,
            &project_b_raw,
            "https://mcp-c.example/api",
            "future_scheme",
            ENCRYPTED_HELLO_WORLD,
        ),
    ] {
        insert_credential(
            &pool,
            CredentialFixture {
                id,
                project_id,
                kind: "mcp",
                provider: None,
                protocol: None,
                data: json!({"token_value": token}),
                group_id: Some(group_id),
                server_url: Some(url),
                scheme: Some(scheme),
                archived: false,
                deleted: false,
            },
        )
        .await;
    }

    let store = test_store(pool.clone());
    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_a)
            .await
            .unwrap_err(),
        CredentialRuntimeError::EnvelopeInvalid,
        "one corrupt persisted member must fail the whole MCP usage"
    );

    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
        .bind(corrupt_id)
        .execute(&pool)
        .await
        .expect("remove corrupt member fixture");
    let members = store
        .load_session_mcp_members(&project_a, session_a)
        .await
        .expect("active same-project MCP members");
    let resolved = resolve_mcp_members(&members).expect("runnable MCP auth");
    assert_eq!(resolved.len(), 1);
    assert_eq!(resolved[0].auth_scheme, "static_bearer");
    assert_eq!(resolved[0].injection.header_name, "authorization");
    assert_eq!(resolved[0].injection.header_value, "Bearer hello-world");
    assert_eq!(
        resolved[0].injection.remove_headers,
        vec!["authorization", "x-api-key"]
    );
    let resolved_debug = format!("{:?}", resolved[0]);
    assert!(!resolved_debug.contains("hello-world"), "{resolved_debug}");
    assert!(resolved_debug.contains("redacted"), "{resolved_debug}");

    bind_group(&pool, session_a, group_b).await;
    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_a)
            .await
            .unwrap_err(),
        CredentialRuntimeError::ProjectMismatch,
        "a persisted cross-project Session association must fail closed"
    );
    sqlx::query(
        "DELETE FROM joysafeter_session_credential_groups WHERE session_id = $1 AND credential_group_id = $2",
    )
    .bind(session_a)
    .bind(group_b)
    .execute(&pool)
    .await
    .expect("remove cross-project association fixture");

    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_b)
            .await
            .unwrap_err(),
        CredentialRuntimeError::ProjectMismatch
    );
    assert_eq!(
        store
            .load_session_mcp_members(&project_b_raw, session_b,)
            .await
            .unwrap_err(),
        CredentialRuntimeError::CorruptRecord
    );
    sqlx::query("UPDATE joysafeter_credentials SET credential_type = 'oauth' WHERE id = $1")
        .bind(unknown_scheme_id)
        .execute(&pool)
        .await
        .expect("set known disabled MCP scheme");
    assert_eq!(
        store
            .load_session_mcp_members(&project_b_raw, session_b,)
            .await
            .unwrap_err(),
        CredentialRuntimeError::UnsupportedScheme
    );

    sqlx::query("UPDATE joysafeter_credential_groups SET archived_at = NOW() WHERE id = $1")
        .bind(group_a)
        .execute(&pool)
        .await
        .expect("archive group fixture");
    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_a)
            .await
            .unwrap_err(),
        CredentialRuntimeError::Archived
    );
    sqlx::query(
        "UPDATE joysafeter_credential_groups SET archived_at = NULL, deleted_at = NOW() WHERE id = $1",
    )
    .bind(group_a)
    .execute(&pool)
    .await
    .expect("delete group fixture");
    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_a)
            .await
            .unwrap_err(),
        CredentialRuntimeError::NotFound
    );
    sqlx::query("UPDATE joysafeter_credential_groups SET deleted_at = NULL WHERE id = $1")
        .bind(group_a)
        .execute(&pool)
        .await
        .expect("restore group fixture");
    sqlx::query("UPDATE joysafeter_sessions SET archived_at = NOW() WHERE id = $1")
        .bind(session_a)
        .execute(&pool)
        .await
        .expect("archive session fixture");
    assert_eq!(
        store
            .load_session_mcp_members(&project_a, session_a)
            .await
            .unwrap_err(),
        CredentialRuntimeError::Archived
    );

    cleanup(
        &pool,
        &[agent_a, agent_b],
        &[session_a, session_b],
        &[bearer_id, corrupt_id, unknown_scheme_id],
        &[group_a, group_b],
        &[(&project_a_raw, &org_a), (&project_b_raw, &org_b)],
    )
    .await;
}

#[tokio::test]
async fn mcp_member_material_selection_preserves_scheme_specific_fields() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let agent_id = AgentId::new();
    let session_id = SessionId::new();
    let group_id = CredentialGroupId::new();
    let custom_header_id = CredentialId::new();
    let api_key_id = CredentialId::new();

    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    insert_group(&pool, group_id, &project_id, false, false).await;
    bind_group(&pool, session_id, group_id).await;

    insert_credential(
        &pool,
        CredentialFixture {
            id: custom_header_id,
            project_id: &project_id,
            kind: "mcp",
            provider: None,
            protocol: None,
            data: json!({
                "token_value": ENCRYPTED_HELLO_WORLD,
                "header_name": ENCRYPTED_HELLO_WORLD,
                "value_prefix": ENCRYPTED_HELLO_WORLD,
                "unrelated": "invalid-envelope",
            }),
            group_id: Some(group_id),
            server_url: Some("https://custom-header.example/mcp"),
            scheme: Some("custom_header"),
            archived: false,
            deleted: false,
        },
    )
    .await;
    insert_credential(
        &pool,
        CredentialFixture {
            id: api_key_id,
            project_id: &project_id,
            kind: "mcp",
            provider: None,
            protocol: None,
            data: json!({
                "token_value": ENCRYPTED_HELLO_WORLD,
                "header_name": ENCRYPTED_HELLO_WORLD,
                "unrelated": "invalid-envelope",
            }),
            group_id: Some(group_id),
            server_url: Some("https://api-key.example/mcp"),
            scheme: Some("header_api_key"),
            archived: false,
            deleted: false,
        },
    )
    .await;
    let store = test_store(pool.clone());
    store
        .load_session_mcp_member_metadata(&project_id, session_id)
        .await
        .expect("load scheme-specific MCP metadata");
    let members = store
        .load_session_mcp_members(&project_id, session_id)
        .await
        .expect("load scheme-specific MCP material");
    let resolved = resolve_mcp_members(&members).expect("resolve scheme-specific MCP headers");

    let custom_header = resolved
        .iter()
        .find(|credential| credential.auth_scheme == "custom_header")
        .expect("custom header credential");
    assert_eq!(custom_header.injection.header_name, "hello-world");
    assert_eq!(
        custom_header.injection.header_value,
        "hello-worldhello-world"
    );

    let api_key = resolved
        .iter()
        .find(|credential| credential.auth_scheme == "header_api_key")
        .expect("header API key credential");
    assert_eq!(api_key.injection.header_name, "hello-world");
    assert_eq!(api_key.injection.header_value, "hello-world");

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[custom_header_id, api_key_id],
        &[group_id],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn mcp_urls_are_canonical_unique_and_stably_ordered() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_raw = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_raw).await;
    let project_id = project_raw;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_agent(&pool, agent_id, &project_raw).await;
    insert_session(&pool, session_id, agent_id, &project_raw).await;

    let group_a = CredentialGroupId::from_uuid(Uuid::now_v7());
    let group_b = CredentialGroupId::from_uuid(Uuid::now_v7());
    insert_group(&pool, group_a, &project_raw, false, false).await;
    insert_group(&pool, group_b, &project_raw, false, false).await;
    bind_group(&pool, session_id, group_b).await;
    bind_group(&pool, session_id, group_a).await;

    let malformed_id = CredentialId::from_uuid(Uuid::now_v7());
    insert_credential(
        &pool,
        CredentialFixture {
            id: malformed_id,
            project_id: &project_raw,
            kind: "mcp",
            provider: None,
            protocol: None,
            data: json!({"token_value": ENCRYPTED_HELLO_WORLD}),
            group_id: Some(group_a),
            server_url: Some("not a runnable url"),
            scheme: Some("static_bearer"),
            archived: false,
            deleted: false,
        },
    )
    .await;
    let store = test_store(pool.clone());
    assert_eq!(
        store
            .load_session_mcp_members(&project_id, session_id)
            .await
            .unwrap_err(),
        CredentialRuntimeError::CorruptRecord
    );
    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
        .bind(malformed_id)
        .execute(&pool)
        .await
        .expect("remove malformed URL fixture");

    let mismatch_id = CredentialId::from_uuid(Uuid::now_v7());
    insert_credential(
        &pool,
        CredentialFixture {
            id: mismatch_id,
            project_id: &project_raw,
            kind: "mcp",
            provider: None,
            protocol: None,
            data: json!({"token_value": ENCRYPTED_HELLO_WORLD}),
            group_id: Some(group_a),
            server_url: Some("https://trusted.example/mcp"),
            scheme: Some("static_bearer"),
            archived: false,
            deleted: false,
        },
    )
    .await;
    sqlx::query(
        "UPDATE joysafeter_credentials SET normalized_mcp_server_url = 'https://attacker.example/mcp' WHERE id = $1",
    )
    .bind(mismatch_id)
    .execute(&pool)
    .await
    .expect("corrupt persisted normalized URL");
    assert_eq!(
        store
            .load_session_mcp_members(&project_id, session_id)
            .await
            .unwrap_err(),
        CredentialRuntimeError::CorruptRecord
    );
    sqlx::query("DELETE FROM joysafeter_credentials WHERE id = $1")
        .bind(mismatch_id)
        .execute(&pool)
        .await
        .expect("remove mismatched URL fixture");

    let credential_ids = [
        CredentialId::from_uuid(Uuid::now_v7()),
        CredentialId::from_uuid(Uuid::now_v7()),
        CredentialId::from_uuid(Uuid::now_v7()),
    ];
    for (id, group_id, url) in [
        (credential_ids[0], group_b, "https://dup.example:443/mcp"),
        (credential_ids[1], group_a, "https://unique.example/mcp"),
        (credential_ids[2], group_a, "https://dup.example/mcp/"),
    ] {
        insert_credential(
            &pool,
            CredentialFixture {
                id,
                project_id: &project_raw,
                kind: "mcp",
                provider: None,
                protocol: None,
                data: json!({"token_value": ENCRYPTED_HELLO_WORLD}),
                group_id: Some(group_id),
                server_url: Some(url),
                scheme: Some("static_bearer"),
                archived: false,
                deleted: false,
            },
        )
        .await;
    }

    let members = store
        .load_session_mcp_members(&project_id, session_id)
        .await
        .expect("canonical active MCP members");
    let actual_order = members
        .iter()
        .map(|member| (member.group_id.to_string(), member.id.to_string()))
        .collect::<Vec<_>>();
    let mut expected_order = actual_order.clone();
    expected_order.sort();
    assert_eq!(
        actual_order, expected_order,
        "MCP member order must be stable"
    );
    assert_eq!(
        resolve_mcp_members(&members).unwrap_err(),
        CredentialRuntimeError::CorruptRecord,
        "duplicate canonical URLs across Groups must fail the whole usage"
    );

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[
            malformed_id,
            mismatch_id,
            credential_ids[0],
            credential_ids[1],
            credential_ids[2],
        ],
        &[group_a, group_b],
        &[(&project_raw, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn credential_access_audit_deduplicates_success_and_preserves_failures() {
    let pool = test_pool().await;
    let writer = CredentialAccessAuditWriter::new(pool.clone());
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let entry = CredentialAccessAuditEntry {
        id: CredentialAccessAuditId::new(),
        project_id: ProjectId::from_uuid(Uuid::from_u128(1)),
        credential_id,
        credential_kind:
            joysafeter_orchestrator::kernel::credentials::record::CredentialKind::Service,
        usage: CredentialAccessUsage::HttpEgress,
        consumer_type: "sandbox".to_string(),
        consumer_id: None,
        principal_type: "system".to_string(),
        principal_id: "runtime".to_string(),
        session_id: Some(session_id),
        task_id: Some(task_id),
        generation: Some(7),
        field_names: ["TOKEN".to_string()].into_iter().collect(),
    };

    assert!(writer.append_success(&entry).await.unwrap());
    assert!(!writer.append_success(&entry).await.unwrap());

    let next_generation = CredentialAccessAuditEntry {
        id: CredentialAccessAuditId::new(),
        generation: Some(8),
        ..entry.clone()
    };
    assert!(writer.append_success(&next_generation).await.unwrap());
    let first_failure = CredentialAccessAuditEntry {
        id: CredentialAccessAuditId::new(),
        ..entry.clone()
    };
    assert!(writer
        .append_failure(
            &first_failure,
            CredentialAccessFailure::Failed,
            "envelope_invalid",
        )
        .await
        .unwrap());
    let second_failure = CredentialAccessAuditEntry {
        id: CredentialAccessAuditId::new(),
        ..entry.clone()
    };
    assert!(writer
        .append_failure(
            &second_failure,
            CredentialAccessFailure::Failed,
            "envelope_invalid",
        )
        .await
        .unwrap());

    let rows = sqlx::query_as::<_, (String, i64, serde_json::Value, String, Option<String>)>(
        r#"
        SELECT result, generation, field_names, principal_id, error_code
        FROM joysafeter_credential_access_audits
        WHERE credential_id = $1
        ORDER BY created_at, id
        "#,
    )
    .bind(credential_id)
    .fetch_all(&pool)
    .await
    .expect("load credential access audits");

    assert_eq!(rows.len(), 4);
    assert_eq!(
        rows.iter()
            .filter(|(result, ..)| result == "success")
            .count(),
        2
    );
    assert_eq!(
        rows.iter()
            .filter(|(result, ..)| result == "failed")
            .count(),
        2
    );
    assert!(rows.iter().all(|(_, _, fields, principal_id, _)| {
        fields == &json!(["TOKEN"]) && principal_id == "runtime"
    }));
    assert!(rows.iter().all(|(_, _, _, _, error_code)| {
        error_code
            .as_deref()
            .is_none_or(|code| code == "envelope_invalid")
    }));
}

#[tokio::test]
async fn credential_material_access_audits_success_and_ciphertext_failure_without_values() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_raw = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_raw).await;
    let project_id = project_raw;
    let model_id = CredentialId::from_uuid(Uuid::now_v7());
    let metadata_only_model_id = CredentialId::from_uuid(Uuid::now_v7());
    let model_name_only_id = CredentialId::from_uuid(Uuid::now_v7());
    let valid_id = CredentialId::from_uuid(Uuid::now_v7());
    let invalid_id = CredentialId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());

    insert_credential(
        &pool,
        CredentialFixture {
            id: model_id,
            project_id: &project_raw,
            kind: "model",
            provider: Some("anthropic"),
            protocol: Some("anthropic_messages"),
            data: json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            group_id: None,
            server_url: None,
            scheme: None,
            archived: false,
            deleted: false,
        },
    )
    .await;
    for (id, model_value) in [
        (metadata_only_model_id, "invalid-model-envelope"),
        (model_name_only_id, ENCRYPTED_HELLO_WORLD),
    ] {
        insert_credential(
            &pool,
            CredentialFixture {
                id,
                project_id: &project_raw,
                kind: "model",
                provider: Some("anthropic"),
                protocol: Some("anthropic_messages"),
                data: json!({
                    "ANTHROPIC_API_KEY": "invalid-api-key-envelope",
                    "ANTHROPIC_MODEL": model_value
                }),
                group_id: None,
                server_url: None,
                scheme: None,
                archived: false,
                deleted: false,
            },
        )
        .await;
    }

    for (id, token) in [
        (valid_id, ENCRYPTED_HELLO_WORLD),
        (invalid_id, "invalid-envelope-secret-sentinel"),
    ] {
        insert_credential(
            &pool,
            CredentialFixture {
                id,
                project_id: &project_raw,
                kind: "service",
                provider: None,
                protocol: None,
                data: json!({"TOKEN": token}),
                group_id: None,
                server_url: None,
                scheme: None,
                archived: false,
                deleted: false,
            },
        )
        .await;
    }

    let access = CredentialMaterialAccessService::with_material_adapter(
        pool.clone(),
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    );
    let context = CredentialAccessContext::runtime(Some(session_id), Some(task_id), Some(12));

    let model = access
        .resolve_model(&project_id, model_id, "claude", &context)
        .await
        .unwrap();
    assert_eq!(model.protocol_id, "anthropic_messages");
    assert_eq!(model.material["ANTHROPIC_API_KEY"], "hello-world");
    let metadata_only = access
        .resolve_model_runtime_config(
            &project_id,
            metadata_only_model_id,
            "claude",
            false,
            &context,
        )
        .await
        .unwrap();
    assert_eq!(metadata_only.binding.protocol_id, "anthropic_messages");
    assert_eq!(metadata_only.model, None);
    let model_name_only = access
        .resolve_model_runtime_config(&project_id, model_name_only_id, "claude", true, &context)
        .await
        .unwrap();
    assert_eq!(model_name_only.binding.protocol_id, "anthropic_messages");
    assert_eq!(model_name_only.model.as_deref(), Some("hello-world"));
    let model_name_debug = format!("{model_name_only:?}");
    assert!(!model_name_debug.contains("hello-world"));
    assert!(model_name_debug.contains("redacted"));
    assert_eq!(
        access
            .resolve_environment(&project_id, valid_id, &context)
            .await
            .unwrap(),
        ResolvedServiceCredential::Environment(json!({"TOKEN": "hello-world"}))
    );
    assert_eq!(
        access
            .resolve_http_egress_field(&project_id, valid_id, "TOKEN", &context)
            .await
            .unwrap(),
        "hello-world"
    );
    assert_eq!(
        access
            .resolve_http_egress_field(&project_id, valid_id, "TOKEN", &context)
            .await
            .unwrap(),
        "hello-world"
    );
    assert_eq!(
        access
            .resolve_http_egress_field(&project_id, invalid_id, "TOKEN", &context)
            .await
            .unwrap_err()
            .downcast_ref::<CredentialRuntimeError>(),
        Some(&CredentialRuntimeError::EnvelopeInvalid)
    );

    let rows = sqlx::query_as::<
        _,
        (
            CredentialId,
            String,
            String,
            serde_json::Value,
            String,
            Option<String>,
        ),
    >(
        r#"
        SELECT credential_id, usage, result, field_names, principal_id, error_code
        FROM joysafeter_credential_access_audits
        WHERE credential_id = ANY($1)
        ORDER BY created_at, id
        "#,
    )
    .bind(
        &[
            model_id,
            metadata_only_model_id,
            model_name_only_id,
            valid_id,
            invalid_id,
        ][..],
    )
    .fetch_all(&pool)
    .await
    .expect("load material access audits");

    assert_eq!(rows.len(), 5);
    assert!(rows
        .iter()
        .any(|(credential_id, usage, result, fields, _, error)| {
            *credential_id == model_id
                && usage == "model_inference"
                && result == "success"
                && fields == &json!(["ANTHROPIC_API_KEY"])
                && error.is_none()
        }));
    assert!(!rows
        .iter()
        .any(|(credential_id, ..)| *credential_id == metadata_only_model_id));
    assert!(rows
        .iter()
        .any(|(credential_id, usage, result, fields, _, error)| {
            *credential_id == model_name_only_id
                && usage == "model_inference"
                && result == "success"
                && fields == &json!(["ANTHROPIC_MODEL"])
                && error.is_none()
        }));
    assert!(rows
        .iter()
        .any(|(credential_id, usage, result, fields, _, error)| {
            *credential_id == valid_id
                && usage == "environment_injection"
                && result == "success"
                && fields == &json!(["TOKEN"])
                && error.is_none()
        }));
    assert!(rows
        .iter()
        .any(|(credential_id, usage, result, fields, _, error)| {
            *credential_id == valid_id
                && usage == "http_egress"
                && result == "success"
                && fields == &json!(["TOKEN"])
                && error.is_none()
        }));
    assert!(rows
        .iter()
        .any(|(credential_id, usage, result, fields, principal, error)| {
            *credential_id == invalid_id
                && usage == "http_egress"
                && result == "failed"
                && fields == &json!(["TOKEN"])
                && principal == "runtime"
                && error.as_deref() == Some("envelope_invalid")
        }));
    assert!(!serde_json::to_string(&rows)
        .unwrap()
        .contains("invalid-envelope-secret-sentinel"));

    cleanup(
        &pool,
        &[],
        &[],
        &[
            model_id,
            metadata_only_model_id,
            model_name_only_id,
            valid_id,
            invalid_id,
        ],
        &[],
        &[(&project_raw, &organization_id)],
    )
    .await;
}

/// Regression: the sandbox resolver and the harness must agree on which
/// environment bindings are valid. Both now route through
/// `resolve_live_environment_binding`, so an explicit session binding that is
/// archived or cross-project fails closed with `SessionBindingInvalid` before a
/// sandbox is ever provisioned. A persisted session with no environment does
/// not inherit a later agent environment.
#[tokio::test]
async fn resolve_live_environment_binding_rejects_invalid_session_environment_id() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let other_project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let other_organization_id =
        insert_project(&pool, &format!("{unique}-other"), &other_project_id).await;
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    insert_agent(&pool, agent_id, &project_id).await;
    insert_session(&pool, session_id, agent_id, &project_id).await;
    insert_environment(
        &pool,
        environment_id,
        &project_id,
        &format!("env-{unique}"),
        false,
    )
    .await;

    // Valid, same-project, non-archived explicit binding resolves.
    let resolved = kernel::environment_binding::resolve_live_environment_binding(
        &pool,
        Some(environment_id),
        None,
        Some(project_id),
        Some(session_id),
    )
    .await;
    assert!(
        matches!(resolved, Ok(Some(_))),
        "valid explicit binding must resolve, got {resolved:?}"
    );

    // Cross-project explicit binding fails closed (before any provisioning).
    let cross_project = kernel::environment_binding::resolve_live_environment_binding(
        &pool,
        Some(environment_id),
        None,
        Some(other_project_id),
        Some(session_id),
    )
    .await;
    assert!(
        matches!(
            cross_project,
            Err(RuntimeFreshnessError::SessionBindingInvalid { .. })
        ),
        "cross-project explicit binding must fail closed, got {cross_project:?}"
    );

    // Archiving the environment makes the explicit binding fail closed too.
    sqlx::query("UPDATE joysafeter_environments SET archived_at = NOW() WHERE id = $1")
        .bind(environment_id)
        .execute(&pool)
        .await
        .expect("archive environment fixture");
    let archived = kernel::environment_binding::resolve_live_environment_binding(
        &pool,
        Some(environment_id),
        None,
        Some(project_id),
        Some(session_id),
    )
    .await;
    assert!(
        matches!(
            archived,
            Err(RuntimeFreshnessError::SessionBindingInvalid { .. })
        ),
        "archived explicit binding must fail closed, got {archived:?}"
    );

    // A persisted session with no environment does not inherit the agent's
    // archived environment binding.
    let unbound_session = kernel::environment_binding::resolve_live_environment_binding(
        &pool,
        None,
        Some(environment_id),
        Some(project_id),
        Some(session_id),
    )
    .await;
    assert!(
        matches!(unbound_session, Ok(None)),
        "unbound session must not inherit agent environment, got {unbound_session:?}"
    );

    let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
        .bind(environment_id)
        .execute(&pool)
        .await;
    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[],
        &[
            (&project_id, &organization_id),
            (&other_project_id, &other_organization_id),
        ],
    )
    .await;
}
