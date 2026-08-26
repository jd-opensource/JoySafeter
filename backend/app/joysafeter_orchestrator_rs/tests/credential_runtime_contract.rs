#[path = "../src/config.rs"]
mod config;
#[path = "../src/db/mod.rs"]
mod db;
#[path = "../src/events/mod.rs"]
mod events;
#[path = "../src/grpc/mod.rs"]
mod grpc;
#[path = "../src/ids.rs"]
mod ids;
#[path = "../src/kernel/mod.rs"]
mod kernel;
#[path = "../src/runtime_config.rs"]
mod runtime_config;
#[path = "../src/sandbox/mod.rs"]
mod sandbox;

use std::env;

use db::models::JoySafeterSandbox;
use ids::{
    AgentId, CredentialGroupId, CredentialId, EnvironmentId, OrganizationId, ProjectId, SandboxId,
    SessionId, TaskId,
};
use kernel::credentials::error::{require_bound_credential_id, CredentialRuntimeError};
use kernel::harness_input_builder::HarnessInputBuilder;
use kernel::sandbox_resolver::rebuild_sandbox_credentials;
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

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
    .bind(format!("Credential Runtime Org {unique}"))
    .bind(format!("credential-runtime-org-{unique}"))
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
    .bind(format!("Credential Runtime Project {unique}"))
    .bind(format!("credential-runtime-project-{unique}"))
    .execute(pool)
    .await
    .expect("insert project fixture");
    organization_id
}

async fn insert_credential(
    pool: &PgPool,
    credential_id: CredentialId,
    project_id: &ProjectId,
    kind: &str,
    provider: Option<&str>,
    protocol: Option<&str>,
    data: Value,
    archived: bool,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_credentials
            (id, project_id, kind, name, provider, protocol, data, archived_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7,
                CASE WHEN $8 THEN NOW() ELSE NULL END)
        "#,
    )
    .bind(credential_id)
    .bind(project_id)
    .bind(kind)
    .bind(format!("runtime-{credential_id}"))
    .bind(provider)
    .bind(protocol)
    .bind(data)
    .bind(archived)
    .execute(pool)
    .await
    .expect("insert credential fixture");
}

async fn insert_agent(
    pool: &PgPool,
    agent_id: AgentId,
    project_id: Option<&ProjectId>,
    engine_kind: &str,
    model_credential_id: Option<CredentialId>,
    environment_id: Option<EnvironmentId>,
    mcp_servers: Value,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (
            id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
            skills, tools, agents, commands, permission_mode, metadata, version,
            environment_id, model_credential_id
        )
        VALUES (
            $1, $2, $3, $4, '{}'::jsonb, '', '{}'::jsonb, $5,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            'bypassPermissions', '{}'::jsonb, 1, $6, $7
        )
        "#,
    )
    .bind(agent_id)
    .bind(project_id)
    .bind(format!("runtime-agent-{agent_id}"))
    .bind(engine_kind)
    .bind(mcp_servers)
    .bind(environment_id)
    .bind(model_credential_id)
    .execute(pool)
    .await
    .expect("insert agent fixture");
}

async fn insert_session(
    pool: &PgPool,
    session_id: SessionId,
    agent_id: AgentId,
    project_id: Option<&ProjectId>,
    snapshot: Option<Value>,
    environment_id: Option<EnvironmentId>,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_sessions
            (id, agent_id, project_id, status, agent_snapshot, environment_id)
        VALUES ($1, $2, $3, 'idle', $4, $5)
        "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(project_id)
    .bind(snapshot)
    .bind(environment_id)
    .execute(pool)
    .await
    .expect("insert session fixture");
}

async fn insert_task(
    pool: &PgPool,
    task_id: TaskId,
    agent_id: AgentId,
    session_id: Option<SessionId>,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_tasks (
            id, agent_id, chat_session_id, status, prompt, output,
            timeout_sec, retry_count, max_retries
        )
        VALUES ($1, $2, $3, 'running', 'credential runtime contract', '', 7200, 0, 2)
        "#,
    )
    .bind(task_id)
    .bind(agent_id)
    .bind(session_id)
    .execute(pool)
    .await
    .expect("insert task fixture");
}

async fn insert_environment(
    pool: &PgPool,
    environment_id: EnvironmentId,
    project_id: &ProjectId,
    config: Value,
) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_environments
            (id, project_id, name, description, config, image_version)
        VALUES ($1, $2, $3, '', $4, 1)
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .bind(format!("runtime-environment-{environment_id}"))
    .bind(config)
    .execute(pool)
    .await
    .expect("insert environment fixture");
}

