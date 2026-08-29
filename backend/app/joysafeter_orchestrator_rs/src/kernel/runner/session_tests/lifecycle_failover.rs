use super::*;
#[tokio::test]
async fn failover_retry_marks_session_rescheduling_and_releases_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "failover-retry", 0, 2).await;

    let result = async {
        let event_bus = test_event_bus(pool.clone());
        failover_or_fail_inline(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "runner disconnected",
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
            .expect("load task after failover retry");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 1);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after failover retry");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after failover retry");
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
        .expect("count failover rescheduling events");
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
async fn failover_exhausted_retries_marks_task_failed_and_session_idle() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "failover-exhausted", 2, 2).await;

    let result = async {
        let event_bus = test_event_bus(pool.clone());
        failover_or_fail_inline(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "runner disconnected",
            None,
        )
        .await;

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
        .expect("load task after exhausted failover");
        assert_eq!(task_status, "failed");
        assert_eq!(retry_count, 2);
        assert_eq!(task_sandbox_id, Some(sandbox_id));
        assert_eq!(task_error.as_deref(), Some("runner disconnected"));

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after exhausted failover");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<serde_json::Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after exhausted failover");
        assert_eq!(session_status, "idle");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("message"))
                .and_then(|value| value.as_str()),
            Some("runner disconnected")
        );

        let idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'runner disconnected'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count failover idle events");
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
async fn task_disconnect_before_result_retries_and_marks_session_rescheduling() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "disconnect-retry", 0, 2).await;

    let result = async {
        let event_bus = test_event_bus(pool.clone());
        let (tx, _rx) = mpsc::channel(4);
        let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));

        let task_result = handle_task_disconnect_before_result(
            &pool,
            &event_bus,
            &bridge,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "Sandbox disconnected unexpectedly",
            None,
        )
        .await;
        assert!(matches!(task_result, TaskResult::Disconnected));

        let (task_status, retry_count, task_sandbox_id): (String, i32, Option<SandboxId>) =
            sqlx::query_as(
                "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
            )
            .bind(task_id)
            .fetch_one(&pool)
            .await
            .expect("load task after disconnect retry");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 1);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after disconnect retry");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after disconnect retry");
        assert_eq!(session_status, "rescheduling");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("type"))
                .and_then(Value::as_str),
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
        .expect("count disconnect rescheduling events");
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
async fn failover_with_agent_output_completes_task_and_releases_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "failover-output", 0, 2).await;

    let result = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'session.status_running', $3, 1)
                "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(json!({"task_id": task_id.to_string()}))
        .execute(&pool)
        .await
        .expect("insert running status event");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'agent.message', $3, $4)
                "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(json!({"content": [{"type": "text", "text": "partial answer"}]}))
        .bind(2_i64)
        .execute(&pool)
        .await
        .expect("insert agent output after running status");

        let event_bus = test_event_bus(pool.clone());
        failover_or_fail_inline(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "runner disconnected after output",
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
            .expect("load task after output failover");
        assert_eq!(task_status, "completed");
        assert_eq!(retry_count, 0);
        assert_eq!(task_sandbox_id, Some(sandbox_id));

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after output failover");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after output failover");
        assert_eq!(session_status, "idle");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("type"))
                .and_then(Value::as_str),
            Some("end_turn")
        );

        let idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count output failover idle events");
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
async fn failover_with_agent_output_does_not_complete_pending_retry() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "failover-output-pending", 0, 2)
            .await;

    let result = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'session.status_running', $3, 1)
                "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(json!({"task_id": task_id.to_string()}))
        .execute(&pool)
        .await
        .expect("insert running status event");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_events
                    (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'agent.message', $3, 2)
                "#,
        )
        .bind(Uuid::now_v7())
        .bind(session_id)
        .bind(json!({"content": [{"type": "text", "text": "partial answer"}]}))
        .execute(&pool)
        .await
        .expect("insert agent output after running status");

        sqlx::query(
            r#"
                UPDATE joysafeter_tasks
                SET status = 'pending',
                    sandbox_id = NULL,
                    retry_count = 1,
                    updated_at = NOW()
                WHERE id = $1
                "#,
        )
        .bind(task_id)
        .execute(&pool)
        .await
        .expect("simulate retry after output");
        queries::complete_sandbox_task(&pool, sandbox_id)
            .await
            .expect("release sandbox after simulated retry");
        let stop_reason = json!({"type": "sandbox_failed"});
        let payload = json!({"task_id": task_id.to_string(), "stop_reason": stop_reason.clone()});
        queries::update_session_status_and_insert_event(
            &pool,
            session_id,
            "rescheduling",
            Some(&stop_reason),
            "session.status_rescheduling",
            &payload,
        )
        .await
        .expect("mark session rescheduling after simulated retry")
        .expect("insert rescheduling event");

        let event_bus = test_event_bus(pool.clone());
        failover_or_fail_inline(
            &pool,
            &event_bus,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            "late failover after retry",
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
            .expect("load pending retry after late output failover");
        assert_eq!(task_status, "pending");
        assert_eq!(retry_count, 1);
        assert_eq!(task_sandbox_id, None);

        let (sandbox_status, last_task_id): (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after late output failover");
        assert_eq!(sandbox_status, "idle");
        assert_eq!(last_task_id, None);

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after late output failover");
        assert_eq!(session_status, "rescheduling");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("type"))
                .and_then(Value::as_str),
            Some("sandbox_failed")
        );

        let end_turn_idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'type' = 'end_turn'
                "#,
        )
        .bind(session_id)
        .bind(task_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("count false end_turn idle events");
        assert_eq!(end_turn_idle_events, 0);
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
