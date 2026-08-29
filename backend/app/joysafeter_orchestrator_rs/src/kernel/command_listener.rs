use base64::Engine as _;
use redis::AsyncCommands;
use sqlx::PgPool;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::db::queries;
use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::ids::{MemoryStoreId, SandboxId};
use crate::kernel::ha::{BridgeStore, DispatchCommand, TaskDispatcher};
use crate::kernel::memory_sync::MemoryStoreSubscribers;
use crate::kernel::network_policy::application::NetworkingReconcileOutcome;
use crate::kernel::network_policy::material::{
    NetworkPolicyMaterialResolver, UnconfiguredNetworkPolicyMaterialResolver,
};
use crate::kernel::network_policy::ports::NetworkPolicyRequestQueue;
use crate::kernel::network_policy::ports::{NetworkPolicyRuntime, NoopNetworkPolicyRuntime};
use crate::kernel::redis_coordinator::RedisCoordinator;
use crate::sandbox::envoy::EnvoyManager;
use crate::sandbox::image_builder::{EnvironmentPackages, ImageBuilder};
use crate::sandbox::provider::SandboxProvider;

const SANDBOX_DESTROY_BROADCAST_CHANNEL: &str = "joysafeter:cmd:destroy";

/// Redis pub/sub command listener for cross-instance gRPC control.
///
/// Subscribes to `joysafeter:cmd:{instance_id}`, dispatches commands:
/// - `cancel` → sends CancelTask to target sandbox bridge
/// - `input` → sends SendInput to target sandbox bridge + notifies confirmation
/// - `shutdown` → sends Shutdown to target sandbox bridge
/// - `destroy` → destroys the provider sandbox on its owner instance
/// - `build_environment_image` → builds custom environment image on one Rust runtime instance
/// - `memory_update` → broadcasts MemoryFileUpdate to all sandboxes sharing the store
pub struct CommandListener {
    client: redis::Client,
    instance_id: String,
    pool: PgPool,
    bridge_store: Arc<dyn BridgeStore>,
    task_dispatcher: Arc<dyn TaskDispatcher>,
    provider: Arc<dyn SandboxProvider>,
    envoy_manager: Option<Arc<EnvoyManager>>,
    image_builder: Option<Arc<ImageBuilder>>,
    redis_coordinator: Option<Arc<RedisCoordinator>>,
    memory_subscribers: Arc<MemoryStoreSubscribers>,
    xds_authority: crate::xds::authority::XdsAuthority,
    network_policy_queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    network_policy_runtime: Arc<dyn NetworkPolicyRuntime>,
    network_policy_material_resolver: Arc<dyn NetworkPolicyMaterialResolver>,
}