fn sandbox_for(session_id: SessionId) -> JoySafeterSandbox {
    JoySafeterSandbox {
        id: SandboxId::from_uuid(Uuid::now_v7()),
        external_id: Some("runtime-contract-sandbox".to_string()),
        status: "ready".to_string(),
        config: None,
        chat_session_id: Some(session_id),
        image: None,
        disconnected_at: None,
        networking_status: "ready".to_string(),
        networking_policy_hash: None,
        networking_policy_version: 0,
        networking_applied_hash: None,
        networking_applied_version: None,
        networking_last_error: None,
        networking_ready_at: None,
        runtime_config_status: "ready".to_string(),
        runtime_config_last_reason: None,
        runtime_config_required_at: None,
        runtime_config_applied_generation: 0,
    }
}

async fn build_harness_error(pool: &PgPool, task_id: TaskId) -> anyhow::Error {
    let task = db::queries::get_task(pool, task_id)
        .await
        .expect("load task fixture")
        .expect("task fixture exists");
    let session_id = task.session_id.expect("runtime contract task has session");
    let (session_project_id, captured_generation): (Option<ProjectId>, i64) = sqlx::query_as(
        "SELECT project_id, runtime_config_generation FROM joysafeter_sessions WHERE id = $1",
    )
    .bind(session_id)
    .fetch_one(pool)
    .await
    .expect("load session runtime scope");
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    db::queries::create_session_bound_sandbox_guarded(
        pool,
        sandbox_id,
        &format!("runtime-contract-{sandbox_id}"),
        "test",
        "joysafeter/runtime-contract:latest",
        session_id,
        session_project_id,
        None,
        Some(&json!({})),
        captured_generation,
    )
    .await
    .expect("create guarded runtime contract sandbox");

    let error = HarnessInputBuilder::new(pool.clone(), false)
        .build(&task, "runtime-contract", sandbox_id)
        .await
        .expect_err("configured invalid credential must fail harness build");
    sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(pool)
        .await
        .expect("delete guarded runtime contract sandbox");
    error
}

async fn cleanup(
    pool: &PgPool,
    agent_ids: &[AgentId],
    session_ids: &[SessionId],
    environment_ids: &[EnvironmentId],
    credential_ids: &[CredentialId],
    group_ids: &[CredentialGroupId],
    projects: &[(&ProjectId, &OrganizationId)],
) {
    for session_id in session_ids {
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1")
            .bind(session_id)
            .execute(pool)
            .await;
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
        let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE agent_id = $1")
            .bind(agent_id)
            .execute(pool)
            .await;
        let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
            .bind(agent_id)
            .execute(pool)
            .await;
    }
    for environment_id in environment_ids {
        let _ = sqlx::query("DELETE FROM joysafeter_environments WHERE id = $1")
            .bind(environment_id)
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

#[test]
fn only_an_absent_optional_binding_is_not_bound() {
    assert_eq!(
        require_bound_credential_id(None),
        Err(CredentialRuntimeError::NotBound)
    );
}

#[tokio::test]
async fn model_credential_fk_and_harness_builder_reject_invalid_bindings() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_a = ProjectId::new();
    let project_b = ProjectId::new();
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b).await;
    let active_id = CredentialId::from_uuid(Uuid::now_v7());
    let archived_id = CredentialId::from_uuid(Uuid::now_v7());
    insert_credential(
        &pool,
        active_id,
        &project_b,
        "model",
        Some("anthropic"),
        Some("anthropic_messages"),
        json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
        false,
    )
    .await;
    insert_credential(
        &pool,
        archived_id,
        &project_a,
        "model",
        Some("anthropic"),
        Some("anthropic_messages"),
        json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
        true,
    )
    .await;

    let missing_agent_id = AgentId::from_uuid(Uuid::now_v7());
    let missing_credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let missing_error = sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (
            id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
            skills, tools, agents, commands, permission_mode, metadata, version,
            model_credential_id
        )
        VALUES (
            $1, $2, $3, 'claude', '{}'::jsonb, '', '{}'::jsonb, '[]'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            'bypassPermissions', '{}'::jsonb, 1, $4
        )
        "#,
    )
    .bind(missing_agent_id)
    .bind(project_a)
    .bind(format!("runtime-missing-agent-{missing_agent_id}"))
    .bind(missing_credential_id)
    .execute(&pool)
    .await
    .expect_err("native model credential foreign key must reject missing credentials");
    assert_eq!(
        missing_error
            .as_database_error()
            .and_then(|database_error| database_error.code().map(|code| code.into_owned()))
            .as_deref(),
        Some("23503")
    );

    let cases = [
        (
            "archived",
            archived_id,
            Some(&project_a),
            CredentialRuntimeError::Archived,
        ),
        (
            "cross-project",
            active_id,
            Some(&project_a),
            CredentialRuntimeError::ProjectMismatch,
        ),
        (
            "null-project",
            active_id,
            None,
            CredentialRuntimeError::ProjectMismatch,
        ),
    ];
    let mut agent_ids = Vec::new();
    let mut session_ids = Vec::new();
    for (name, credential_id, project_id, expected) in cases {
        let agent_id = AgentId::from_uuid(Uuid::now_v7());
        let session_id = SessionId::from_uuid(Uuid::now_v7());
        let task_id = TaskId::from_uuid(Uuid::now_v7());
        insert_agent(
            &pool,
            agent_id,
            project_id,
            "claude",
            Some(credential_id),
            None,
            json!([]),
        )
        .await;
        insert_session(&pool, session_id, agent_id, project_id, None, None).await;
        insert_task(&pool, task_id, agent_id, Some(session_id)).await;

        let error = build_harness_error(&pool, task_id).await;
        assert_eq!(error.downcast_ref(), Some(&expected), "{name}");
        agent_ids.push(agent_id);
        session_ids.push(session_id);
    }

    cleanup(
        &pool,
        &agent_ids,
        &session_ids,
        &[],
        &[active_id, archived_id],
        &[],
        &[(&project_a, &org_a), (&project_b, &org_b)],
    )
    .await;
}

