use std::env;

use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

use super::*;
use crate::ids::EventId;
use crate::kernel::runner::execution::{handle_task_message, replay_pending_control_inputs};
use crate::kernel::sandbox_bridge::BridgeRegistry;

fn database_url() -> Option<String> {
    env::var("JOYSAFETER_TEST_DATABASE_URL")
        .ok()
        .or_else(|| env::var("DATABASE_URL").ok())
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
}

async fn test_pool() -> Option<PgPool> {
    let Some(url) = database_url() else {
        eprintln!("skipping real Postgres control replay test: DATABASE_URL is not set");
        return None;
    };
    Some(
        PgPoolOptions::new()
            .max_connections(5)
            .connect(&url)
            .await
            .expect("connect to migrated Postgres test database"),
    )
}

async fn create_agent_and_session(pool: &PgPool) -> (AgentId, SessionId) {
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let organization_id = OrganizationId::new();
    let project_id = ProjectId::new();
    sqlx::query(
        r#"
            INSERT INTO joysafeter_organizations
                (id, name, slug, storage_used_bytes, departed_member_usage)
            VALUES ($1, $2, $3, 0, 0)
            "#,
    )
    .bind(&organization_id)
    .bind(format!("gRPC Test Org {unique}"))
    .bind(format!("grpc-test-org-{unique}"))
    .execute(pool)
    .await
    .expect("insert test organization");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_organization_projects
                (id, org_id, name, slug, is_default)
            VALUES ($1, $2, $3, $4, false)
            "#,
    )
    .bind(&project_id)
    .bind(&organization_id)
    .bind(format!("gRPC Test Project {unique}"))
    .bind(format!("grpc-test-project-{unique}"))
    .execute(pool)
    .await
    .expect("insert test project");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_agents
                (id, project_id, name, engine_kind, version)
            VALUES ($1, $2, $3, 'claude', 1)
            "#,
    )
    .bind(agent_id)
    .bind(&project_id)
    .bind(format!("control-replay-agent-{agent_id}"))
    .execute(pool)
    .await
    .expect("insert test agent");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
            VALUES ($1, $2, $3, 'running')
            "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(&project_id)
    .execute(pool)
    .await
    .expect("insert test session");

    (agent_id, session_id)
}

async fn cleanup(pool: &PgPool, agent_id: AgentId, session_id: SessionId) {
    let project = sqlx::query_as::<_, (Option<ProjectId>, Option<OrganizationId>)>(
        r#"
            SELECT agents.project_id, projects.org_id
            FROM joysafeter_agents AS agents
            LEFT JOIN joysafeter_organization_projects AS projects
              ON projects.id = agents.project_id
            WHERE agents.id = $1
            "#,
    )
    .bind(agent_id)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
        .bind(session_id)
        .bind(agent_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(pool)
        .await;
    if let Some((Some(project_id), organization_id)) = project {
        let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
            .bind(&project_id)
            .execute(pool)
            .await;
        if let Some(organization_id) = organization_id {
            let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
                .bind(&organization_id)
                .execute(pool)
                .await;
        }
    }
}

#[test]
fn initial_setup_is_deferred_only_for_an_unclaimed_pool_sandbox() {
    assert!(should_defer_initial_setup(Some("pooled"), false));
    assert!(!should_defer_initial_setup(Some("pooled"), true));
    assert!(!should_defer_initial_setup(Some("creating"), false));
    assert!(!should_defer_initial_setup(None, false));
}

async fn create_mounted_memory_store(pool: &PgPool, session_id: SessionId) -> MemoryStoreId {
    let store_id = MemoryStoreId::from_uuid(Uuid::now_v7());
    sqlx::query(
        r#"
            INSERT INTO joysafeter_memory_stores (id, name, description)
            VALUES ($1, $2, '')
            "#,
    )
    .bind(store_id)
    .bind(format!("memory-sync-store-{store_id}"))
    .execute(pool)
    .await
    .expect("insert memory store");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_session_memory_stores
                (id, session_id, store_id, access, mount_name)
            VALUES ($1, $2, $3, 'read_write', 'main')
            "#,
    )
    .bind(Uuid::now_v7())
    .bind(session_id)
    .bind(store_id)
    .execute(pool)
    .await
    .expect("insert session memory store mount");

    store_id
}

async fn cleanup_memory_store(pool: &PgPool, session_id: SessionId, store_id: MemoryStoreId) {
    let _ = sqlx::query("DELETE FROM joysafeter_session_memory_stores WHERE session_id = $1")
        .bind(session_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_memory_versions WHERE store_id = $1")
        .bind(store_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_memories WHERE store_id = $1")
        .bind(store_id)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_memory_stores WHERE id = $1")
        .bind(store_id)
        .execute(pool)
        .await;
}

fn test_event_bus(pool: PgPool) -> EventBus {
    let config = JoySafeterConfig::from_env();
    let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
    let redis_client = redis::Client::open(
        config
            .redis_url
            .clone()
            .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
    )
    .expect("build redis client");
    EventBus::new(pool, &config, runtime_config, redis_client)
}

async fn create_running_sandbox_task(
    pool: &PgPool,
    agent_id: AgentId,
    session_id: SessionId,
    label: &str,
    retry_count: i32,
    max_retries: i32,
) -> (SandboxId, TaskId) {
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    queries::create_sandbox(
        pool,
        sandbox_id,
        &format!("{label}-{sandbox_id}"),
        "recording",
        "test-image:latest",
        Some(session_id),
        None,
        None,
        Some(&json!({})),
    )
    .await
    .expect("insert linked sandbox");
    let _ = queries::transition_sandbox_cas(pool, sandbox_id, "creating", "idle")
        .await
        .expect("sandbox idle");
    let _ = queries::transition_sandbox_cas(pool, sandbox_id, "idle", "running")
        .await
        .expect("sandbox running");
    sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
        .bind(sandbox_id)
        .bind(task_id)
        .execute(pool)
        .await
        .expect("set sandbox last task");

    sqlx::query(
        r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, $5, $6)
            "#,
    )
    .bind(task_id)
    .bind(agent_id)
    .bind(session_id)
    .bind(sandbox_id)
    .bind(retry_count)
    .bind(max_retries)
    .execute(pool)
    .await
    .expect("insert running task");

    (sandbox_id, task_id)
}

#[path = "session_tests/cleanup.rs"]
mod cleanup_tests;
#[path = "session_tests/execution.rs"]
mod execution_tests;
#[path = "session_tests/lifecycle_dispatch.rs"]
mod lifecycle_dispatch_tests;
#[path = "session_tests/lifecycle_failover.rs"]
mod lifecycle_failover_tests;
#[path = "session_tests/lifecycle_pre_start.rs"]
mod lifecycle_pre_start_tests;
#[path = "session_tests/memory_sync.rs"]
mod memory_sync_tests;
#[path = "session_tests/recovery.rs"]
mod recovery_tests;
#[path = "session_tests/setup.rs"]
mod setup_tests;
