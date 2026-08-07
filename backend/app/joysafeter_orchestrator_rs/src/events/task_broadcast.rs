use std::sync::Arc;

use tokio::sync::broadcast;
use tracing::warn;

use super::envelope::EventEnvelope;
use crate::kernel::ha::BridgeStore;

/// TaskBroadcastSubscriber — BROADCAST phase.
///
/// Fans out events to per-task WebSocket subscribers via SandboxBridge,
/// and publishes to Redis for cross-instance delivery.
/// Mirrors the Python `TaskBroadcastSubscriber`.
pub struct TaskBroadcastSubscriber {
    bridge_store: Arc<dyn BridgeStore>,
}

impl TaskBroadcastSubscriber {
    pub fn new(bridge_store: Arc<dyn BridgeStore>) -> Self {
        Self { bridge_store }
    }

    /// Spawn as a background task listening on the event bus.
    pub fn spawn(
        self,
        mut rx: broadcast::Receiver<Arc<EventEnvelope>>,
    ) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(envelope) => {
                        self.handle(&envelope).await;
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!("TaskBroadcastSubscriber lagged by {n} messages");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        })
    }

    async fn handle(&self, envelope: &EventEnvelope) {
        let task_id = match envelope.task_id {
            Some(id) => id,
            None => return,
        };

        let sandbox_id = match envelope.sandbox_id {
            Some(id) => id,
            None => return,
        };

        // Broadcast to per-task WebSocket subscribers via bridge
        if let Some(bridge) = self.bridge_store.get_by_db_id(sandbox_id) {
            let payload = envelope
                .task_broadcast_payload
                .as_ref()
                .unwrap_or(&envelope.payload);
            bridge.broadcast_to_task(task_id, payload.clone()).await;
        }
    }
}