#[tokio::test]
async fn production_builders_reject_missing_model_profile_material() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let credential_id = CredentialId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    insert_credential(
        &pool,
        credential_id,
        &project_id,
        "model",
        Some("openai"),
        Some("chat_completions"),
        json!({"UNRELATED_TOKEN": ENCRYPTED_HELLO_WORLD}),
        false,
    )
    .await;
    insert_agent(
        &pool,
        agent_id,
        Some(&project_id),
        "pi",
        Some(credential_id),
        None,
        json!([]),
    )
    .await;
    insert_session(&pool, session_id, agent_id, Some(&project_id), None, None).await;
    insert_task(&pool, task_id, agent_id, Some(session_id)).await;

    let harness_error = build_harness_error(&pool, task_id).await;
    assert_eq!(
        harness_error.downcast_ref(),
        Some(&CredentialRuntimeError::FieldMissing)
    );

    let recovery_error = rebuild_sandbox_credentials(&pool, &sandbox_for(session_id), &[])
        .await
        .expect_err("missing model profile material must stop recovery");
    assert_eq!(
        recovery_error.downcast_ref(),
        Some(&CredentialRuntimeError::FieldMissing)
    );

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[],
        &[credential_id],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn recovery_rejects_cross_project_environment_instead_of_suppressing_lookup() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_a = ProjectId::new();
    let project_b = ProjectId::new();
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b).await;
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_environment(
        &pool,
        environment_id,
        &project_b,
        json!({"egress_services": []}),
    )
    .await;
    insert_agent(
        &pool,
        agent_id,
        Some(&project_a),
        "claude",
        None,
        Some(environment_id),
        json!([]),
    )
    .await;
    insert_session(
        &pool,
        session_id,
        agent_id,
        Some(&project_a),
        None,
        Some(environment_id),
    )
    .await;

    let error = rebuild_sandbox_credentials(&pool, &sandbox_for(session_id), &[])
        .await
        .expect_err("cross-project configured environment must stop recovery");
    assert_eq!(
        error.downcast_ref(),
        Some(&CredentialRuntimeError::ProjectMismatch)
    );

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[environment_id],
        &[],
        &[],
        &[(&project_a, &org_a), (&project_b, &org_b)],
    )
    .await;
}

#[tokio::test]
async fn recovery_rejects_present_non_array_egress_services() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_environment(
        &pool,
        environment_id,
        &project_id,
        json!({"egress_services": {"configured": true}}),
    )
    .await;
    insert_agent(
        &pool,
        agent_id,
        Some(&project_id),
        "claude",
        None,
        Some(environment_id),
        json!([]),
    )
    .await;
    insert_session(
        &pool,
        session_id,
        agent_id,
        Some(&project_id),
        None,
        Some(environment_id),
    )
    .await;

    let error = rebuild_sandbox_credentials(&pool, &sandbox_for(session_id), &[])
        .await
        .expect_err("present non-array egress_services must stop recovery");
    assert_eq!(
        error.downcast_ref(),
        Some(&CredentialRuntimeError::CorruptRecord)
    );

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[environment_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn recovery_does_not_inherit_agent_environment_for_unbound_session() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_id = ProjectId::new();
    let organization_id = insert_project(&pool, &unique, &project_id).await;
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_environment(
        &pool,
        environment_id,
        &project_id,
        json!({"egress_services": {"invalid": true}}),
    )
    .await;
    insert_agent(
        &pool,
        agent_id,
        Some(&project_id),
        "claude",
        None,
        Some(environment_id),
        json!([]),
    )
    .await;
    insert_session(&pool, session_id, agent_id, Some(&project_id), None, None).await;

    rebuild_sandbox_credentials(&pool, &sandbox_for(session_id), &[])
        .await
        .expect("unbound session must not inherit the live agent environment");

    cleanup(
        &pool,
        &[agent_id],
        &[session_id],
        &[environment_id],
        &[],
        &[],
        &[(&project_id, &organization_id)],
    )
    .await;
}

