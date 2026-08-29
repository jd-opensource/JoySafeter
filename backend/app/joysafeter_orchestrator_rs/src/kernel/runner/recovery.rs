use crate::ids::TaskId;
use sqlx::PgPool;
use tracing::{error, info, warn};

use crate::events::bus::EventBus;
use crate::ids::SandboxId;
use crate::kernel::queue::TaskQueue;

use super::session::handle_dispatch_retryable_failure;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ReconnectPlan {
    Fresh,
    Resume(TaskId),
    RescueOrphans,
}

/// Owns reconnect classification and orphan-recovery policy for Runner sessions.
#[derive(Clone, Default)]
pub(crate) struct RunnerRecoveryService;

impl RunnerRecoveryService {
    pub(crate) fn new() -> Self {
        Self
    }

    pub(crate) fn handle_reconnect(
        &self,
        is_reconnect: bool,
        active_task_id: Option<&str>,
    ) -> Result<ReconnectPlan, crate::ids::EntityIdParseError> {
        if !is_reconnect {
            return Ok(ReconnectPlan::Fresh);
        }
        active_task_id
            .map(TaskId::from_public)
            .transpose()
            .map(|task_id| match task_id {
                Some(task_id) => ReconnectPlan::Resume(task_id),
                None => ReconnectPlan::RescueOrphans,
            })
    }

    pub(crate) async fn rescue_orphaned_tasks(
        &self,
        pool: &PgPool,
        event_bus: &EventBus,
        sandbox_id: SandboxId,
        queue: &TaskQueue,
    ) {
        match crate::db::queries::find_running_tasks_for_sandbox(pool, sandbox_id).await {
            Ok(tasks) => {
                for task in tasks {
                    let task_id = task.id;
                    handle_dispatch_retryable_failure(
                        pool,
                        event_bus,
                        &task,
                        task.session_id,
                        sandbox_id,
                        task.owner_epoch,
                        "Orphaned running task exceeded reconnect retry limit",
                        None,
                    )
                    .await;
                    if matches!(
                        crate::db::queries::get_task(pool, task_id).await,
                        Ok(Some(ref updated)) if updated.status == "pending"
                    ) {
                        match queue.push_to_global(task_id).await {
                            Ok(()) => {
                                info!(task_id = %task_id, "Orphaned task reset and re-queued")
                            }
                            Err(error) => {
                                warn!(task_id = %task_id, %error, "Failed to re-queue orphaned task")
                            }
                        }
                    }
                }
            }
            Err(error) => {
                error!(sandbox_id = %sandbox_id, %error, "Failed to rescue orphaned tasks")
            }
        }
    }
}
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{mpsc, Semaphore};
use tonic::Streaming;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::grpc::proto;
use crate::grpc::proto::{orchestrator_message, OrchestratorMessage, RunnerMessage};
use crate::ids::SessionId;
use crate::kernel::ha::BridgeStore;
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::sandbox_bridge::SandboxBridge;
use crate::kernel::sandbox_resolver::SandboxResolver;
use crate::runtime_config::RuntimeConfig;

use super::execution::{replay_pending_control_inputs, run_single_task, TaskResult};
use super::session::{emit_session_running_status, failover_or_fail_inline};

const HEARTBEAT_TIMEOUT_DEFAULT: u64 = 120;

