use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use dashmap::DashMap;
use tokio::sync::{mpsc, oneshot, watch, Mutex, Notify};
use uuid::Uuid;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage, SandboxFileResponse};
use crate::kernel::ha::BridgeStore;

#[derive(Clone, Debug)]
pub struct RunnerRuntimeActivity {
    pub runtime_state: String,
    pub active_task_id: Option<String>,
    pub session_id: Option<String>,
    pub observed_at: DateTime<Utc>,
}

/// Per-sandbox in-process state.
///
/// Mirrors the Python `SandboxBridge` class with full parity:
/// task subscribers, HITL control queue, requires_action state, capabilities.
#[derive(Debug)]
pub struct SandboxBridge {
    pub sandbox_db_id: Uuid,
    /// Channel to send messages to the connected runner.
    pub runner_tx: mpsc::Sender<OrchestratorMessage>,
    /// Current task being executed (if any).
    pub current_task_id: Mutex<Option<Uuid>>,
    /// Owner epoch captured when the current task was claimed/resumed.
    pub current_task_owner_epoch: Mutex<Option<i64>>,
    /// Notify when a new task is available for this sandbox.
    pub task_available: Notify,
    /// HITL confirmation: use watch channel for resettable signal.
    confirmation_tx: watch::Sender<bool>,
    /// HITL confirmation receiver.
    pub confirmation_rx: Mutex<watch::Receiver<bool>>,
    /// Cancel signal — resettable per-task.
    task_cancel: Mutex<tokio_util::sync::CancellationToken>,
    /// HITL control input queue.
    pub control_tx: mpsc::Sender<String>,
    pub control_rx: Mutex<mpsc::Receiver<String>>,
    /// Whether the task is waiting for human input.
    pub requires_action_pending: AtomicBool,
    /// Whether SetupSandbox has been sent.
    pub setup_done: AtomicBool,
    /// Set to true when this bridge has been replaced by a reconnecting runner.
    /// The old connection's multi_task_loop should check this and exit.
    pub displaced: AtomicBool,
    /// Runner capabilities from RunnerReady.
    pub runner_capabilities: Mutex<Vec<String>>,
    /// Signature of session file resources already injected into this sandbox.
    pub injected_session_files_signature: Mutex<Option<String>>,
    /// Last error message.
    pub last_error: Mutex<Option<String>>,
    /// Maps control_request call_id → event_id for HITL tracking.
    pub pending_control_request_ids: Mutex<HashMap<String, Uuid>>,
    /// Last result status (for idle handler stop_reason computation).
    pub last_result_status: Mutex<Option<String>>,
    pub last_result_error: Mutex<Option<String>>,
    /// Last runner-side busy/idle heartbeat.
    runner_runtime_activity: Mutex<Option<RunnerRuntimeActivity>>,
    /// Per-task WebSocket subscriber queues.
    task_subscribers: Mutex<HashMap<Uuid, Vec<mpsc::Sender<serde_json::Value>>>>,
    /// Pending live file requests awaiting runner responses.
    pending_sandbox_file_requests: Mutex<HashMap<String, oneshot::Sender<SandboxFileResponse>>>,
}

impl SandboxBridge {
    pub fn new(sandbox_db_id: Uuid, runner_tx: mpsc::Sender<OrchestratorMessage>) -> Self {
        let (confirmation_tx, confirmation_rx) = watch::channel(false);
        let (control_tx, control_rx) = mpsc::channel(64);
        Self {
            sandbox_db_id,
            runner_tx,
            current_task_id: Mutex::new(None),
            current_task_owner_epoch: Mutex::new(None),
            task_available: Notify::new(),
            confirmation_tx,
            confirmation_rx: Mutex::new(confirmation_rx),
            task_cancel: Mutex::new(tokio_util::sync::CancellationToken::new()),
            control_tx,
            control_rx: Mutex::new(control_rx),
            requires_action_pending: AtomicBool::new(false),
            setup_done: AtomicBool::new(false),
            displaced: AtomicBool::new(false),
            runner_capabilities: Mutex::new(Vec::new()),
            injected_session_files_signature: Mutex::new(None),
            last_error: Mutex::new(None),
            pending_control_request_ids: Mutex::new(HashMap::new()),
            last_result_status: Mutex::new(None),
            last_result_error: Mutex::new(None),
            runner_runtime_activity: Mutex::new(None),
            task_subscribers: Mutex::new(HashMap::new()),
            pending_sandbox_file_requests: Mutex::new(HashMap::new()),
        }
    }

