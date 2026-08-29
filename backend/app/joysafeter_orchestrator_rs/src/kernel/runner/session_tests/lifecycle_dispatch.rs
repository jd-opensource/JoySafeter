use super::*;
#[tokio::test]
async fn start_task_send_failure_retries_and_marks_session_rescheduling() {
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
            &format!("start-send-retry-{sandbox_id}"),
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
        let (closed_tx, closed_rx) = mpsc::channel(1);
        drop(closed_rx);
        let task = queries::get_task(&pool, task_id)
            .await
            .expect("load task")
            .expect("task exists");
        let msg = OrchestratorMessage {
            payload: Some(orchestrator_message::Payload::Start(
                proto::StartTask::default(),
            )),
        };

        let sent = send_start_task_or_handle_failure(
            &pool,
            &event_bus,
            &closed_tx,
            &task,
            Some(session_id),
            sandbox_id,
            msg,
            None,
        )
        .await;
        assert!(!sent);

        let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
            sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load task after send failure");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 1);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after send failure");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after send failure");
        assert_eq!(session_status, "rescheduling");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("type"))
                .and_then(|value| value.as_str()),
            Some("sandbox_failed")
        );

        let rescheduling_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'sandbox_failed'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count rescheduling events");
        assert_eq!(rescheduling_events, 1);
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
async fn dispatch_retry_failure_does_not_release_sandbox_on_terminal_conflict() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "dispatch-terminal-retry", 0, 2)
            .await;

    let result = async {
        let stale_task = queries::get_task(&pool, task_id)
            .await
            .expect("load stale running task")
            .expect("task exists");
        let completed = queries::transition_task_cas(
            &pool,
            task_id,
            "running",
            "completed",
            Some("result won before retry"),
            None,
        )
        .await
        .expect("complete task before stale dispatch retry");
        assert!(completed);

        let event_bus = test_event_bus(pool.clone());
        handle_dispatch_retryable_failure(
            &pool,
            &event_bus,
            &stale_task,
            Some(session_id),
            sandbox_id,
            stale_task.owner_epoch,
            "stale dispatch retry",
            None,
        )
        .await;

        let (task_status, retry_count): (String, i32) =
            sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after stale dispatch retry");
        assert_eq!(task_status, "completed");
        assert_eq!(retry_count, 0);

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale dispatch retry");
        assert_eq!(sandbox_status, "running");
        assert_eq!(last_task_id, Some(task_id));

        let rescheduling_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count stale dispatch retry events");
        assert_eq!(rescheduling_events, 0);
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
async fn dispatch_retry_failure_does_not_retry_pending_task_on_stale_snapshot() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "dispatch-pending-retry", 0, 2)
            .await;

    let result = async {
        let stale_task = queries::get_task(&pool, task_id)
            .await
            .expect("load stale running task")
            .expect("task exists");
        sqlx::query(
            r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 0,
                    updated_at = NOW()
                WHERE id = $1
                "#,
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("simulate task already pending");
        queries::complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("release sandbox for pending task");

        let event_bus = test_event_bus(pool.clone());
        handle_dispatch_retryable_failure(
            &pool,
            &event_bus,
            &stale_task,
            Some(session_id),
            sandbox_id,
            stale_task.owner_epoch,
            "stale dispatch retry",
            None,
        )
        .await;

        let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
            sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load pending task after stale dispatch retry");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 0);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale dispatch retry");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let rescheduling_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_rescheduling'
                  AND payload->>'task_id' = $2
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count stale dispatch retry events");
        assert_eq!(rescheduling_events, 0);
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
async fn start_task_send_failure_exhausts_retries_and_marks_session_idle() {
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
                &format!("start-send-exhausted-{sandbox_id}"),
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
                VALUES ($1, $2, $3, $4, 'running', 'test prompt', '', 7200, 2, 2)
                "#,
            )
            .bind(task_id)
            .bind(agent_id)
            .bind(session_id)
            .bind(sandbox_id)
            .execute(&pool)
            .await
            .expect("insert running task at retry limit");

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
            let (closed_tx, closed_rx) = mpsc::channel(1);
            drop(closed_rx);
            let task = queries::get_task(&pool, task_id)
                .await
                .expect("load task")
                .expect("task exists");
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Start(
                    proto::StartTask::default(),
                )),
            };

            let sent = send_start_task_or_handle_failure(
                &pool,
                &event_bus,
                &closed_tx,
                &task,
                Some(session_id),
                sandbox_id,
                msg,
                None,
            )
            .await;
            assert!(!sent);

            let (task_status, retry_count, task_sandbox_id, task_error): (
                String,
                i32,
                Option<SandboxId>,
                Option<String>,
            ) = sqlx::query_as(
                "SELECT status, retry_count, sandbox_id, error FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load exhausted task after send failure");
            assert_eq!(task_status, "failed");
            assert_eq!(retry_count, 2);
            assert_eq!(task_sandbox_id, Some(sandbox_id));
            assert_eq!(
                task_error.as_deref(),
                Some("Failed to send StartTask: outbound channel closed")
            );

            let (sandbox_status, last_task_id): (String, Option<Uuid>) = sqlx::query_as(
                "SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1",
            )
            .bind(sandbox_id)
            .fetch_one(&pool)
            .await
            .expect("load sandbox after exhausted send failure");
            assert_eq!(sandbox_status, "idle");
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after exhausted send failure");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                Some("Failed to send StartTask: outbound channel closed")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'Failed to send StartTask: outbound channel closed'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count idle events");
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
async fn dispatch_exhausted_failure_does_not_release_sandbox_on_terminal_conflict() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) = create_running_sandbox_task(
        &pool,
        agent_id,
        session_id,
        "dispatch-terminal-exhausted",
        2,
        2,
    )
    .await;

    let result = async {
        let stale_task = queries::get_task(&pool, task_id)
            .await
            .expect("load stale exhausted task")
            .expect("task exists");
        let cancelled =
            queries::transition_task_cas(&pool, task_id, "running", "cancelled", None, None)
                .await
                .expect("cancel task before stale exhausted failure");
        assert!(cancelled);

        let event_bus = test_event_bus(pool.clone());
        handle_dispatch_retryable_failure(
            &pool,
            &event_bus,
            &stale_task,
            Some(session_id),
            sandbox_id,
            stale_task.owner_epoch,
            "stale exhausted dispatch failure",
            None,
        )
        .await;

        let (task_status, retry_count): (String, i32) =
            sqlx::query_as("SELECT status, retry_count FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after stale exhausted dispatch failure");
        assert_eq!(task_status, "cancelled");
        assert_eq!(retry_count, 2);

        let (sandbox_status, last_task_id): (String, Option<TaskId>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale exhausted dispatch failure");
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
        .expect("count stale exhausted dispatch idle events");
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
async fn dispatch_exhausted_failure_does_not_fail_pending_task_on_stale_snapshot() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) = create_running_sandbox_task(
        &pool,
        agent_id,
        session_id,
        "dispatch-pending-exhausted",
        2,
        2,
    )
    .await;

    let result = async {
        let stale_task = queries::get_task(&pool, task_id)
            .await
            .expect("load stale exhausted task")
            .expect("task exists");
        sqlx::query(
            r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 2,
                    updated_at = NOW()
                WHERE id = $1
                "#,
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("simulate exhausted task already pending");
        queries::complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("release sandbox for pending task");

        let event_bus = test_event_bus(pool.clone());
        handle_dispatch_retryable_failure(
            &pool,
            &event_bus,
            &stale_task,
            Some(session_id),
            sandbox_id,
            stale_task.owner_epoch,
            "stale exhausted dispatch failure",
            None,
        )
        .await;

        let (task_status, retry_count, task_error, task_sandbox_id): (
            String,
            i32,
            Option<String>,
            Option<SandboxId>,
        ) = sqlx::query_as(
            "SELECT status, retry_count, error, sandbox_id FROM joysafeter_tasks WHERE id = $1",
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load pending task after stale exhausted dispatch failure");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 2);
        assert_eq!(task_error, None);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after stale exhausted dispatch failure");
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
        .expect("count stale exhausted dispatch idle events");
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
