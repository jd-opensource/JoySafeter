use redis::AsyncCommands;
use sqlx::PgPool;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::db::queries;
use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::redis_coordinator::RedisCoordinator;
use crate::kernel::sandbox_bridge::BridgeRegistry;
use crate::sandbox::envoy::EnvoyManager;
use crate::sandbox::provider::SandboxProvider;

const SANDBOX_DESTROY_BROADCAST_CHANNEL: &str = "joysafeter:cmd:destroy";

/// Redis pub/sub command listener for cross-instance gRPC control.
///
/// Subscribes to `joysafeter:cmd:{instance_id}`, dispatches commands:
/// - `cancel` → sends CancelTask to target sandbox bridge
/// - `input` → sends SendInput to target sandbox bridge + notifies confirmation
/// - `shutdown` → sends Shutdown to target sandbox bridge
/// - `destroy` → destroys the provider sandbox on its owner instance
/// - `memory_update` → broadcasts MemoryFileUpdate to all sandboxes sharing the store
pub struct CommandListener {
    client: redis::Client,
    instance_id: String,
    pool: PgPool,
    bridge_registry: BridgeRegistry,
    provider: Arc<dyn SandboxProvider>,
    envoy_manager: Option<Arc<EnvoyManager>>,
    redis_coordinator: Option<Arc<RedisCoordinator>>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
}

impl CommandListener {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        pool: PgPool,
        bridge_registry: BridgeRegistry,
        provider: Arc<dyn SandboxProvider>,
        envoy_manager: Option<Arc<EnvoyManager>>,
        redis_coordinator: Option<Arc<RedisCoordinator>>,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
    ) -> Self {
        Self {
            client,
            instance_id: instance_id.to_string(),
            pool,
            bridge_registry,
            provider,
            envoy_manager,
            redis_coordinator,
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
        pubsub.subscribe(SANDBOX_DESTROY_BROADCAST_CHANNEL).await?;
        info!(
            channel = channel,
            destroy_channel = SANDBOX_DESTROY_BROADCAST_CHANNEL,
            "Command listener subscribed"
        );

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
            let result = self.handle_memory_update(&cmd).await;
            self.publish_ack(&cmd, result.is_ok()).await;
            return result;
        }

        let sandbox_id_str = cmd["sandbox_id"].as_str().unwrap_or("");

        debug!(
            cmd_type = cmd_type,
            sandbox_id = sandbox_id_str,
            "Received cross-instance command"
        );

        let sandbox_id: Uuid = match sandbox_id_str.parse() {
            Ok(id) => id,
            Err(_) => {
                warn!("Invalid sandbox_id in command: {sandbox_id_str}");
                self.publish_ack(&cmd, false).await;
                return Ok(());
            }
        };

        if cmd_type == "destroy" {
            let result = self.handle_destroy_sandbox(&cmd, sandbox_id).await;
            self.publish_ack(&cmd, result.is_ok()).await;
            return result;
        }

        let bridge = match self.bridge_registry.get_by_db_id(sandbox_id) {
            Some(b) => b,
            None => {
                debug!("No local bridge for sandbox {sandbox_id}, ignoring command");
                self.publish_ack(&cmd, false).await;
                return Ok(());
            }
        };

        let mut ack_ok = false;
        match cmd_type {
            "cancel" => {
                let reason = cmd["reason"].as_str().unwrap_or("cancelled by remote");
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Cancel(proto::CancelTask {
                        reason: reason.to_string(),
                    })),
                };
                ack_ok = bridge.send_to_runner(msg).await.is_ok();
                bridge.request_cancel().await;
                info!(sandbox_id = %sandbox_id, "Relayed cancel command");
            }
            "input" => {
                let content = cmd["content"].as_str().unwrap_or("");
                bridge.send_control_input(content.to_string()).await;
                ack_ok = true;
                info!(sandbox_id = %sandbox_id, "Relayed input command");
            }
            "shutdown" => {
                let reason = cmd["reason"].as_str().unwrap_or("remote shutdown");
                let msg = OrchestratorMessage {
                    payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                        reason: reason.to_string(),
                    })),
                };
                ack_ok = bridge.send_to_runner(msg).await.is_ok();
                info!(sandbox_id = %sandbox_id, "Relayed shutdown command");
            }
            other => {
                warn!("Unknown command type: {other}");
            }
        }
        self.publish_ack(&cmd, ack_ok).await;

        Ok(())
    }

    async fn handle_destroy_sandbox(
        &self,
        cmd: &serde_json::Value,
        sandbox_id: Uuid,
    ) -> anyhow::Result<()> {
        let reason = cmd["reason"].as_str().unwrap_or("remote destroy");
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id).await?;
        let external_id = cmd["external_id"]
            .as_str()
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .or_else(|| {
                sandbox
                    .as_ref()
                    .and_then(|row| row.external_id.clone())
                    .filter(|value| !value.is_empty())
            });

        if sandbox.is_none() && external_id.is_none() {
            anyhow::bail!("destroy command has no DB row or external_id for sandbox {sandbox_id}");
        }

        if let Some(bridge) = self.bridge_registry.get_by_db_id(sandbox_id) {
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                    reason: reason.to_string(),
                })),
            };
            let _ = bridge.send_to_runner(msg).await;
        }

        if let Some(ref ext_id) = external_id {
            self.bridge_registry.remove(ext_id);
            if let Err(e) = self.provider.destroy(ext_id).await {
                let err = format!("{e}");
                if !(err.contains("No such container") || err.contains("404")) {
                    return Err(e);
                }
            }
        }

        if let Some(ref envoy) = self.envoy_manager {
            if let Err(e) = envoy.remove_sandbox(sandbox_id).await {
                warn!(sandbox_id = %sandbox_id, "Failed to remove sandbox from Envoy during destroy command: {e}");
            }
        }

        queries::destroy_sandbox(&self.pool, sandbox_id).await?;

        if let Some(ref coord) = self.redis_coordinator {
            let _ = coord.remove_sandbox(sandbox_id).await;
            let _ = coord.remove_sandbox_queue(sandbox_id).await;
        }

        info!(sandbox_id = %sandbox_id, "Destroyed sandbox via command listener");
        Ok(())
    }

    async fn publish_ack(&self, cmd: &serde_json::Value, ok: bool) {
        let Some(ack_key) = cmd["ack_key"].as_str() else {
            return;
        };
        let command_id = cmd["command_id"].as_str().unwrap_or("");
        let payload = serde_json::json!({
            "command_id": command_id,
            "ok": ok,
        });
        let Ok(encoded) = serde_json::to_string(&payload) else {
            return;
        };
        let mut conn = match self.client.get_multiplexed_async_connection().await {
            Ok(conn) => conn,
            Err(e) => {
                warn!("Failed to open Redis connection for command ACK: {e}");
                return;
            }
        };
        if let Err(e) = conn.rpush::<_, _, ()>(ack_key, encoded).await {
            warn!("Failed to write command ACK {ack_key}: {e}");
            return;
        }
        let _ = conn.expire::<_, ()>(ack_key, 30).await;
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