    pub async fn record_runner_heartbeat(
        &self,
        runtime_state: &str,
        active_task_id: Option<String>,
        session_id: Option<String>,
    ) {
        let state = runtime_state.trim();
        if state.is_empty() {
            return;
        }
        *self.runner_runtime_activity.lock().await = Some(RunnerRuntimeActivity {
            runtime_state: state.to_string(),
            active_task_id,
            session_id,
            observed_at: Utc::now(),
        });
    }

    pub async fn runner_runtime_activity(&self) -> Option<RunnerRuntimeActivity> {
        self.runner_runtime_activity.lock().await.clone()
    }

    /// Send a message to the connected runner.
    pub async fn send_to_runner(
        &self,
        msg: OrchestratorMessage,
    ) -> Result<(), mpsc::error::SendError<OrchestratorMessage>> {
        self.runner_tx.send(msg).await
    }

    /// Get the current per-task cancel token (for use in select! loops).
    pub async fn current_cancel_token(&self) -> tokio_util::sync::CancellationToken {
        self.task_cancel.lock().await.clone()
    }

    /// Cancel the current task.
    pub async fn request_cancel(&self) {
        self.task_cancel.lock().await.cancel();
    }

    /// Reset the cancel token for the next task (call between tasks).
    pub async fn reset_cancel(&self) {
        *self.task_cancel.lock().await = tokio_util::sync::CancellationToken::new();
    }

    /// Send a control input (HITL confirmation) and trigger the confirmation signal.
    pub async fn send_control_input(
        &self,
        content: String,
    ) -> Result<(), mpsc::error::SendError<String>> {
        self.control_tx.send(content).await?;
        let _ = self.confirmation_tx.send(true);
        Ok(())
    }

    /// Reset the confirmation signal (call after processing confirmation).
    pub fn reset_confirmation(&self) {
        let _ = self.confirmation_tx.send(false);
    }

    /// Wait for confirmation signal.
    pub async fn wait_confirmation(&self) {
        let mut rx = self.confirmation_rx.lock().await;
        // Wait until value becomes true
        loop {
            if *rx.borrow() {
                return;
            }
            if rx.changed().await.is_err() {
                return;
            }
        }
    }

    pub async fn request_sandbox_file(
        &self,
        operation: String,
        path: String,
        max_bytes: u64,
        timeout: std::time::Duration,
    ) -> anyhow::Result<SandboxFileResponse> {
        let request_id = Uuid::now_v7().to_string();
        let (tx, rx) = oneshot::channel();
        self.pending_sandbox_file_requests
            .lock()
            .await
            .insert(request_id.clone(), tx);

        let message = OrchestratorMessage {
            payload: Some(orchestrator_message::Payload::SandboxFileRequest(
                proto::SandboxFileRequest {
                    request_id: request_id.clone(),
                    operation,
                    path,
                    max_bytes,
                },
            )),
        };

        if let Err(e) = self.runner_tx.send(message).await {
            self.pending_sandbox_file_requests
                .lock()
                .await
                .remove(&request_id);
            return Err(anyhow::anyhow!("failed to send sandbox file request: {e}"));
        }

        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(response)) => Ok(response),
            Ok(Err(_)) => Err(anyhow::anyhow!("sandbox file response channel closed")),
            Err(_) => {
                self.pending_sandbox_file_requests
                    .lock()
                    .await
                    .remove(&request_id);
                Err(anyhow::anyhow!("sandbox file request timed out"))
            }
        }
    }

    pub async fn complete_sandbox_file_response(&self, response: SandboxFileResponse) -> bool {
        let request_id = response.request_id.clone();
        let tx = self
            .pending_sandbox_file_requests
            .lock()
            .await
            .remove(&request_id);
        match tx {
            Some(tx) => tx.send(response).is_ok(),
            None => false,
        }
    }

    /// Remove all subscribers for a task.
    pub async fn remove_task_subscribers(&self, task_id: Uuid) {
        let mut subs = self.task_subscribers.lock().await;
        subs.remove(&task_id);
    }

    /// Broadcast an event to all subscribers for a task.
    /// Removes dead senders automatically.
    pub async fn broadcast_to_task(&self, task_id: Uuid, event: serde_json::Value) {
        let mut subs = self.task_subscribers.lock().await;
        if let Some(senders) = subs.get_mut(&task_id) {
            senders.retain(|tx| tx.try_send(event.clone()).is_ok());
            if senders.is_empty() {
                subs.remove(&task_id);
            }
        }
    }
}