impl CommandListener {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        pool: PgPool,
        bridge_store: Arc<dyn BridgeStore>,
        task_dispatcher: Arc<dyn TaskDispatcher>,
        provider: Arc<dyn SandboxProvider>,
        envoy_manager: Option<Arc<EnvoyManager>>,
        image_builder: Option<Arc<ImageBuilder>>,
        redis_coordinator: Option<Arc<RedisCoordinator>>,
        memory_subscribers: Arc<MemoryStoreSubscribers>,
    ) -> Self {
        Self {
            client,
            instance_id: instance_id.to_string(),
            pool,
            bridge_store,
            task_dispatcher,
            provider,
            envoy_manager,
            image_builder,
            redis_coordinator,
            memory_subscribers,
            xds_authority: crate::xds::authority::XdsAuthority::standalone(),
            network_policy_queue: None,
            network_policy_runtime: Arc::new(NoopNetworkPolicyRuntime),
            network_policy_material_resolver: Arc::new(UnconfiguredNetworkPolicyMaterialResolver),
        }
    }

    pub fn with_network_policy_runtime(mut self, runtime: Arc<dyn NetworkPolicyRuntime>) -> Self {
        self.network_policy_runtime = runtime;
        self
    }

    pub fn with_network_policy_material_resolver(
        mut self,
        resolver: Arc<dyn NetworkPolicyMaterialResolver>,
    ) -> Self {
        self.network_policy_material_resolver = resolver;
        self
    }

    pub fn with_network_policy_control(
        mut self,
        authority: crate::xds::authority::XdsAuthority,
        queue: Option<Arc<dyn NetworkPolicyRequestQueue>>,
    ) -> Self {
        self.xds_authority = authority;
        self.network_policy_queue = queue;
        self
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

        if cmd_type == "build_environment_image" {
            self.handle_build_environment_image(&cmd).await;
            return Ok(());
        }

        let sandbox_id_str = cmd["sandbox_id"].as_str().unwrap_or("");

        debug!(
            cmd_type = cmd_type,
            sandbox_id = sandbox_id_str,
            "Received cross-instance command"
        );

        let sandbox_id = match sandbox_id_str.parse::<Uuid>() {
            Ok(id) => SandboxId::from_uuid(id),
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

        if cmd_type == "sandbox_file" {
            let bridge = match self.bridge_store.get_by_db_id(sandbox_id) {
                Some(b) => b,
                None => {
                    self.publish_ack_payload(
                        &cmd,
                        serde_json::json!({"ok": false, "code": "SANDBOX_NOT_CONNECTED", "error": "sandbox runner is not connected"}),
                    )
                    .await;
                    return Ok(());
                }
            };
            let result = self.handle_sandbox_file(&cmd, &bridge).await;
            match &result {
                Ok(payload) => self.publish_ack_payload(&cmd, payload.clone()).await,
                Err(ref e) => {
                    self.publish_ack_payload(
                        &cmd,
                        serde_json::json!({"ok": false, "error": e.to_string()}),
                    )
                    .await;
                }
            }
            return result.map(|_| ());
        }

        if cmd_type == "network_policy_refresh" {
            let result = self.handle_network_policy_refresh(&cmd, sandbox_id).await;
            match &result {
                Ok(payload) => self.publish_ack_payload(&cmd, payload.clone()).await,
                Err(ref e) => {
                    self.publish_ack_payload(
                        &cmd,
                        serde_json::json!({"ok": false, "error": e.to_string()}),
                    )
                    .await;
                }
            }
            return result.map(|_| ());
        }

        let bridge = match self.bridge_store.get_by_db_id(sandbox_id) {
            Some(b) => b,
            None => {
                // Bridge not local — try cross-instance dispatch via TaskDispatcher
                let dispatch_cmd = match cmd_type {
                    "cancel" => DispatchCommand::Cancel {
                        reason: cmd["reason"]
                            .as_str()
                            .unwrap_or("cancelled by remote")
                            .to_string(),
                    },
                    "input" => DispatchCommand::SendInput {
                        content: cmd["content"].as_str().unwrap_or("").to_string(),
                    },
                    "shutdown" => DispatchCommand::Shutdown {
                        reason: cmd["reason"]
                            .as_str()
                            .unwrap_or("remote shutdown")
                            .to_string(),
                    },
                    _ => {
                        debug!("No local bridge for sandbox {sandbox_id}, ignoring unknown command {cmd_type}");
                        self.publish_ack(&cmd, false).await;
                        return Ok(());
                    }
                };
                match self
                    .task_dispatcher
                    .dispatch_command(sandbox_id, dispatch_cmd)
                    .await
                {
                    Ok(()) => {
                        self.publish_ack(&cmd, true).await;
                        info!(sandbox_id = %sandbox_id, cmd_type = cmd_type, "Dispatched command via TaskDispatcher (cross-instance)");
                    }
                    Err(e) => {
                        debug!(sandbox_id = %sandbox_id, "TaskDispatcher failed: {e}");
                        self.publish_ack(&cmd, false).await;
                    }
                }
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
                ack_ok = bridge.send_control_input(content.to_string()).await.is_ok();
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

    async fn handle_sandbox_file(
        &self,
        cmd: &serde_json::Value,
        bridge: &Arc<crate::kernel::sandbox_bridge::SandboxBridge>,
    ) -> anyhow::Result<serde_json::Value> {
        let op = cmd["op"].as_str().unwrap_or("list");
        let path = cmd["path"].as_str().unwrap_or("/workspace");
        let max_bytes = cmd["max_bytes"].as_u64().unwrap_or(8 * 1024 * 1024);
        let response = bridge
            .request_sandbox_file(
                op.to_string(),
                path.to_string(),
                max_bytes,
                std::time::Duration::from_secs(15),
            )
            .await?;
        Ok(sandbox_file_response_to_json(response))
    }

    async fn handle_network_policy_refresh(
        &self,
        _cmd: &serde_json::Value,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<serde_json::Value> {
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("sandbox not found: {sandbox_id}"))?;

        match crate::kernel::network_policy::application::request_reconcile(
            &self.pool,
            self.network_policy_runtime.as_ref(),
            self.network_policy_material_resolver.as_ref(),
            &sandbox,
            self.network_policy_queue.as_deref(),
            &self.xds_authority,
        )
        .await?
        {
            NetworkingReconcileOutcome::NotLimited => {
                Ok(serde_json::json!({"ok": true, "refreshed": false, "reason": "not_limited"}))
            }
            NetworkingReconcileOutcome::Refreshed { policy_hash }
            | NetworkingReconcileOutcome::AlreadyReady { policy_hash } => {
                info!(sandbox_id = %sandbox_id, policy_hash = %policy_hash, "Refreshed sandbox network policy");
                Ok(serde_json::json!({
                    "ok": true,
                    "refreshed": true,
                    "policy_hash": policy_hash,
                }))
            }
        }
    }

    async fn handle_destroy_sandbox(
        &self,
        cmd: &serde_json::Value,
        sandbox_id: SandboxId,
    ) -> anyhow::Result<()> {
        let reason = cmd["reason"].as_str().unwrap_or("remote destroy");
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id).await?;
        let command_external_id = cmd["external_id"]
            .as_str()
            .filter(|value| !value.is_empty())
            .map(str::to_string);

        if sandbox.is_none() && command_external_id.is_none() {
            anyhow::bail!("destroy command has no DB row or external_id for sandbox {sandbox_id}");
        }

        let (external_id, restore_status) = match sandbox.as_ref() {
            Some(row) if row.status == "destroyed" => {
                let command_matches = command_external_id
                    .as_deref()
                    .is_none_or(|ext_id| row.external_id.as_deref() == Some(ext_id));
                if command_matches {
                    info!(sandbox_id = %sandbox_id, "Destroy command already finalized");
                    return Ok(());
                }
                anyhow::bail!(
                    "destroy command external_id does not match destroyed sandbox {sandbox_id}"
                );
            }
            Some(_) => {
                let Some(claim) = queries::claim_sandbox_for_command_destroy(
                    &self.pool,
                    sandbox_id,
                    command_external_id.as_deref(),
                )
                .await?
                else {
                    anyhow::bail!(
                        "destroy command could not claim sandbox {sandbox_id}; row changed or external_id mismatched"
                    );
                };
                (claim.external_id, Some(claim.previous_status))
            }
            None => (command_external_id.clone(), None),
        };

        if let Some(bridge) = self.bridge_store.get_by_db_id(sandbox_id) {
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                    reason: reason.to_string(),
                })),
            };
            let _ = bridge.send_to_runner(msg).await;
        }

        if let Some(ref ext_id) = external_id {
            self.bridge_store.remove(ext_id);
            if let Err(e) = self.provider.destroy(ext_id).await {
                let err = format!("{e}");
                if !(err.contains("No such container") || err.contains("404")) {
                    if let Some(ref status) = restore_status {
                        let _ = queries::restore_sandbox_after_passive_destroy_failure(
                            &self.pool,
                            sandbox_id,
                            status,
                            external_id.as_deref(),
                        )
                        .await;
                    }
                    return Err(e);
                }
            }
        }

        if let Some(ref envoy) = self.envoy_manager {
            if let Err(e) = envoy.remove_sandbox(sandbox_id).await {
                warn!(sandbox_id = %sandbox_id, "Failed to remove sandbox from Envoy during destroy command: {e}");
            }
        }

        if restore_status.is_some() {
            let finalized = queries::destroy_sandbox_if_status_and_external_id(
                &self.pool,
                sandbox_id,
                "stopping",
                external_id.as_deref(),
            )
            .await?;
            if !finalized {
                anyhow::bail!(
                    "destroy command provider cleanup completed but DB finalize was fenced out for sandbox {sandbox_id}"
                );
            }
        } else {
            queries::destroy_sandbox(&self.pool, sandbox_id).await?;
        }

        if let Some(ref coord) = self.redis_coordinator {
            let _ = coord.remove_sandbox(sandbox_id).await;
            let _ = coord.remove_sandbox_queue(sandbox_id).await;
        }

        info!(sandbox_id = %sandbox_id, "Destroyed sandbox via command listener");
        Ok(())
    }

    async fn handle_build_environment_image(&self, cmd: &serde_json::Value) {
        let Some(builder) = self.image_builder.as_ref() else {
            self.publish_ack_payload(
                cmd,
                serde_json::json!({
                    "ok": false,
                    "code": "IMAGE_BUILDER_UNAVAILABLE",
                    "error": "image builder is not enabled on this runtime instance",
                }),
            )
            .await;
            return;
        };

        let env_id = match cmd["environment_id"]
            .as_str()
            .and_then(|value| value.parse().ok())
        {
            Some(env_id) => env_id,
            None => {
                self.publish_ack_payload(
                    cmd,
                    serde_json::json!({
                        "ok": false,
                        "code": "IMAGE_BUILD_INVALID_COMMAND",
                        "error": "build_environment_image command has invalid environment_id",
                    }),
                )
                .await;
                return;
            }
        };
        let version = match cmd["version"]
            .as_i64()
            .and_then(|value| i32::try_from(value).ok())
        {
            Some(version) if version > 0 => version,
            _ => {
                self.publish_ack_payload(
                    cmd,
                    serde_json::json!({
                        "ok": false,
                        "code": "IMAGE_BUILD_INVALID_COMMAND",
                        "error": "build_environment_image command has invalid version",
                    }),
                )
                .await;
                return;
            }
        };
        let package_config = serde_json::json!({
            "packages": cmd["packages"].clone(),
        });
        let packages = EnvironmentPackages::from_config(&package_config);

        match builder
            .build_environment_image(env_id, version, &packages)
            .await
        {
            Ok(image_tag) => {
                self.publish_ack_payload(
                    cmd,
                    serde_json::json!({
                        "ok": true,
                        "image_tag": image_tag,
                    }),
                )
                .await;
            }
            Err(e) => {
                self.publish_ack_payload(
                    cmd,
                    serde_json::json!({
                        "ok": false,
                        "code": "IMAGE_BUILD_FAILED",
                        "error": e.to_string(),
                    }),
                )
                .await;
            }
        }
    }

    async fn publish_ack(&self, cmd: &serde_json::Value, ok: bool) {
        self.publish_ack_payload(cmd, serde_json::json!({ "ok": ok }))
            .await;
    }

    async fn publish_ack_payload(&self, cmd: &serde_json::Value, mut payload: serde_json::Value) {
        let Some(ack_key) = cmd["ack_key"].as_str() else {
            return;
        };
        let command_id = cmd["command_id"].as_str().unwrap_or("");
        if let Some(obj) = payload.as_object_mut() {
            obj.insert(
                "command_id".to_string(),
                serde_json::Value::String(command_id.to_string()),
            );
        }
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
    /// Payload: `{"type": "memory_update", "store_id": "...",
    ///            "relative_path": "...", "content": "...", "operation": "modified"}`
    async fn handle_memory_update(&self, cmd: &serde_json::Value) -> anyhow::Result<()> {
        let store_id = cmd["store_id"].as_str().unwrap_or("");
        let rel_path = cmd["relative_path"].as_str().unwrap_or("");
        let content = cmd["content"].as_str().unwrap_or("");
        let operation = cmd["operation"].as_str().unwrap_or("modified");

        if store_id.is_empty() || rel_path.is_empty() {
            warn!("memory_update command missing store_id or relative_path");
            return Ok(());
        }

        let store_id = Uuid::parse_str(store_id)
            .map(MemoryStoreId::from_uuid)
            .map_err(|error| anyhow::anyhow!("invalid memory store id: {error}"))?;

        // API-originated updates target every active subscriber of the store.
        self.memory_subscribers
            .notify_store_peers(
                store_id,
                rel_path,
                content.as_bytes(),
                operation,
                &*self.bridge_store,
            )
            .await;

        info!(
            store_id = %store_id,
            path = rel_path,
            operation = operation,
            "Relayed memory_update to peers"
        );
        Ok(())
    }
}

