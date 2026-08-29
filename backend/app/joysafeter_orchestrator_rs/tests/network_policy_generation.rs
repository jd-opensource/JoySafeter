use std::env;

use joysafeter_orchestrator::db::queries;
use joysafeter_orchestrator::ids::{SandboxId, SandboxNetworkPolicyId};
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

async fn networking_state(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> (String, Option<String>, i64, Option<String>, Option<i64>) {
    sqlx::query_as(
        r#"
        SELECT networking_status, networking_policy_hash, networking_policy_version,
               networking_applied_hash, networking_applied_version
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
async fn same_policy_prepare_keeps_ready_generation_ready() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;

    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation");
    assert!(matches!(
        first,
        queries::NetworkPolicyPrepareOutcome::Pending(_)
    ));
    let first = first.into_generation();
    assert_eq!(first.policy_hash, "policy-a");
    assert_eq!(first.policy_version, 1);
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &first)
            .await
            .expect("ack first policy generation"),
        queries::NetworkPolicyAckOutcome::Applied
    );

    let repush = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare same ready policy");
    assert_eq!(
        repush,
        queries::NetworkPolicyPrepareOutcome::AlreadyReady(first.clone())
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "ready".to_string(),
            Some("policy-a".to_string()),
            1,
            Some("policy-a".to_string()),
            Some(1),
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn duplicate_ack_is_idempotent() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let generation = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare policy generation")
        .into_generation();

    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("apply policy ACK"),
        queries::NetworkPolicyAckOutcome::Applied
    );
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("repeat policy ACK"),
        queries::NetworkPolicyAckOutcome::AlreadyReady
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn ready_generation_cannot_be_claimed_for_failed_setup_cleanup() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let external_id = format!("network-policy-generation-{sandbox_id}");
    let generation = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare policy generation")
        .into_generation();
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("ack policy generation"),
        queries::NetworkPolicyAckOutcome::Applied
    );

    assert!(
        !queries::begin_owned_sandbox_cleanup(&pool, sandbox_id, &external_id, &generation)
            .await
            .expect("ready generation rejects stale cleanup")
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn stale_generation_cannot_claim_newer_pending_sandbox_for_cleanup() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let external_id = format!("network-policy-generation-{sandbox_id}");
    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation")
        .into_generation();
    let second = queries::prepare_generation(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer policy generation")
        .into_generation();

    assert!(
        !queries::begin_owned_sandbox_cleanup(&pool, sandbox_id, &external_id, &first)
            .await
            .expect("stale generation rejects cleanup")
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "pending".to_string(),
            Some("policy-b".to_string()),
            second.policy_version,
            None,
            None,
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn current_failed_generation_can_claim_cleanup_ownership() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let external_id = format!("network-policy-generation-{sandbox_id}");
    let generation = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare policy generation")
        .into_generation();

    assert!(
        queries::begin_owned_sandbox_cleanup(&pool, sandbox_id, &external_id, &generation)
            .await
            .expect("current failed generation claims cleanup")
    );
    let status: String =
        sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load claimed sandbox status");
    assert_eq!(status, "stopping");

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn stale_ack_cannot_mark_a_newer_policy_generation_ready() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;

    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation")
        .into_generation();
    let second = queries::prepare_generation(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer policy generation")
        .into_generation();
    assert_eq!(second.policy_version, first.policy_version + 1);

    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &first)
            .await
            .expect("reject stale ACK"),
        queries::NetworkPolicyAckOutcome::Stale
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "pending".to_string(),
            Some("policy-b".to_string()),
            2,
            None,
            None,
        )
    );

    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &second)
            .await
            .expect("ack current policy generation"),
        queries::NetworkPolicyAckOutcome::Applied
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "ready".to_string(),
            Some("policy-b".to_string()),
            2,
            Some("policy-b".to_string()),
            Some(2),
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn stale_failure_cannot_nack_a_newer_policy_generation() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let desired = json!({"networking": {"type": "limited"}});
    let rendered = json!({"routes": []});

    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first policy generation")
        .into_generation();
    let second = queries::prepare_generation(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer policy generation")
        .into_generation();

    assert_eq!(
        queries::record_generation_failure(
            &pool,
            queries::UpsertNetworkPolicy {
                id: SandboxNetworkPolicyId::new(),
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
        .expect("ignore stale policy failure"),
        queries::NetworkPolicyFailureOutcome::Stale
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "pending".to_string(),
            Some("policy-b".to_string()),
            2,
            None,
            None,
        )
    );

    assert_eq!(
        queries::record_generation_failure(
            &pool,
            queries::UpsertNetworkPolicy {
                id: SandboxNetworkPolicyId::new(),
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
        .expect("record current policy failure"),
        queries::NetworkPolicyFailureOutcome::Recorded
    );
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

    let generation = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare policy generation")
        .into_generation();
    assert_eq!(
        queries::mark_generation_applied(&pool, sandbox_id, &generation)
            .await
            .expect("ack policy generation"),
        queries::NetworkPolicyAckOutcome::Applied
    );

    assert_eq!(
        queries::record_generation_failure(
            &pool,
            queries::UpsertNetworkPolicy {
                id: SandboxNetworkPolicyId::new(),
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
        .expect("ignore late policy failure"),
        queries::NetworkPolicyFailureOutcome::AlreadyReady
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "ready".to_string(),
            Some("policy-a".to_string()),
            1,
            Some("policy-a".to_string()),
            Some(1),
        )
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
async fn recovery_quarantine_is_fenced_by_the_observed_generation() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first generation")
        .into_generation();
    let second = queries::prepare_generation(&pool, sandbox_id, "policy-b")
        .await
        .expect("prepare newer generation")
        .into_generation();

    assert_eq!(
        queries::quarantine_recovery_generation(
            &pool,
            sandbox_id,
            Some(&first.policy_hash),
            first.policy_version,
            "late recovery failure",
        )
        .await
        .expect("fence late quarantine"),
        queries::NetworkPolicyFailureOutcome::Stale
    );
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "pending".to_string(),
            Some(second.policy_hash),
            second.policy_version,
            None,
            None,
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn recovery_prepare_advances_canonical_generation_and_clears_old_proof() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    let first = queries::prepare_generation(&pool, sandbox_id, "policy-a")
        .await
        .expect("prepare first generation")
        .into_generation();
    queries::mark_generation_applied(&pool, sandbox_id, &first)
        .await
        .expect("apply first generation");

    let prepared = queries::prepare_recovery_generation(
        &pool,
        sandbox_id,
        Some(&first.policy_hash),
        first.policy_version,
        "policy-b",
    )
    .await
    .expect("prepare canonical recovery generation");
    let queries::RecoveryGenerationPrepareOutcome::Pending(second) = prepared else {
        panic!("expected a pending recovery generation");
    };
    assert_eq!(second.policy_hash, "policy-b");
    assert_eq!(second.policy_version, first.policy_version + 1);
    assert_eq!(
        networking_state(&pool, sandbox_id).await,
        (
            "pending".to_string(),
            Some("policy-b".to_string()),
            second.policy_version,
            None,
            None,
        )
    );

    delete_sandbox(&pool, sandbox_id).await;
}

#[tokio::test]
async fn recovery_inventory_includes_inconsistent_live_network_policy_rows() {
    let pool = test_pool().await;
    let sandbox_id = create_sandbox(&pool).await;
    queries::prepare_generation(&pool, sandbox_id, "orphaned-policy")
        .await
        .expect("prepare orphaned network policy state");

    let inventory = queries::load_recovery_inventory(&pool)
        .await
        .expect("load recovery inventory");
    assert!(inventory.iter().any(|sandbox| sandbox.id == sandbox_id));

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
