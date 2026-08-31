use super::*;
use crate::kernel::runner::setup::validate_reconnect_setup_generation;

#[test]
fn setup_flow_error_keeps_runner_and_infrastructure_failures_distinct() {
    let protocol =
        crate::kernel::runner::setup::SetupFlowError::runner_protocol("forged skill receipt");
    let infrastructure =
        crate::kernel::runner::setup::SetupFlowError::setup("skill audit database unavailable");

    assert!(protocol.is_runner_fault());
    assert!(!infrastructure.is_runner_fault());
}

#[test]
fn only_unexpected_disconnects_receive_runner_reconnect_grace() {
    assert!(should_wait_for_runner_reconnect(
        RunnerSessionExit::Disconnected
    ));
    assert!(!should_wait_for_runner_reconnect(
        RunnerSessionExit::Rejected
    ));
    assert!(!should_wait_for_runner_reconnect(
        RunnerSessionExit::FailureEjected
    ));
}

#[test]
fn runner_protocol_admission_requires_setup_ack_capability() {
    assert!(
        crate::kernel::runner::admission::validate_runner_protocol(&["setup_ack_v1".to_string(),])
            .is_ok()
    );
    let error = crate::kernel::runner::admission::validate_runner_protocol(&[])
        .expect_err("legacy Runner must be rejected");
    assert_eq!(error.code(), "runner_protocol_incompatible");
    assert_eq!(error.message(), "runner protocol is missing setup_ack_v1");
}

#[test]
fn runner_execution_threshold_failure_has_stable_code() {
    let failure = crate::kernel::runner::failure::RunnerFailure::execution_unhealthy(
        "runner exceeded consecutive failure threshold",
    );
    assert_eq!(failure.code(), "runner_execution_unhealthy");
}

#[test]
fn malformed_runner_reconnect_metadata_has_stable_failure_code() {
    let failure =
        crate::kernel::runner::failure::RunnerFailure::protocol_invalid("invalid active task id");
    assert_eq!(failure.code(), "runner_protocol_invalid");
}

#[test]
fn reconnect_setup_requires_ready_status_and_exact_reported_generation() {
    assert_eq!(
        validate_reconnect_setup_generation("ready", 7, Some(7)),
        Ok(7)
    );
    assert!(validate_reconnect_setup_generation("ready", 7, None).is_err());
    assert!(validate_reconnect_setup_generation("ready", 7, Some(6)).is_err());
    assert!(validate_reconnect_setup_generation("restart_required", 7, Some(7)).is_err());
}

#[tokio::test]
async fn setup_ack_applies_only_the_matching_setup_generation() {
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let (tx, _rx) = mpsc::channel(4);
    let bridge = SandboxBridge::new(sandbox_id, tx);

    bridge.begin_setup("setup-current".to_string(), 7).await;

    let stale = bridge.record_setup_result("setup-old", 6, true, None).await;
    assert_eq!(
        stale,
        crate::kernel::sandbox_bridge::SetupResultDisposition::Stale
    );
    assert_eq!(
        bridge.setup_state().await,
        crate::kernel::sandbox_bridge::SandboxSetupState::Applying {
            setup_id: "setup-current".to_string(),
            runtime_config_generation: 7,
        }
    );
    assert!(!bridge.setup_applied_for(7).await);

    let applied = bridge
        .record_setup_result("setup-current", 7, true, None)
        .await;
    assert_eq!(
        applied,
        crate::kernel::sandbox_bridge::SetupResultDisposition::Applied
    );
    assert!(bridge.setup_applied_for(7).await);
}

#[tokio::test]
async fn older_setup_ack_cannot_unlock_a_newer_pending_setup() {
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let (tx, _rx) = mpsc::channel(4);
    let bridge = SandboxBridge::new(sandbox_id, tx);

    bridge.begin_setup("setup-7".to_string(), 7).await;
    bridge.begin_setup("setup-8".to_string(), 8).await;

    let stale = bridge.record_setup_result("setup-7", 7, true, None).await;
    assert_eq!(
        stale,
        crate::kernel::sandbox_bridge::SetupResultDisposition::Stale
    );
    assert_eq!(
        bridge.setup_state().await,
        crate::kernel::sandbox_bridge::SandboxSetupState::Applying {
            setup_id: "setup-8".to_string(),
            runtime_config_generation: 8,
        }
    );
    assert!(!bridge.setup_applied_for(8).await);
}