fn sandbox_file_response_to_json(response: proto::SandboxFileResponse) -> serde_json::Value {
    let mut payload = serde_json::json!({
        "ok": response.ok,
        "code": response.code,
        "error": response.error,
        "path": response.path,
    });
    if let Some(obj) = payload.as_object_mut() {
        if !response.entries.is_empty() {
            obj.insert(
                "entries".to_string(),
                serde_json::Value::Array(
                    response
                        .entries
                        .into_iter()
                        .map(|entry| {
                            serde_json::json!({
                                "name": entry.name,
                                "path": entry.path,
                                "type": entry.file_type,
                                "size": entry.size,
                                "mtime": entry.mtime,
                            })
                        })
                        .collect(),
                ),
            );
        }
        if !response.encoding.is_empty() {
            obj.insert(
                "encoding".to_string(),
                serde_json::Value::String(response.encoding),
            );
        }
        if !response.content.is_empty() {
            obj.insert(
                "content".to_string(),
                serde_json::Value::String(response.content),
            );
        }
        if !response.content_bytes.is_empty() {
            obj.insert(
                "content_base64".to_string(),
                serde_json::Value::String(
                    base64::engine::general_purpose::STANDARD.encode(response.content_bytes),
                ),
            );
        }
        if !response.filename.is_empty() {
            obj.insert(
                "filename".to_string(),
                serde_json::Value::String(response.filename),
            );
        }
        if !response.content_type.is_empty() {
            obj.insert(
                "content_type".to_string(),
                serde_json::Value::String(response.content_type),
            );
        }
        if response.size > 0 {
            obj.insert("size".to_string(), serde_json::Value::from(response.size));
        }
    }
    payload
}

