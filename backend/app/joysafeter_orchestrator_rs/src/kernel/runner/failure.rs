use serde_json::json;
use sqlx::PgPool;
use tracing::{error, info, warn};

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::ids::{SandboxId, SessionId};
use crate::kernel::queue::TaskQueue;

use super::task_lifecycle::compute_retry_delay;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RunnerFailure {
    code: &'static str,
    message: String,
}

impl RunnerFailure {
    pub(crate) fn protocol_incompatible(message: impl Into<String>) -> Self {
        Self {
            code: "runner_protocol_incompatible",
            message: message.into(),
        }
    }

    pub(crate) fn protocol_invalid(message: impl Into<String>) -> Self {
        Self {
            code: "runner_protocol_invalid",
            message: message.into(),
        }
    }

    pub(crate) fn setup_failed(message: impl Into<String>) -> Self {
        Self {
            code: "runner_setup_failed",
            message: message.into(),
        }
    }

    pub(crate) fn execution_unhealthy(message: impl Into<String>) -> Self {
        Self {
            code: "runner_execution_unhealthy",
            message: message.into(),
        }
    }

    pub(crate) fn code(&self) -> &'static str {
        self.code
    }

    pub(crate) fn message(&self) -> &str {
        &self.message
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct RunnerFailureOutcome {
    pub(crate) reset_tasks: usize,
    pub(crate) failed_tasks: usize,
}

#[derive(Clone, Default)]
pub(crate) struct RunnerFailureService;

impl RunnerFailureService {
    pub(crate) fn new() -> Self {
        Self
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn eject_sandbox(
        &self,
        pool: &PgPool,
        sandbox_id: SandboxId,
        session_id: Option<SessionId>,
        failure: RunnerFailure,
        queue: Option<&TaskQueue>,
        redis_coordinator: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
        config: &JoySafeterConfig,
    ) -> anyhow::Result<RunnerFailureOutcome> {
        let recovery = queries::quarantine_and_recover_runner_failure(
            pool,
            sandbox_id,
            failure.code(),
            failure.message(),
        )
        .await?;
        let Some(recovery) = recovery else {
            anyhow::bail!("sandbox {sandbox_id} changed state before Runner failure quarantine");
        };
        let failed_tasks = recovery.failed_tasks;
        self.persist_failed_tasks_idle(pool, &failed_tasks, &failure)
            .await;
        let reset_tasks = recovery.reset_tasks;
        self.persist_reset_tasks_rescheduling(pool, &reset_tasks, &failure)
            .await;

        if let Some(queue) = queue {
            let _ = queue.drain(sandbox_id).await;
            for task in &reset_tasks {
                let delay = compute_retry_delay(task.previous_retry_count as u32, task.id, config);
                let queue = queue.clone();
                let task_id = task.id;
                tokio::spawn(async move {
                    tokio::time::sleep(delay).await;
                    if let Err(error) = queue.push_to_global(task_id).await {
                        warn!(task_id = %task_id, error = %error, "Failed to enqueue Runner failure retry");
                    }
                });
            }
        }

        if let Some(coordinator) = redis_coordinator {
            let _ = coordinator.remove_sandbox_queue(sandbox_id).await;
        }

        if reset_tasks.is_empty() && failed_tasks.is_empty() {
            self.persist_unbound_session_failure(pool, session_id, &failure)
                .await;
        }

        info!(
            sandbox_id = %sandbox_id,
            failure_code = failure.code(),
            reset_tasks = reset_tasks.len(),
            failed_tasks = failed_tasks.len(),
            "Runner failure quarantined sandbox"
        );

        Ok(RunnerFailureOutcome {
            reset_tasks: reset_tasks.len(),
            failed_tasks: failed_tasks.len(),
        })
    }

    async fn persist_failed_tasks_idle(
        &self,
        pool: &PgPool,
        tasks: &[queries::FailedSandboxTask],
        failure: &RunnerFailure,
    ) {
        for task in tasks {
            let Some(session_id) = task.session_id else {
                continue;
            };
            let stop_reason = json!({
                "type": "error",
                "code": failure.code(),
                "message": failure.message(),
            });
            let payload = json!({
                "task_id": task.id.to_string(),
                "stop_reason": stop_reason.clone(),
            });
            if let Err(error) = queries::update_session_status_if_no_active_tasks_and_insert_event(
                pool,
                session_id,
                "idle",
                Some(&stop_reason),
                "session.status_idle",
                &payload,
            )
            .await
            {
                error!(task_id = %task.id, session_id = %session_id, error = %error, "Failed to persist Runner failure task outcome");
            }
        }
    }

    async fn persist_reset_tasks_rescheduling(
        &self,
        pool: &PgPool,
        tasks: &[queries::ResetSandboxTask],
        failure: &RunnerFailure,
    ) {
        for task in tasks {
            let Some(session_id) = task.session_id else {
                continue;
            };
            let stop_reason = json!({
                "type": "sandbox_failed",
                "code": failure.code(),
                "message": failure.message(),
            });
            let payload = json!({
                "task_id": task.id.to_string(),
                "stop_reason": stop_reason.clone(),
            });
            if let Err(error) = queries::update_session_status_and_insert_event(
                pool,
                session_id,
                "rescheduling",
                Some(&stop_reason),
                "session.status_rescheduling",
                &payload,
            )
            .await
            {
                error!(task_id = %task.id, session_id = %session_id, error = %error, "Failed to persist Runner failure rescheduling status");
            }
        }
    }

    async fn persist_unbound_session_failure(
        &self,
        pool: &PgPool,
        session_id: Option<SessionId>,
        failure: &RunnerFailure,
    ) {
        let Some(session_id) = session_id else {
            return;
        };
        let stop_reason = json!({
            "type": "error",
            "code": failure.code(),
            "message": failure.message(),
        });
        let payload = json!({"stop_reason": stop_reason.clone()});
        if let Err(error) = queries::update_session_status_if_no_active_tasks_and_insert_event(
            pool,
            session_id,
            "idle",
            Some(&stop_reason),
            "session.status_idle",
            &payload,
        )
        .await
        {
            error!(session_id = %session_id, error = %error, "Failed to persist unbound Runner failure");
        }
    }
}