#[tokio::test]
async fn recovery_propagates_http_and_mcp_credential_failures() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_a = ProjectId::new();
    let project_b = ProjectId::new();
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b).await;
    let service_id = CredentialId::from_uuid(Uuid::now_v7());
    let environment_id = EnvironmentId::from_uuid(Uuid::now_v7());
    let http_agent_id = AgentId::from_uuid(Uuid::now_v7());
    let http_session_id = SessionId::from_uuid(Uuid::now_v7());
    insert_credential(
        &pool,
        service_id,
        &project_b,
        "service",
        None,
        None,
        json!({"API_TOKEN": ENCRYPTED_HELLO_WORLD}),
        false,
    )
    .await;
    insert_environment(
        &pool,
        environment_id,
        &project_a,
        json!({
            "egress_services": [{
                "name": "cross-project-http",
                "base_url": "https://api.example.com",
                "credential_ref": service_id.to_string(),
                "inject": {"type": "bearer", "credential_field": "API_TOKEN"}
            }]
        }),
    )
    .await;
    insert_agent(
        &pool,
        http_agent_id,
        Some(&project_a),
        "claude",
        None,
        Some(environment_id),
        json!([]),
    )
    .await;
    insert_session(
        &pool,
        http_session_id,
        http_agent_id,
        Some(&project_a),
        None,
        Some(environment_id),
    )
    .await;
    let http_error = rebuild_sandbox_credentials(&pool, &sandbox_for(http_session_id), &[])
        .await
        .expect_err("cross-project HTTP credential must stop recovery");
    assert_eq!(
        http_error.downcast_ref(),
        Some(&CredentialRuntimeError::ProjectMismatch)
    );

    let group_id = CredentialGroupId::from_uuid(Uuid::now_v7());
    let mcp_id = CredentialId::from_uuid(Uuid::now_v7());
    let mcp_agent_id = AgentId::from_uuid(Uuid::now_v7());
    let mcp_session_id = SessionId::from_uuid(Uuid::now_v7());
    let mcp_url = "https://mcp.example.com/api";
    sqlx::query(
        "INSERT INTO joysafeter_credential_groups (id, project_id, name, description) VALUES ($1, $2, $3, '')",
    )
    .bind(group_id)
    .bind(&project_a)
    .bind(format!("runtime-group-{unique}"))
    .execute(&pool)
    .await
    .expect("insert MCP group fixture");
    sqlx::query(
        r#"
        INSERT INTO joysafeter_credentials (
            id, project_id, kind, name, credential_type, mcp_server_url,
            normalized_mcp_server_url, group_id, data
        )
        VALUES ($1, $2, 'mcp', $3, 'static_bearer', $4, $5, $6, '{}'::jsonb)
        "#,
    )
    .bind(mcp_id)
    .bind(&project_a)
    .bind(format!("runtime-mcp-{unique}"))
    .bind(mcp_url)
    .bind(kernel::mcp_url::normalize(mcp_url))
    .bind(group_id)
    .execute(&pool)
    .await
    .expect("insert MCP credential fixture");
    insert_agent(
        &pool,
        mcp_agent_id,
        Some(&project_a),
        "claude",
        None,
        None,
        json!([{
            "name": "runtime-mcp",
            "type": "streamable_http",
            "url": mcp_url,
            "auth_requirement": "required"
        }]),
    )
    .await;
    insert_session(
        &pool,
        mcp_session_id,
        mcp_agent_id,
        Some(&project_a),
        None,
        None,
    )
    .await;
    sqlx::query(
        "INSERT INTO joysafeter_session_credential_groups (session_id, credential_group_id) VALUES ($1, $2)",
    )
    .bind(mcp_session_id)
    .bind(group_id)
    .execute(&pool)
    .await
    .expect("bind MCP group fixture");

    let mcp_error = rebuild_sandbox_credentials(&pool, &sandbox_for(mcp_session_id), &[])
        .await
        .expect_err("missing MCP token must stop recovery");
    assert_eq!(
        mcp_error.downcast_ref(),
        Some(&CredentialRuntimeError::FieldMissing)
    );

    cleanup(
        &pool,
        &[http_agent_id, mcp_agent_id],
        &[http_session_id, mcp_session_id],
        &[environment_id],
        &[service_id, mcp_id],
        &[group_id],
        &[(&project_a, &org_a), (&project_b, &org_b)],
    )
    .await;
}