// Need to use futures for the pubsub stream
use futures::StreamExt;

#[cfg(test)]
mod tests {
    use std::env;
    use std::sync::Arc;

    use async_trait::async_trait;
    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;
    use tokio::sync::Mutex;

    use super::*;
    use crate::kernel::ha::BridgeStore;
    use crate::kernel::memory_sync::MemoryStoreSubscribers;
    use crate::kernel::sandbox_bridge::BridgeRegistry;
    use crate::sandbox::provider::{SandboxCreateConfig, SandboxStatus};

    fn database_url() -> Option<String> {
        env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
            .map(|url| url.replace("postgresql+asyncpg://", "postgres://"))
    }

    async fn test_pool() -> Option<PgPool> {
        let Some(url) = database_url() else {
            eprintln!("skipping real Postgres command listener test: DATABASE_URL is not set");
            return None;
        };
        Some(
            PgPoolOptions::new()
                .max_connections(3)
                .connect(&url)
                .await
                .expect("connect to migrated Postgres test database"),
        )
    }

    #[derive(Default)]
    struct CommandRecordingProvider {
        destroyed: Mutex<Vec<String>>,
        destroy_status_probe: Mutex<Option<(PgPool, SandboxId)>>,
        destroy_observed_statuses: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl SandboxProvider for CommandRecordingProvider {
        async fn create(&self, config: &SandboxCreateConfig) -> anyhow::Result<String> {
            Ok(format!("unused-{}", config.sandbox_id))
        }

        async fn start(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn stop(&self, _external_id: &str) -> anyhow::Result<()> {
            Ok(())
        }

        async fn destroy(&self, external_id: &str) -> anyhow::Result<()> {
            if let Some((pool, sandbox_id)) = self.destroy_status_probe.lock().await.clone() {
                if let Some(status) = sqlx::query_scalar::<_, String>(
                    "SELECT status FROM joysafeter_sandboxes WHERE id = $1",
                )
                .bind(sandbox_id)
                .fetch_optional(&pool)
                .await?
                {
                    self.destroy_observed_statuses.lock().await.push(status);
                }
            }
            self.destroyed.lock().await.push(external_id.to_string());
            Ok(())
        }

        async fn status(&self, _external_id: &str) -> anyhow::Result<SandboxStatus> {
            Ok(SandboxStatus::Running)
        }

        async fn exec(&self, _external_id: &str, _cmd: &[&str]) -> anyhow::Result<String> {
            Ok(String::new())
        }

        fn provider_name(&self) -> &'static str {
            "command-recording"
        }
    }