/// Global registry of active sandbox bridges.
///
/// Mirrors the Python `SandboxBridgeRegistry` with full parity.
#[derive(Clone)]
pub struct BridgeRegistry {
    /// Maps sandbox external ID → bridge.
    bridges: Arc<DashMap<String, Arc<SandboxBridge>>>,
    /// Maps sandbox DB UUID → external ID (for lookup by DB ID).
    db_id_map: Arc<DashMap<Uuid, String>>,
}

impl BridgeRegistry {
    pub fn new() -> Self {
        Self {
            bridges: Arc::new(DashMap::new()),
            db_id_map: Arc::new(DashMap::new()),
        }
    }

    /// Register a new sandbox bridge.
    pub fn register(&self, external_id: String, bridge: Arc<SandboxBridge>) {
        // If old bridge exists, mark it displaced and cancel its current task.
        // The old connection's multi_task_loop checks `displaced` and exits.
        if let Some(old) = self.bridges.get(&external_id) {
            old.displaced.store(true, Ordering::Release);
            // Best-effort cancel — try_lock may fail if task is mid-reset,
            // but `displaced` flag ensures the old loop exits regardless.
            if let Ok(token) = old.task_cancel.try_lock() {
                token.cancel();
            }
            tracing::warn!(
                external_id = %external_id,
                "Bridge replaced (old session displaced by reconnect)"
            );
        }
        self.db_id_map
            .insert(bridge.sandbox_db_id, external_id.clone());
        self.bridges.insert(external_id, bridge);
    }

    /// Get a bridge by external ID.
    pub fn get(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        self.bridges.get(external_id).map(|r| r.value().clone())
    }

    /// Get a bridge by DB UUID.
    pub fn get_by_db_id(&self, db_id: Uuid) -> Option<Arc<SandboxBridge>> {
        self.db_id_map
            .get(&db_id)
            .and_then(|ext_id| self.bridges.get(ext_id.value()).map(|r| r.value().clone()))
    }

    /// Remove a bridge by external ID.
    pub fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        if let Some((_, bridge)) = self.bridges.remove(external_id) {
            self.db_id_map.remove(&bridge.sandbox_db_id);
            Some(bridge)
        } else {
            None
        }
    }

    /// Get all bridges as a Vec.
    pub fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        self.bridges.iter().map(|r| r.value().clone()).collect()
    }

    /// Send shutdown to all connected runners.
    pub async fn shutdown_all(&self) {
        use crate::grpc::proto::{orchestrator_message, Shutdown};

        for entry in self.bridges.iter() {
            let bridge = entry.value();
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Shutdown(Shutdown {
                    reason: "orchestrator shutting down".to_string(),
                })),
            };
            let _ = bridge.send_to_runner(msg).await;
        }
    }
}

#[async_trait]
impl BridgeStore for BridgeRegistry {
    fn register(&self, external_id: String, bridge: Arc<SandboxBridge>) {
        BridgeRegistry::register(self, external_id, bridge);
    }

    fn get(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        BridgeRegistry::get(self, external_id)
    }

    fn get_by_db_id(&self, db_id: Uuid) -> Option<Arc<SandboxBridge>> {
        BridgeRegistry::get_by_db_id(self, db_id)
    }

    fn remove(&self, external_id: &str) -> Option<Arc<SandboxBridge>> {
        BridgeRegistry::remove(self, external_id)
    }

    fn all_bridges(&self) -> Vec<Arc<SandboxBridge>> {
        BridgeRegistry::all_bridges(self)
    }

    async fn shutdown_all(&self) {
        BridgeRegistry::shutdown_all(self).await;
    }

    async fn get_owner_instance(&self, _sandbox_id: Uuid) -> Option<String> {
        Some("self".to_string())
    }

    async fn heartbeat(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use tokio::sync::mpsc;

    use super::SandboxBridge;

    #[tokio::test]
    async fn send_control_input_reports_closed_queue() {
        let (runner_tx, _runner_rx) = mpsc::channel(1);
        let bridge = SandboxBridge::new(uuid::Uuid::nil(), runner_tx);
        bridge.control_rx.lock().await.close();

        let result = bridge.send_control_input("input".to_string()).await;

        assert!(result.is_err());
        assert!(!*bridge.confirmation_rx.lock().await.borrow());
    }
}
