use std::env;
use std::sync::Arc;

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

async fn create_agent_and_session(pool: &PgPool, status: &str) -> (Uuid, Uuid) {
    let agent_id = Uuid::now_v7();
    let session_id = Uuid::now_v7();
    let agent_name = format!("rust-status-scenario-{agent_id}");

    sqlx::query(
        r#"
        INSERT INTO joysafeter_agents (id, name, engine_kind, permission_mode, version)
        VALUES ($1, $2, 'claude', 'bypassPermissions', 1)
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

async fn cleanup(pool: &PgPool, agent_id: Uuid, session_id: Uuid) {
    let _ =
        sqlx::query("DELETE FROM joysafeter_tasks WHERE chat_session_id = $1 OR agent_id = $2")
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

async fn create_task(pool: &PgPool, agent_id: Uuid, session_id: Uuid, status: &str) -> Uuid {
    let task_id = Uuid::now_v7();
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
        .expect("simulate reclaim after legacy null-owner observation");

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

        let null_owner_row: (String, Option<i64>, Option<String>) = sqlx::query_as(
            "SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1",
        )
        .bind(null_owner_task)
        .fetch_one(&pool)
        .await
        .expect("load null-owner reclaimed task");
        assert_eq!(null_owner_row.0, "running");
        assert_eq!(null_owner_row.1, Some(51));
        assert!(null_owner_row.2.is_none());

        let epoch_owner_row: (String, Option<i64>, Option<String>) = sqlx::query_as(
            "SELECT status, owner_epoch, error FROM joysafeter_tasks WHERE id = $1",
        )
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

        let rows: Vec<(Uuid, bool)> = sqlx::query_as(
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
    let sandbox_id = Uuid::now_v7();

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
        transition_sandbox(&pool, sandbox_id, "idle")
            .await
            .expect("sandbox idle");
        transition_sandbox(&pool, sandbox_id, "running")
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
    let sandbox_id = Uuid::now_v7();

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
    let sandbox_id = Uuid::now_v7();

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

        let transitioned = transition_sandbox(&pool, sandbox_id, "idle")
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
    let sandbox_id = Uuid::now_v7();

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
        transition_sandbox(&pool, sandbox_id, "idle")
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

        let sandbox: (String, Option<Uuid>, Option<String>) = sqlx::query_as(
            "SELECT status, last_task_id, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load protected active sandbox");
        assert_eq!(sandbox.0, "running");
        assert_eq!(sandbox.1, Some(task_id));
        assert_eq!(sandbox.2, None);

        let task: (String, Option<Uuid>) =
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
async fn atomic_session_status_helper_writes_status_event_and_canonical_seq() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool, "idle").await;
    let task_id = Uuid::now_v7();

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

        let running_event: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
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
    let task_id = Uuid::now_v7();

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

        let rows: Vec<(Uuid, String, i64)> = sqlx::query_as(
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

        let row: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
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

        let row: (Uuid, String, serde_json::Value, i64) = sqlx::query_as(
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
async fn event_bus_stream_primary_without_fallback_does_not_direct_write_to_db() {
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

        let envelope = EventEnvelope::new(session_id, "agent.message", json!({"content": "no fallback"}))
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
            count, 0,
            "stream-enabled EventBus must not use the direct DB persister as a second primary path"
        );
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

        let redelivered_id = Uuid::now_v7();
        let next_id = Uuid::now_v7();
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

        let rows: Vec<(Uuid, serde_json::Value, i64)> = sqlx::query_as(
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
                Uuid::now_v7(),
                session_id,
                "session.status_idle",
                &json!({"task_id": Uuid::now_v7().to_string(), "stop_reason": {"type": "end_turn"}}),
                None,
            )
            .await;
        let message_id = Uuid::now_v7();
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

        let rows: Vec<(Uuid, String, serde_json::Value, i64)> = sqlx::query_as(
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
        let envelope =
            EventEnvelope::new(session_id, "session.status_running", payload.clone())
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
        let envelope =
            EventEnvelope::new(session_id, "session.status_running", payload.clone())
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
        let envelope =
            EventEnvelope::new(session_id, "session.status_running", payload.clone())
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
    let sandbox_id = Uuid::now_v7();

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
    let sandbox_id = Uuid::now_v7();

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
        transition_sandbox(&pool, sandbox_id, "idle")
            .await
            .expect("sandbox idle");

        let started = start_sandbox_task(&pool, sandbox_id, task_id)
            .await
            .expect("start sandbox task");
        assert!(started);

        let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
            sqlx::query_as(
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
    let sandbox_id = Uuid::now_v7();

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
    let sandbox_id = Uuid::now_v7();

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
        transition_sandbox(&pool, sandbox_id, "idle")
            .await
            .expect("sandbox idle before start");
        assert!(
            start_sandbox_task(&pool, sandbox_id, task_id)
                .await
                .expect("start sandbox task")
        );

        let stopped = mark_sandbox_stopped_if_active(&pool, sandbox_id)
            .await
            .expect("mark active sandbox stopped");
        assert!(stopped);

        let sandbox: (String, Option<Uuid>, Option<chrono::DateTime<chrono::Utc>>) =
            sqlx::query_as(
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
    let sandbox_id = Uuid::now_v7();

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
    let sandbox_id = Uuid::now_v7();

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
    let sandbox_id = Uuid::now_v7();

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
        transition_sandbox(&pool, sandbox_id, "idle")
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
    let sandbox_id = Uuid::now_v7();

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
