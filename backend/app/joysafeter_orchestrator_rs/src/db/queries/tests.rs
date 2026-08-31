use std::env;
use std::sync::Arc;

use chrono::{Duration, Utc};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

use super::*;
use crate::config::JoySafeterConfig;
use crate::events::bus::EventBus;
use crate::events::envelope::EventEnvelope;
use crate::events::persist::EventPersister;
use crate::events::session_state::SessionStateSubscriber;
use crate::events::stream_publisher::EventStreamPublisher;
use crate::ids::{AgentId, EventId, SandboxId, SessionId, SkillId, SkillVersionId, TaskId};
use crate::runtime_config::RuntimeConfig;

fn database_url() -> Option<String> {
    env::var("JOYSAFETER_TEST_DATABASE_URL")
        .ok()
        .or_else(|| env::var("DATABASE_URL").ok())
        .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
}

async fn test_pool() -> Option<PgPool> {
    let Some(url) = database_url() else {
        eprintln!("skipping real Postgres scenario test: DATABASE_URL is not set");
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

#[tokio::test]
async fn loaded_skill_usage_is_idempotent_per_sandbox_artifact() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let row = sqlx::query_as::<_, (SandboxId, SkillId, SkillVersionId, String, String)>(
        r#"
        SELECT sandbox.id, version.skill_id, version.id, version.version, version.skill_name
        FROM joysafeter_sandboxes sandbox
        CROSS JOIN joysafeter_skill_versions version
        LIMIT 1
        "#,
    )
    .fetch_optional(&pool)
    .await
    .expect("load sandbox and published skill version for idempotency test");
    let Some((sandbox_id, skill_id, skill_version_id, skill_version, skill_name)) = row else {
        eprintln!("skipping skill usage idempotency test: no sandbox or skill version fixture");
        return;
    };
    let artifact_hash = "f".repeat(64);
    sqlx::query(
        "DELETE FROM joysafeter_skill_usage_log WHERE sandbox_id = $1 AND artifact_hash = $2",
    )
    .bind(sandbox_id)
    .bind(&artifact_hash)
    .execute(&pool)
    .await
    .expect("clear prior idempotency test rows");
    let usage = LoadedSkillUsage {
        skill_id,
        skill_version,
        skill_version_id,
        skill_name,
        skill_source_type: Some("test".to_string()),
        target: "skills".to_string(),
        security_scan_id: None,
        target_hash: None,
        artifact_hash: artifact_hash.clone(),
    };

    assert_eq!(
        record_loaded_skill_usage(&pool, sandbox_id, &usage)
            .await
            .expect("insert first loaded skill usage"),
        RecordLoadedSkillUsage::Inserted
    );
    assert_eq!(
        record_loaded_skill_usage(&pool, sandbox_id, &usage)
            .await
            .expect("deduplicate repeated loaded skill usage"),
        RecordLoadedSkillUsage::AlreadyRecorded
    );
    assert_eq!(
        record_loaded_skill_usage(&pool, SandboxId::from_uuid(Uuid::now_v7()), &usage)
            .await
            .expect("distinguish missing sandbox from idempotent conflict"),
        RecordLoadedSkillUsage::SandboxMissing
    );

    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM joysafeter_skill_usage_log WHERE sandbox_id = $1 AND artifact_hash = $2",
    )
    .bind(sandbox_id)
    .bind(&artifact_hash)
    .fetch_one(&pool)
    .await
    .expect("count idempotent skill usage rows");
    assert_eq!(count, 1);

    sqlx::query(
        "DELETE FROM joysafeter_skill_usage_log WHERE sandbox_id = $1 AND artifact_hash = $2",
    )
    .bind(sandbox_id)
    .bind(&artifact_hash)
    .execute(&pool)
    .await
    .expect("clean up idempotency test row");
}

async fn create_agent_and_session(pool: &PgPool, status: &str) -> (AgentId, SessionId) {
    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let agent_name = format!("rust-status-scenario-{agent_id}");

    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (id, name, engine_kind, version)
        VALUES ($1, $2, 'claude', 1)
        "#,
    )
    .bind(agent_id)
    .bind(agent_name)
    .execute(pool)
    .await
    .expect("insert test agent");

    sqlx::query(
        r#"
        INSERT INTO joysafeter_sessions (id, agent_id, status)
        VALUES ($1, $2, $3)
        "#,
    )
    .bind(session_id)
    .bind(agent_id)
    .bind(status)
    .execute(pool)
    .await
    .expect("insert test session");

    (agent_id, session_id)
}

async fn cleanup(pool: &PgPool, agent_id: AgentId, session_id: SessionId) {
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
}

async fn create_task(
    pool: &PgPool,
    agent_id: AgentId,
    session_id: SessionId,
    status: &str,
) -> TaskId {
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    sqlx::query(
        r#"
        INSERT INTO joysafeter_tasks (
            id, agent_id, chat_session_id, status, prompt, output,
            timeout_sec, retry_count, max_retries
        )
        VALUES ($1, $2, $3, $4, 'test prompt', '', 7200, 0, 2)
        "#,
    )
    .bind(task_id)
    .bind(agent_id)
    .bind(session_id)
    .bind(status)
    .execute(pool)
    .await
    .expect("insert test task");
    task_id
}

