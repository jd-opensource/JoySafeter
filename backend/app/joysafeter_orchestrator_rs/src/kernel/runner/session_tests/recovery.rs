use super::*;
#[tokio::test]
async fn orphaned_task_rescue_marks_session_rescheduling_before_requeue() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "orphan-rescue", 0, 2).await;
    let event_bus = test_event_bus(pool.clone());
    let queue = TaskQueue::new(
        redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client"),
    );

    let result = async {
        RunnerRecoveryService::new()
            .rescue_orphaned_tasks(&pool, &event_bus, sandbox_id, &queue)
            .await;

        let task: (String, i32, Option<SandboxId>) = sqlx::query_as(
            "SELECT status, retry_count, sandbox_id FROM joysafeter_tasks WHERE id = $1",
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load rescued orphan task");
        assert_eq!(task.0, "pending");
        assert_eq!(task.1, 1);
        assert_eq!(task.2, None);

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load rescued orphan session");
        assert_eq!(session_status, "rescheduling");
        assert_eq!(stop_reason, Some(json!({"type": "sandbox_failed"})));

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
        .expect("count orphan rescue rescheduling events");
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
async fn orphaned_task_rescue_exhausted_marks_session_idle_without_requeue() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "orphan-exhausted", 2, 2).await;
    let event_bus = test_event_bus(pool.clone());
    let queue = TaskQueue::new(
        redis::Client::open("redis://127.0.0.1:1/").expect("build unreachable redis client"),
    );

    let result = async {
        RunnerRecoveryService::new()
            .rescue_orphaned_tasks(&pool, &event_bus, sandbox_id, &queue)
            .await;

        let task: (String, i32, Option<String>) =
            sqlx::query_as("SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load exhausted orphan task");
        assert_eq!(task.0, "failed");
        assert_eq!(task.1, 2);
        assert_eq!(
            task.2.as_deref(),
            Some("Orphaned running task exceeded reconnect retry limit")
        );

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load exhausted orphan session");
        assert_eq!(session_status, "idle");
        assert_eq!(
            stop_reason
                .as_ref()
                .and_then(|value| value.get("message"))
                .and_then(Value::as_str),
            Some("Orphaned running task exceeded reconnect retry limit")
        );

        let sandbox: (String, Option<Uuid>) =
            sqlx::query_as("SELECT status, last_task_id FROM joysafeter_sandboxes WHERE id = $1")
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load exhausted orphan sandbox");
        assert_eq!(sandbox.0, "idle");
        assert_eq!(sandbox.1, None);

        let pending_retries: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_tasks WHERE id = $1 AND status = 'pending'",
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("count pending exhausted orphan task");
        assert_eq!(pending_retries, 0);
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
