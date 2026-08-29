use super::*;
#[tokio::test]
async fn pending_control_replay_marks_processed_only_after_send_succeeds() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;

    let result = async {
            let confirmation_event_id = Uuid::now_v7();
            let custom_result_event_id = Uuid::now_v7();
            let interrupt_event_id = Uuid::now_v7();
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.tool_confirmation', $3, 1)
                "#,
            )
            .bind(confirmation_event_id)
            .bind(session_id)
            .bind(json!({"call_id": "req_1", "approved": true}))
            .execute(&pool)
            .await
            .expect("insert pending confirmation event");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.custom_tool_result', $3, 2)
                "#,
            )
            .bind(custom_result_event_id)
            .bind(session_id)
            .bind(json!({"call_id": "req_2", "content": "tool output"}))
            .execute(&pool)
            .await
            .expect("insert pending custom result event");
            sqlx::query(
                r#"
                INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq)
                VALUES ($1, $2, 'user.interrupt', $3, 3)
                "#,
            )
            .bind(interrupt_event_id)
            .bind(session_id)
            .bind(json!({}))
            .execute(&pool)
            .await
            .expect("insert pending interrupt event");

            let (closed_tx, closed_rx) = mpsc::channel(1);
            drop(closed_rx);
            let replayed =
                replay_pending_control_inputs(
                    &pool,
                    session_id,
                    &closed_tx,
                    TaskId::from_uuid(Uuid::now_v7()),
                )
                    .await
                    .expect("closed replay should not fail DB query");
            assert_eq!(replayed, 0);

            let processed_after_failed_send: Option<chrono::DateTime<chrono::Utc>> =
                sqlx::query_scalar(
                    "SELECT processed_at FROM joysafeter_session_events WHERE id = $1",
                )
                .bind(confirmation_event_id)
                .fetch_one(&pool)
                .await
                .expect("load processed_at after failed send");
            assert_eq!(processed_after_failed_send, None);

            let (tx, mut rx) = mpsc::channel(8);
            let replayed = replay_pending_control_inputs(
                &pool,
                session_id,
                &tx,
                TaskId::from_uuid(Uuid::now_v7()),
            )
            .await
            .expect("open replay succeeds");
            assert_eq!(replayed, 3);

            let mut replayed_inputs = Vec::new();
            for _ in 0..3 {
                let msg = rx.recv().await.expect("receive replayed control input");
                match msg.payload {
                    Some(orchestrator_message::Payload::Input(input)) => {
                        replayed_inputs.push(input.content);
                    }
                    other => panic!("unexpected replay message: {other:?}"),
                }
            }
            assert_eq!(replayed_inputs.len(), 3);

            let confirmation_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[0]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("confirmation uses live input prefix"),
            )
            .expect("decode confirmation live input");
            assert_eq!(
                confirmation_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("tool_confirmation")
            );
            assert_eq!(
                confirmation_payload
                    .get("tool_use_call_id")
                    .and_then(|value| value.as_str()),
                Some("req_1")
            );
            assert_eq!(
                confirmation_payload
                    .get("approved")
                    .and_then(|value| value.as_bool()),
                Some(true)
            );

            let custom_result_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[1]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("custom result uses live input prefix"),
            )
            .expect("decode custom result live input");
            assert_eq!(
                custom_result_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("custom_tool_result")
            );
            assert_eq!(
                custom_result_payload
                    .get("tool_use_call_id")
                    .and_then(|value| value.as_str()),
                Some("req_2")
            );
            assert_eq!(
                custom_result_payload
                    .get("content")
                    .and_then(|value| value.as_str()),
                Some("tool output")
            );

            let interrupt_payload: serde_json::Value = serde_json::from_str(
                replayed_inputs[2]
                    .strip_prefix(LIVE_INPUT_PREFIX)
                    .expect("interrupt uses live input prefix"),
            )
            .expect("decode interrupt live input");
            assert_eq!(
                interrupt_payload
                    .get("type")
                    .and_then(|value| value.as_str()),
                Some("interrupt")
            );
            assert_eq!(
                interrupt_payload
                    .get("source_event_id")
                    .and_then(|value| value.as_str())
                    .map(str::to_string),
                Some(EventId::from_uuid(interrupt_event_id).to_string())
            );

            let processed_after_success: i64 =
                sqlx::query_scalar(
                    "SELECT COUNT(*) FROM joysafeter_session_events WHERE session_id = $1 AND processed_at IS NOT NULL",
                )
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load processed_at after successful send");
            assert_eq!(processed_after_success, 3);
        }
        .await;

    cleanup(&pool, agent_id, session_id).await;
    result
}