#[tokio::test]
async fn staged_sandbox_auth_is_durable_before_external_id_activation() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let expires_at = Utc::now() + Duration::minutes(5);
    let token_digest = crate::kernel::runtime_auth::runner_token_digest("runner-token");

    let result = async {
        stage_sandbox(
            &pool,
            sandbox_id,
            "test",
            "joysafeter/test:latest",
            None,
            None,
            None,
            Some(&json!({"provisioning": {"stage": "admission"}})),
            &token_digest,
            expires_at,
            None,
        )
        .await
        .expect("persist staged sandbox admission");

        let staged: (
            String,
            String,
            Option<String>,
            Option<chrono::DateTime<Utc>>,
        ) = sqlx::query_as(
            r#"
                SELECT external_id, runner_auth_state, runner_token_digest,
                       runner_auth_expires_at
                FROM joysafeter_sandboxes
                WHERE id = $1
                "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load staged sandbox");
        assert_eq!(staged.0, "");
        assert_eq!(staged.1, "admission");
        assert_eq!(staged.2.as_deref(), Some(token_digest.as_str()));
        assert_eq!(staged.3, Some(expires_at));

        assert!(activate_staged_sandbox(
            &pool,
            sandbox_id,
            "provider-external-id",
            &json!({"provisioning": {"stage": "container_started"}}),
            None,
            None,
            None,
        )
        .await
        .expect("activate staged sandbox"));

        let active: (
            String,
            String,
            Option<String>,
            Option<chrono::DateTime<Utc>>,
        ) = sqlx::query_as(
            r#"
                SELECT external_id, runner_auth_state, runner_token_digest,
                       runner_auth_expires_at
                FROM joysafeter_sandboxes
                WHERE id = $1
                "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load active sandbox");
        assert_eq!(active.0, "provider-external-id");
        assert_eq!(active.1, "active");
        assert_eq!(active.2.as_deref(), Some(token_digest.as_str()));
        assert_eq!(active.3, None);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn expired_staged_sandbox_cannot_activate() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        let token_digest = crate::kernel::runtime_auth::runner_token_digest("runner-token");
        stage_sandbox(
            &pool,
            sandbox_id,
            "test",
            "joysafeter/test:latest",
            None,
            None,
            None,
            Some(&json!({"provisioning": {"stage": "admission"}})),
            &token_digest,
            Utc::now() - Duration::seconds(1),
            None,
        )
        .await
        .expect("persist expired staged sandbox fixture");

        assert!(!activate_staged_sandbox(
            &pool,
            sandbox_id,
            "provider-external-id",
            &json!({"provisioning": {"stage": "container_started"}}),
            None,
            None,
            None,
        )
        .await
        .expect("reject expired staged sandbox"));

        let state: (String, String) = sqlx::query_as(
            "SELECT external_id, runner_auth_state FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load rejected staged sandbox");
        assert_eq!(state, (String::new(), "admission".to_string()));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn transition_task_cas_sets_terminal_completion_metadata() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        sqlx::query(
            "UPDATE joysafeter_tasks SET started_at = NOW() - INTERVAL '3 seconds' WHERE id = $1",
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("backdate running task start");

        let transitioned = transition_task_cas(
            &pool,
            task_id,
            "running",
            "timeout",
            Some("server-side deadline"),
            None,
        )
        .await
        .expect("timeout CAS transition");
        assert!(transitioned);

        let row: (
            String,
            Option<String>,
            Option<chrono::DateTime<chrono::Utc>>,
            Option<i64>,
        ) = sqlx::query_as(
            "SELECT status, error, completed_at, duration_ms FROM joysafeter_tasks WHERE id = $1",
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load terminal task metadata");

        assert_eq!(row.0, "timeout");
        assert_eq!(row.1.as_deref(), Some("server-side deadline"));
        assert!(row.2.is_some());
        assert!(row.3.unwrap_or_default() >= 2_000);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn scheduling_retry_helpers_do_not_move_running_tasks_back_to_pending() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let scheduling_task_id = create_task(&pool, agent_id, session_id, "scheduling").await;
    let running_task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let reset = reset_scheduling_task_to_pending(&pool, scheduling_task_id)
            .await
            .expect("reset scheduling task");
        assert!(reset);

        let scheduling_row: (String, i32) =
            sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                .bind(scheduling_task_id)
                .fetch_one(&pool)
                .await
                .expect("load reset scheduling task");
        assert_eq!(scheduling_row.0, "pending");
        assert_eq!(scheduling_row.1, 0);

        let reset_running = reset_scheduling_task_to_pending(&pool, running_task_id)
            .await
            .expect("reset running task should be no-op");
        assert!(!reset_running);

        let retry_running = increment_scheduling_retry(&pool, running_task_id, 0)
            .await
            .expect("retry running task should be no-op");
        assert!(!retry_running);

        let running_row: (String, i32) =
            sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                .bind(running_task_id)
                .fetch_one(&pool)
                .await
                .expect("load running task after scheduling-only helpers");
        assert_eq!(running_row.0, "running");
        assert_eq!(running_row.1, 0);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn running_retry_is_owner_epoch_fenced_and_clears_lease() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET owner_instance_id = 'owner-a',
                owner_epoch = 41,
                lease_expires_at = NOW() + INTERVAL '60 seconds',
                started_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("stamp owner lease");

        let stale_retry = increment_running_retry(&pool, task_id, 0, Some(40))
            .await
            .expect("stale owner retry should be a clean CAS miss");
        assert!(!stale_retry);

        let owned_retry = increment_running_retry(&pool, task_id, 0, Some(41))
            .await
            .expect("current owner retry should succeed");
        assert!(owned_retry);

        let row: (
            String,
            i32,
            Option<String>,
            Option<i64>,
            Option<chrono::DateTime<chrono::Utc>>,
            Option<chrono::DateTime<chrono::Utc>>,
        ) = sqlx::query_as(
            r#"
            SELECT status, retry_count, owner_instance_id, owner_epoch, lease_expires_at, started_at
            FROM joysafeter_tasks
            WHERE id = $1
            "#,
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load retried task");

        assert_eq!(row.0, "pending");
        assert_eq!(row.1, 1);
        assert!(row.2.is_none());
        assert!(row.3.is_none());
        assert!(row.4.is_none());
        assert!(row.5.is_none());
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn observed_owner_epoch_transition_does_not_mutate_reclaimed_task() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let null_owner_task = create_task(&pool, agent_id, session_id, "running").await;
    let epoch_owner_task = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET owner_instance_id = 'owner-b',
                owner_epoch = 51,
                started_at = NOW(),
                lease_expires_at = NOW() + INTERVAL '60 seconds'
            WHERE id = $1
            "#,
        )
        .bind(null_owner_task)
        .execute(&pool)
        .await
        .expect("simulate reclaim after null-owner observation");

        let stale_null_transition = transition_task_cas_observed_owner_epoch(
            &pool,
            null_owner_task,
            "running",
            "timeout",
            Some("stale null-owner watchdog"),
            None,
        )
        .await
        .expect("stale null owner transition should be a clean CAS miss");
        assert!(!stale_null_transition);

        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET owner_instance_id = 'owner-a',
                owner_epoch = 41,
                started_at = NOW() - INTERVAL '10 seconds',
                lease_expires_at = NOW() + INTERVAL '60 seconds'
            WHERE id = $1
            "#,
        )
        .bind(epoch_owner_task)
        .execute(&pool)
        .await
        .expect("stamp original owner");
        sqlx::query(
            r#"
            UPDATE joysafeter_tasks
            SET owner_instance_id = 'owner-b',
                owner_epoch = 42,
                started_at = NOW(),
                lease_expires_at = NOW() + INTERVAL '60 seconds'
            WHERE id = $1
            "#,
        )
        .bind(epoch_owner_task)
        .execute(&pool)
        .await
        .expect("simulate reclaim with new owner");

        let stale_epoch_transition = transition_task_cas_observed_owner_epoch(
            &pool,
            epoch_owner_task,
            "running",
            "timeout",
            Some("stale owner watchdog"),
            Some(41),
        )
        .await
        .expect("stale owner transition should be a clean CAS miss");
        assert!(!stale_epoch_transition);

        let current_epoch_transition = transition_task_cas_observed_owner_epoch(
            &pool,
            epoch_owner_task,
            "running",
            "completed",
            None,
            Some(42),
        )
        .await
        .expect("current owner transition should succeed");
        assert!(current_epoch_transition);

        let null_owner_row: (String, Option<i64>, Option<String>) =
            sqlx::query_as("SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1")
                .bind(null_owner_task)
                .fetch_one(&pool)
                .await
                .expect("load null-owner reclaimed task");
        assert_eq!(null_owner_row.0, "running");
        assert_eq!(null_owner_row.1, Some(51));
        assert!(null_owner_row.2.is_none());

        let epoch_owner_row: (String, Option<i64>, Option<String>) =
            sqlx::query_as("SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1")
                .bind(epoch_owner_task)
                .fetch_one(&pool)
                .await
                .expect("load epoch-owner reclaimed task");
        assert_eq!(epoch_owner_row.0, "completed");
        assert!(epoch_owner_row.1.is_none());
        assert!(epoch_owner_row.2.is_none());
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn lease_renewal_matches_task_id_and_owner_epoch_pair() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_a = create_task(&pool, agent_id, session_id, "running").await;
    let task_b = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        for (task_id, owner_epoch) in [(task_a, 10_i64), (task_b, 20_i64)] {
            sqlx::query(
                r#"
                UPDATE joysafeter_tasks
                SET owner_instance_id = 'owner-a',
                    owner_epoch = $2,
                    lease_expires_at = NOW() - INTERVAL '10 seconds'
                WHERE id = $1
                "#,
            )
            .bind(task_id)
            .bind(owner_epoch)
            .execute(&pool)
            .await
            .expect("stamp expired owner lease");
        }

        let renewed =
            renew_running_task_leases(&pool, "owner-a", 60, &[(task_a, 10), (task_b, 19)])
                .await
                .expect("renew matching leases");
        assert_eq!(renewed, 1);

        let rows: Vec<(TaskId, bool)> = sqlx::query_as(
            r#"
            SELECT id, lease_expires_at > NOW() AS renewed
            FROM joysafeter_tasks
            WHERE id = ANY($1)
            ORDER BY id
            "#,
        )
        .bind(&[task_a, task_b][..])
        .fetch_all(&pool)
        .await
        .expect("load renewal state");

        assert!(rows.iter().any(|(id, renewed)| *id == task_a && *renewed));
        assert!(rows.iter().any(|(id, renewed)| *id == task_b && !*renewed));
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn complete_sandbox_task_returns_running_sandbox_to_idle() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("complete-running-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create running completion sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle");
        transition_sandbox_cas(&pool, sandbox_id, "idle", "running")
            .await
            .expect("sandbox running");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("set sandbox last task");

        let completed = complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("complete running sandbox");
        assert!(completed);

        let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
            sqlx::query_as(
                "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load completed sandbox");
        assert_eq!(sandbox.0, "idle");
        assert_eq!(sandbox.1, None);
        assert!(sandbox.2.is_some());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn complete_sandbox_task_does_not_resurrect_error_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("complete-error-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create error completion sandbox");
        mark_sandbox_error(&pool, sandbox_id, Some("setup failed"))
            .await
            .expect("mark sandbox error");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("set errored sandbox last task");

        let completed = complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("complete errored sandbox");
        assert!(!completed);

        let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
            "SELECT status, last_task_id, config FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load errored sandbox after completion");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1, None);
        assert_eq!(
            sandbox
                .2
                .get("setup_error")
                .and_then(serde_json::Value::as_str),
            Some("setup failed")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn transition_sandbox_rejects_invalid_error_to_idle_resurrection() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("invalid-resurrection-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create sandbox for invalid transition");
        mark_sandbox_error(&pool, sandbox_id, Some("setup failed"))
            .await
            .expect("mark sandbox error");

        let transitioned = transition_sandbox_cas(&pool, sandbox_id, "error", "idle")
            .await
            .expect("attempt invalid transition");
        assert!(!transitioned);

        let sandbox: (String, serde_json::Value) =
            sqlx::query_as("SELECT status, config FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after rejected transition");
        assert_eq!(sandbox.0, "error");
        assert_eq!(
            sandbox
                .1
                .get("setup_error")
                .and_then(serde_json::Value::as_str),
            Some("setup failed")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn mark_sandbox_error_does_not_clear_active_task_binding() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("active-error-guard-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create active sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle");
        sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
            .bind(task_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("bind active task to sandbox");
        assert!(
            start_sandbox_task(&pool, sandbox_id, task_id)
                .await
                .expect("start sandbox task")
        );

        let marked = mark_sandbox_error(&pool, sandbox_id, Some("late setup failure"))
            .await
            .expect("attempt late sandbox error");
        assert!(!marked);

        let sandbox: (String, Option<TaskId>, Option<String>) = sqlx::query_as(
            "SELECT status, last_task_id, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load protected active sandbox");
        assert_eq!(sandbox.0, "running");
        assert_eq!(sandbox.1, Some(task_id));
        assert_eq!(sandbox.2, None);

        let task: (String, Option<SandboxId>) =
            sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load protected active task");
        assert_eq!(task.0, "running");
        assert_eq!(task.1, Some(sandbox_id));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn runner_failure_quarantine_fences_sandbox_even_with_scheduling_task() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "scheduling").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("runner-failure-quarantine-{sandbox_id}"),
            "docker",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create runner failure sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "provisioning")
            .await
            .expect("sandbox provisioning");
        sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET runner_auth_state = 'active', runner_token_digest = $2
            WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .bind(crate::kernel::runtime_auth::runner_token_digest(
            "runner-token",
        ))
        .execute(&pool)
        .await
        .expect("activate runner credential");
        sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
            .bind(task_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("bind scheduling task");

        let recovery = quarantine_and_recover_runner_failure(
            &pool,
            sandbox_id,
            "runner_protocol_incompatible",
            "runner protocol is missing setup_ack_v1",
        )
        .await
        .expect("quarantine incompatible runner")
        .expect("healthy sandbox should be quarantined");
        assert_eq!(recovery.reset_tasks.len(), 1);
        assert!(recovery.failed_tasks.is_empty());

        let sandbox: (
            String,
            String,
            Option<String>,
            Option<String>,
            Option<String>,
        ) = sqlx::query_as(
            r#"
                SELECT status,
                       runner_auth_state,
                       runner_token_digest,
                       config #>> '{runtime_failure,code}',
                       config->>'setup_error'
                FROM joysafeter_sandboxes
                WHERE id = $1
                "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load quarantined sandbox");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1, "revoked");
        assert_eq!(sandbox.2, None);
        assert_eq!(sandbox.3.as_deref(), Some("runner_protocol_incompatible"));
        assert_eq!(
            sandbox.4.as_deref(),
            Some("runner protocol is missing setup_ack_v1")
        );

        let task: (String, Option<SandboxId>) =
            sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after sandbox quarantine");
        assert_eq!(task.0, "pending");
        assert_eq!(task.1, None);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn runner_failure_preserves_concurrent_stop_claim_while_revoking_runtime() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "scheduling").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("runner-failure-stop-race-{sandbox_id}"),
            "docker",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create runner failure race sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "provisioning")
            .await
            .expect("sandbox provisioning");
        sqlx::query(
            r#"
            UPDATE joysafeter_sandboxes
            SET runner_auth_state = 'active', runner_token_digest = $2,
                status = 'stopping'
            WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .bind(crate::kernel::runtime_auth::runner_token_digest(
            "runner-token",
        ))
        .execute(&pool)
        .await
        .expect("race lifecycle stop after Runner verification");
        sqlx::query("UPDATE joysafeter_tasks SET sandbox_id = $2 WHERE id = $1")
            .bind(task_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("bind scheduling task");

        let recovery = quarantine_and_recover_runner_failure(
            &pool,
            sandbox_id,
            "runner_protocol_incompatible",
            "runner protocol is missing setup_ack_v1",
        )
        .await
        .expect("record incompatible runner during stop race")
        .expect("failure ownership must survive a concurrent lifecycle stop claim");
        assert_eq!(recovery.reset_tasks.len(), 1);
        assert!(recovery.failed_tasks.is_empty());

        let sandbox: (String, String, Option<String>) = sqlx::query_as(
            r#"
            SELECT status, runner_auth_state, config #>> '{runtime_failure,code}'
            FROM joysafeter_sandboxes
            WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load stop-raced sandbox");
        assert_eq!(sandbox.0, "stopping");
        assert_eq!(sandbox.1, "revoked");
        assert_eq!(sandbox.2.as_deref(), Some("runner_protocol_incompatible"));

        let task: (String, Option<SandboxId>) =
            sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load recovered task after stop race");
        assert_eq!(task.0, "pending");
        assert_eq!(task.1, None);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn atomic_session_status_helper_writes_status_event_and_canonical_seq() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = TaskId::from_uuid(Uuid::now_v7());

    let result = async {
        let running_payload = json!({"task_id": task_id.to_string()});
        let running = update_session_status_and_insert_event(
            &pool,
            session_id,
            "running",
            None,
            "session.status_running",
            &running_payload,
        )
        .await
        .expect("running transition succeeds")
        .expect("running transition inserts event");

        assert_eq!(running.1, 1);

        let session_row: (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after running transition");
        assert_eq!(session_row.0, "running");
        assert_eq!(session_row.1, None);

        let running_event: (EventId, String, serde_json::Value, i64) = sqlx::query_as(
            "SELECT id, event_type, payload, seq FROM joysafeter_session_events WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("load running event");
        assert_eq!(running_event.0, running.0);
        assert_eq!(running_event.1, "session.status_running");
        assert_eq!(running_event.2, running_payload);
        assert_eq!(running_event.3, 1);

        let duplicate = update_session_status_and_insert_event(
            &pool,
            session_id,
            "running",
            None,
            "session.status_running",
            &running_payload,
        )
        .await
        .expect("duplicate running transition is accepted as no-op");
        assert_eq!(duplicate, None);

        let count_after_duplicate: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count events after duplicate");
        assert_eq!(count_after_duplicate, 1);

        let stop_reason = json!({"type": "end_turn"});
        let idle_payload = json!({
            "task_id": task_id.to_string(),
            "stop_reason": stop_reason.clone()
        });
        let idle = update_session_status_and_insert_event(
            &pool,
            session_id,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &idle_payload,
        )
        .await
        .expect("idle transition succeeds")
        .expect("idle transition inserts event");
        assert_eq!(idle.1, 2);

        let final_session: (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after idle transition");
        assert_eq!(final_session.0, "idle");
        assert_eq!(final_session.1, Some(stop_reason));

        let events: Vec<(String, i64)> = sqlx::query_as(
            r#"
            SELECT event_type, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            ORDER BY seq ASC
            "#,
        )
        .bind(session_id)
        .fetch_all(&pool)
        .await
        .expect("load ordered status events");
        assert_eq!(
            events,
            vec![
                ("session.status_running".to_string(), 1),
                ("session.status_idle".to_string(), 2),
            ]
        );
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn atomic_session_status_helper_rolls_back_status_when_seq_assignment_fails() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;

    let result = async {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
            VALUES ($1, $2, 'agent.message', '{}'::jsonb, $3)
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(i64::MAX)
        .execute(&pool)
        .await
        .expect("insert max seq sentinel");

        let payload = json!({"task_id": Uuid::now_v7().to_string()});
        let err = update_session_status_and_insert_event(
            &pool,
            session_id,
            "running",
            None,
            "session.status_running",
            &payload,
        )
        .await
        .expect_err("seq overflow must fail the transition");

        assert!(
            err.to_string().contains("out of range") || err.to_string().contains("overflow"),
            "unexpected error: {err}"
        );

        let status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after failed transition");
        assert_eq!(status, "idle");

        let status_event_count: i64 = sqlx::query_scalar(
            r#"
            SELECT COUNT(*)
            FROM joysafeter_session_events
            WHERE session_id = $1 AND event_type = 'session.status_running'
            "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count failed status events");
        assert_eq!(status_event_count, 0);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn db_persisted_status_envelope_does_not_reenter_event_bus_db_persister() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = TaskId::from_uuid(Uuid::now_v7());

    let result = async {
        let payload = json!({"task_id": task_id.to_string()});
        let (event_id, seq) = update_session_status_and_insert_event(
            &pool,
            session_id,
            "running",
            None,
            "session.status_running",
            &payload,
        )
        .await
        .expect("running transition succeeds")
        .expect("running transition inserts event");

        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = false;
        config.event_batch_max_size = 1;
        config.event_batch_max_delay_ms = 1;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

        let envelope = EventEnvelope::new(session_id, "session.status_running", payload)
            .with_task(task_id)
            .status_change(None)
            .with_db_persisted(event_id, seq);
        event_bus.publish(envelope).await;
        event_bus.flush().await;

        let rows: Vec<(EventId, String, i64)> = sqlx::query_as(
            r#"
            SELECT id, event_type, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            ORDER BY seq ASC
            "#,
        )
        .bind(session_id)
        .fetch_all(&pool)
        .await
        .expect("load events after publishing db-persisted envelope");

        assert_eq!(
            rows,
            vec![(event_id, "session.status_running".to_string(), 1)]
        );
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_bus_persists_runner_event_with_canonical_db_seq_not_runner_seq() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = false;
        config.event_batch_max_size = 1;
        config.event_batch_max_delay_ms = 1;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

        let payload = json!({"content": "hello from runner"});
        let envelope = EventEnvelope::new(session_id, "agent.message", payload.clone())
            .with_task(task_id)
            .with_runner_seq(777)
            .flush_immediately();
        let event_id = envelope.event_id.expect("new envelope has event id");
        event_bus.publish(envelope).await;
        event_bus.flush().await;

        let row: (EventId, String, serde_json::Value, i64) = sqlx::query_as(
            r#"
            SELECT id, event_type, payload, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("load persisted runner event");

        assert_eq!(row.0, event_id);
        assert_eq!(row.1, "agent.message");
        assert_eq!(row.2, payload);
        assert_eq!(row.3, 1, "DB canonical seq must not reuse runner seq");
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn running_status_with_preserved_terminal_reason_does_not_emit_duplicate_event() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let previous_reason = json!({"type": "end_turn"});
        sqlx::query("UPDATE joysafeter_sessions SET stop_reason = $2 WHERE id = $1")
            .bind(session_id)
            .bind(&previous_reason)
            .execute(&pool)
            .await
            .expect("seed preserved terminal stop reason");

        let payload = json!({"task_id": task_id.to_string()});
        sqlx::query(
            r#"
            INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
            VALUES ($1, $2, 'session.status_running', $3, 1, NOW())
            "#,
        )
        .bind(EventId::from_uuid(Uuid::now_v7()))
        .bind(session_id)
        .bind(&payload)
        .execute(&pool)
        .await
        .expect("seed original running event");

        let inserted = update_session_status_and_insert_event(
            &pool,
            session_id,
            "running",
            None,
            "session.status_running",
            &payload,
        )
        .await
        .expect("repeat running transition");

        assert_eq!(inserted, None);
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1 AND event_type = 'session.status_running'",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count running events");
        assert_eq!(count, 1);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_bus_stream_primary_falls_back_to_db_before_flush_immediate_returns() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = true;
        config.event_stream_fallback_to_db = true;
        config.event_batch_max_size = 10;
        config.event_batch_max_delay_ms = 60_000;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

        let payload = json!({"content": "stream fallback"});
        let envelope = EventEnvelope::new(session_id, "agent.message", payload.clone())
            .with_task(task_id)
            .flush_immediately();
        let event_id = envelope.event_id.expect("new envelope has event id");
        event_bus.publish(envelope).await;

        let row: (EventId, String, serde_json::Value, i64) = sqlx::query_as(
            r#"
            SELECT id, event_type, payload, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("fallback DB row should be visible when publish returns");

        assert_eq!(row.0, event_id);
        assert_eq!(row.1, "agent.message");
        assert_eq!(row.2, payload);
        assert_eq!(row.3, 1);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_bus_stream_mode_keeps_ordered_direct_db_durability_mirror() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = true;
        config.event_stream_fallback_to_db = false;
        config.event_batch_max_size = 1;
        config.event_batch_max_delay_ms = 1;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

        let envelope = EventEnvelope::new(
            session_id,
            "agent.message",
            json!({"content": "no fallback"}),
        )
        .with_task(task_id)
        .flush_immediately();
        event_bus.publish(envelope).await;
        event_bus.flush().await;

        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count events after stream publish failure without fallback");

        assert_eq!(
            count, 1,
            "stream mode must keep the ordered DB mirror so status events cannot overtake agent output"
        );
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_bus_flush_persists_all_agent_output_before_atomic_idle_status() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = true;
        config.event_stream_fallback_to_db = false;
        config.event_batch_max_size = 100;
        config.event_batch_max_delay_ms = 60_000;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);

        for (event_type, payload) in [
            ("agent.message", json!({"content": "first"})),
            ("agent.message", json!({"content": "second"})),
            (
                "span.model_request_end",
                json!({"model": "test-model", "usage": {"output_tokens": 2}}),
            ),
        ] {
            event_bus
                .publish(EventEnvelope::new(session_id, event_type, payload).with_task(task_id))
                .await;
        }
        event_bus.flush().await;

        let transitioned = transition_task_cas(&pool, task_id, "running", "completed", None, None)
            .await
            .expect("complete test task");
        assert!(transitioned);

        let stop_reason = json!({"type": "end_turn"});
        let idle_payload =
            json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
        let (_, idle_seq) = update_session_status_if_no_active_tasks_and_insert_event(
            &pool,
            session_id,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &idle_payload,
        )
        .await
        .expect("idle transition succeeds")
        .expect("idle transition inserts event");

        let rows: Vec<(String, serde_json::Value, i64)> = sqlx::query_as(
            r#"
            SELECT event_type, payload, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            ORDER BY seq ASC
            "#,
        )
        .bind(session_id)
        .fetch_all(&pool)
        .await
        .expect("load persisted output and idle boundary");

        assert_eq!(
            rows.iter()
                .map(|(event_type, _, seq)| (event_type.as_str(), *seq))
                .collect::<Vec<_>>(),
            vec![
                ("agent.message", 1),
                ("agent.message", 2),
                ("span.model_request_end", 3),
                ("session.status_idle", 4),
            ]
        );
        assert_eq!(rows[0].1, json!({"content": "first"}));
        assert_eq!(rows[1].1, json!({"content": "second"}));
        assert!(rows[..3].iter().all(|(_, _, seq)| *seq < idle_seq));
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_persister_redelivered_event_id_does_not_consume_next_db_seq() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;

    let result = async {
        let persister = EventPersister::new(
            pool.clone(),
            10,
            60_000,
            None,
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
            "rust-event-persister-test".to_string(),
        );

        let redelivered_id = EventId::from_uuid(Uuid::now_v7());
        let next_id = EventId::from_uuid(Uuid::now_v7());
        persister
            .push(
                redelivered_id,
                session_id,
                "agent.message",
                &json!({"content": "first delivery"}),
                None,
            )
            .await;
        persister.flush().await;

        persister
            .push(
                redelivered_id,
                session_id,
                "agent.message",
                &json!({"content": "redelivery"}),
                None,
            )
            .await;
        persister
            .push(
                next_id,
                session_id,
                "agent.message",
                &json!({"content": "next event"}),
                None,
            )
            .await;
        persister.flush().await;

        let rows: Vec<(EventId, serde_json::Value, i64)> = sqlx::query_as(
            r#"
            SELECT id, payload, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            ORDER BY seq ASC
            "#,
        )
        .bind(session_id)
        .fetch_all(&pool)
        .await
        .expect("load persisted events after duplicate event id");

        assert_eq!(
            rows,
            vec![
                (redelivered_id, json!({"content": "first delivery"}), 1),
                (next_id, json!({"content": "next event"}), 2),
            ],
            "a duplicate event id must not consume the next canonical DB seq"
        );
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_persister_skips_session_status_events_even_when_called_directly() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;

    let result = async {
        let persister = EventPersister::new(
            pool.clone(),
            10,
            60_000,
            None,
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
            "rust-event-persister-status-test".to_string(),
        );

        persister
            .push(
                EventId::from_uuid(Uuid::now_v7()),
                session_id,
                "session.status_idle",
                &json!({"task_id": Uuid::now_v7().to_string(), "stop_reason": {"type": "end_turn"}}),
                None,
            )
            .await;
        let message_id = EventId::from_uuid(Uuid::now_v7());
        persister
            .push(
                message_id,
                session_id,
                "agent.message",
                &json!({"content": "still persists"}),
                None,
            )
            .await;
        persister.flush().await;

        let rows: Vec<(EventId, String, serde_json::Value, i64)> = sqlx::query_as(
            r#"
            SELECT id, event_type, payload, seq
            FROM joysafeter_session_events
            WHERE session_id = $1
            ORDER BY seq ASC
            "#,
        )
        .bind(session_id)
        .fetch_all(&pool)
        .await
        .expect("load persisted events after direct persister status skip");

        assert_eq!(
            rows,
            vec![(
                message_id,
                "agent.message".to_string(),
                json!({"content": "still persists"}),
                1,
            )],
            "generic persister must not persist session.status_* or consume seq"
        );

        let status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session status after direct persister status skip");
        assert_eq!(status, "running", "generic persister must not mutate session status");
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn raw_status_envelope_through_subscriber_uses_canonical_db_seq_not_runner_seq() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let (tx, rx) = tokio::sync::broadcast::channel(8);
        let subscriber = SessionStateSubscriber::new(
            pool.clone(),
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
            "rust-status-test".to_string(),
        );
        let handle = subscriber.spawn(rx);

        let payload = json!({"task_id": task_id.to_string()});
        let envelope = EventEnvelope::new(session_id, "session.status_running", payload.clone())
            .with_task(task_id)
            .with_runner_seq(777)
            .status_change(None);
        tx.send(Arc::new(envelope))
            .expect("send raw status envelope to subscriber");

        let mut observed: Option<(String, String, serde_json::Value, i64)> = None;
        for _ in 0..50 {
            observed = sqlx::query_as(
                r#"
                SELECT s.status, e.event_type, e.payload, e.seq
                FROM joysafeter_sessions s
                JOIN joysafeter_session_events e ON e.session_id = s.id
                WHERE s.id = $1
                ORDER BY e.seq ASC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_optional(&pool)
            .await
            .expect("poll raw status subscriber result");
            if observed.is_some() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }

        handle.abort();

        let observed = observed.expect("subscriber should persist raw status envelope");
        assert_eq!(observed.0, "running");
        assert_eq!(observed.1, "session.status_running");
        assert_eq!(observed.2, payload);
        assert_eq!(observed.3, 1, "DB canonical seq must not reuse runner seq");
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn raw_idle_status_with_active_task_is_skipped_except_requires_action() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let (tx, rx) = tokio::sync::broadcast::channel(8);
        let subscriber = SessionStateSubscriber::new(
            pool.clone(),
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
            "rust-status-active-task-test".to_string(),
        );
        let handle = subscriber.spawn(rx);

        let stale_reason = json!({"type": "end_turn"});
        let stale_payload = json!({
            "task_id": task_id.to_string(),
            "stop_reason": stale_reason.clone()
        });
        let stale_idle =
            EventEnvelope::new(session_id, "session.status_idle", stale_payload.clone())
                .with_task(task_id)
                .status_change(Some(stale_reason));
        tx.send(Arc::new(stale_idle))
            .expect("send stale idle status envelope");

        let requires_action_reason = json!({
            "type": "requires_action",
            "event_ids": ["evt_test_requires_action"]
        });
        let requires_action_payload = json!({
            "task_id": task_id.to_string(),
            "stop_reason": requires_action_reason.clone()
        });
        let requires_action_idle = EventEnvelope::new(
            session_id,
            "session.status_idle",
            requires_action_payload.clone(),
        )
        .with_task(task_id)
        .status_change(Some(requires_action_reason.clone()));
        tx.send(Arc::new(requires_action_idle))
            .expect("send requires_action idle status envelope");

        let mut observed: Option<(String, serde_json::Value)> = None;
        for _ in 0..50 {
            observed = sqlx::query_as(
                r#"
                SELECT s.status, e.payload
                FROM joysafeter_sessions s
                JOIN joysafeter_session_events e ON e.session_id = s.id
                WHERE s.id = $1
                  AND e.event_type = 'session.status_idle'
                  AND e.payload->'stop_reason'->>'type' = 'requires_action'
                ORDER BY e.seq ASC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_optional(&pool)
            .await
            .expect("poll requires_action idle status subscriber result");
            if observed.is_some() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }

        handle.abort();

        let observed = observed.expect("requires_action idle should be persisted");
        assert_eq!(observed.0, "idle");
        assert_eq!(observed.1, requires_action_payload);

        let stale_idle_events: i64 = sqlx::query_scalar(
            r#"
            SELECT COUNT(*)
            FROM joysafeter_session_events
            WHERE session_id = $1
              AND event_type = 'session.status_idle'
              AND payload->'stop_reason'->>'type' = 'end_turn'
            "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count stale end_turn idle events");
        assert_eq!(stale_idle_events, 0);
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn event_bus_routes_raw_status_to_state_subscriber_not_generic_persister() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let mut config = JoySafeterConfig::from_env();
        config.event_stream_enabled = false;
        config.event_batch_max_size = 1;
        config.event_batch_max_delay_ms = 1;
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client =
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
        let subscriber = SessionStateSubscriber::new(
            pool.clone(),
            redis::Client::open("redis://127.0.0.1/").expect("construct redis client"),
            "rust-status-test".to_string(),
        );
        let handle = subscriber.spawn(event_bus.subscribe());

        let payload = json!({"task_id": task_id.to_string()});
        let envelope = EventEnvelope::new(session_id, "session.status_running", payload.clone())
            .with_task(task_id)
            .with_runner_seq(777)
            .status_change(None);
        event_bus.publish(envelope).await;
        event_bus.flush().await;

        let mut observed: Option<(String, String, serde_json::Value, i64)> = None;
        for _ in 0..50 {
            observed = sqlx::query_as(
                r#"
                SELECT s.status, e.event_type, e.payload, e.seq
                FROM joysafeter_sessions s
                JOIN joysafeter_session_events e ON e.session_id = s.id
                WHERE s.id = $1
                ORDER BY e.seq ASC
                LIMIT 1
                "#,
            )
            .bind(session_id)
            .fetch_optional(&pool)
            .await
            .expect("poll event bus status subscriber result");
            if observed.is_some() {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }

        handle.abort();

        let observed = observed.expect("event bus should route raw status to subscriber");
        assert_eq!(observed.0, "running");
        assert_eq!(observed.1, "session.status_running");
        assert_eq!(observed.2, payload);
        assert_eq!(observed.3, 1, "DB canonical seq must not reuse runner seq");
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn stream_publisher_skips_status_events_instead_of_falling_back_to_db() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;

    let result = async {
        let fallback_persister = Arc::new(EventPersister::new(
            pool.clone(),
            1,
            1,
            None,
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
            "rust-status-test".to_string(),
        ));
        let stream_publisher = EventStreamPublisher::new(
            redis::Client::open("redis://127.0.0.1:1/").expect("construct redis client"),
            "joysafeter:test:events",
            100,
            Some(fallback_persister),
            true,
        );
        let (tx, rx) = tokio::sync::broadcast::channel(8);
        let handle = stream_publisher.spawn(rx);

        let payload = json!({"task_id": task_id.to_string()});
        let envelope = EventEnvelope::new(session_id, "session.status_running", payload.clone())
            .with_task(task_id)
            .with_runner_seq(777)
            .status_change(None);
        tx.send(Arc::new(envelope))
            .expect("send status envelope to stream publisher");
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        handle.abort();

        let event_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count status events after stream publisher skip");
        assert_eq!(event_count, 0);

        let status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after stream publisher skip");
        assert_eq!(status, "idle");
    }
    .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn provisioning_progress_update_does_not_resurrect_error_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("progress-error-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({"provisioning": {"stage": "booting"}})),
        )
        .await
        .expect("create provisioning progress sandbox");
        mark_sandbox_error(&pool, sandbox_id, Some("provider setup failed"))
            .await
            .expect("mark sandbox error");

        let updated = update_sandbox_status_and_config(
            &pool,
            sandbox_id,
            "provisioning",
            &json!({"provisioning": {"stage": "late_poll", "progress": 90}}),
        )
        .await
        .expect("attempt progress update after concurrent error");
        assert!(!updated);

        let sandbox: (
            String,
            serde_json::Value,
            Option<chrono::DateTime<chrono::Utc>>,
        ) = sqlx::query_as(
            "SELECT status, config, idle_since FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load sandbox after late progress update");
        assert_eq!(sandbox.0, "error");
        assert_eq!(
            sandbox
                .1
                .get("setup_error")
                .and_then(|value| value.as_str()),
            Some("provider setup failed")
        );
        assert_eq!(
            sandbox
                .1
                .get("provisioning")
                .and_then(|value| value.get("stage"))
                .and_then(|value| value.as_str()),
            Some("booting")
        );
        assert!(sandbox.2.is_none());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn start_sandbox_task_binds_healthy_sandbox_to_task() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("start-healthy-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create dispatch sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle");

        let started = start_sandbox_task(&pool, sandbox_id, task_id)
            .await
            .expect("start sandbox task");
        assert!(started);

        let sandbox: (
            String,
            Option<TaskId>,
            Option<chrono::DateTime<chrono::Utc>>,
        ) = sqlx::query_as(
            "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load started sandbox");
        assert_eq!(sandbox.0, "running");
        assert_eq!(sandbox.1, Some(task_id));
        assert!(sandbox.2.is_none());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn start_sandbox_task_does_not_resurrect_error_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("start-error-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create error dispatch sandbox");
        mark_sandbox_error(&pool, sandbox_id, Some("setup failed before dispatch"))
            .await
            .expect("mark sandbox error");

        let started = start_sandbox_task(&pool, sandbox_id, task_id)
            .await
            .expect("attempt start on error sandbox");
        assert!(!started);

        let sandbox: (String, Option<Uuid>, serde_json::Value) = sqlx::query_as(
            "SELECT status, last_task_id, config FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load error sandbox");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1, None);
        assert_eq!(
            sandbox
                .2
                .get("setup_error")
                .and_then(|value| value.as_str()),
            Some("setup failed before dispatch")
        );
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn mark_sandbox_stopped_if_active_stops_running_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let task_id = create_task(&pool, agent_id, session_id, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("stop-running-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create running stop sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle before start");
        assert!(start_sandbox_task(&pool, sandbox_id, task_id)
            .await
            .expect("start sandbox task"));

        let stopped = mark_sandbox_stopped_if_active(&pool, sandbox_id)
            .await
            .expect("mark active sandbox stopped");
        assert!(stopped);

        let sandbox: (
            String,
            Option<TaskId>,
            Option<chrono::DateTime<chrono::Utc>>,
        ) = sqlx::query_as(
            "SELECT status, last_task_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load stopped sandbox");
        assert_eq!(sandbox.0, "stopped");
        assert_eq!(sandbox.1, Some(task_id));
        assert!(sandbox.2.is_none());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn mark_sandbox_stopped_if_active_does_not_overwrite_error_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "running").await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("stop-error-preserve-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("create error stop sandbox");
        mark_sandbox_error(&pool, sandbox_id, Some("must stay error"))
            .await
            .expect("mark sandbox error");

        let stopped = mark_sandbox_stopped_if_active(&pool, sandbox_id)
            .await
            .expect("attempt mark error sandbox stopped");
        assert!(!stopped);

        let sandbox: (String, Option<String>) = sqlx::query_as(
            "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load preserved error sandbox");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1.as_deref(), Some("must stay error"));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn mark_pool_sandbox_ready_finalizes_creating_pool_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("pool-ready-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            None,
            None,
            None,
            Some(&json!({"provisioning": {"stage": "pool_warm"}})),
        )
        .await
        .expect("create warm pool sandbox");

        let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("finalize warm pool sandbox");
        assert!(ready);

        let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
            sqlx::query_as(
                "SELECT status, chat_session_id, idle_since FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load finalized pool sandbox");
        assert_eq!(sandbox.0, "pooled");
        assert_eq!(sandbox.1, None);
        assert!(sandbox.2.is_none());
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn mark_pool_sandbox_ready_accepts_runner_ready_idle_race() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("pool-ready-idle-race-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            None,
            None,
            None,
            Some(&json!({"provisioning": {"stage": "pool_warm"}})),
        )
        .await
        .expect("create warm pool sandbox");
        transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("simulate fast runner ready before pool finalization");

        let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("finalize warm pool after runner-ready race");
        assert!(ready);

        let status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load finalized pool sandbox");
        assert_eq!(status, "pooled");
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}

#[tokio::test]
async fn mark_pool_sandbox_ready_does_not_resurrect_error_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        create_sandbox(
            &pool,
            sandbox_id,
            &format!("pool-ready-error-{sandbox_id}"),
            "test",
            "joysafeter/test:latest",
            None,
            None,
            None,
            Some(&json!({"provisioning": {"stage": "pool_warm"}})),
        )
        .await
        .expect("create warm pool sandbox");
        mark_sandbox_error(&pool, sandbox_id, Some("pool setup failed"))
            .await
            .expect("mark warm pool sandbox error");

        let ready = mark_pool_sandbox_ready(&pool, sandbox_id)
            .await
            .expect("attempt late pool finalization after error");
        assert!(!ready);

        let sandbox: (String, Option<String>) = sqlx::query_as(
            "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load preserved pool error sandbox");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1.as_deref(), Some("pool setup failed"));
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    result
}
