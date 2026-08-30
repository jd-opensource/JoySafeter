use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use sqlx::PgPool;
use tokio::sync::{mpsc, OwnedSemaphorePermit};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Status, Streaming};
use tracing::{debug, info, warn};
use uuid::Uuid;

use crate::config::JoySafeterConfig;
use crate::db::queries;
use crate::events::bus::EventBus;
use crate::grpc::proto;
use crate::grpc::proto::{
    orchestrator_message, runner_message, OrchestratorMessage, RunnerMessage, Shutdown,
};
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
use crate::kernel::runner::execution::handle_task_setup_failure_result;
use crate::kernel::runner::execution::multi_task_loop;
use crate::kernel::runner::flows::RunnerFlowSet;
#[cfg(test)]
use crate::kernel::runner::memory_sync::handle_memory_sync_db;
use crate::kernel::runner::recovery::ReconnectPlan;
#[cfg(test)]
use crate::kernel::runner::recovery::RunnerRecoveryService;
use crate::kernel::runner::setup::send_setup;
#[cfg(test)]
use crate::kernel::runner::setup::{
    build_start_task_full, is_setup_failure_result, is_setup_failure_task_result,
    mark_idle_setup_failure,
};
#[cfg(test)]
use crate::kernel::runner::task_lifecycle::{
    fail_pre_start_task, failover_or_fail_inline, handle_dispatch_retryable_failure,
    handle_task_disconnect_before_result, send_start_task_or_handle_failure,
    transition_running_task_and_emit_idle, TaskResult,
};
use crate::kernel::runtime_auth::RunnerAuthenticator;
use crate::kernel::sandbox_bridge::SandboxBridge;
use crate::kernel::sandbox_resolver::SandboxIdentityPolicy;
use crate::runtime_config::RuntimeConfig;

#[cfg(test)]
const LIVE_INPUT_PREFIX: &str = "__joysafeter_input_v1__:";