    fn command_listener(pool: PgPool, provider: Arc<dyn SandboxProvider>) -> CommandListener {
        let bridge_store: Arc<dyn BridgeStore> = Arc::new(BridgeRegistry::new());
        let task_dispatcher: Arc<dyn crate::kernel::ha::TaskDispatcher> = Arc::new(
            crate::kernel::ha::LocalTaskDispatcher::new(bridge_store.clone()),
        );
        CommandListener::new(
            redis::Client::open("redis://127.0.0.1:1/").expect("redis url"),
            "test-instance",
            pool,
            bridge_store,
            task_dispatcher,
            provider,
            None,
            None,
            None,
            Arc::new(MemoryStoreSubscribers::new()),
        )
    }

    #[tokio::test]
    async fn destroy_command_rejects_stale_external_id_before_provider_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let current_external_id = format!("command-current-{sandbox_id}");
        let stale_external_id = format!("command-stale-{sandbox_id}");
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &current_external_id,
            "command-recording",
            "test-image",
            None,
            None,
            None,
            Some(&json!({"test": "destroy_command_rejects_stale_external_id"})),
        )
        .await
        .expect("insert command listener sandbox");
        queries::transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("mark sandbox idle");

        let provider = Arc::new(CommandRecordingProvider::default());
        let listener = command_listener(pool.clone(), provider.clone());
        let cmd = json!({
            "type": "destroy",
            "sandbox_id": sandbox_id.as_uuid().to_string(),
            "external_id": stale_external_id,
            "reason": "stale command test"
        });