#[tokio::test]
async fn setup_success_outside_the_correlated_gate_fails_closed() {
    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let (tx, _rx) = mpsc::channel(4);
    let bridge = Arc::new(SandboxBridge::new(sandbox_id, tx));
    bridge.begin_setup("setup-current".to_string(), 7).await;

    let result = proto::SandboxSetupResult {
        setup_id: "setup-current".to_string(),
        runtime_config_generation: 7,
        status: proto::SandboxSetupStatus::Applied as i32,
        loaded_skills: Vec::new(),
        ..Default::default()
    };

    let handling = crate::kernel::runner::setup::handle_out_of_band_setup_result(
        &bridge,
        sandbox_id,
        &result,
        &RunnerMetrics::default(),
    )
    .await;

    assert!(matches!(handling, SetupResultHandling::Failed(_)));
    assert!(!bridge.setup_applied_for(7).await);
    assert!(matches!(
        bridge.setup_state().await,
        crate::kernel::sandbox_bridge::SandboxSetupState::Failed {
            runtime_config_generation: 7,
            ..
        }
    ));
}

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

        let harness_input_builder =
            crate::kernel::harness_input_builder::HarnessInputBuilder::new(pool.clone(), false);
        let metrics = RunnerMetrics::default();
        let sent = send_setup(
            &pool,
            &bridge,
            sandbox_id,
            &tx,
            &harness_input_builder,
            &metrics,
        )
        .await
        .expect("send setup after late session link");
        link_task.await.expect("late link task joined");
        let pending = sent.expect("linked sandbox should produce a pending setup");
        assert_eq!(pending.runtime_config_generation, 0);
        assert!(!pending.setup_id.is_empty());
        assert_eq!(
            bridge.setup_state().await,
            crate::kernel::sandbox_bridge::SandboxSetupState::Applying {
                setup_id: pending.setup_id.clone(),
                runtime_config_generation: 0,
            }
        );

        let msg = tokio::time::timeout(Duration::from_secs(1), rx.recv())
            .await
            .expect("setup message should arrive")
            .expect("setup channel open");
        match msg.payload {
            Some(orchestrator_message::Payload::Setup(setup)) => {
                assert!(!setup.provider.is_empty());
                assert_eq!(setup.setup_id, pending.setup_id);
                assert_eq!(setup.runtime_config_generation, 0);
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
async fn authenticated_runner_failure_quarantines_runtime_and_reschedules_bound_task() {
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
            &format!("runner-admission-failure-{sandbox_id}"),
            "docker",
            "test-image:latest",
            Some(session_id),
            None,
            None,
            Some(&json!({})),
        )
        .await
        .expect("insert linked sandbox");
        queries::transition_sandbox_cas(&pool, sandbox_id, "creating", "provisioning")
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
        sqlx::query(
            r#"
            INSERT INTO joysafeter_tasks (
                id, agent_id, chat_session_id, sandbox_id, status, prompt, output,
                timeout_sec, retry_count, max_retries
            )
            VALUES ($1, $2, $3, $4, 'scheduling', 'test prompt', '', 7200, 0, 2)
            "#,
        )
        .bind(task_id)
        .bind(agent_id)
        .bind(session_id)
        .bind(sandbox_id)
        .execute(&pool)
        .await
        .expect("insert scheduling task");

        crate::kernel::runner::failure::RunnerFailureService::new()
            .eject_sandbox(
                &pool,
                sandbox_id,
                Some(session_id),
                crate::kernel::runner::failure::RunnerFailure::protocol_incompatible(
                    "runner protocol is missing setup_ack_v1",
                ),
                None,
                None,
                &JoySafeterConfig::from_env(),
            )
            .await
            .expect("eject incompatible runner sandbox");

        let sandbox: (String, String, Option<String>) = sqlx::query_as(
            r#"
            SELECT status, runner_auth_state, config #>> '{runtime_failure,code}'
            FROM joysafeter_sandboxes WHERE id = $1
            "#,
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load ejected sandbox");
        assert_eq!(sandbox.0, "error");
        assert_eq!(sandbox.1, "revoked");
        assert_eq!(sandbox.2.as_deref(), Some("runner_protocol_incompatible"));

        let task: (String, Option<SandboxId>, i32) = sqlx::query_as(
            "SELECT status, sandbox_id, retry_count FROM joysafeter_tasks WHERE id = $1",
        )
        .bind(task_id)
        .fetch_one(&pool)
        .await
        .expect("load rescheduled task");
        assert_eq!(task.0, "pending");
        assert_eq!(task.1, None);
        assert_eq!(task.2, 1);

        let session_status: String =
            sqlx::query_scalar("SELECT status FROM joysafeter_sessions WHERE id = $1")
                .bind(session_id)
                .fetch_one(&pool)
                .await
                .expect("load rescheduling session");
        assert_eq!(session_status, "rescheduling");
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
async fn matching_setup_failure_updates_bridge_without_mutating_sandbox_lifecycle() {
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
        bridge.begin_setup("setup-failed".to_string(), 0).await;
        let setup_failure = proto::SandboxSetupResult {
            setup_id: "setup-failed".to_string(),
            runtime_config_generation: 0,
            status: proto::SandboxSetupStatus::Failed as i32,
            error: Some(
                "SetupSandbox failed: clone setup repos to /workspace: clone repo missing"
                    .to_string(),
            ),
            error_code: Some("SETUP_FAILED".to_string()),
            ..Default::default()
        };

        let handling = crate::kernel::runner::setup::record_correlated_setup_result(
            &bridge,
            sandbox_id,
            &setup_failure,
            &RunnerMetrics::default(),
        )
        .await;

        assert!(matches!(handling, SetupResultHandling::Failed(_)));
        assert!(matches!(
            bridge.setup_state().await,
            crate::kernel::sandbox_bridge::SandboxSetupState::Failed {
                runtime_config_generation: 0,
                ..
            }
        ));
        let (status, setup_error): (String, Option<String>) = sqlx::query_as(
            "SELECT status, config->>'setup_error' FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load sandbox after setup failure");
        assert_eq!(status, "creating");
        assert_eq!(setup_error, None);
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
                    mcp_servers, skills, tools, agents, commands,
                    metadata, version
                )
                VALUES (
                    $1, $2, $3, 'claude', $4, '', '{}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, '{}'::jsonb, 1
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
        let harness_input_builder =
            crate::kernel::harness_input_builder::HarnessInputBuilder::new(pool.clone(), false);
        let err = build_start_task_full(
            &harness_input_builder,
            &task,
            sandbox_id,
            &JoySafeterConfig::from_env(),
        )
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
