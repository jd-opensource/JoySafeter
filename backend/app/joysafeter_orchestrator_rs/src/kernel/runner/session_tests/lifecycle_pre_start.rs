use super::*;
#[tokio::test]
async fn pre_start_failure_marks_task_failed_and_session_idle() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());

    let result = async {
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &format!("pre-start-failed-{sandbox_id}"),
            "recording",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("insert linked sandbox");
        let _ = queries::transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("sandbox idle");
        let _ = queries::transition_sandbox_cas(&pool, sandbox_id, "idle", "running")
            .await
            .expect("sandbox running");
        sqlx::query("UPDATE joysafeter_sandboxes SET last_task_id = $2 WHERE id = $1")
            .bind(sandbox_id)
            .bind(task_id)
            .execute(&pool)
            .await
            .expect("set sandbox last task");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 0, 2)
                "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("insert running task");

        let config = JoySafeterConfig::from_env();
        let runtime_config = Arc::new(RuntimeConfig::from_config(&config));
        let redis_client = redis::Client::open(
            config
                .redis_url
                .clone()
                .unwrap_or_else(|| "redis://127.0.0.1:6379".to_string()),
        )
        .expect("build redis client");
        let event_bus = EventBus::new(pool.clone(), &config, runtime_config, redis_client);
        let reason = "Failed to build harness input before StartTask: missing declared file";

        fail_pre_start_task(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            reason,
        )
        .await;

        let (task_status, task_error): (String, Option<String>) =
            sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after pre-start failure");
        assert_eq!(task_status, "failed");
        assert_eq!(task_error.as_deref(), Some(reason));

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after pre-start failure");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after pre-start failure");
        assert_eq!(session_status, "idle");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("message"))
                .and_then(|value| value.as_str()),
            Some(reason)
        );

        let idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = $3
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .bind(reason)
        .fetch_one(&pool)
        .await
        .expect("count pre-start idle events");
        assert_eq!(idle_events, 1);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn pre_start_failure_does_not_release_sandbox_on_terminal_conflict() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "pre-start-terminal", 0, 2).await;

    let result = async {
        let cancelled =
            queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                .await
                .expect("cancel running task before stale pre-start failure");
        assert!(cancelled);

        let event_bus = test_event_bus(pool.clone());
        fail_pre_start_task(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "stale pre-start failure",
        )
        .await;

        let task_status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after stale pre-start failure");
        assert_eq!(task_status, "cancelled");

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale pre-start failure");
        assert_eq!(sandbox_status, "running");
        assert_eq!(last_task_id, Some(task_id));

        let idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count stale pre-start idle events");
        assert_eq!(idle_events, 0);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn pre_start_failure_does_not_fail_pending_task_on_stale_observation() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "pre-start-pending", 0, 2).await;

    let result = async {
        sqlx::query(
            r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    updated_at = NOW()
                WHERE id = $1
                "#,
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("simulate task already pending before stale pre-start failure");
        queries::complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("release sandbox for pending task");

        let event_bus = test_event_bus(pool.clone());
        fail_pre_start_task(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "stale pre-start failure",
        )
        .await;

        let (task_status, task_error, task_sandbox_id): (
            String,
            Option<String>,
            Option<SandboxId>,
        ) = sqlx::query_as("SELECT status, error, sandbox_id FROM joysafeter_tasks WHERE id = $1")
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load task after stale pre-start pending failure");
        assert_eq!(task_status, "pending");
        assert_eq!(task_error, None);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale pre-start pending failure");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count stale pre-start pending idle events");
        assert_eq!(idle_events, 0);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn terminal_transition_helper_does_not_rewrite_session_on_cas_conflict() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "terminal-cas-conflict", 0, 2)
            .await;

    let result = async {
        let cancelled =
            queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                .await
                .expect("cancel running task");
        assert!(cancelled);

        let cancelled_reason = json!({"type": "cancelled"});
        let cancelled_payload =
            json!({"task_id": task_id.to_string(), "stop_reason": cancelled_reason.clone()});
        queries::update_session_status_and_insert_event(
            &pool,
            session_id,
            "idle",
            Some(&cancelled_reason),
            "session.status_idle",
            &cancelled_payload,
        )
        .await
        .expect("write cancel idle")
        .expect("insert cancel idle event");

        let event_bus = test_event_bus(pool.clone());
        let transitioned = transition_running_task_and_emit_idle(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "timeout",
            Some("deadline should not overwrite cancelled task"),
            json!({"type": "timeout"}),
            "test timeout conflict",
        )
        .await;
        assert!(!transitioned);

        let task_status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task status");
        assert_eq!(task_status, "cancelled");

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session status");
        assert_eq!(session_status, "idle");
        assert_eq!(stop_reason, Some(cancelled_reason));

        let cancel_idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'cancelled'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count cancel idle events");
        assert_eq!(cancel_idle_events, 1);

        let timeout_idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'timeout'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count timeout idle events");
        assert_eq!(timeout_idle_events, 0);
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
    result
}