        let result = listener.handle_destroy_sandbox(&cmd, sandbox_id).await;
        let destroyed = provider.destroyed.lock().await.clone();
        let row: (String, Option<String>, bool) = sqlx::query_as(
            "SELECT status, external_id, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load command listener sandbox");

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;

        assert!(
            result.is_err(),
            "stale external_id command must fail instead of acking destructive ownership"
        );
        assert!(
            destroyed.is_empty(),
            "provider.destroy must not run for stale external_id"
        );
        assert_eq!(row, ("idle".to_string(), Some(current_external_id), false));
    }

    #[tokio::test]
    async fn destroy_command_claims_row_before_provider_destroy() {
        let Some(pool) = test_pool().await else {
            return;
        };

        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let external_id = format!("command-owned-{sandbox_id}");
        queries::create_sandbox(
            &pool,
            sandbox_id,
            &external_id,
            "command-recording",
            "test-image",
            None,
            None,
            None,
            Some(&json!({"test": "destroy_command_claims_row_before_provider_destroy"})),
        )
        .await
        .expect("insert command listener sandbox");
        queries::transition_sandbox_cas(&pool, sandbox_id, "creating", "idle")
            .await
            .expect("mark sandbox idle");

        let provider = Arc::new(CommandRecordingProvider::default());
        *provider.destroy_status_probe.lock().await = Some((pool.clone(), sandbox_id));
        let listener = command_listener(pool.clone(), provider.clone());
        let cmd = json!({
            "type": "destroy",
            "sandbox_id": sandbox_id.as_uuid().to_string(),
            "external_id": external_id.clone(),
            "reason": "owned command test"
        });

        listener
            .handle_destroy_sandbox(&cmd, sandbox_id)
            .await
            .expect("destroy matching command");
        let destroyed = provider.destroyed.lock().await.clone();
        let observed = provider.destroy_observed_statuses.lock().await.clone();
        let row: (String, bool) = sqlx::query_as(
            "SELECT status, destroyed_at IS NOT NULL FROM joysafeter_sandboxes WHERE id = $1",
        )
        .bind(sandbox_id)
        .fetch_one(&pool)
        .await
        .expect("load command listener sandbox");

        let _ = sqlx::query("DELETE FROM joysafeter_sandboxes WHERE id = $1")
            .bind(sandbox_id)
            .execute(&pool)
            .await;

        assert_eq!(destroyed, vec![external_id]);
        assert_eq!(observed, vec!["stopping".to_string()]);
        assert_eq!(row, ("destroyed".to_string(), true));
    }
}
