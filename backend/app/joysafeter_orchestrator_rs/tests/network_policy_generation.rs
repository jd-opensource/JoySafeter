use std::env;

use joysafeter_orchestrator::db::queries;
use joysafeter_orchestrator::ids::SandboxId;
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

fn database_url() -> String {
    env::var("JOYSAFETER_TEST_DATABASE_URL")
        .or_else(|_| env::var("DATABASE_URL"))
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
        .expect("a network-policy test database URL must point to migrated PostgreSQL")
}

async fn test_pool() -> PgPool {
    PgPoolOptions::new()
        .max_connections(4)
        .connect(&database_url())
        .await
        .expect("connect to migrated PostgreSQL test database")
}

async fn create_sandbox(pool: &PgPool) -> SandboxId {
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    queries::create_sandbox(
        pool,
        sandbox_id,
        &format!("network-policy-generation-{sandbox_id}"),
        "test",
        "joysafeter/network-policy-generation:latest",
        None,
        None,
        None,
        Some(&json!({})),
    )
    .await
    .expect("create sandbox fixture");
    sandbox_id
}

async fn delete_sandbox(pool: &PgPool, sandbox_id: SandboxId) {
    sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(pool)
        .await
        .expect("delete sandbox fixture");
}

async fn networking_state(pool: &PgPool, sandbox_id: SandboxId) -> (String, String, i64) {
    sqlx::query_as(
        r#"
        SELECT networking_status, networking_policy_hash, networking_policy_version
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(pool)
    .await
    .expect("load sandbox networking state")
}

#[tokio::test]
async fn same_policy_repush_keeps_generation_and_returns_to_pending() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;

    let first = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation");
    assert_eq!(first.policy_hash, "policy-a");
    assert_eq!(first.policy_version, 1);
    assert!(
        queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &first)
            .await
            .expect("ack first policy generation")
    );

    let repush = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare same policy after in-memory xDS state loss");
    assert_eq!(repush, first);
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        ("pending".to_string(), "policy-a".to_string(), 1)
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn stale_ack_cannot_mark_a_newer_policy_generation_ready() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;

    let first = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation");
    let second = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer policy generation");
    assert_eq!(second.policy_version, first.policy_version + 1);

    assert!(
        !queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &first)
            .await
            .expect("reject stale ACK")
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        ("pending".to_string(), "policy-b".to_string(), 2)
    );

    assert!(
        queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &second)
            .await
            .expect("ack current policy generation")
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        ("ready".to_string(), "policy-b".to_string(), 2)
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn stale_failure_cannot_nack_a_newer_policy_generation() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let desired = json!({"networking": {"type": "limited"}});
    let rendered = json!({"routes": []});

    let first = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation");
    let second = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer policy generation");

    assert!(!queries::record_network_policy_failure_detail(
        &pool,
        queries::UpsertNetworkPolicy {
            sandbox_id,
            session_id: None,
            task_id: None,
            generation: &first,
            desired_policy_json: &desired,
            rendered_summary_json: &rendered,
        },
        "stale failure",
    )
    .await
    .expect("ignore stale policy failure"));
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        ("pending".to_string(), "policy-b".to_string(), 2)
    );

    assert!(queries::record_network_policy_failure_detail(
        &pool,
        queries::UpsertNetworkPolicy {
            sandbox_id,
            session_id: None,
            task_id: None,
            generation: &second,
            desired_policy_json: &desired,
            rendered_summary_json: &rendered,
        },
        "current failure",
    )
    .await
    .expect("record current policy failure"));
    let state: (String, String, i64, Option<String>) = sqlx::query_as(
        r#"
        SELECT networking_status, networking_policy_hash,
               networking_policy_version, networking_last_error
        FROM joysafeter_sandboxes
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("load failed current generation");
    assert_eq!(
        state,
        (
            "nacked".to_string(),
            "policy-b".to_string(),
            2,
            Some("current failure".to_string()),
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn late_failure_cannot_replace_an_acknowledged_generation() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let desired = json!({"networking": {"type": "limited"}});
    let rendered = json!({"routes": []});

    let generation = queries::prepare_sandbox_network_policy_push(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare policy generation");
    assert!(
        queries::mark_sandbox_network_policy_acked(&pool, sandbox_id, &generation)
            .await
            .expect("ack policy generation")
    );

    assert!(!queries::record_network_policy_failure_detail(
        &pool,
        queries::UpsertNetworkPolicy {
            sandbox_id,
            session_id: None,
            task_id: None,
            generation: &generation,
            desired_policy_json: &desired,
            rendered_summary_json: &rendered,
        },
        "late failure after ACK",
    )
    .await
    .expect("ignore late policy failure"));
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        ("ready".to_string(), "policy-a".to_string(), 1)
    );

    let policy_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM joysafeter_sandbox_network_policies WHERE sandbox_id = $1",
    )
    .bind(sandbox_id)
    .fetch_one(&pool)
    .await
    .expect("count policy audit rows");
    assert_eq!(policy_rows, 0);

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn network_policy_removal_follows_current_durable_lifecycle() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;

    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET status = 'running',
            config = '{"fingerprint":{"networking":{"type":"limited"}}}'::jsonb
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .execute(&pool)
    .await
    .expect("mark sandbox as live limited networking");

    assert!(
        !queries::network_policy_removal_is_current(&pool, sandbox_id)
            .await
            .expect("reject stale removal for live limited sandbox")
    );

    sqlx::query("UPDATE joysafeter_sandboxes SET status = 'stopped' WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("stop sandbox");
    assert!(
        queries::network_policy_removal_is_current(&pool, sandbox_id)
            .await
            .expect("allow removal for stopped sandbox")
    );

    delete_sandbox(&pool, sandbox_id).await;
    assert!(
        queries::network_policy_removal_is_current(&pool, sandbox_id)
            .await
            .expect("allow cleanup for absent sandbox")
    );
}