/// Coordinates authenticated Runner sessions and delegates execution/recovery flows.
pub(crate) struct RunnerSessionCoordinator {
    bridge_store: Arc<dyn BridgeStore>,
    event_bus: EventBus,
    queue: TaskQueue,
    pool: PgPool,
    authenticator: RunnerAuthenticator,
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
        authenticator: RunnerAuthenticator,
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
            authenticator,
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
        mut inbound: Streaming<RunnerMessage>,
        conn_permit: OwnedSemaphorePermit,
    ) -> ReceiverStream<OrchestratorMessage> {
        let (tx, rx) = mpsc::channel::<OrchestratorMessage>(256);
        let outbound = ReceiverStream::new(rx);

        let bridge_store = self.bridge_store.clone();
        let event_bus = self.event_bus.clone();
        let queue = self.queue.clone();
        let pool = self.pool.clone();
        let authenticator = self.authenticator.clone();
        let config = self.config.clone();
        let identity_policy = self.identity_policy.clone();
        let runtime_config = self.runtime_config.clone();
        let redis_coordinator = self.redis_coordinator.clone();
        let memory_subscribers = self.memory_subscribers.clone();
        let execution_semaphore = self.flows.execution_semaphore();
        let harness_input_builder = self.flows.harness_input_builder();
        let recovery_service = self.flows.recovery();
        let cleanup_service = self.flows.cleanup();

        tokio::spawn(async move {
            // Keep the connection permit for the lifetime of the spawned task.
            let _conn_permit = conn_permit;
            // Now inside the spawned task, response headers have been sent.
            // The client can send RunnerReady.
            let ready = match wait_for_ready(&mut inbound).await {
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

            let authenticated = match authenticator
                .authenticate_and_record_connection(
                    sandbox_db_id,
                    ready.runner_token.as_deref(),
                    Utc::now(),
                )
                .await
            {
                Ok(authenticated) => authenticated,
                Err(error) => {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Runner authentication rejected");
                    send_shutdown(&tx, "authentication failed".to_string()).await;
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

            // Register sandbox ownership in Redis after authentication.
            if let Some(ref coord) = redis_coordinator {
                let _ = coord.register_sandbox(sandbox_db_id).await;
            }

            // Resolve linked session_id
            let linked_session_id = authenticated.linked_session_id;
            let unclaimed_pool_sandbox = should_defer_initial_setup(
                Some(authenticated.sandbox_status.as_str()),
                linked_session_id.is_some(),
            );

            if unclaimed_pool_sandbox {
                bridge.setup_done.store(false, Ordering::Relaxed);
                debug!(
                    sandbox_id = %sandbox_db_id,
                    "Warm-pool sandbox connected; deferring SetupSandbox until session claim"
                );
            } else if !ready.is_reconnect {
                match send_setup(&pool, &bridge, sandbox_db_id, &tx, &harness_input_builder).await {
                    Ok(true) => bridge.setup_done.store(true, Ordering::Relaxed),
                    Ok(false) => {
                        bridge.setup_done.store(false, Ordering::Relaxed);
                    }
                    Err(e) => {
                        warn!(sandbox_id = %sandbox_db_id, "Failed to send SetupSandbox: {e}");
                        bridge.setup_done.store(false, Ordering::Relaxed);
                    }
                }
            } else {
                bridge.setup_done.store(true, Ordering::Relaxed);
            }

            // Capture reconnect info for the spawned task
            let reconnect_plan = match recovery_service
                .handle_reconnect(ready.is_reconnect, ready.active_task_id.as_deref())
            {
                Ok(plan) => plan,
                Err(error) => {
                    warn!(sandbox_id = %sandbox_db_id, error = %error, "Runner sent invalid reconnect task id");
                    send_shutdown(&tx, format!("invalid active task id: {error}")).await;
                    return;
                }
            };

            // Spawn the multi-task loop
            let pool = pool.clone();
            let event_bus = event_bus.clone();
            let queue = queue.clone();
            let config = config.clone();
            let runtime_config = runtime_config.clone();
            let registry = bridge_store.clone();
            let bridge_clone = bridge.clone();
            let exec_sem = execution_semaphore.clone();
            let redis_coord = redis_coordinator.clone();
            let memory_subscribers = memory_subscribers.clone();

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

            // Handle reconnect (inline, already inside spawned task)
            if let ReconnectPlan::Resume(active_task_id) = reconnect_plan {
                // Run the reconnect event loop with the actual stream
                recovery_service
                    .handle_reconnect_with_event_loop(
                        &mut inbound,
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
                    )
                    .await;
            } else if reconnect_plan == ReconnectPlan::RescueOrphans {
                // Rescue orphaned running tasks
                recovery_service
                    .rescue_orphaned_tasks(&pool, &event_bus, sandbox_db_id, &queue)
                    .await;
            }

            let failure_ejected = multi_task_loop(
                &mut inbound,
                &tx,
                &bridge_clone,
                &pool,
                &event_bus,
                &queue,
                &config,
                &harness_input_builder,
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
            .await;

            // Cleanup: remove from registry, then grace period
            registry.remove(&sandbox_external_id);

            // Stamp disconnected_at so the fallback sweeper can reap this
            // sandbox after the grace window if no reconnect arrives. Best
            // effort — a failure here means the sweeper waits for
            // idle_timeout / hard_timeout instead. Idempotent: if the
            // marker is already set, this is a no-op (we want the earliest
            // disconnect timestamp).
            let _ = queries::mark_bridge_disconnected(&pool, sandbox_db_id).await;

            // M2 fix: Release the connection permit before entering the 120s
            // grace period. Without this, batch disconnects can exhaust the
            // connection semaphore for 2 minutes even though the gRPC stream
            // is already closed.
            drop(_conn_permit);

            // Spawn grace period cleanup (120s reconnect window)
            let registry_for_grace = registry.clone();
            cleanup_service
                .probe_and_cleanup(
                    &pool,
                    sandbox_db_id,
                    linked_session_id,
                    failure_ejected,
                    registry_for_grace.clone(),
                    Some(&queue),
                    redis_coord.as_deref(),
                    &config,
                )
                .await;

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
    inbound: &mut Streaming<RunnerMessage>,
) -> Result<Option<proto::RunnerReady>, Status> {
    let timeout = Duration::from_secs(30);
    match tokio::time::timeout(timeout, inbound.message()).await {
        Ok(Ok(Some(msg))) => match msg.payload {
            Some(runner_message::Payload::Ready(ready)) => Ok(Some(ready)),
            _ => Ok(None),
        },
        Ok(Ok(None)) => Err(Status::aborted("stream closed before RunnerReady")),
        Ok(Err(e)) => Err(e),
        Err(_) => Err(Status::deadline_exceeded("timeout waiting for RunnerReady")),
    }
}
