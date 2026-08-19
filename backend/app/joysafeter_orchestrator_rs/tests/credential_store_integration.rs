use std::env;

use joysafeter_orchestrator::ids::{AgentId, CredentialGroupId, CredentialId, SessionId};
use joysafeter_orchestrator::kernel;
use joysafeter_orchestrator::kernel::credentials::error::{
    require_bound_credential_id, CredentialRuntimeError,
};
use joysafeter_orchestrator::kernel::credentials::material::ManagedCredentialMaterialAdapter;
use joysafeter_orchestrator::kernel::credentials::mcp::resolve_mcp_members;
use joysafeter_orchestrator::kernel::credentials::model::resolve_model_credential;
use joysafeter_orchestrator::kernel::credentials::record::ProjectId;
use joysafeter_orchestrator::kernel::credentials::service::{
    resolve_service_credential, ResolvedServiceCredential, ServiceUsage,
};
use joysafeter_orchestrator::kernel::credentials::store::CredentialStore;
use joysafeter_orchestrator::kernel::harness_input_builder::HarnessInput;
use serde_json::{json, Value};
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

fn test_store(pool: PgPool) -> CredentialStore {
    CredentialStore::with_material_adapter(
        pool,
        ManagedCredentialMaterialAdapter::from_key(TEST_KEY),
    )
}

async fn insert_project(pool: &PgPool, unique: &str, project_id: &str) -> String {
    let organization_id = format!("org-task10-{unique}");
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

async fn insert_agent(pool: &PgPool, agent_id: AgentId, project_id: &str) {
    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (
            id, project_id, name, engine_kind, model, system_prompt, env, mcp_servers,
            skills, tools, agents, commands, permission_mode, metadata, version
        )
        VALUES (
            $1, $2, $3, 'claude', '{}'::jsonb, '', '{}'::jsonb, '[]'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            'bypassPermissions', '{}'::jsonb, 1
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

async fn insert_session(pool: &PgPool, session_id: SessionId, agent_id: AgentId, project_id: &str) {
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

struct CredentialFixture<'a> {
    id: CredentialId,
    project_id: &'a str,
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
            archived_at, deleted_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11,
            CASE WHEN $12 THEN NOW() ELSE NULL END,
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
    project_id: &str,
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
    projects: &[(&str, &str)],
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

#[tokio::test]
async fn store_and_usage_resolvers_cover_model_and_service_happy_paths() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_raw = format!("proj-task10-{unique}");
    let organization_id = insert_project(&pool, &unique, &project_raw).await;
    let project_id = ProjectId::parse(&project_raw).expect("valid project id");
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

    let mut harness_input = HarnessInput::default();
    harness_input.env.insert(
        "EXPLICIT_SERVICE_TOKEN".to_string(),
        "hello-world".to_string(),
    );
    harness_input
        .secrets
        .insert("MODEL_TOKEN".to_string(), "hello-world".to_string());
    for formatted in [
        format!("{model:?}"),
        format!("{resolved_model:?}"),
        format!("{service:?}"),
        format!("{injected:?}"),
        format!("{egress:?}"),
        format!("{harness_input:?}"),
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
    let project_a_raw = format!("proj-task10-{unique}-a");
    let project_b_raw = format!("proj-task10-{unique}-b");
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a_raw).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b_raw).await;
    let project_a = ProjectId::parse(&project_a_raw).expect("valid project id");
    let archived_id = CredentialId::from_uuid(Uuid::now_v7());
    let deleted_id = CredentialId::from_uuid(Uuid::now_v7());
    let cross_project_id = CredentialId::from_uuid(Uuid::now_v7());
    let missing_field_id = CredentialId::from_uuid(Uuid::now_v7());
    let malformed_material_id = CredentialId::from_uuid(Uuid::now_v7());
    let malformed_envelope_id = CredentialId::from_uuid(Uuid::now_v7());

    for (id, project_id, data, archived, deleted) in [
        (
            archived_id,
            project_a_raw.as_str(),
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            true,
            false,
        ),
        (
            deleted_id,
            project_a_raw.as_str(),
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            false,
            true,
        ),
        (
            cross_project_id,
            project_b_raw.as_str(),
            json!({"ANTHROPIC_API_KEY": ENCRYPTED_HELLO_WORLD}),
            false,
            false,
        ),
        (
            missing_field_id,
            project_a_raw.as_str(),
            json!({}),
            false,
            false,
        ),
        (
            malformed_material_id,
            project_a_raw.as_str(),
            json!([ENCRYPTED_HELLO_WORLD]),
            false,
            false,
        ),
        (
            malformed_envelope_id,
            project_a_raw.as_str(),
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
    let project_a_raw = format!("proj-task10-{unique}-a");
    let project_b_raw = format!("proj-task10-{unique}-b");
    let org_a = insert_project(&pool, &format!("{unique}-a"), &project_a_raw).await;
    let org_b = insert_project(&pool, &format!("{unique}-b"), &project_b_raw).await;
    let project_a = ProjectId::parse(&project_a_raw).expect("valid project id");
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
            project_a_raw.as_str(),
            "https://mcp-a.example/api",
            "bearer",
            ENCRYPTED_HELLO_WORLD,
        ),
        (
            corrupt_id,
            group_a,
            project_a_raw.as_str(),
            "https://mcp-b.example/api",
            "static_bearer",
            "enc:v1:not-base64",
        ),
        (
            unknown_scheme_id,
            group_b,
            project_b_raw.as_str(),
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
    assert_eq!(resolved[0].token, "hello-world");
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
            .load_session_mcp_members(
                &ProjectId::parse(&project_b_raw).expect("valid project id"),
                session_b,
            )
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
            .load_session_mcp_members(
                &ProjectId::parse(&project_b_raw).expect("valid project id"),
                session_b,
            )
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
async fn mcp_urls_are_canonical_unique_and_stably_ordered() {
    let pool = test_pool().await;
    let unique = Uuid::now_v7().simple().to_string();
    let project_raw = format!("proj-task10-{unique}");
    let organization_id = insert_project(&pool, &unique, &project_raw).await;
    let project_id = ProjectId::parse(&project_raw).expect("valid project id");
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
