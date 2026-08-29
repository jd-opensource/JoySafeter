use super::*;
#[tokio::test]
async fn sandbox_cleanup_exhausted_scheduling_task_marks_session_idle() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "cleanup-exhausted", 2, 2).await;

    let result = async {
            sqlx::query("UPDATE joysafeter_tasks SET status = 'scheduling' WHERE id = $1")
                .bind(task_id)
                .execute(&pool)
                .await
                .expect("move task back to scheduling for cleanup test");

            let config = JoySafeterConfig::from_env();
            RunnerCleanupService::new()
                .cleanup_sandbox(
                    &pool,
                    sandbox_id,
                    Some(session_id),
                    false,
                    None,
                    None,
                    &config,
                )
                .await;

            let task: (String, i32, Option<String>) =
                sqlx::query_as("SELECT status, retry_count, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load cleanup exhausted task");
            assert_eq!(task.0, "failed");
            assert_eq!(task.1, 2);
            assert_eq!(
                task.2.as_deref(),
                Some("sandbox cleanup exceeded task retry limit")
            );

            let (session_status, stop_reason): (String, Option<Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load cleanup exhausted session");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(Value::as_str),
                Some("sandbox cleanup exceeded task retry limit")
            );

            let idle_events: i64 = sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->>'task_id' = $2
                  AND payload->'stop_reason'->>'message' = 'sandbox cleanup exceeded task retry limit'
                "#,
            )
            .bind(session_id)
            .bind(task_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("count cleanup exhausted idle events");
            assert_eq!(idle_events, 1);

            let rescheduling_events: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1 AND event_type = 'session.status_rescheduling'",
            )
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("count cleanup exhausted rescheduling events");
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
async fn sandbox_cleanup_does_not_idle_session_with_active_task_on_another_sandbox() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let stale_sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        queries::create_sandbox(
            &pool,
            stale_sandbox_id,
            &format!("cleanup-stale-sandbox-{stale_sandbox_id}"),
            "recording",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("insert stale linked sandbox");
        queries::destroy_sandbox(&pool, stale_sandbox_id)
            .await
            .expect("mark stale sandbox destroyed before replacement");

        let (active_sandbox_id, active_task_id) = create_running_sandbox_task(
            &pool,
            agent_id,
            session_id,
            "cleanup-active-other-sandbox",
            0,
            2,
        )
        .await;

        let config = JoySafeterConfig::from_env();
        RunnerCleanupService::new()
            .cleanup_sandbox(
                &pool,
                stale_sandbox_id,
                Some(session_id),
                false,
                None,
                None,
                &config,
            )
            .await;

        let session_status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after stale sandbox cleanup");
        assert_eq!(session_status, "running");

        let disconnected_idle_events: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'session.status_idle'
                  AND payload->'stop_reason'->>'type' = 'sandbox_disconnected'
                "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count false sandbox disconnected idle events");
        assert_eq!(disconnected_idle_events, 0);

        let active_task: (String, Option<SandboxId>) =
            sqlx::query_as("SELECT status, sandbox_id FROM joysafeter_tasks WHERE id = $1")
                .bind(active_task_id)
                .fetch_one(&pool)
                .await
                .expect("load active task after stale sandbox cleanup");
        assert_eq!(active_task.0, "running");
        assert_eq!(active_task.1, Some(active_sandbox_id));

        (active_sandbox_id, active_task_id)
    }
    .await;

    let (active_sandbox_id, active_task_id) = result;
    let _ = sqlx::query("DELETE FROM joysafeter_session_events WHERE session_id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(active_task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id IN ($1, $2)")
        .bind(stale_sandbox_id)
        .bind(active_sandbox_id)
        .execute(&pool)
        .await;
    cleanup(&pool, agent_id, session_id).await;
}
