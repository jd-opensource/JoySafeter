use std::sync::Arc;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::sandbox_bridge::BridgeRegistry;

/// Redis pub/sub command listener for cross-instance gRPC control.
///
/// Subscribes to `joysafeter:cmd:{instance_id}`, dispatches commands:
/// - `cancel` → sends CancelTask to target sandbox bridge
/// - `input` → sends SendInput to target sandbox bridge + notifies confirmation
/// - `shutdown` → sends Shutdown to target sandbox bridge
/// - `memory_update` → broadcasts MemoryFileUpdate to all sandboxes sharing the store
///
/// Mirrors the Python `CommandListener`.
pub struct CommandListener {
    client: redis::Client,
    instance_id: String,
    bridge_registry: BridgeRegistry,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
}

impl CommandListener {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        bridge_registry: BridgeRegistry,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
    ) -> Self {
        Self {
            client,
            instance_id: instance_id.to_string(),
            bridge_registry,
            memory_subscribers,
        }
    }

    /// Spawn the listener as a background task.
    pub fn spawn(self) -> JoinHandle<()> {
        tokio::spawn(async move {
            self.run().await;
        })
    }

    async fn run(&self) {
        let channel = format!("joysafeter:cmd:{}", self.instance_id);
        let mut backoff = 1u64;
        let max_backoff = 30u64;

        loop {
            match self.subscribe_loop(&channel).await {
                Ok(()) => {
                    info!("Command listener channel closed, reconnecting...");
                    backoff = 1;
                }
                Err(e) => {
                    warn!("Command listener error: {e}, reconnecting in {backoff}s");
                    tokio::time::sleep(std::time::Duration::from_secs(backoff)).await;
                    backoff = (backoff * 2).min(max_backoff);
                }
            }
        }
    }

    async fn subscribe_loop(&self, channel: &str) -> anyhow::Result<()> {
        let mut pubsub = self.client.get_async_pubsub().await?;
        pubsub.subscribe(channel).await?;
        info!(channel = channel, "Command listener subscribed");

        loop {
            let msg = pubsub.on_message().next().await;
            match msg {
                Some(msg) => {
                    let payload: String = msg.get_payload()?;
                    if let Err(e) = self.handle_command(&payload).await {
                        error!("Failed to handle command: {e}");
                    }
                }
                None => {
                    return Ok(());
                }
            }
        }
    }

    async fn handle_command(&self, payload: &str) -> anyhow::Result<()> {
        let cmd: serde_json::Value = serde_json::from_str(payload)?;
        let cmd_type = cmd["type"].as_str().unwrap_or("");

        // memory_update is a broadcast command — no sandbox_id needed.
        if cmd_type == "memory_update" {
            return self.handle_memory_update(&cmd).await;
        }

        let sandbox_id_str = cmd["sandbox_id"].as_str().unwrap_or("");

        debug!(
            cmd_type = cmd_type,
            sandbox_id = sandbox_id_str,
            "Received cross-instance command"
        );

        let sandbox_id: uuid::Uuid = match sandbox_id_str.parse() {
            Ok(id) => id,
            Err(_) => {
                warn!("Invalid sandbox_id in command: {sandbox_id_str}");
                return Ok(());
            }
        };

        let bridge = match self.bridge_registry.get_by_db_id(sandbox_id) {
            Some(b) => b,
            None => {
                debug!("No local bridge for sandbox {sandbox_id}, ignoring command");
                return Ok(());
            }
        };

        match cmd_type {
            "cancel" => {
                let reason = cmd["reason"].as_str().unwrap_or("cancelled by remote");
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Cancel(proto::CancelTask {
                        reason: reason.to_string(),
                    })),
                };
                let _ = bridge.send_to_runner(msg).await;
                bridge.request_cancel().await;
                info!(sandbox_id = %sandbox_id, "Relayed cancel command");
            }
            "input" => {
                let content = cmd["content"].as_str().unwrap_or("");
                bridge.send_control_input(content.to_string()).await;
                info!(sandbox_id = %sandbox_id, "Relayed input command");
            }
            "shutdown" => {
                let reason = cmd["reason"].as_str().unwrap_or("remote shutdown");
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                        reason: reason.to_string(),
                    })),
                };
                let _ = bridge.send_to_runner(msg).await;
                info!(sandbox_id = %sandbox_id, "Relayed shutdown command");
            }
            other => {
                warn!("Unknown command type: {other}");
            }
        }

        Ok(())
    }

    /// Handle a `memory_update` broadcast: notify all sandboxes sharing the
    /// given store so their FUSE caches are refreshed in real time.
    ///
    /// Payload: `{"type": "memory_update", "store_mount_name": "...",
    ///            "relative_path": "...", "content": "...", "operation": "modified"}`
    async fn handle_memory_update(&self, cmd: &serde_json::Value) -> anyhow::Result<()> {
        let mount_name = cmd["store_mount_name"].as_str().unwrap_or("");
        let rel_path = cmd["relative_path"].as_str().unwrap_or("");
        let content = cmd["content"].as_str().unwrap_or("");
        let operation = cmd["operation"].as_str().unwrap_or("modified");

        if mount_name.is_empty() || rel_path.is_empty() {
            warn!("memory_update command missing store_mount_name or relative_path");
            return Ok(());
        }

        // Use a zero UUID as sender — no sandbox originated this update
        // (it came from the API), so all peers receive the notification.
        let no_sender = uuid::Uuid::nil();
        self.memory_subscribers
            .notify_peers(
                mount_name,
                rel_path,
                content.as_bytes(),
                operation,
                no_sender,
                &self.bridge_registry,
            )
            .await;

        info!(
            store_mount_name = mount_name,
            path = rel_path,
            operation = operation,
            "Relayed memory_update to peers"
        );
        Ok(())
    }
}

// Need to use futures for the pubsub stream
use futures::StreamExt;
