use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::grpc::harness_projection;
use crate::grpc::proto;
use crate::grpc::proto::{orchestrator_message, runner_message, OrchestratorMessage};
use crate::ids::{SandboxId, TaskId};
use crate::kernel::harness_input_builder::HarnessInputBuilder;
use crate::kernel::runner::inbound::RunnerInbound;
use crate::kernel::runner::metrics::{RunnerMetrics, SetupFailureKind};
use crate::kernel::runner::skill_usage::{
    persist_skill_materialization_receipts, SkillLoadManifest,
};
use crate::kernel::sandbox_bridge::{SandboxBridge, SetupResultDisposition};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PendingSetup {
    pub(crate) setup_id: String,
    pub(crate) runtime_config_generation: i64,
    pub(crate) skill_manifest: SkillLoadManifest,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum SetupResultHandling {
    Applied,
    Failed(String),
    Stale,
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum SetupFlowError {
    #[error("{0}")]
    RunnerProtocol(String),
    #[error("{0}")]
    Setup(String),
}

impl SetupFlowError {
    pub(crate) fn runner_protocol(message: impl Into<String>) -> Self {
        Self::RunnerProtocol(message.into())
    }

    pub(crate) fn setup(message: impl Into<String>) -> Self {
        Self::Setup(message.into())
    }

    pub(crate) fn is_runner_fault(&self) -> bool {
        matches!(self, Self::RunnerProtocol(_))
    }
}

pub(crate) fn validate_reconnect_setup_generation(
    runtime_config_status: &str,
    applied_generation: i64,
    reported_generation: Option<i64>,
) -> Result<i64, String> {
    if runtime_config_status != "ready" {
        return Err(format!(
            "runtime configuration is {runtime_config_status}, expected ready"
        ));
    }
    match reported_generation {
        Some(generation) if generation == applied_generation => Ok(generation),
        Some(generation) => Err(format!(
            "runner reported runtime configuration generation {generation}, expected {applied_generation}"
        )),
        None => Err(format!(
            "runner did not report applied runtime configuration generation {applied_generation}"
        )),
    }
}

pub(crate) async fn record_correlated_setup_result(
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    result: &proto::SandboxSetupResult,
    metrics: &RunnerMetrics,
) -> SetupResultHandling {
    let status = proto::SandboxSetupStatus::try_from(result.status)
        .unwrap_or(proto::SandboxSetupStatus::Unspecified);
    let success = status == proto::SandboxSetupStatus::Applied;
    let error_message = if success {
        None
    } else {
        Some(
            result
                .error
                .clone()
                .unwrap_or_else(|| "SetupSandbox failed without an error message".to_string()),
        )
    };
    let disposition = bridge
        .record_setup_result(
            &result.setup_id,
            result.runtime_config_generation,
            success,
            error_message.clone(),
        )
        .await;

    match disposition {
        SetupResultDisposition::Applied => {
            metrics.record_setup_applied();
            SetupResultHandling::Applied
        }
        SetupResultDisposition::Stale => {
            metrics.record_setup_stale();
            debug!(
                sandbox_id = %sandbox_db_id,
                setup_id = %result.setup_id,
                runtime_config_generation = result.runtime_config_generation,
                "Ignoring stale SetupSandbox result"
            );
            SetupResultHandling::Stale
        }
        SetupResultDisposition::Failed => {
            metrics.record_setup_failed(SetupFailureKind::RunnerRejected);
            let error_message = error_message
                .unwrap_or_else(|| "SetupSandbox failed without an error message".to_string());
            error!(
                sandbox_id = %sandbox_db_id,
                setup_id = %result.setup_id,
                runtime_config_generation = result.runtime_config_generation,
                error = %error_message,
                error_code = ?result.error_code,
                "Runner rejected SetupSandbox"
            );
            SetupResultHandling::Failed(error_message)
        }
    }
}

pub(crate) async fn handle_out_of_band_setup_result(
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    result: &proto::SandboxSetupResult,
    metrics: &RunnerMetrics,
) -> SetupResultHandling {
    let status = proto::SandboxSetupStatus::try_from(result.status)
        .unwrap_or(proto::SandboxSetupStatus::Unspecified);
    let reported_success = status == proto::SandboxSetupStatus::Applied;
    let error_message = if reported_success {
        "Runner SetupSandbox success arrived outside the correlated setup gate".to_string()
    } else {
        result
            .error
            .clone()
            .unwrap_or_else(|| "SetupSandbox failed without an error message".to_string())
    };
    let disposition = bridge
        .record_setup_result(
            &result.setup_id,
            result.runtime_config_generation,
            false,
            Some(error_message.clone()),
        )
        .await;

    match disposition {
        SetupResultDisposition::Stale => {
            metrics.record_setup_stale();
            debug!(
                sandbox_id = %sandbox_db_id,
                setup_id = %result.setup_id,
                runtime_config_generation = result.runtime_config_generation,
                "Ignoring stale SetupSandbox result outside the setup gate"
            );
            SetupResultHandling::Stale
        }
        SetupResultDisposition::Failed | SetupResultDisposition::Applied => {
            metrics.record_setup_failed(if reported_success {
                SetupFailureKind::ProtocolError
            } else {
                SetupFailureKind::RunnerRejected
            });
            error!(
                sandbox_id = %sandbox_db_id,
                setup_id = %result.setup_id,
                runtime_config_generation = result.runtime_config_generation,
                error = %error_message,
                error_code = ?result.error_code,
                "Rejected SetupSandbox result outside the correlated setup gate"
            );
            SetupResultHandling::Failed(error_message)
        }
    }
}

pub(crate) async fn send_setup(
    pool: &PgPool,
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    tx: &mpsc::Sender<OrchestratorMessage>,
    harness_input_builder: &HarnessInputBuilder,
    metrics: &RunnerMetrics,
) -> anyhow::Result<Option<PendingSetup>> {
    let mut session_id = None;
    for attempt in 0..50 {
        if let Some(sandbox) = queries::get_sandbox(pool, sandbox_db_id).await? {
            if let Some(linked_session_id) = sandbox.chat_session_id {
                session_id = Some(linked_session_id);
                break;
            }
        }
        if attempt < 49 {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    let Some(session_id) = session_id else {
        warn!(sandbox_id = %sandbox_db_id, "Timed out waiting for session link; setup not sent");
        return Ok(None);
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
    let setup = harness_projection::setup_sandbox(&input, Uuid::now_v7().to_string());
    let pending = PendingSetup {
        setup_id: setup.setup_id.clone(),
        runtime_config_generation: input.runtime_config_generation,
        skill_manifest: SkillLoadManifest::from_archives(&setup.skills)?,
    };
    bridge
        .begin_setup(pending.setup_id.clone(), pending.runtime_config_generation)
        .await;
    let message = OrchestratorMessage {
        payload: Some(orchestrator_message::Payload::Setup(setup)),
    };
    if let Err(send_error) = tx.send(message).await {
        let reason = format!("Failed to send SetupSandbox: {send_error}");
        metrics.record_setup_failed(SetupFailureKind::SendFailed);
        let _ = bridge
            .record_setup_result(
                &pending.setup_id,
                pending.runtime_config_generation,
                false,
                Some(reason.clone()),
            )
            .await;
        anyhow::bail!(reason);
    }
    metrics.record_setup_sent();
    info!(
        sandbox_id = %sandbox_db_id,
        setup_id = %pending.setup_id,
        runtime_config_generation = pending.runtime_config_generation,
        "SetupSandbox sent"
    );

    Ok(Some(pending))
}

pub(crate) async fn initialize_setup(
    inbound: &mut dyn RunnerInbound,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    sandbox_db_id: SandboxId,
    harness_input_builder: &HarnessInputBuilder,
    metrics: &RunnerMetrics,
) -> Result<(), SetupFlowError> {
    send_and_wait_setup(
        inbound,
        tx,
        bridge,
        pool,
        sandbox_db_id,
        None,
        harness_input_builder,
        metrics,
    )
    .await
}

pub(crate) async fn ensure_setup_applied(
    inbound: &mut dyn RunnerInbound,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    sandbox_db_id: SandboxId,
    expected_generation: i64,
    harness_input_builder: &HarnessInputBuilder,
    metrics: &RunnerMetrics,
) -> Result<(), SetupFlowError> {
    if bridge.setup_applied_for(expected_generation).await {
        return Ok(());
    }

    send_and_wait_setup(
        inbound,
        tx,
        bridge,
        pool,
        sandbox_db_id,
        Some(expected_generation),
        harness_input_builder,
        metrics,
    )
    .await
}

#[allow(clippy::too_many_arguments)]
async fn send_and_wait_setup(
    inbound: &mut dyn RunnerInbound,
    tx: &mpsc::Sender<OrchestratorMessage>,
    bridge: &Arc<SandboxBridge>,
    pool: &PgPool,
    sandbox_db_id: SandboxId,
    expected_generation: Option<i64>,
    harness_input_builder: &HarnessInputBuilder,
    metrics: &RunnerMetrics,
) -> Result<(), SetupFlowError> {
    let pending = send_setup(
        pool,
        bridge,
        sandbox_db_id,
        tx,
        harness_input_builder,
        metrics,
    )
    .await
    .map_err(|error| SetupFlowError::setup(error.to_string()))?
    .ok_or_else(|| {
        SetupFlowError::setup(format!(
            "Failed to send SetupSandbox: sandbox {sandbox_db_id} has no linked session"
        ))
    })?;

    if let Some(expected_generation) = expected_generation {
        if pending.runtime_config_generation != expected_generation {
            let reason = format!(
                "SetupSandbox generation {} does not match StartTask generation {expected_generation}",
                pending.runtime_config_generation
            );
            record_setup_gate_failure(
                bridge,
                sandbox_db_id,
                &pending,
                SetupFailureKind::GenerationMismatch,
                &reason,
                metrics,
            )
            .await;
            return Err(SetupFlowError::setup(reason));
        }
    }

    let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
    loop {
        let runner_message = match tokio::time::timeout_at(deadline, inbound.message()).await {
            Err(_) => {
                let reason = format!(
                    "Timed out waiting for SetupSandbox ACK for generation {}",
                    pending.runtime_config_generation
                );
                record_setup_gate_failure(
                    bridge,
                    sandbox_db_id,
                    &pending,
                    SetupFailureKind::AckTimeout,
                    &reason,
                    metrics,
                )
                .await;
                return Err(SetupFlowError::setup(reason));
            }
            Ok(Err(error)) => {
                let reason = format!("Runner stream failed before SetupSandbox ACK: {error}");
                record_setup_gate_failure(
                    bridge,
                    sandbox_db_id,
                    &pending,
                    SetupFailureKind::StreamError,
                    &reason,
                    metrics,
                )
                .await;
                return Err(SetupFlowError::setup(reason));
            }
            Ok(Ok(None)) => {
                let reason = "Runner disconnected before SetupSandbox ACK".to_string();
                record_setup_gate_failure(
                    bridge,
                    sandbox_db_id,
                    &pending,
                    SetupFailureKind::RunnerDisconnected,
                    &reason,
                    metrics,
                )
                .await;
                return Err(SetupFlowError::setup(reason));
            }
            Ok(Ok(Some(message))) => message,
        };

        match runner_message.payload {
            Some(runner_message::Payload::SetupResult(result)) => {
                if result.setup_id != pending.setup_id
                    || result.runtime_config_generation != pending.runtime_config_generation
                {
                    let _ =
                        handle_out_of_band_setup_result(bridge, sandbox_db_id, &result, metrics)
                            .await;
                    continue;
                }
                let applied = proto::SandboxSetupStatus::try_from(result.status)
                    .is_ok_and(|status| status == proto::SandboxSetupStatus::Applied);
                if applied {
                    if let Err(error) = persist_skill_materialization_receipts(
                        pool,
                        sandbox_db_id,
                        &pending.skill_manifest,
                        &result.loaded_skills,
                    )
                    .await
                    {
                        let runner_fault = error.is_protocol();
                        let reason = error.to_string();
                        let failure_kind = if runner_fault {
                            SetupFailureKind::ProtocolError
                        } else {
                            SetupFailureKind::AuditPersistence
                        };
                        record_setup_gate_failure(
                            bridge,
                            sandbox_db_id,
                            &pending,
                            failure_kind,
                            &reason,
                            metrics,
                        )
                        .await;
                        return Err(if runner_fault {
                            SetupFlowError::runner_protocol(reason)
                        } else {
                            SetupFlowError::setup(reason)
                        });
                    }
                } else if !result.loaded_skills.is_empty() {
                    let reason = "Runner returned skill receipts for a failed SetupSandbox";
                    record_setup_gate_failure(
                        bridge,
                        sandbox_db_id,
                        &pending,
                        SetupFailureKind::ProtocolError,
                        reason,
                        metrics,
                    )
                    .await;
                    return Err(SetupFlowError::runner_protocol(reason));
                }
                match record_correlated_setup_result(bridge, sandbox_db_id, &result, metrics).await
                {
                    SetupResultHandling::Applied
                        if bridge
                            .setup_applied_for(pending.runtime_config_generation)
                            .await =>
                    {
                        return Ok(())
                    }
                    SetupResultHandling::Failed(reason) => {
                        return Err(SetupFlowError::setup(reason))
                    }
                    SetupResultHandling::Applied | SetupResultHandling::Stale => {}
                }
            }
            Some(runner_message::Payload::Heartbeat(heartbeat)) => {
                if let Err(error) = bridge
                    .record_runner_heartbeat(
                        &heartbeat.runtime_state,
                        heartbeat.active_task_id.as_deref(),
                        heartbeat.harness_session_id,
                    )
                    .await
                {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Ignoring invalid runner heartbeat during setup");
                }
            }
            Some(runner_message::Payload::SandboxFileResponse(response)) => {
                let _ = bridge.complete_sandbox_file_response(response).await;
            }
            Some(runner_message::Payload::Idle(_)) => {}
            Some(other) => {
                let reason =
                    format!("Unexpected runner message before SetupSandbox ACK: {other:?}");
                record_setup_gate_failure(
                    bridge,
                    sandbox_db_id,
                    &pending,
                    SetupFailureKind::ProtocolError,
                    &reason,
                    metrics,
                )
                .await;
                return Err(SetupFlowError::runner_protocol(reason));
            }
            None => {}
        }
    }
}

async fn record_setup_gate_failure(
    bridge: &Arc<SandboxBridge>,
    sandbox_db_id: SandboxId,
    pending: &PendingSetup,
    failure_kind: SetupFailureKind,
    reason: &str,
    metrics: &RunnerMetrics,
) {
    let disposition = bridge
        .record_setup_result(
            &pending.setup_id,
            pending.runtime_config_generation,
            false,
            Some(reason.to_string()),
        )
        .await;
    if disposition != SetupResultDisposition::Failed {
        return;
    }
    metrics.record_setup_failed(failure_kind);
    error!(
        sandbox_id = %sandbox_db_id,
        setup_id = %pending.setup_id,
        runtime_config_generation = pending.runtime_config_generation,
        error = reason,
        error_code = failure_kind.as_str(),
        "SetupSandbox gate failed"
    );
}

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
