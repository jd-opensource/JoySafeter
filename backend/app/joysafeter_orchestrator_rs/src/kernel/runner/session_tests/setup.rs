use super::*;
#[tokio::test]
async fn send_setup_waits_for_late_session_link_before_marking_done() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let project_id: ProjectId =
        sqlx::query_scalar("SELECT project_id FROM joysafeter_sessions WHERE id = $1")
            .bind(session_id)
            .fetch_one(&pool)
            .await
            .expect("load late-link session project");

    let result = async {
        let sandbox_config = json!({});
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &format!("setup-late-link-{sandbox_id}"),
            "recording",
            "test-image:latest",
            None,
            None,
            None,
            Some(&sandbox_config),
        )
        .await
        .expect("insert unlinked sandbox");

        let (tx, mut rx) = mpsc::channel(4);
        let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx.clone()));
        let link_pool = pool.clone();
        let link_task = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(25)).await;
            sqlx::query(
                r#"
                    UPDATE joysafeter_sandboxes
                    SET chat_session_id = $2,
                        project_id = $3,
                        runtime_config_status = 'ready',
                        runtime_config_applied_generation = 0
                    WHERE id = $1
                    "#,
            )
            .bind(sandbox_id)
            .bind(session_id)
            .bind(&project_id)
            .execute(&link_pool)
            .await
            .expect("link sandbox to session with complete runtime ownership");
        });

        let sent = send_setup(&pool, &bridge, sandbox_id, &tx, false)
            .await
            .expect("send setup after late session link");
        link_task.await.expect("late link task joined");
        assert!(sent);
        assert!(!bridge.setup_done.load(Ordering::Relaxed));

        let msg = tokio::time::timeout(Duration::from_secs(1), rx.recv())
            .await
            .expect("setup message should arrive")
            .expect("setup channel open");
        match msg.payload {
            Some(orchestrator_message::Payload::Setup(setup)) => {
                assert!(!setup.provider.is_empty());
            }
            other => panic!("unexpected setup message: {other:?}"),
        }
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
async fn idle_setup_failure_result_marks_sandbox_error_and_clears_setup_done() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

    let result = async {
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &format!("setup-failed-{sandbox_id}"),
            "recording",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("insert linked sandbox");

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

        assert!(is_setup_failure_result(&setup_failure));
        mark_idle_setup_failure(&pool, &bridge, sandbox_id, &setup_failure).await;

        assert!(!bridge.setup_done.load(Ordering::Relaxed));
        let (status, setup_error): (String, Option<String>) = sqlx::query_as(
            "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load sandbox after setup failure");
        assert_eq!(status, "error");
        assert_eq!(setup_error, setup_failure.error);
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
async fn build_start_task_full_propagates_harness_input_error_without_minimal_fallback() {
    let Some(pool) = test_pool().await else {
        return;
    };

    let agent_id = AgentId::from_uuid(Uuid::now_v7());
    let session_id = SessionId::from_uuid(Uuid::now_v7());
    let task_id = TaskId::from_uuid(Uuid::now_v7());
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let file_id = FileId::from_uuid(Uuid::now_v7());
    let session_file_id = SessionResourceId::from_uuid(Uuid::now_v7());
    let unique = agent_id.as_uuid().simple().to_string();
    let org_id = OrganizationId::new();
    let project_id = ProjectId::new();
    let missing_storage_key = format!("grpc-missing-session-file-{unique}.txt");

    let result = async {
        sqlx::query(
            r#"
                INSERT INTO joysafeter_organizations
                    (id, name, slug, storage_used_bytes, departed_member_usage)
                VALUES ($1, $2, $3, 0, 0)
                "#,
        )
        .bind(&org_id)
        .bind(format!("Grpc Harness Org {unique}"))
        .bind(format!("grpc-harness-org-{unique}"))
        .execute(&pool)
        .await
        .expect("insert organization");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_organization_projects
                    (id, org_id, name, slug, is_default)
                VALUES ($1, $2, $3, $4, false)
                "#,
        )
        .bind(&project_id)
        .bind(&org_id)
        .bind(format!("Grpc Harness Project {unique}"))
        .bind(format!("grpc-harness-project-{unique}"))
        .execute(&pool)
        .await
        .expect("insert project");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_agents (
                    id, project_id, name, engine_kind, model, system_prompt, env,
                    mcp_servers, skills, tools, agents, commands, permission_mode,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'bypassPermissions', '{}'::jsonb, 1
                )
                "#,
        )
        .bind(agent_id)
        .bind(&project_id)
        .bind(format!("grpc-harness-agent-{unique}"))
        .bind(json!({"id": "claude-sonnet"}))
        .execute(&pool)
        .await
        .expect("insert agent");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sessions (id, agent_id, project_id, status)
                VALUES ($1, $2, $3, 'idle')
                "#,
        )
        .bind(session_id)
        .bind(agent_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert session");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_sandboxes (
                    id, external_id, provider, status, config, chat_session_id,
                    project_id, image, runtime_config_status,
                    runtime_config_applied_generation
                )
                VALUES ($1, $2, 'docker', 'running', '{}'::jsonb, $3, $4,
                        'test-image:latest', 'ready', 0)
                "#,
        )
        .bind(sandbox_id)
        .bind(format!("grpc-harness-sandbox-{unique}"))
        .bind(session_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert ready sandbox");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_files (
                    id, project_id, filename, purpose, content_type, size_bytes,
                    sha256, storage_key, downloadable
                )
                VALUES (
                    $1, $2, 'missing.txt', 'user_upload', 'text/plain', 12,
                    'missing-sha', $3, true
                )
                "#,
        )
        .bind(file_id)
        .bind(&project_id)
        .bind(&missing_storage_key)
        .execute(&pool)
        .await
        .expect("insert file metadata");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_session_files
                    (id, session_id, file_id, mount_path, access)
                VALUES ($1, $2, $3, '/workspace/missing.txt', 'read_only')
                "#,
        )
        .bind(session_file_id)
        .bind(session_id)
        .bind(file_id)
        .execute(&pool)
        .await
        .expect("insert session file mount");

        sqlx::query(
            r#"
                INSERT INTO joysafeter_tasks (
                    id, agent_id, chat_session_id, project_id, status, prompt, output,
                    timeout_sec, retry_count, max_retries
                )
                VALUES ($1, $2, $3, $4, 'running', 'use declared file', '', 7200, 0, 2)
                "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(&project_id)
        .execute(&pool)
        .await
        .expect("insert task");

        let task = queries::get_task(&pool, task_id)
            .await
            .expect("load task")
            .expect("task exists");
        let err = build_start_task_full(&pool, &task, sandbox_id, &JoySafeterConfig::from_env())
            .await
            .expect_err("harness input build failure must not produce fallback StartTask")
            .to_string();

        assert!(err.contains("failed to prepare session file"), "{err}");
        assert!(err.contains(&missing_storage_key), "{err}");
    }
    .await;

    let _ = sqlx::query("DELETE FROM joysafeter_tasks WHERE id = $1")
        .bind(task_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_session_files WHERE id = $1")
        .bind(session_file_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_files WHERE id = $1")
        .bind(file_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
        .bind(sandbox_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_sessions WHERE id = $1")
        .bind(session_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_agents WHERE id = $1")
        .bind(agent_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organization_projects WHERE id = $1")
        .bind(&project_id)
        .execute(&pool)
        .await;
    let _ = sqlx::query("DELETE FROM joysafeter_organizations WHERE id = $1")
        .bind(&org_id)
        .execute(&pool)
        .await;

    result
}