#[tokio::test]
async fn task_setup_failure_result_marks_task_failed_and_keeps_sandbox_error() {
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
                &format!("task-setup-failed-{sandbox_id}"),
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
            let (tx, _rx) = mpsc::channel(4);
            let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));
            bridge.setup_done.store(true, Ordering::Relaxed);
            let setup_failure = proto::RunnerHarnessResult {
                status: "failed".to_string(),
                error: Some(
                    "SetupSandbox failed: clone setup repos to /workspace: clone repo missing"
                        .to_string(),
                ),
                ..Default::default()
            };
            let mut task_error = false;

            let outcome = handle_task_setup_failure_result(
                &setup_failure,
                &pool,
                &event_bus,
                &bridge,
                task_id,
                None,
                Some(session_id),
                sandbox_id,
                &mut task_error,
            )
            .await;

            assert!(outcome.task_done);
            assert!(!outcome.runner_idle_seen);
            assert!(outcome.terminal_idle_handled);
            assert!(matches!(outcome.task_result, Some(TaskResult::Failed(_))));
            assert!(task_error);
            assert!(!bridge.setup_done.load(Ordering::Relaxed));
            assert!(is_setup_failure_task_result(&TaskResult::Failed(
                setup_failure.error.clone().unwrap()
            )));

            let (task_status, task_error_msg): (String, Option<String>) =
                sqlx::query_as("SELECT status, error FROM joysafeter_tasks WHERE id = $1")
                    .bind(task_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load task after setup failure");
            assert_eq!(task_status, "failed");
            assert_eq!(task_error_msg, setup_failure.error);

            let (sandbox_status, setup_error, last_task_id): (String, Option<String>, Option<Uuid>) =
                sqlx::query_as(
                    "SELECT status, config->>'setup_error', last_task_id FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_one(&pool)
                .await
                .expect("load sandbox after task setup failure");
            assert_eq!(sandbox_status, "error");
            assert_eq!(setup_error, setup_failure.error);
            assert_eq!(last_task_id, None);

            let (session_status, stop_reason): (String, Option<serde_json::Value>) =
                sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                    .bind(session_id)
                    .fetch_one(&pool)
                    .await
                    .expect("load session after task setup failure");
            assert_eq!(session_status, "idle");
            assert_eq!(
                stop_reason
                    .as_ref()
                    .and_then(|value| value.get("message"))
                    .and_then(|value| value.as_str()),
                setup_failure.error.as_deref()
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
async fn late_runner_result_after_cancel_keeps_cancelled_session_authority() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let (sandbox_id, task_id) =
        create_running_sandbox_task(&pool, agent_id, session_id, "late-result-cancel", 0, 2).await;

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
        let (tx, _rx) = mpsc::channel(4);
        let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
        let runner_result = RunnerMessage {
            payload: Some(runner_message::Payload::Result(
                proto::RunnerHarnessResult {
                    status: "completed".to_string(),
                    output: "late success".to_string(),
                    ..Default::default()
                },
            )),
        };
        let mut requires_action_pending = false;
        let mut buffered_events = Vec::new();
        let mut task_completed = false;
        let mut task_error = false;
        let custom_names = std::collections::HashSet::new();
        let mcp_names = std::collections::HashSet::new();

        let outcome = handle_task_message(
            &runner_result,
            &pool,
            &event_bus,
            &bridge,
            task_id,
            None,
            Some(session_id),
            sandbox_id,
            &tx,
            &mut requires_action_pending,
            &mut buffered_events,
            &mut task_completed,
            &mut task_error,
            &custom_names,
            &mcp_names,
            Arc::new(MemoryStoreSubscribers::new()),
            Arc::new(BridgeRegistry::new()) as Arc<dyn BridgeStore>,
            2000,
        )
        .await;

        assert!(outcome.task_done);
        assert!(outcome.terminal_idle_handled);
        assert!(matches!(outcome.task_result, Some(TaskResult::Cancelled)));
        assert!(task_completed);
        assert!(!task_error);

        let (task_status, task_output): (String, String) =
            sqlx::query_as("SELECT status, output FROM joysafeter_tasks WHERE id = $1")
                .bind(task_id)
                .fetch_one(&pool)
                .await
                .expect("load task after late result");
        assert_eq!(task_status, "cancelled");
        assert_eq!(task_output, "");

        let (session_status, stop_reason): (String, Option<Value>) =
            sqlx::query_as("SELECT status, stop_reason FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load session after late result");
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
        .expect("count cancel idle events after late result");
        assert_eq!(cancel_idle_events, 1);

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
        .expect("count end_turn idle events after late result");
        assert_eq!(end_turn_idle_events, 0);

        let late_agent_messages: i64 = sqlx::query_scalar(
            r#"
                SELECT COUNT(*)
                FROM joysafeter_session_events
                WHERE session_id = $1
                  AND event_type = 'agent.message'
                  AND payload::text LIKE '%late success%'
                "#,
        )
        .bind(session_id)
        .fetch_one(&pool)
        .await
        .expect("count late fallback messages");
        assert_eq!(late_agent_messages, 0);
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
