use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tokio::sync::mpsc;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::grpc::harness_projection;
use crate::grpc::proto;
use crate::grpc::proto::{orchestrator_message, OrchestratorMessage};
use crate::ids::{SandboxId, TaskId};
use crate::kernel::harness_input_builder::HarnessInputBuilder;
use crate::kernel::sandbox_bridge::SandboxBridge;

use super::task_lifecycle::TaskResult;

pub(crate) fn is_setup_failure_result(result: &proto::RunnerHarnessResult) -> bool {
    result.status == "failed" && result.error.as_deref().is_some_and(is_setup_failure_error)
}

pub(crate) fn is_setup_failure_error(error: &str) -> bool {
    error.starts_with("SetupSandbox failed")
}

pub(crate) fn is_setup_failure_task_result(result: &TaskResult) -> bool {
    matches!(result, TaskResult::Failed(reason) if is_setup_failure_error(reason))
}

pub(crate) async fn mark_idle_setup_failure(
    pool: &PgPool,
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    result: &proto::RunnerHarnessResult,
) {
    bridge.setup_done.store(false, Ordering::Relaxed);
    let error = result.error.as_deref().unwrap_or("SetupSandbox failed");
    error!(
        sandbox_id = %sandbox_db_id,
        error = error,
        "Runner reported SetupSandbox failure while idle; marking sandbox error"
    );
    if let Err(err) = queries::mark_sandbox_error(pool, sandbox_db_id, Some(error)).await {
        warn!(
            sandbox_id = %sandbox_db_id,
            error = %err,
            "Failed to mark sandbox error after SetupSandbox failure"
        );
    }
}

pub(crate) async fn send_setup(
    pool: &PgPool,
    _bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    tx: &mpsc::Sender<OrchestratorMessage>,
    harness_input_builder: &HarnessInputBuilder,
) -> anyhow::Result<bool> {
    let mut session_id = None;
    for attempt in 0..50 {
        if let Some(sandbox) = queries::get_sandbox(pool, sandbox_db_id).await? {
            if let Some(sid) = sandbox.chat_session_id {
                session_id = Some(sid);
                break;
            }
        }
        if attempt < 49 {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    let Some(session_id) = session_id else {
        warn!(sandbox_id = %sandbox_db_id, "Timed out waiting for session link; setup not sent");
        return Ok(false);
    };

    let Some(session) = queries::get_session(pool, session_id).await? else {
        anyhow::bail!("linked session {session_id} not found for sandbox {sandbox_db_id}");
    };

    let setup_task = crate::db::models::JoySafeterTask {
        id: TaskId::from_uuid(Uuid::now_v7()),
        project_id: session.project_id.clone(),
        agent_id: session.agent_id,
        session_id: Some(session_id),
        sandbox_id: Some(sandbox_db_id),
        status: "setup".to_string(),
        prompt: String::new(),
        system_prompt: None,
        output: String::new(),
        error: None,
        usage: None,
        timeout_sec: None,
        retry_count: 0,
        max_retries: 0,
        schedule_attempts: 0,
        next_schedule_at: None,
        last_schedule_error: None,
        last_schedule_error_type: None,
        scheduling_started_at: None,
        started_at: None,
        completed_at: None,
        duration_ms: None,
        created_at: chrono::Utc::now(),
        updated_at: chrono::Utc::now(),
        owner_epoch: None,
    };

    let input = harness_input_builder
        .build(
            &setup_task,
            &sandbox_db_id.as_uuid().to_string(),
            sandbox_db_id,
        )
        .await?;
    let msg = OrchestratorMessage {
        payload: Some(orchestrator_message::Payload::Setup(
            harness_projection::setup_sandbox(&input),
        )),
    };
    tx.send(msg)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to send SetupSandbox: {e}"))?;
    info!(sandbox_id = %sandbox_db_id, "SetupSandbox sent");

    Ok(true)
}

// ---------------------------------------------------------------------------
// Sandbox cleanup
// ---------------------------------------------------------------------------

pub(crate) async fn build_start_task_full(
    harness_input_builder: &HarnessInputBuilder,
    task: &crate::db::models::JoySafeterTask,
    sandbox_db_id: SandboxId,
    config: &JoySafeterConfig,
) -> anyhow::Result<proto::StartTask> {
    let timeout_seconds = task
        .timeout_sec
        .unwrap_or(config.task_default_timeout as i32) as u64;
    let input = harness_input_builder
        .build(task, &sandbox_db_id.as_uuid().to_string(), sandbox_db_id)
        .await?;
    Ok(harness_projection::start_task(
        &input,
        task.id,
        timeout_seconds,
    ))
}