impl RunnerRecoveryService {
    /// Runs a complete event loop for a reconnected active task.
    pub(crate) async fn handle_reconnect_with_event_loop(
        &self,
        inbound: &mut Streaming<RunnerMessage>,
        tx: &mpsc::Sender<OrchestratorMessage>,
        bridge: &Arc<SandboxBridge>,
        pool: &PgPool,
        event_bus: &EventBus,
        config: &JoySafeterConfig,
        sandbox_db_id: SandboxId,
        active_task_id: TaskId,
        linked_session_id: Option<SessionId>,
        exec_sem: &Arc<Semaphore>,
        redis_coord: Option<&crate::kernel::redis_coordinator::RedisCoordinator>,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
        bridge_store: Arc<dyn BridgeStore>,
        runtime_config: &RuntimeConfig,
        sandbox_resolver: Arc<SandboxResolver>,
    ) {
        // Verify task exists and belongs to this sandbox
        let task = match queries::get_task(pool, active_task_id).await {
            Ok(Some(t)) => t,
            _ => {
                warn!(task_id = %active_task_id, "Reconnect: task not found");
                return;
            }
        };

        if task.sandbox_id != Some(sandbox_db_id) {
            warn!(task_id = %active_task_id, "Reconnect: task belongs to different sandbox");
            return;
        }

        let status = crate::db::models::TaskStatus::from_str(&task.status);
        if status.as_ref().map(|s| s.is_terminal()).unwrap_or(false) {
            info!(task_id = %active_task_id, status = %task.status, "Reconnect: task already terminal");
            return;
        }

        // #17: Acquire execution semaphore (blocking, Python L374)
        // G2 fix: handle closed semaphore gracefully (same as multi_task_loop)
        let _exec_permit = match exec_sem.clone().acquire_owned().await {
            Ok(p) => p,
            Err(_) => {
                warn!(task_id = %active_task_id, "Execution semaphore closed during reconnect");
                return;
            }
        };

        info!(task_id = %active_task_id, "Resuming reconnected active task with full event loop");

        bridge.setup_done.store(true, Ordering::Relaxed);
        *bridge.current_task_owner_epoch.lock().await = task.owner_epoch;
        *bridge.current_task_id.lock().await = Some(active_task_id);
        let session_id = task.session_id.or(linked_session_id);

        // #5: Redis set_task_sandbox (Python L382-384)
        if let Some(coord) = redis_coord {
            let _ = coord
                .map_task_to_sandbox(active_task_id, sandbox_db_id)
                .await;
        }

        if let Some(sid) = session_id {
            if let Err(e) = replay_pending_control_inputs(pool, sid, tx, active_task_id).await {
                warn!(task_id = %active_task_id, session_id = %sid, error = %e, "Failed to replay pending DB control inputs");
            }
        }

        // Also drain in-memory control queue
        {
            let mut ctrl_rx = bridge.control_rx.lock().await;
            while let Ok(content) = ctrl_rx.try_recv() {
                let input_msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Input(proto::SendInput {
                        content,
                    })),
                };
                let _ = tx.send(input_msg).await;
            }
        }

        let _ = emit_session_running_status(
            pool,
            event_bus,
            active_task_id,
            session_id,
            sandbox_db_id,
            "reconnect",
        )
        .await;

        // Run the full task event loop (same as run_single_task)
        let heartbeat_timeout = Duration::from_secs(
            runtime_config
                .heartbeat_timeout_sec()
                .max(HEARTBEAT_TIMEOUT_DEFAULT),
        );
        // Reset cancel token for the reconnected task
        bridge.reset_cancel().await;
        let task_cancel = bridge.current_cancel_token().await;
        let result = run_single_task(
            inbound,
            tx,
            bridge,
            pool,
            event_bus,
            config,
            active_task_id,
            task.owner_epoch,
            session_id,
            sandbox_db_id,
            heartbeat_timeout,
            memory_subscribers.clone(),
            bridge_store,
            sandbox_resolver.as_ref(),
            &task_cancel,
            None,
        )
        .await;

        if !matches!(result, TaskResult::Disconnected) {
            if let Err(error) = sandbox_resolver
                .clear_task_agent_identity_policy(sandbox_db_id, active_task_id)
                .await
            {
                error!(
                    sandbox_id = %sandbox_db_id,
                    task_id = %active_task_id,
                    error = %error,
                    "Agent Identity policy cleanup failed closed after reconnect"
                );
            }
        }

        // Clear task on bridge
        *bridge.current_task_id.lock().await = None;
        *bridge.current_task_owner_epoch.lock().await = None;
        bridge
            .requires_action_pending
            .store(false, Ordering::Relaxed);
        bridge.reset_confirmation();
        let _ = queries::complete_sandbox_task(pool, sandbox_db_id).await;

        match result {
            TaskResult::Completed => {
                info!(task_id = %active_task_id, "Reconnected task completed");
            }
            TaskResult::Failed(ref reason) => {
                // #6: failover_or_fail_task on reconnect failure (Python L824-835)
                warn!(task_id = %active_task_id, "Reconnected task failed: {reason}");
                failover_or_fail_inline(
                    pool,
                    event_bus,
                    active_task_id,
                    task.owner_epoch,
                    session_id,
                    sandbox_db_id,
                    reason,
                    None,
                )
                .await;
                if let Some(coord) = redis_coord {
                    let _ = coord.remove_task_sandbox(active_task_id).await;
                }
            }
            TaskResult::Timeout => {
                warn!(task_id = %active_task_id, "Reconnected task timed out");
                if let Some(coord) = redis_coord {
                    let _ = coord.remove_task_sandbox(active_task_id).await;
                }
            }
            TaskResult::Cancelled => {
                info!(task_id = %active_task_id, "Reconnected task cancelled");
                if let Some(coord) = redis_coord {
                    let _ = coord.remove_task_sandbox(active_task_id).await;
                }
            }
            TaskResult::Disconnected => {
                // #6: failover on disconnect (Python L824-835)
                warn!(task_id = %active_task_id, "Runner disconnected again during reconnected task");
                failover_or_fail_inline(
                    pool,
                    event_bus,
                    active_task_id,
                    task.owner_epoch,
                    session_id,
                    sandbox_db_id,
                    "runner disconnected",
                    None,
                )
                .await;
                if let Some(coord) = redis_coord {
                    let _ = coord.remove_task_sandbox(active_task_id).await;
                }
            }
        }
    }
}
