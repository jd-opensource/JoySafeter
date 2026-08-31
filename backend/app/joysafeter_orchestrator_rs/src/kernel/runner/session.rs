use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use sqlx::PgPool;
use tokio::sync::{mpsc, OwnedSemaphorePermit};
use tokio_stream::wrappers::ReceiverStream;
use tracing::{debug, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::events::bus::EventBus;
use crate::grpc::proto;
use crate::grpc::proto::{orchestrator_message, runner_message, OrchestratorMessage, Shutdown};
use crate::ids::SandboxId;
#[cfg(test)]
use crate::ids::{
    AgentId, FileId, MemoryStoreId, OrganizationId, ProjectId, SessionId, SessionResourceId, TaskId,
};
use crate::kernel::ha::BridgeStore;
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::queue::TaskQueue;
#[cfg(test)]
use crate::kernel::runner::cleanup::RunnerCleanupService;
#[cfg(test)]
use crate::kernel::runner::execution::fail_setup_gate;
use crate::kernel::runner::execution::multi_task_loop;
use crate::kernel::runner::flows::RunnerFlowSet;
use crate::kernel::runner::inbound::RunnerInbound;
#[cfg(test)]
use crate::kernel::runner::memory_sync::handle_memory_sync_db;
#[cfg(test)]
use crate::kernel::runner::metrics::RunnerMetrics;
#[cfg(test)]
use crate::kernel::runner::recovery::RunnerRecoveryService;
use crate::kernel::runner::recovery::{ReconnectPlan, ReconnectSetupRestoreError};
use crate::kernel::runner::setup::initialize_setup;
#[cfg(test)]
use crate::kernel::runner::setup::{build_start_task_full, send_setup, SetupResultHandling};
#[cfg(test)]
use crate::kernel::runner::task_lifecycle::{
    fail_pre_start_task, failover_or_fail_inline, handle_dispatch_retryable_failure,
    handle_task_disconnect_before_result, send_start_task_or_handle_failure,
    transition_running_task_and_emit_idle, TaskResult,
};
use crate::kernel::sandbox_bridge::SandboxBridge;
use crate::kernel::sandbox_resolver::SandboxIdentityPolicy;
use crate::runtime_config::RuntimeConfig;

#[cfg(test)]
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RunnerSessionExit {
    Disconnected,
    Rejected,
    FailureEjected,
}

fn should_wait_for_runner_reconnect(exit: RunnerSessionExit) -> bool {
    exit == RunnerSessionExit::Disconnected
}

/// Coordinates authenticated Runner sessions and delegates execution/recovery flows.
pub(crate) struct RunnerSessionCoordinator {
    bridge_store: Arc<dyn BridgeStore>,
    event_bus: EventBus,
    queue: TaskQueue,
    pool: PgPool,
    config: JoySafeterConfig,
    identity_policy: Arc<dyn SandboxIdentityPolicy>,
    runtime_config: Arc<RuntimeConfig>,
    flows: RunnerFlowSet,
    redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
}

impl RunnerSessionCoordinator {
    pub(crate) fn new(
        bridge_store: Arc<dyn BridgeStore>,
        event_bus: EventBus,
        queue: TaskQueue,
        pool: PgPool,
        config: JoySafeterConfig,
        identity_policy: Arc<dyn SandboxIdentityPolicy>,
        redis_coordinator: Option<Arc<crate::kernel::redis_coordinator::RedisCoordinator>>,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
        runtime_config: Arc<RuntimeConfig>,
        flows: RunnerFlowSet,
    ) -> Self {
        Self {
            bridge_store,
            event_bus,
            queue,
            pool,
            config,
            identity_policy,
            runtime_config,
            flows,
            redis_coordinator,
            memory_subscribers,
        }
    }
}

impl RunnerSessionCoordinator {
    pub(crate) async fn open_session(
        &self,
        mut inbound: Box<dyn RunnerInbound>,
        conn_permit: OwnedSemaphorePermit,
    ) -> ReceiverStream<OrchestratorMessage> {
        let (tx, rx) = mpsc::channel::<OrchestratorMessage>(256);
        let outbound = ReceiverStream::new(rx);

        let bridge_store = self.bridge_store.clone();
        let event_bus = self.event_bus.clone();
        let queue = self.queue.clone();
        let pool = self.pool.clone();
        let config = self.config.clone();
        let identity_policy = self.identity_policy.clone();
        let runtime_config = self.runtime_config.clone();
        let redis_coordinator = self.redis_coordinator.clone();
        let memory_subscribers = self.memory_subscribers.clone();
        let execution_semaphore = self.flows.execution_semaphore();
        let harness_input_builder = self.flows.harness_input_builder();
        let runner_metrics = self.flows.metrics();
        let admission_service = self.flows.admission();
        let failure_service = self.flows.failure();
        let recovery_service = self.flows.recovery();
        let cleanup_service = self.flows.cleanup();

        tokio::spawn(async move {
            // Keep the connection permit for the lifetime of the spawned task.
            let _conn_permit = conn_permit;
            // Now inside the spawned task, response headers have been sent.
            // The client can send RunnerReady.
            let ready = match wait_for_ready(inbound.as_mut()).await {
                Ok(Some(r)) => r,
                Ok(None) => {
                    warn!("First message was not RunnerReady, closing");
                    return;
                }
                Err(e) => {
                    warn!("Failed to receive RunnerReady: {e}");
                    return;
                }
            };

            // The runner protocol carries the physical bare UUID.
            let sandbox_db_id = match ready.sandbox_id.parse::<Uuid>() {
                Ok(id) => SandboxId::from_uuid(id),
                Err(_) => {
                    warn!("Invalid sandbox_id: {}", ready.sandbox_id);
                    return;
                }
            };

            let sandbox_external_id = ready.sandbox_id.clone();
            info!(
                sandbox_id = %sandbox_external_id,
                runner_version = %ready.runner_version,
                providers = ?ready.available_providers,
                is_reconnect = ready.is_reconnect,
                "Runner connected"
            );

            let verified = match admission_service
                .verify_identity(sandbox_db_id, ready.runner_token.as_deref(), Utc::now())
                .await
            {
                Ok(authenticated) => authenticated,
                Err(error) => {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Runner authentication rejected");
                    send_shutdown(&tx, "authentication failed".to_string()).await;
                    return;
                }
            };

            if let Err(protocol_failure) =
                super::admission::validate_runner_protocol(&ready.capabilities)
            {
                warn!(
                    sandbox_id = %sandbox_db_id,
                    runner_version = %ready.runner_version,
                    failure_code = protocol_failure.code(),
                    "Authenticated Runner is incompatible with the required protocol"
                );
                let failure = super::failure::RunnerFailure::protocol_incompatible(
                    protocol_failure.message(),
                );
                if let Err(error) = failure_service
                    .eject_sandbox(
                        &pool,
                        sandbox_db_id,
                        verified.linked_session_id(),
                        failure,
                        Some(&queue),
                        redis_coordinator.as_deref(),
                        &config,
                    )
                    .await
                {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Failed to quarantine incompatible Runner");
                }
                send_shutdown(&tx, protocol_failure.message().to_string()).await;
                return;
            }

            let authenticated = match admission_service.accept(&verified).await {
                Ok(authenticated) => authenticated,
                Err(error) => {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Runner connection admission changed before commit");
                    send_shutdown(&tx, "authentication state changed".to_string()).await;
                    return;
                }
            };

            // Create and register bridge
            let bridge = Arc::new(SandboxBridge::new(sandbox_db_id, tx.clone()));
            // Store capabilities
            {
                let mut caps = bridge.runner_capabilities.lock().await;
                *caps = ready.capabilities.clone();
            }
            bridge_store.register(sandbox_external_id.clone(), bridge.clone());

            // Resolve linked session_id. From this point onward every exit is
            // finalized through the same bridge/Redis/memory cleanup path.
            let linked_session_id = authenticated.linked_session_id;
            let registry = bridge_store.clone();
            let bridge_clone = bridge.clone();
            let exec_sem = execution_semaphore.clone();
            let redis_coord = redis_coordinator.clone();
            let session_exit = async {
                let unclaimed_pool_sandbox = should_defer_initial_setup(
                    Some(authenticated.sandbox_status.as_str()),
                    linked_session_id.is_some(),
                );

                if unclaimed_pool_sandbox {
                    bridge.clear_setup().await;
                    debug!(
                        sandbox_id = %sandbox_db_id,
                        "Warm-pool sandbox connected; deferring SetupSandbox until session claim"
                    );
                } else if !ready.is_reconnect {
                    match initialize_setup(
                        inbound.as_mut(),
                        &tx,
                        &bridge,
                        &pool,
                        sandbox_db_id,
                        &harness_input_builder,
                        &runner_metrics,
                    )
                    .await
                    {
                        Ok(()) => {}
                        Err(error) => {
                            warn!(sandbox_id = %sandbox_db_id, "Failed to establish SetupSandbox: {error}");
                            let runner_fault = error.is_runner_fault();
                            let reason = format!("Failed to establish SetupSandbox: {error}");
                            let failure = if runner_fault {
                                super::failure::RunnerFailure::protocol_invalid(reason.clone())
                            } else {
                                super::failure::RunnerFailure::setup_failed(reason.clone())
                            };
                            if let Err(failure_error) = failure_service
                                .eject_sandbox(
                                    &pool,
                                    sandbox_db_id,
                                    linked_session_id,
                                    failure,
                                    Some(&queue),
                                    redis_coordinator.as_deref(),
                                    &config,
                                )
                                .await
                            {
                                warn!(sandbox_id = %sandbox_db_id, error = %failure_error, "Failed to quarantine sandbox after SetupSandbox send failure");
                            }
                            send_shutdown(&tx, reason).await;
                            return RunnerSessionExit::FailureEjected;
                        }
                    }
                } else {
                    match recovery_service
                        .restore_setup_state(
                            &pool,
                            &bridge,
                            sandbox_db_id,
                            ready.applied_runtime_config_generation,
                            &runner_metrics,
                        )
                        .await
                    {
                        Ok(()) => {}
                        Err(ReconnectSetupRestoreError::MissingSandbox) => {
                            send_shutdown(&tx, "sandbox disappeared during reconnect".to_string())
                                .await;
                            return RunnerSessionExit::Rejected;
                        }
                        Err(ReconnectSetupRestoreError::Store(error)) => {
                            warn!(sandbox_id = %sandbox_db_id, error = %error, "Failed to load sandbox generation during reconnect");
                            send_shutdown(
                                &tx,
                                "failed to validate runner setup generation".to_string(),
                            )
                            .await;
                            return RunnerSessionExit::Disconnected;
                        }
                    }
                }

                let reconnect_plan = match recovery_service
                    .handle_reconnect(ready.is_reconnect, ready.active_task_id.as_deref())
                {
                    Ok(plan) => plan,
                    Err(error) => {
                        warn!(sandbox_id = %sandbox_db_id, error = %error, "Runner sent invalid reconnect task id");
                        let reason = format!("invalid active task id: {error}");
                        if let Err(failure_error) = failure_service
                            .eject_sandbox(
                                &pool,
                                sandbox_db_id,
                                linked_session_id,
                                super::failure::RunnerFailure::protocol_invalid(reason.clone()),
                                Some(&queue),
                                redis_coordinator.as_deref(),
                                &config,
                            )
                            .await
                        {
                            warn!(sandbox_id = %sandbox_db_id, error = %failure_error, "Failed to quarantine Runner with invalid reconnect metadata");
                        }
                        send_shutdown(&tx, reason).await;
                        return RunnerSessionExit::FailureEjected;
                    }
                };

                if let Some(sid) = linked_session_id {
                    if let Ok(stores) = queries::list_session_memory_stores(&pool, sid).await {
                        for store in stores {
                            let mount_path = format!("/mnt/memory/{}", store.mount_name);
                            memory_subscribers
                                .register(
                                    store.store_id,
                                    sid,
                                    sandbox_db_id,
                                    &store.mount_name,
                                    &mount_path,
                                )
                                .await;
                        }
                    }
                }

                if let ReconnectPlan::Resume(active_task_id) = reconnect_plan {
                    recovery_service
                        .handle_reconnect_with_event_loop(
                            inbound.as_mut(),
                            &tx,
                            &bridge_clone,
                            &pool,
                            &event_bus,
                            &config,
                            sandbox_db_id,
                            active_task_id,
                            linked_session_id,
                            &exec_sem,
                            redis_coord.as_deref(),
                            memory_subscribers.clone(),
                            registry.clone(),
                            &runtime_config,
                            identity_policy.clone(),
                            &runner_metrics,
                            &failure_service,
                        )
                        .await;
                } else if reconnect_plan == ReconnectPlan::RescueOrphans {
                    recovery_service
                        .rescue_orphaned_tasks(&pool, &event_bus, sandbox_db_id, &queue)
                        .await;
                }

                if multi_task_loop(
                    inbound.as_mut(),
                    &tx,
                    &bridge_clone,
                    &pool,
                    &event_bus,
                    &queue,
                    &config,
                    &harness_input_builder,
                    &runner_metrics,
                    &failure_service,
                    &identity_policy,
                    sandbox_db_id,
                    &sandbox_external_id,
                    linked_session_id,
                    &exec_sem,
                    redis_coord.as_deref(),
                    memory_subscribers.clone(),
                    registry.clone(),
                    &runtime_config,
                )
                .await
                {
                    RunnerSessionExit::FailureEjected
                } else {
                    RunnerSessionExit::Disconnected
                }
            }
            .await;

            // Cleanup: remove from registry, then grace period
            registry.remove_if_current(&sandbox_external_id, &bridge_clone);

            // Stamp disconnected_at so the fallback sweeper can reap this
            // sandbox after the grace window if no reconnect arrives. Best
            // effort — a failure here means the sweeper waits for
            // idle_timeout / hard_timeout instead. Idempotent: if the
            // marker is already set, this is a no-op (we want the earliest
            // disconnect timestamp).
            if should_wait_for_runner_reconnect(session_exit) {
                let _ = queries::mark_bridge_disconnected(&pool, sandbox_db_id).await;
            }

            // M2 fix: Release the connection permit before entering the 120s
            // grace period. Without this, batch disconnects can exhaust the
            // connection semaphore for 2 minutes even though the gRPC stream
            // is already closed.
            drop(_conn_permit);

            if should_wait_for_runner_reconnect(session_exit) {
                cleanup_service
                    .probe_and_cleanup(
                        &pool,
                        sandbox_db_id,
                        linked_session_id,
                        false,
                        registry.clone(),
                        Some(&queue),
                        redis_coord.as_deref(),
                        &config,
                    )
                    .await;
            } else {
                cleanup_service
                    .cleanup_sandbox(
                        &pool,
                        sandbox_db_id,
                        linked_session_id,
                        session_exit == RunnerSessionExit::FailureEjected,
                        Some(&queue),
                        redis_coord.as_deref(),
                        &config,
                    )
                    .await;
            }

            if let Some(sid) = linked_session_id {
                memory_subscribers.unregister(sid, sandbox_db_id).await;
            }

            info!(sandbox_id = %sandbox_external_id, "Runner disconnected, cleanup complete");
        }); // end of outer tokio::spawn

        outbound
    }
}

#[cfg(test)]
#[path = "session_tests.rs"]
mod tests;

// ---------------------------------------------------------------------------
// SetupSandbox
// ---------------------------------------------------------------------------

fn should_defer_initial_setup(sandbox_status: Option<&str>, has_session_link: bool) -> bool {
    sandbox_status == Some("pooled") && !has_session_link
}

pub(crate) async fn send_shutdown(tx: &mpsc::Sender<OrchestratorMessage>, reason: String) {
    let message = OrchestratorMessage {
        payload: Some(orchestrator_message::Payload::Shutdown(Shutdown { reason })),
    };
    if let Err(e) = tx.send(message).await {
        debug!("Failed to send runner shutdown: {e}");
    }
}

async fn wait_for_ready(
    inbound: &mut dyn RunnerInbound,
) -> anyhow::Result<Option<proto::RunnerReady>> {
    let timeout = Duration::from_secs(30);
    match tokio::time::timeout(timeout, inbound.message()).await {
        Ok(Ok(Some(msg))) => match msg.payload {
            Some(runner_message::Payload::Ready(ready)) => Ok(Some(ready)),
            _ => Ok(None),
        },
        Ok(Ok(None)) => anyhow::bail!("stream closed before RunnerReady"),
        Ok(Err(e)) => Err(e),
        Err(_) => anyhow::bail!("timeout waiting for RunnerReady"),
    }
}
